"""Alarm Control Panel platform for INIM Alarm."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import InimApi
from .const import (
    AREA_ARMED_DISARMED,
    ATTR_AREA_ID,
    ATTR_DEVICE_ID,
    ATTR_FIRMWARE,
    ATTR_MODEL,
    ATTR_SERIAL_NUMBER,
    ATTR_VOLTAGE,
    CONF_SCAN_INTERVAL,
    CONF_USER_CODE,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import InimDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up INIM alarm control panel from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: InimDataUpdateCoordinator = data["coordinator"]
    api: InimApi = data["api"]
    options: dict = data.get("options", {})

    entities = []
    
    for device in coordinator.devices:
        device_id = device.get("device_id")
        if not device_id:
            continue
        
        # Get all configured area IDs for the main panel
        areas = device.get("areas", [])
        area_ids = []
        for area in areas:
            area_id = area.get("AreaId")
            area_name = area.get("Name", f"Area {area_id}")
            # Only include areas with custom names (configured)
            if not (area_name.startswith("Area ") and area_name[5:].isdigit()):
                area_ids.append(area_id)
            
        # Main panel (uses InsertAreas on ALL configured areas)
        entities.append(
            InimAlarmControlPanel(
                coordinator=coordinator,
                api=api,
                device_id=device_id,
                area_ids=area_ids,
                options=options,
            )
        )
        
        # Individual area panels
        for area in areas:
            area_id = area.get("AreaId")
            area_name = area.get("Name", f"Area {area_id}")
            
            # Skip generic "Area X" names (not configured)
            if area_name.startswith("Area ") and area_name[5:].isdigit():
                continue
            
            entities.append(
                InimAreaAlarmControlPanel(
                    coordinator=coordinator,
                    api=api,
                    device_id=device_id,
                    area_id=area_id,
                    area_name=area_name,
                    options=options,
                )
            )

    async_add_entities(entities)


class InimAlarmControlPanel(
    CoordinatorEntity[InimDataUpdateCoordinator], AlarmControlPanelEntity
):
    """Representation of the main INIM Alarm Control Panel.
    
    Uses InsertAreas API to arm/disarm ALL configured areas at once.
    Only supports Armed Away and Disarmed states (simple UX).
    """

    _attr_has_entity_name = True
    _attr_name = None  # Use device name
    _attr_supported_features = AlarmControlPanelEntityFeature.ARM_AWAY
    _attr_code_format = CodeFormat.NUMBER  # Enable numeric keypad
    _attr_code_arm_required = False  # Code requirement managed by Lovelace card

    def __init__(
        self,
        coordinator: InimDataUpdateCoordinator,
        api: InimApi,
        device_id: int,
        area_ids: list[int],
        options: dict | None = None,
    ) -> None:
        """Initialize the alarm control panel."""
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_id
        self._area_ids = area_ids  # All configured areas
        self._options = options or {}
        self._attr_unique_id = f"{device_id}_alarm"
        
        # User code for API calls
        self._user_code = self._options.get(CONF_USER_CODE, "")

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
    def alarm_state(self) -> AlarmControlPanelState | None:
        """Return the state of the alarm based on all areas."""
        device = self.coordinator.get_device(self._device_id)
        if not device:
            return None
        
        areas = device.get("areas", [])
        
        # Check for alarm in any area first
        for area in areas:
            if area.get("Alarm", False):
                return AlarmControlPanelState.TRIGGERED
        
        # Check if all configured areas are disarmed
        all_disarmed = True
        any_armed = False
        
        for area in areas:
            area_id = area.get("AreaId")
            if area_id not in self._area_ids:
                continue  # Skip unconfigured areas
            
            armed = area.get("Armed", AREA_ARMED_DISARMED)
            if armed != AREA_ARMED_DISARMED:
                all_disarmed = False
                any_armed = True
        
        if any_armed:
            return AlarmControlPanelState.ARMED_AWAY
        
        return AlarmControlPanelState.DISARMED

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        device = self.coordinator.get_device(self._device_id)
        if not device:
            return {}
        
        polling_interval = self._options.get(CONF_SCAN_INTERVAL, 30)
        
        # Get area names for display
        area_names = []
        for area in device.get("areas", []):
            if area.get("AreaId") in self._area_ids:
                area_names.append(area.get("Name", f"Area {area.get('AreaId')}"))
        
        return {
            ATTR_DEVICE_ID: self._device_id,
            ATTR_SERIAL_NUMBER: device.get("serial_number"),
            ATTR_MODEL: device.get("model"),
            ATTR_FIRMWARE: device.get("firmware"),
            ATTR_VOLTAGE: device.get("voltage"),
            "network_status": device.get("network_status"),
            "faults": device.get("faults"),
            "polling_interval_seconds": polling_interval,
            "controlled_areas": area_names,
            "area_ids": self._area_ids,
        }

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command for all areas."""
        if not self._user_code:
            _LOGGER.error(
                "Cannot disarm: No user code configured. "
                "Reconfigure the integration to set the user code."
            )
            return
        
        if not self._area_ids:
            _LOGGER.warning("No configured areas to disarm")
            return
            
        _LOGGER.info(
            "Disarming all areas for device %s (areas: %s)", 
            self._device_id, 
            self._area_ids
        )
        await self._api.insert_areas(self._device_id, self._area_ids, self._user_code, arm=False)
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm command for all areas."""
        if not self._user_code:
            _LOGGER.error(
                "Cannot arm: No user code configured. "
                "Reconfigure the integration to set the user code."
            )
            return
        
        if not self._area_ids:
            _LOGGER.warning("No configured areas to arm")
            return
            
        _LOGGER.info(
            "Arming all areas for device %s (areas: %s)", 
            self._device_id,
            self._area_ids
        )
        await self._api.insert_areas(self._device_id, self._area_ids, self._user_code, arm=True)
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class InimAreaAlarmControlPanel(
    CoordinatorEntity[InimDataUpdateCoordinator], AlarmControlPanelEntity
):
    """Representation of an INIM Area Alarm Control Panel (per-area control)."""

    _attr_has_entity_name = True
    _attr_supported_features = AlarmControlPanelEntityFeature.ARM_AWAY
    _attr_code_format = CodeFormat.NUMBER  # Enable numeric keypad
    _attr_code_arm_required = False  # Code requirement managed by Lovelace card

    def __init__(
        self,
        coordinator: InimDataUpdateCoordinator,
        api: InimApi,
        device_id: int,
        area_id: int,
        area_name: str,
        options: dict | None = None,
    ) -> None:
        """Initialize the area alarm control panel."""
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_id
        self._area_id = area_id
        self._area_name = area_name
        self._options = options or {}
        
        self._attr_unique_id = f"{device_id}_area_{area_id}"
        self._attr_name = area_name
        
        # User code for API calls
        self._user_code = self._options.get(CONF_USER_CODE, "")

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
    def alarm_state(self) -> AlarmControlPanelState | None:
        """Return the state of the area."""
        area = self.coordinator.get_area(self._device_id, self._area_id)
        if not area:
            return None
        
        # Check for alarm first
        if area.get("Alarm", False):
            return AlarmControlPanelState.TRIGGERED
        
        # Armed status: 1 = armed, 4 = disarmed
        armed = area.get("Armed", AREA_ARMED_DISARMED)
        
        if armed == AREA_ARMED_DISARMED:
            return AlarmControlPanelState.DISARMED
        
        return AlarmControlPanelState.ARMED_AWAY

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        area = self.coordinator.get_area(self._device_id, self._area_id)
        if not area:
            return {}
        
        return {
            ATTR_DEVICE_ID: self._device_id,
            ATTR_AREA_ID: self._area_id,
            "alarm": area.get("Alarm", False),
            "alarm_memory": area.get("AlarmMemory", False),
            "tamper": area.get("Tamper", False),
            "tamper_memory": area.get("TamperMemory", False),
            "auto_insert": area.get("AutoInsert", False),
        }

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command for this area."""
        if not self._user_code:
            _LOGGER.error(
                "Cannot disarm area %s: No user code configured. "
                "Reconfigure the integration to set the user code.",
                self._area_name
            )
            return
            
        _LOGGER.info("Disarming area '%s' (ID: %s)", self._area_name, self._area_id)
        await self._api.insert_areas(self._device_id, [self._area_id], self._user_code, arm=False)
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm command for this area."""
        if not self._user_code:
            _LOGGER.error(
                "Cannot arm area %s: No user code configured. "
                "Reconfigure the integration to set the user code.",
                self._area_name
            )
            return
            
        _LOGGER.info("Arming area '%s' (ID: %s)", self._area_name, self._area_id)
        await self._api.insert_areas(self._device_id, [self._area_id], self._user_code, arm=True)
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
