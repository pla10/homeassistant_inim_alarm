"""Alarm Control Panel platform for INIM Alarm."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import InimApi
from .const import (
    ATTR_DEVICE_ID,
    ATTR_FIRMWARE,
    ATTR_MODEL,
    ATTR_SERIAL_NUMBER,
    ATTR_VOLTAGE,
    CONF_ARM_AWAY_SCENARIO,
    CONF_ARM_HOME_SCENARIO,
    CONF_DISARM_SCENARIO,
    CONF_SCAN_INTERVAL,
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
        if device_id:
            entities.append(
                InimAlarmControlPanel(
                    coordinator=coordinator,
                    api=api,
                    device_id=device_id,
                    entry_id=entry.entry_id,
                    options=options,
                )
            )

    async_add_entities(entities)


class InimAlarmControlPanel(
    CoordinatorEntity[InimDataUpdateCoordinator], AlarmControlPanelEntity
):
    """Representation of an INIM Alarm Control Panel."""

    _attr_has_entity_name = True
    _attr_name = None  # Use device name
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_AWAY
    )
    _attr_code_arm_required = False

    def __init__(
        self,
        coordinator: InimDataUpdateCoordinator,
        api: InimApi,
        device_id: int,
        entry_id: str,
        options: dict | None = None,
    ) -> None:
        """Initialize the alarm control panel."""
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_id
        self._entry_id = entry_id
        self._options = options or {}
        self._attr_unique_id = f"{device_id}_alarm"
        
        # Get scenarios from device
        device = coordinator.get_device(device_id)
        self._scenarios = device.get("scenarios", []) if device else []
        
        # Get configured scenarios (required, no auto-detect)
        self._arm_away_scenario = self._options.get(CONF_ARM_AWAY_SCENARIO, 0)
        self._arm_home_scenario = self._options.get(CONF_ARM_HOME_SCENARIO, 2)
        self._disarm_scenario = self._options.get(CONF_DISARM_SCENARIO, 1)

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
        """Return the state of the alarm."""
        device = self.coordinator.get_device(self._device_id)
        if not device:
            return None
        
        active_scenario = device.get("active_scenario")
        
        if active_scenario is None:
            return None
        
        # Check areas for alarm state first
        areas = device.get("areas", [])
        for area in areas:
            if area.get("Alarm", False):
                return AlarmControlPanelState.TRIGGERED
        
        # Check scenario states
        if active_scenario == self._disarm_scenario:
            return AlarmControlPanelState.DISARMED
        
        if active_scenario == self._arm_away_scenario:
            return AlarmControlPanelState.ARMED_AWAY
        
        if active_scenario == self._arm_home_scenario:
            return AlarmControlPanelState.ARMED_HOME
        
        # Unknown scenario - check if any area is armed
        for area in areas:
            if area.get("Armed", 4) != 4:  # 4 = disarmed
                return AlarmControlPanelState.ARMED_AWAY
        
        return AlarmControlPanelState.DISARMED

    def _get_scenario_name(self, scenario_id: int) -> str:
        """Get scenario name by ID."""
        for scenario in self._scenarios:
            if scenario.get("ScenarioId") == scenario_id:
                return scenario.get("Name", f"Scenario {scenario_id}")
        return f"Scenario {scenario_id}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        device = self.coordinator.get_device(self._device_id)
        if not device:
            return {}
        
        active_scenario = self.coordinator.get_active_scenario(self._device_id)
        polling_interval = self._options.get(CONF_SCAN_INTERVAL, 30)
        
        attrs = {
            # Device info
            ATTR_DEVICE_ID: self._device_id,
            ATTR_SERIAL_NUMBER: device.get("serial_number"),
            ATTR_MODEL: device.get("model"),
            ATTR_FIRMWARE: device.get("firmware"),
            ATTR_VOLTAGE: device.get("voltage"),
            
            # Current state
            "active_scenario_id": device.get("active_scenario"),
            "active_scenario_name": active_scenario.get("Name") if active_scenario else None,
            "network_status": device.get("network_status"),
            "faults": device.get("faults"),
            
            # Configuration
            "polling_interval_seconds": polling_interval,
            "configured_arm_away": self._get_scenario_name(self._arm_away_scenario),
            "configured_arm_home": self._get_scenario_name(self._arm_home_scenario),
            "configured_disarm": self._get_scenario_name(self._disarm_scenario),
        }
        
        # Add available scenarios
        scenarios_info = [
            {"id": s.get("ScenarioId"), "name": s.get("Name")}
            for s in self._scenarios
        ]
        attrs["available_scenarios"] = scenarios_info
        
        return attrs

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command."""
        _LOGGER.info(
            "Disarming alarm for device %s (scenario: %s)", 
            self._device_id, 
            self._get_scenario_name(self._disarm_scenario)
        )
        await self._api.activate_scenario(self._device_id, self._disarm_scenario)
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm home command (partial arm)."""
        _LOGGER.info(
            "Arming home for device %s (scenario: %s)", 
            self._device_id,
            self._get_scenario_name(self._arm_home_scenario)
        )
        await self._api.activate_scenario(self._device_id, self._arm_home_scenario)
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command (full arm)."""
        _LOGGER.info(
            "Arming away for device %s (scenario: %s)", 
            self._device_id,
            self._get_scenario_name(self._arm_away_scenario)
        )
        await self._api.activate_scenario(self._device_id, self._arm_away_scenario)
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
