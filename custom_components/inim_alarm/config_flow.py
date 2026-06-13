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
from homeassistant.helpers import config_validation as cv, selector

from .const import (
    CONF_ARM_AWAY_SCENARIO,
    CONF_ARM_HOME_SCENARIO,
    CONF_AWAY_ONLY_AREAS,
    CONF_DISARM_SCENARIO,
    CONF_ENABLE_SIA,
    CONF_SCAN_INTERVAL,
    CONF_SIA_ACCOUNT,
    CONF_SIA_PORT,
    CONF_USER_CODE,
    DEFAULT_SIA_PORT,
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

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Get current values
        current_scan = self.config_entry.options.get(CONF_SCAN_INTERVAL, 30)

        current_sia = self.config_entry.options.get(
            CONF_ENABLE_SIA,
            self.config_entry.data.get(CONF_ENABLE_SIA, False),
        )
        current_sia_port = self.config_entry.options.get(
            CONF_SIA_PORT,
            self.config_entry.data.get(CONF_SIA_PORT, DEFAULT_SIA_PORT),
        )
        current_sia_account = self.config_entry.options.get(
            CONF_SIA_ACCOUNT,
            self.config_entry.data.get(CONF_SIA_ACCOUNT, ""),
        )

        # Build the scenario list from the coordinator so users pick by name.
        scenario_options = self._build_scenario_options()
        area_options = self._build_area_options()

        scenario_schema: dict[Any, Any] = {}
        if scenario_options:
            scenario_selector = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=scenario_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
            for key in (
                CONF_ARM_AWAY_SCENARIO,
                CONF_ARM_HOME_SCENARIO,
                CONF_DISARM_SCENARIO,
            ):
                current = self.config_entry.options.get(key)
                field = (
                    vol.Optional(key, default=current)
                    if current is not None
                    else vol.Optional(key)
                )
                scenario_schema[field] = scenario_selector

        area_schema: dict[Any, Any] = {}
        if area_options:
            current_away_only = self.config_entry.options.get(
                CONF_AWAY_ONLY_AREAS, []
            )
            area_schema[
                vol.Optional(
                    CONF_AWAY_ONLY_AREAS,
                    default=current_away_only,
                )
            ] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=area_options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )

        options_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=current_scan,
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
                vol.Optional(
                    CONF_ENABLE_SIA,
                    default=current_sia,
                ): bool,
                vol.Optional(
                    CONF_SIA_PORT,
                    default=current_sia_port,
                ): cv.port,
                vol.Optional(
                    CONF_SIA_ACCOUNT,
                    default=current_sia_account,
                ): str,
                **scenario_schema,
                **area_schema,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
        )

    def _build_scenario_options(self) -> list[selector.SelectOptionDict]:
        """Return panel scenarios as selector options (value=id, label=name)."""
        options: list[selector.SelectOptionDict] = []
        seen: set[str] = set()
        try:
            coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
            for device in coordinator.data.get("devices", []):
                for scenario in device.get("scenarios", []):
                    scenario_id = scenario.get("ScenarioId")
                    if scenario_id is None:
                        continue
                    value = str(scenario_id)
                    if value in seen:
                        continue
                    seen.add(value)
                    options.append(
                        selector.SelectOptionDict(
                            value=value,
                            label=scenario.get("Name", f"Scenario {scenario_id}"),
                        )
                    )
        except (KeyError, AttributeError, TypeError):
            pass
        return options

    def _build_area_options(self) -> list[selector.SelectOptionDict]:
        """Return alarm areas as selector options (value=id, label=name)."""
        options: list[selector.SelectOptionDict] = []
        seen: set[str] = set()
        try:
            coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
            for device in coordinator.data.get("devices", []):
                for area in device.get("areas", []):
                    area_id = area.get("AreaId")
                    if area_id is None:
                        continue
                    value = str(area_id)
                    if value in seen:
                        continue
                    seen.add(value)
                    options.append(
                        selector.SelectOptionDict(
                            value=value,
                            label=area.get("Name", f"Area {area_id}"),
                        )
                    )
        except (KeyError, AttributeError, TypeError):
            pass
        return options
