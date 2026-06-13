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
    ATTR_LAST_CHANGED_AT,
    ATTR_LAST_CHANGED_BY,
    ATTR_MODEL,
    ATTR_SERIAL_NUMBER,
    ATTR_VOLTAGE,
    CONF_AREA_SCENARIOS,
    CONF_ARM_AWAY_SCENARIO,
    CONF_ARM_HOME_SCENARIO,
    CONF_AWAY_ONLY_AREAS,
    CONF_DISARM_SCENARIO,
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
    Supports Armed Home, Armed Away and Disarmed states.
    """

    _attr_has_entity_name = True
    _attr_name = None  # Use device name
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_HOME | 
        AlarmControlPanelEntityFeature.ARM_AWAY
    )
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
        
        # Track arming state and mode
        self._pending_state: AlarmControlPanelState | None = None
        self._armed_mode: str = "home"  # "home" or "away" - default to home

    def _configured_scenario(self, conf_key: str) -> int | None:
        """Return the scenario ID mapped to an action, or None if unset."""
        value = self._options.get(conf_key)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            _LOGGER.warning("Invalid scenario configured for %s: %r", conf_key, value)
            return None

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
        # If we have a pending state (arming in progress), return it
        if self._pending_state is not None:
            return self._pending_state
        
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
            # Return armed state based on the mode set when arming
            if self._armed_mode == "away":
                return AlarmControlPanelState.ARMED_AWAY
            return AlarmControlPanelState.ARMED_HOME
        
        # Reset armed mode to default when disarmed
        self._armed_mode = "home"
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
        
        # Get last changed info from coordinator
        entity_key = f"{self._device_id}_alarm"
        last_changed_by = self.coordinator.get_last_changed_by(entity_key)
        last_changed_at = self.coordinator.get_last_changed_at(entity_key)
        
        attrs = {
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
            ATTR_LAST_CHANGED_BY: last_changed_by,
        }
        
        if last_changed_at:
            attrs[ATTR_LAST_CHANGED_AT] = last_changed_at.isoformat()
        
        return attrs

    async def _async_run_action(
        self, action: str, conf_key: str, arm: bool
    ) -> bool:
        """Run an arm/disarm action via scenario (if mapped) or InsertAreas.

        Returns True if a command was sent, False otherwise.
        """
        scenario_id = self._configured_scenario(conf_key)

        # Register that this command is from Home Assistant
        self.coordinator.register_ha_command(self._device_id, None)

        if scenario_id is not None:
            _LOGGER.info(
                "%s device %s via scenario %s", action, self._device_id, scenario_id
            )
            await self._api.activate_scenario(self._device_id, scenario_id)
            return True

        # Fallback: arm/disarm every configured area the same way
        if not self._user_code:
            _LOGGER.error(
                "Cannot %s: configure a scenario in the integration options "
                "or set the user code.",
                action.lower(),
            )
            return False
        if not self._area_ids:
            _LOGGER.warning("No configured areas to %s", action.lower())
            return False

        _LOGGER.info(
            "%s all areas for device %s (areas: %s)",
            action,
            self._device_id,
            self._area_ids,
        )
        await self._api.insert_areas(
            self._device_id, self._area_ids, self._user_code, arm=arm
        )
        return True

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command for all areas."""
        await self._async_run_action("Disarming", CONF_DISARM_SCENARIO, arm=False)
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm home command (partial protection or mapped scenario)."""
        self._pending_state = AlarmControlPanelState.ARMING
        self._armed_mode = "home"
        self.async_write_ha_state()

        if not await self._async_run_action(
            "Arming HOME", CONF_ARM_HOME_SCENARIO, arm=True
        ):
            self._pending_state = None
            self.async_write_ha_state()
            return

        self._pending_state = None
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command (full protection or mapped scenario)."""
        self._pending_state = AlarmControlPanelState.ARMING
        self._armed_mode = "away"
        self.async_write_ha_state()

        if not await self._async_run_action(
            "Arming AWAY", CONF_ARM_AWAY_SCENARIO, arm=True
        ):
            self._pending_state = None
            self.async_write_ha_state()
            return

        self._pending_state = None
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Clear pending state when coordinator updates
        self._pending_state = None
        self.async_write_ha_state()


