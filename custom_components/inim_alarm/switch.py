"""Switch platform for INIM Alarm - Zone bypass switches."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import InimApi, InimApiError
from .const import CONF_USER_CODE, DOMAIN, MANUFACTURER
from .coordinator import InimDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up INIM bypass switches from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: InimDataUpdateCoordinator = data["coordinator"]
    api: InimApi = data["api"]
    options: dict = data.get("options", {})

    entities = []
    
    for device in coordinator.devices:
        device_id = device.get("device_id")
        zones = device.get("zones", [])
        
        if device_id and zones:
            for zone in zones:
                zone_id = zone.get("ZoneId")
                zone_name = zone.get("Name")
                
                if zone_id is not None and zone_name:
                    entities.append(
                        InimBypassSwitch(
                            coordinator=coordinator,
                            api=api,
                            device_id=device_id,
                            zone_id=zone_id,
                            zone_name=zone_name,
                            options=options,
                        )
                    )

    async_add_entities(entities)


class InimBypassSwitch(
    CoordinatorEntity[InimDataUpdateCoordinator], SwitchEntity
):
    """Representation of an INIM Zone Bypass Switch."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-off-outline"

    def __init__(
        self,
        coordinator: InimDataUpdateCoordinator,
        api: InimApi,
        device_id: int,
        zone_id: int,
        zone_name: str,
        options: dict | None = None,
    ) -> None:
        """Initialize the bypass switch."""
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_id
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._options = options or {}
        
        self._attr_unique_id = f"{device_id}_bypass_{zone_id}"
        self._attr_name = f"Bypass {zone_name}"

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
        """Return true if zone is bypassed."""
        zone = self.coordinator.get_zone(self._device_id, self._zone_id)
        if not zone:
            return None
        
        # Bypassed = Mode 3
        return zone.get("Bypass", False)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        zone = self.coordinator.get_zone(self._device_id, self._zone_id)
        if not zone:
            return {}
        
        return {
            "zone_id": self._zone_id,
            "zone_name": self._zone_name,
            "status": zone.get("Status"),
            "alarm_memory": zone.get("AlarmMemory"),
            "tamper_memory": zone.get("TamperMemory"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch - bypass the zone."""
        user_code = self._options.get(CONF_USER_CODE, "")
        
        if not user_code:
            _LOGGER.error(
                "Cannot bypass zone %s: No user code configured. "
                "Set it in integration options.",
                self._zone_name
            )
            return
        
        _LOGGER.info("Bypassing zone '%s' (ID: %s)", self._zone_name, self._zone_id)
        
        try:
            await self._api.bypass_zone(self._device_id, self._zone_id, user_code, bypass=True)
            await self.coordinator.async_request_refresh()
        except InimApiError as err:
            _LOGGER.error("Failed to bypass zone %s: %s", self._zone_name, err)
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch - reinstate the zone."""
        user_code = self._options.get(CONF_USER_CODE, "")
        
        if not user_code:
            _LOGGER.error(
                "Cannot reinstate zone %s: No user code configured. "
                "Set it in integration options.",
                self._zone_name
            )
            return
        
        _LOGGER.info("Reinstating zone '%s' (ID: %s)", self._zone_name, self._zone_id)
        
        try:
            await self._api.bypass_zone(self._device_id, self._zone_id, user_code, bypass=False)
            await self.coordinator.async_request_refresh()
        except InimApiError as err:
            _LOGGER.error("Failed to reinstate zone %s: %s", self._zone_name, err)
            raise
