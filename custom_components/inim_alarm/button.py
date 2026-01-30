"""Button platform for INIM Alarm - Scenario buttons."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import InimApi, InimApiError
from .const import DOMAIN, MANUFACTURER
from .coordinator import InimDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up INIM scenario buttons from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: InimDataUpdateCoordinator = data["coordinator"]
    api: InimApi = data["api"]

    entities = []
    
    for device in coordinator.devices:
        device_id = device.get("device_id")
        scenarios = device.get("scenarios", [])
        
        if device_id and scenarios:
            for scenario in scenarios:
                scenario_id = scenario.get("ScenarioId")
                scenario_name = scenario.get("Name")
                
                if scenario_id is not None and scenario_name:
                    entities.append(
                        InimScenarioButton(
                            coordinator=coordinator,
                            api=api,
                            device_id=device_id,
                            scenario_id=scenario_id,
                            scenario_name=scenario_name,
                        )
                    )

    async_add_entities(entities)


class InimScenarioButton(
    CoordinatorEntity[InimDataUpdateCoordinator], ButtonEntity
):
    """Representation of an INIM Scenario Button.
    
    Disabled by default for security - these buttons don't require PIN.
    Users can enable them manually in Settings → Devices → Show disabled entities.
    """

    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False  # Disabled for security

    def __init__(
        self,
        coordinator: InimDataUpdateCoordinator,
        api: InimApi,
        device_id: int,
        scenario_id: int,
        scenario_name: str,
    ) -> None:
        """Initialize the scenario button."""
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_id
        self._scenario_id = scenario_id
        self._scenario_name = scenario_name
        
        self._attr_unique_id = f"{device_id}_scenario_{scenario_id}"
        self._attr_name = f"Scenario {scenario_name}"
        self._attr_icon = self._get_icon()

    def _get_icon(self) -> str:
        """Get appropriate icon based on scenario name."""
        name_upper = self._scenario_name.upper()
        
        if "SPENTO" in name_upper or "OFF" in name_upper:
            return "mdi:shield-off"
        elif "TOTALE" in name_upper or "TOTAL" in name_upper:
            return "mdi:shield-lock"
        else:
            return "mdi:shield-home"

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
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        device = self.coordinator.get_device(self._device_id)
        active_scenario = device.get("active_scenario") if device else None
        
        return {
            "scenario_id": self._scenario_id,
            "scenario_name": self._scenario_name,
            "is_active": active_scenario == self._scenario_id,
        }

    async def async_press(self) -> None:
        """Handle the button press - activate this scenario."""
        _LOGGER.info(
            "Activating scenario '%s' (ID: %s) on device %s",
            self._scenario_name,
            self._scenario_id,
            self._device_id,
        )
        
        try:
            await self._api.activate_scenario(self._device_id, self._scenario_id)
            await self.coordinator.async_request_refresh()
        except InimApiError as err:
            _LOGGER.error("Failed to activate scenario %s: %s", self._scenario_name, err)
            raise
