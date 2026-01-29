"""Sensor platform for INIM Alarm."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricPotential
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    AREA_ARMED_ARMED,
    AREA_ARMED_DISARMED,
    ATTR_ALARM_MEMORY,
    ATTR_AREA_ID,
    ATTR_DEVICE_ID,
    ATTR_TAMPER_MEMORY,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import InimDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Armed status mapping
ARMED_STATUS_MAP = {
    1: "armed",
    2: "armed_partial",
    3: "armed_partial",
    4: "disarmed",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up INIM sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: InimDataUpdateCoordinator = data["coordinator"]

    entities: list[SensorEntity] = []
    
    for device in coordinator.devices:
        device_id = device.get("device_id")
        device_name = device.get("name", "INIM Alarm")
        
        if not device_id:
            continue
        
        # Create voltage sensor for the device
        entities.append(
            InimVoltageSensor(
                coordinator=coordinator,
                device_id=device_id,
                device_name=device_name,
            )
        )
        
        # Create sensors for each area (only for areas that seem to be in use)
        for area in device.get("areas", []):
            area_id = area.get("AreaId")
            area_name = area.get("Name", f"Area {area_id}")
            
            # Skip generic/unused areas (those with default names like "Area 3", "Area 4", etc.)
            if area_name.startswith("Area ") and area_name[5:].isdigit():
                continue
            
            entities.append(
                InimAreaSensor(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=device_name,
                    area_id=area_id,
                    area_name=area_name,
                )
            )

    async_add_entities(entities)


class InimVoltageSensor(
    CoordinatorEntity[InimDataUpdateCoordinator], SensorEntity
):
    """Representation of an INIM Voltage sensor."""

    _attr_has_entity_name = True
    _attr_name = "Voltage"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT

    def __init__(
        self,
        coordinator: InimDataUpdateCoordinator,
        device_id: int,
        device_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._attr_unique_id = f"{device_id}_voltage"

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
    def native_value(self) -> float | None:
        """Return the voltage value."""
        device = self.coordinator.get_device(self._device_id)
        if not device:
            return None
        
        voltage = device.get("voltage")
        if voltage is not None:
            return round(voltage, 2)
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class InimAreaSensor(
    CoordinatorEntity[InimDataUpdateCoordinator], SensorEntity
):
    """Representation of an INIM Area sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: InimDataUpdateCoordinator,
        device_id: int,
        device_name: str,
        area_id: int,
        area_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._area_id = area_id
        self._area_name = area_name
        self._attr_unique_id = f"{device_id}_area_{area_id}"
        self._attr_name = area_name
        self._attr_icon = "mdi:shield-home"

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
    def native_value(self) -> str | None:
        """Return the area status."""
        area = self.coordinator.get_area(self._device_id, self._area_id)
        if not area:
            return None
        
        armed = area.get("Armed", AREA_ARMED_DISARMED)
        return ARMED_STATUS_MAP.get(armed, "unknown")

    @property
    def icon(self) -> str:
        """Return the icon based on state."""
        area = self.coordinator.get_area(self._device_id, self._area_id)
        if not area:
            return "mdi:shield-off"
        
        armed = area.get("Armed", AREA_ARMED_DISARMED)
        alarm = area.get("Alarm", 0)
        
        if alarm > 0:
            return "mdi:shield-alert"
        if armed == AREA_ARMED_DISARMED:
            return "mdi:shield-off"
        return "mdi:shield-check"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        area = self.coordinator.get_area(self._device_id, self._area_id)
        if not area:
            return {}
        
        return {
            ATTR_DEVICE_ID: self._device_id,
            ATTR_AREA_ID: self._area_id,
            "armed_value": area.get("Armed"),
            "alarm": area.get("Alarm", 0) > 0,
            ATTR_ALARM_MEMORY: area.get("AlarmMemory", 0) > 0,
            "tamper": area.get("Tamper", 0) > 0,
            ATTR_TAMPER_MEMORY: area.get("TamperMemory", 0) > 0,
            "auto_insert": area.get("AutoInsert", 0) > 0,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
