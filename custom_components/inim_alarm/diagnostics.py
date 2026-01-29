"""Diagnostics support for INIM Alarm."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_USER_CODE, DOMAIN

TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_USER_CODE,
    "SerialNumber",
    "serial_number",
    "ClientToken",
    "ClientId",
    "UserId",
    "Email",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = hass.data[DOMAIN].get(entry.entry_id, {})
    coordinator = data.get("coordinator")
    api = data.get("api")
    
    diagnostics_data: dict[str, Any] = {
        "config_entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "domain": entry.domain,
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "api_info": {},
        "coordinator_data": {},
    }
    
    # Add API info
    if api:
        diagnostics_data["api_info"] = {
            "authenticated": api._client_token is not None,
            "client_id": "REDACTED" if api._client_id else None,
        }
    
    # Add coordinator data (redacted)
    if coordinator and coordinator.data:
        redacted_data = async_redact_data(coordinator.data, TO_REDACT)
        diagnostics_data["coordinator_data"] = redacted_data
        
        # Add summary info
        devices = coordinator.data.get("devices", [])
        diagnostics_data["summary"] = {
            "device_count": len(devices),
            "devices": [],
        }
        
        for device in devices:
            device_summary = {
                "device_id": device.get("device_id"),
                "name": device.get("name"),
                "model": device.get("model"),
                "firmware": device.get("firmware"),
                "zone_count": len(device.get("zones", [])),
                "area_count": len(device.get("areas", [])),
                "scenario_count": len(device.get("scenarios", [])),
                "thermostat_count": len(device.get("thermostats", [])),
                "active_scenario": device.get("active_scenario"),
                "network_status": device.get("network_status"),
                "faults": device.get("faults"),
            }
            diagnostics_data["summary"]["devices"].append(device_summary)
    
    return diagnostics_data
