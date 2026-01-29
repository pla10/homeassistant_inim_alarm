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
    ATTR_SCENARIO_ID,
    ATTR_SERIAL_NUMBER,
    ATTR_VOLTAGE,
    DOMAIN,
    MANUFACTURER,
    SCENARIO_DISARMED,
    SCENARIO_TOTAL,
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
    ) -> None:
        """Initialize the alarm control panel."""
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_id
        self._entry_id = entry_id
        self._attr_unique_id = f"{device_id}_alarm"
        
        # Get device info
        device = coordinator.get_device(device_id)
        if device:
            self._scenarios = device.get("scenarios", [])
            self._arm_away_scenario = self._find_scenario_id("TOTALE", SCENARIO_TOTAL)
            self._disarm_scenario = self._find_scenario_id("SPENTO", SCENARIO_DISARMED)
            self._arm_home_scenarios = self._find_partial_scenarios()

    def _find_scenario_id(self, name: str, default: int) -> int:
        """Find scenario ID by name or return default."""
        for scenario in self._scenarios:
            if name.lower() in scenario.get("Name", "").lower():
                return scenario.get("ScenarioId", default)
        return default

    def _find_partial_scenarios(self) -> list[int]:
        """Find partial arm scenarios (not TOTALE or SPENTO)."""
        partial = []
        for scenario in self._scenarios:
            scenario_id = scenario.get("ScenarioId")
            name = scenario.get("Name", "").upper()
            if scenario_id is not None and name not in ("TOTALE", "SPENTO"):
                partial.append(scenario_id)
        return partial

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
        
        # Check if disarmed
        if active_scenario == self._disarm_scenario:
            return AlarmControlPanelState.DISARMED
        
        # Check if fully armed (away)
        if active_scenario == self._arm_away_scenario:
            return AlarmControlPanelState.ARMED_AWAY
        
        # Check if partially armed (home)
        if active_scenario in self._arm_home_scenarios:
            return AlarmControlPanelState.ARMED_HOME
        
        # Check areas for alarm state
        areas = device.get("areas", [])
        for area in areas:
            if area.get("Alarm", 0) > 0:
                return AlarmControlPanelState.TRIGGERED
        
        # Default to armed_away if scenario is unknown but not disarmed
        return AlarmControlPanelState.ARMED_AWAY

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        device = self.coordinator.get_device(self._device_id)
        if not device:
            return {}
        
        active_scenario = self.coordinator.get_active_scenario(self._device_id)
        
        attrs = {
            ATTR_DEVICE_ID: self._device_id,
            ATTR_SERIAL_NUMBER: device.get("serial_number"),
            ATTR_MODEL: device.get("model"),
            ATTR_FIRMWARE: device.get("firmware"),
            ATTR_VOLTAGE: device.get("voltage"),
            "active_scenario_id": device.get("active_scenario"),
            "active_scenario_name": active_scenario.get("Name") if active_scenario else None,
            "network_status": device.get("network_status"),
            "faults": device.get("faults"),
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
        _LOGGER.info("Disarming alarm for device %s", self._device_id)
        await self._api.disarm(self._device_id, self._disarm_scenario)
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm home command (partial arm)."""
        _LOGGER.info("Arming home for device %s", self._device_id)
        # Use the first partial scenario if available, otherwise use away
        if self._arm_home_scenarios:
            scenario_id = self._arm_home_scenarios[0]
        else:
            scenario_id = self._arm_away_scenario
        await self._api.arm_home(self._device_id, scenario_id)
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command (full arm)."""
        _LOGGER.info("Arming away for device %s", self._device_id)
        await self._api.arm_away(self._device_id, self._arm_away_scenario)
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
