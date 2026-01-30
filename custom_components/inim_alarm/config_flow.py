"""Config flow for INIM Alarm integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import InimApi, InimApiError, InimAuthError
from .const import (
    CONF_ARM_AWAY_SCENARIO,
    CONF_ARM_HOME_SCENARIO,
    CONF_DISARM_SCENARIO,
    CONF_SCAN_INTERVAL,
    CONF_USER_CODE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Setup schema includes user_code for API operations
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_USER_CODE): str,  # Required for bypass/area control
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    session = async_get_clientsession(hass)
    api = InimApi(
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        session=session,
    )

    try:
        await api.authenticate()
        devices = await api.get_devices()
        
        if not devices:
            raise InimApiError("No devices found")
        
        # Get the first device info for the title
        first_device = devices[0]
        title = first_device.get("Name", "INIM Alarm")
        
        return {
            "title": title,
            "device_count": len(devices),
        }
        
    except InimAuthError as err:
        raise InvalidAuth from err
    except InimApiError as err:
        raise CannotConnect from err


class InimAlarmConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for INIM Alarm."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return InimAlarmOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Check if already configured
                await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=info["title"],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle reauthorization."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reauthorization confirmation."""
        errors: dict[str, str] = {}

        if user_input is not None:
            reauth_entry = self._get_reauth_entry()
            
            try:
                await validate_input(
                    self.hass,
                    {
                        CONF_USERNAME: reauth_entry.data[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={
                        **reauth_entry.data,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""


class InimAlarmOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for INIM Alarm."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self._scenarios: list[dict[str, Any]] = []

    def _find_scenario_by_name(self, name: str, default: int) -> int:
        """Find scenario ID by name."""
        for scenario in self._scenarios:
            if name.upper() in scenario.get("Name", "").upper():
                return scenario.get("ScenarioId", default)
        if self._scenarios:
            return self._scenarios[0].get("ScenarioId", default)
        return default

    def _find_first_partial_scenario(self, default: int) -> int:
        """Find first partial scenario (not TOTALE or SPENTO)."""
        for scenario in self._scenarios:
            name = scenario.get("Name", "").upper()
            if name not in ("TOTALE", "SPENTO"):
                return scenario.get("ScenarioId", default)
        return default

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        # Get current scenarios from the coordinator
        if DOMAIN in self.hass.data and self.config_entry.entry_id in self.hass.data[DOMAIN]:
            coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id].get("coordinator")
            if coordinator and coordinator.data:
                devices = coordinator.data.get("devices", [])
                if devices:
                    self._scenarios = devices[0].get("scenarios", [])

        # Build scenario options for dropdown
        scenario_options = {}
        for scenario in self._scenarios:
            scenario_id = scenario.get("ScenarioId")
            scenario_name = scenario.get("Name", f"Scenario {scenario_id}")
            if scenario_id is not None:
                scenario_options[scenario_id] = scenario_name

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Get current values with reasonable defaults
        current_scan = self.config_entry.options.get(CONF_SCAN_INTERVAL, 30)
        
        # Default scenarios
        default_arm_away = self.config_entry.options.get(
            CONF_ARM_AWAY_SCENARIO, 
            self._find_scenario_by_name("TOTALE", 0)
        )
        default_disarm = self.config_entry.options.get(
            CONF_DISARM_SCENARIO, 
            self._find_scenario_by_name("SPENTO", 1)
        )
        default_arm_home = self.config_entry.options.get(
            CONF_ARM_HOME_SCENARIO, 
            self._find_first_partial_scenario(2)
        )

        # Options: only scan interval and scenarios (no codes - they're in setup)
        options_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=current_scan,
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
                vol.Required(
                    CONF_ARM_AWAY_SCENARIO,
                    default=default_arm_away,
                ): vol.In(scenario_options),
                vol.Required(
                    CONF_ARM_HOME_SCENARIO,
                    default=default_arm_home,
                ): vol.In(scenario_options),
                vol.Required(
                    CONF_DISARM_SCENARIO,
                    default=default_disarm,
                ): vol.In(scenario_options),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,
        )
