"""The INIM Alarm integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import InimApi, InimApiError, InimAuthError
from .const import (
    ATTR_DEVICE_ID,
    ATTR_ZONE_ID,
    CONF_ARM_AWAY_SCENARIO,
    CONF_ARM_HOME_SCENARIO,
    CONF_DISARM_SCENARIO,
    CONF_SCAN_INTERVAL,
    CONF_USER_CODE,
    DOMAIN,
    PLATFORMS,
    SERVICE_BYPASS_ZONE,
)
from .coordinator import InimDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
]

DEFAULT_SCAN_INTERVAL_SECONDS = 30


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up INIM Alarm from a config entry."""
    session = async_get_clientsession(hass)
    
    api = InimApi(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        session=session,
    )

    try:
        await api.authenticate()
    except InimAuthError as err:
        raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
    except InimApiError as err:
        raise ConfigEntryNotReady(f"Failed to connect: {err}") from err

    # Get scan interval from options or use default
    scan_interval_seconds = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS)
    update_interval = timedelta(seconds=scan_interval_seconds)

    coordinator = InimDataUpdateCoordinator(hass, api, update_interval)
    
    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "options": {
            CONF_ARM_AWAY_SCENARIO: entry.options.get(CONF_ARM_AWAY_SCENARIO, -1),
            CONF_ARM_HOME_SCENARIO: entry.options.get(CONF_ARM_HOME_SCENARIO, -1),
            CONF_DISARM_SCENARIO: entry.options.get(CONF_DISARM_SCENARIO, -1),
            CONF_USER_CODE: entry.options.get(CONF_USER_CODE, ""),
        },
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    await async_register_services(hass)

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update - reload integration."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN].pop(entry.entry_id)
        api: InimApi = data["api"]
        await api.close()

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


# Service schemas
SERVICE_BYPASS_ZONE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.positive_int,
        vol.Required(ATTR_ZONE_ID): cv.positive_int,
        vol.Optional("bypass", default=True): cv.boolean,
        vol.Optional("user_code"): cv.string,
    }
)


async def async_register_services(hass: HomeAssistant) -> None:
    """Register services for INIM Alarm."""
    
    if hass.services.has_service(DOMAIN, SERVICE_BYPASS_ZONE):
        return  # Already registered

    async def handle_bypass_zone(call: ServiceCall) -> None:
        """Handle the bypass_zone service call."""
        device_id = call.data[ATTR_DEVICE_ID]
        zone_id = call.data[ATTR_ZONE_ID]
        bypass = call.data.get("bypass", True)
        user_code = call.data.get("user_code")

        # Find the API and user_code from config entries
        for entry_id, data in hass.data[DOMAIN].items():
            api: InimApi = data.get("api")
            if api:
                # Use provided code or get from options
                if not user_code:
                    user_code = data.get("options", {}).get(CONF_USER_CODE, "")
                
                if not user_code:
                    _LOGGER.error(
                        "No user code provided. Set it in integration options or provide it in service call"
                    )
                    return

                try:
                    await api.bypass_zone(device_id, zone_id, user_code, bypass)
                    # Refresh data after bypass
                    coordinator = data.get("coordinator")
                    if coordinator:
                        await coordinator.async_request_refresh()
                except InimApiError as err:
                    _LOGGER.error("Failed to bypass zone %s: %s", zone_id, err)
                return

        _LOGGER.error("No INIM Alarm API found")

    hass.services.async_register(
        DOMAIN,
        SERVICE_BYPASS_ZONE,
        handle_bypass_zone,
        schema=SERVICE_BYPASS_ZONE_SCHEMA,
    )