class InimAreaAlarmControlPanel(
    CoordinatorEntity[InimDataUpdateCoordinator], AlarmControlPanelEntity
):
    """Representation of an INIM Area Alarm Control Panel (per-area control)."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_HOME | 
        AlarmControlPanelEntityFeature.ARM_AWAY
    )
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
        
        # Track arming state and mode
        self._pending_state: AlarmControlPanelState | None = None
        self._armed_mode: str = "home"  # "home" or "away" - default to home

        away_only_areas = {
            str(value)
            for value in self._options.get(CONF_AWAY_ONLY_AREAS, [])
        }
        self._away_only = str(area_id) in away_only_areas
        if self._away_only:
            self._attr_supported_features = AlarmControlPanelEntityFeature.ARM_AWAY

    def _configured_scenario(self, conf_key: str) -> int | None:
        """Return the scenario explicitly mapped to this area's action."""
        area_ref = f"{self._device_id}:{self._area_id}"
        mapping = self._options.get(CONF_AREA_SCENARIOS, {}).get(area_ref, {})
        value = mapping.get(conf_key)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            _LOGGER.warning(
                "Invalid scenario configured for area %s action %s: %r",
                area_ref,
                conf_key,
                value,
            )
            return None

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
        # If we have a pending state (arming in progress), return it
        if self._pending_state is not None:
            return self._pending_state
        
        area = self.coordinator.get_area(self._device_id, self._area_id)
        if not area:
            return None
        
        # Check for alarm first
        if area.get("Alarm", False):
            return AlarmControlPanelState.TRIGGERED
        
        # Armed status: 1 = armed, 4 = disarmed
        armed = area.get("Armed", AREA_ARMED_DISARMED)
        
        if armed == AREA_ARMED_DISARMED:
            # Reset armed mode to default when disarmed
            self._armed_mode = "home"
            return AlarmControlPanelState.DISARMED

        if self._away_only:
            # Away-only areas cannot represent an armed-home state in Home Assistant.
            self._armed_mode = "away"
            return AlarmControlPanelState.ARMED_AWAY

        # Return armed state based on the mode set when arming
        if self._armed_mode == "away":
            return AlarmControlPanelState.ARMED_AWAY
        return AlarmControlPanelState.ARMED_HOME

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        area = self.coordinator.get_area(self._device_id, self._area_id)
        if not area:
            return {}
        
        # Get last changed info from coordinator
        entity_key = f"{self._device_id}_area_{self._area_id}"
        last_changed_by = self.coordinator.get_last_changed_by(entity_key)
        last_changed_at = self.coordinator.get_last_changed_at(entity_key)
        
        attrs = {
            ATTR_DEVICE_ID: self._device_id,
            ATTR_AREA_ID: self._area_id,
            "alarm": area.get("Alarm", False),
            "alarm_memory": area.get("AlarmMemory", False),
            "tamper": area.get("Tamper", False),
            "tamper_memory": area.get("TamperMemory", False),
            "auto_insert": area.get("AutoInsert", False),
            ATTR_LAST_CHANGED_BY: last_changed_by,
        }
        
        if last_changed_at:
            attrs[ATTR_LAST_CHANGED_AT] = last_changed_at.isoformat()
        
        return attrs

    async def _async_run_action(
        self, action: str, conf_key: str, arm: bool
    ) -> bool:
        """Run an area action via its mapped scenario or InsertAreas fallback."""
        scenario_id = self._configured_scenario(conf_key)
        if scenario_id is not None:
            self.coordinator.register_ha_command(self._device_id, self._area_id)
            _LOGGER.info(
                "%s area '%s' via scenario %s",
                action,
                self._area_name,
                scenario_id,
            )
            await self._api.activate_scenario(self._device_id, scenario_id)
            return True

        if not self._user_code:
            _LOGGER.error(
                "Cannot %s area %s: configure an area scenario or set the user code.",
                action.lower(),
                self._area_name,
            )
            return False

        self.coordinator.register_ha_command(self._device_id, self._area_id)
        _LOGGER.info(
            "%s area '%s' via InsertAreas (ID: %s)",
            action,
            self._area_name,
            self._area_id,
        )
        await self._api.insert_areas(
            self._device_id,
            [self._area_id],
            self._user_code,
            arm=arm,
        )
        return True

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command for this area."""
        if await self._async_run_action(
            "Disarming", CONF_DISARM_SCENARIO, arm=False
        ):
            await self.coordinator.async_request_refresh()

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm home command for this area (partial protection)."""
        if self._away_only:
            _LOGGER.warning(
                "Cannot arm area %s in Home mode: area is configured as Away-only",
                self._area_name,
            )
            return

        self._pending_state = AlarmControlPanelState.ARMING
        self._armed_mode = "home"
        self.async_write_ha_state()

        if not await self._async_run_action(
            "Arming HOME", CONF_ARM_HOME_SCENARIO, arm=True
        ):
            self._pending_state = None
            self.async_write_ha_state()
            return

        self._pending_state = None
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command for this area (full protection)."""
        self._pending_state = AlarmControlPanelState.ARMING
        self._armed_mode = "away"
        self.async_write_ha_state()

        if not await self._async_run_action(
            "Arming AWAY", CONF_ARM_AWAY_SCENARIO, arm=True
        ):
            self._pending_state = None
            self.async_write_ha_state()
            return

        self._pending_state = None
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Clear pending state when coordinator updates
        self._pending_state = None
        self.async_write_ha_state()
