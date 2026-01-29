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
    CONF_ARM_AWAY_SCENARIO,
    CONF_ARM_HOME_SCENARIO,
    CONF_DISARM_SCENARIO,
    CONF_SCAN_INTERVAL,
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
    options: dict = data.get("options", {})

    entities = []
    
    for device in coordinator.devices:
        device_id = device.get("device_id")
        if device_id:
            # Main alarm panel (device-level)
            entities.append(
                InimAlarmControlPanel(
                    coordinator=coordinator,
                    api=api,
                    device_id=device_id,
                    entry_id=entry.entry_id,
                    options=options,
                )
            )
            
            # Area-specific alarm panels
            for area in device.get("areas", []):
                area_id = area.get("AreaId")
                area_name = area.get("Name")
                if area_id is not None and area_name:
                    entities.append(
                        InimAreaAlarmControlPanel(
                            coordinator=coordinator,
                            api=api,
                            device_id=device_id,
                            area_id=area_id,
                            area_name=area_name,
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
        
        # Get device info
        device = coordinator.get_device(device_id)
        if device:
            self._scenarios = device.get("scenarios", [])
            
            # Use configured scenarios if set, otherwise auto-detect
            configured_away = self._options.get(CONF_ARM_AWAY_SCENARIO, -1)
            configured_home = self._options.get(CONF_ARM_HOME_SCENARIO, -1)
            configured_disarm = self._options.get(CONF_DISARM_SCENARIO, -1)
            
            # Arm Away scenario
            if configured_away >= 0:
                self._arm_away_scenario = configured_away
            else:
                self._arm_away_scenario = self._find_scenario_id("TOTALE", SCENARIO_TOTAL)
            
            # Disarm scenario
            if configured_disarm >= 0:
                self._disarm_scenario = configured_disarm
            else:
                self._disarm_scenario = self._find_scenario_id("SPENTO", SCENARIO_DISARMED)
            
            # Arm Home scenario
            if configured_home >= 0:
                self._arm_home_scenario = configured_home
                self._arm_home_scenarios = [configured_home]
            else:
                self._arm_home_scenarios = self._find_partial_scenarios()
                self._arm_home_scenario = self._arm_home_scenarios[0] if self._arm_home_scenarios else self._arm_away_scenario

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
        
        # Get configured values
        configured_away = self._options.get(CONF_ARM_AWAY_SCENARIO, -1)
        configured_home = self._options.get(CONF_ARM_HOME_SCENARIO, -1)
        configured_disarm = self._options.get(CONF_DISARM_SCENARIO, -1)
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
            "configured_arm_away": self._get_scenario_name(self._arm_away_scenario) if configured_away >= 0 else f"Auto ({self._get_scenario_name(self._arm_away_scenario)})",
            "configured_arm_home": self._get_scenario_name(self._arm_home_scenario) if configured_home >= 0 else f"Auto ({self._get_scenario_name(self._arm_home_scenario)})",
            "configured_disarm": self._get_scenario_name(self._disarm_scenario) if configured_disarm >= 0 else f"Auto ({self._get_scenario_name(self._disarm_scenario)})",
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


class InimAreaAlarmControlPanel(
    CoordinatorEntity[InimDataUpdateCoordinator], AlarmControlPanelEntity
):
    """Representation of an INIM Area-specific Alarm Control Panel."""

    _attr_has_entity_name = True
    _attr_supported_features = AlarmControlPanelEntityFeature(0)  # Read-only, control via scenarios
    _attr_code_arm_required = False

    def __init__(
        self,
        coordinator: InimDataUpdateCoordinator,
        api: InimApi,
        device_id: int,
        area_id: int,
        area_name: str,
        entry_id: str,
        options: dict | None = None,
    ) -> None:
        """Initialize the area alarm control panel."""
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_id
        self._area_id = area_id
        self._area_name = area_name
        self._entry_id = entry_id
        self._options = options or {}
        self._attr_unique_id = f"{device_id}_area_{area_id}"
        self._attr_name = area_name
        self._attr_translation_key = "area_alarm"

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
        """Return the state of this area."""
        area = self.coordinator.get_area(self._device_id, self._area_id)
        if not area:
            return None
        
        # Check for alarm condition first
        if area.get("Alarm", False):
            return AlarmControlPanelState.TRIGGERED
        
        # Check armed status
        # Armed values: 1=armed (totale), 4=disarmed
        # Partial: other values (2, 3, etc.)
        armed_status = area.get("Armed", 4)
        
        if armed_status == 4:
            return AlarmControlPanelState.DISARMED
        elif armed_status == 1:
            return AlarmControlPanelState.ARMED_AWAY
        else:
            # Any other armed state is partial/home
            return AlarmControlPanelState.ARMED_HOME

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        area = self.coordinator.get_area(self._device_id, self._area_id)
        if not area:
            return {}
        
        return {
            "area_id": self._area_id,
            "area_name": self._area_name,
            "armed_raw": area.get("Armed"),
            "alarm": area.get("Alarm"),
            "alarm_memory": area.get("AlarmMemory"),
            "tamper": area.get("Tamper"),
            "tamper_memory": area.get("TamperMemory"),
            "ready": area.get("Ready"),
            "fault": area.get("Fault"),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
