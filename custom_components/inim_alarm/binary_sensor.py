"""Binary Sensor platform for INIM Alarm."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ALARM_MEMORY,
    ATTR_BYPASSED,
    ATTR_DEVICE_ID,
    ATTR_TAMPER_MEMORY,
    ATTR_ZONE_ID,
    DOMAIN,
    MANUFACTURER,
    ZONE_STATUS_CLOSED,
)
from .coordinator import InimDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


# Keywords to identify zone types
DOOR_KEYWORDS = ["porta", "ingr", "scorr", "door", "gate", "cancell"]
WINDOW_KEYWORDS = ["finestra", "f.", "f:", "window", "cam.", "bagno", "cucina", "salotto", "studio", "palestra", "svago", "quadro"]
TAMPER_KEYWORDS = ["tamper", "sirena"]
MOTION_KEYWORDS = ["pir", "movimento", "motion", "volumetrico"]


def _guess_device_class(zone_name: str) -> BinarySensorDeviceClass:
    """Guess the device class based on zone name."""
    name_lower = zone_name.lower()
    
    # Check for tamper sensors first
    for keyword in TAMPER_KEYWORDS:
        if keyword in name_lower:
            return BinarySensorDeviceClass.TAMPER
    
    # Check for motion sensors
    for keyword in MOTION_KEYWORDS:
        if keyword in name_lower:
            return BinarySensorDeviceClass.MOTION
    
    # Check for doors
    for keyword in DOOR_KEYWORDS:
        if keyword in name_lower:
            return BinarySensorDeviceClass.DOOR
    
    # Check for windows (this includes many room names that typically have windows)
    for keyword in WINDOW_KEYWORDS:
        if keyword in name_lower:
            return BinarySensorDeviceClass.WINDOW
    
    # Default to opening for generic sensors
    return BinarySensorDeviceClass.OPENING


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up INIM binary sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: InimDataUpdateCoordinator = data["coordinator"]

    entities = []
    
    for device in coordinator.devices:
        device_id = device.get("device_id")
        device_name = device.get("name", "INIM Alarm")
        
        if not device_id:
            continue
        
        # Create binary sensors for each zone
        for zone in device.get("zones", []):
            zone_id = zone.get("ZoneId")
            zone_name = zone.get("Name", f"Zone {zone_id}")
            
            # Skip zones that are not visible
            if zone.get("Visibility", 1) == 0:
                continue
            
            entities.append(
                InimZoneBinarySensor(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=device_name,
                    zone_id=zone_id,
                    zone_name=zone_name,
                )
            )

    async_add_entities(entities)


class InimZoneBinarySensor(
    CoordinatorEntity[InimDataUpdateCoordinator], BinarySensorEntity
):
    """Representation of an INIM Zone binary sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: InimDataUpdateCoordinator,
        device_id: int,
        device_name: str,
        zone_id: int,
        zone_name: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._attr_unique_id = f"{device_id}_zone_{zone_id}"
        self._attr_name = zone_name
        self._attr_device_class = _guess_device_class(zone_name)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        device = self.coordinator.get_device(self._device_id)
        if not device:
            return DeviceInfo(
                identifiers={(DOMAIN, str(self._device_id))},
                manufacturer=MANUFACTURER,
            )
        
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._device_id))},
            manufacturer=MANUFACTURER,
            model=device.get("model"),
            name=device.get("name", "INIM Alarm"),
            sw_version=device.get("firmware"),
            serial_number=device.get("serial_number"),
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if the zone is open/triggered."""
        zone = self.coordinator.get_zone(self._device_id, self._zone_id)
        if not zone:
            return None
        
        # Status: 1 = closed, 2 = open
        # Subtract 1 to get: 0 = closed (False), 1 = open (True)
        status = zone.get("Status", ZONE_STATUS_CLOSED)
        return (status - 1) > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        zone = self.coordinator.get_zone(self._device_id, self._zone_id)
        if not zone:
            return {}
        
        return {
            ATTR_DEVICE_ID: self._device_id,
            ATTR_ZONE_ID: self._zone_id,
            ATTR_ALARM_MEMORY: zone.get("AlarmMemory", 0) > 0,
            ATTR_TAMPER_MEMORY: zone.get("TamperMemory", 0) > 0,
            ATTR_BYPASSED: zone.get("Bypassed", 0) > 0,
            "output_on": zone.get("OutputOn", 0) > 0,
            "output_value": zone.get("OutputValue", 0),
            "areas": zone.get("Areas"),
            "type": zone.get("Type"),
            "terminal_id": zone.get("TerminalId"),
            "voltage": zone.get("Voltage", 0) if zone.get("Voltage", 0) > 0 else None,
            "power": zone.get("Power", 0) if zone.get("Power", 0) > 0 else None,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
