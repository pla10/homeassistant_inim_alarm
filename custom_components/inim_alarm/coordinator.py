"""DataUpdateCoordinator for INIM Alarm."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import InimApi, InimApiError, InimAuthError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class InimDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching INIM data."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        api: InimApi,
        update_interval: timedelta = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.api = api
        self._devices: list[dict[str, Any]] = []

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from INIM API."""
        try:
            # Get devices with all data
            devices = await self.api.get_devices()
            
            if not devices:
                _LOGGER.warning("No devices found in INIM Cloud")
                return {"devices": []}
            
            self._devices = devices
            
            # Build a structured data response
            data: dict[str, Any] = {
                "devices": [],
            }
            
            for device in devices:
                device_data = {
                    "device_id": device.get("DeviceId"),
                    "name": device.get("Name", "INIM Alarm"),
                    "serial_number": device.get("SerialNumber"),
                    "model": f"{device.get('ModelFamily', '')} {device.get('ModelNumber', '')}".strip(),
                    "firmware": f"{device.get('FirmwareVersionMajor', '')}.{device.get('FirmwareVersionMinor', '')}",
                    "voltage": device.get("Voltage"),
                    "active_scenario": device.get("ActiveScenario"),
                    "network_status": device.get("NetworkStatus"),
                    "faults": device.get("Faults", 0),
                    "areas": device.get("Areas", []),
                    "zones": device.get("Zones", []),
                    "scenarios": device.get("Scenarios", []),
                    "peripherals": device.get("Peripherals", []),
                    "thermostats": device.get("Thermostats", []),
                    "blinds": device.get("Blinds", []),
                }
                data["devices"].append(device_data)
            
            _LOGGER.debug("Updated data for %d devices", len(data["devices"]))
            return data

        except InimAuthError as err:
            _LOGGER.error("Authentication error: %s", err)
            raise UpdateFailed(f"Authentication error: {err}") from err
        except InimApiError as err:
            _LOGGER.error("API error: %s", err)
            raise UpdateFailed(f"API error: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error updating INIM data")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    def get_device(self, device_id: int) -> dict[str, Any] | None:
        """Get a specific device by ID."""
        if not self.data:
            return None
        for device in self.data.get("devices", []):
            if device.get("device_id") == device_id:
                return device
        return None

    def get_zone(self, device_id: int, zone_id: int) -> dict[str, Any] | None:
        """Get a specific zone by device and zone ID."""
        device = self.get_device(device_id)
        if not device:
            return None
        for zone in device.get("zones", []):
            if zone.get("ZoneId") == zone_id:
                return zone
        return None

    def get_area(self, device_id: int, area_id: int) -> dict[str, Any] | None:
        """Get a specific area by device and area ID."""
        device = self.get_device(device_id)
        if not device:
            return None
        for area in device.get("areas", []):
            if area.get("AreaId") == area_id:
                return area
        return None

    def get_scenario(self, device_id: int, scenario_id: int) -> dict[str, Any] | None:
        """Get a specific scenario by device and scenario ID."""
        device = self.get_device(device_id)
        if not device:
            return None
        for scenario in device.get("scenarios", []):
            if scenario.get("ScenarioId") == scenario_id:
                return scenario
        return None

    def get_active_scenario(self, device_id: int) -> dict[str, Any] | None:
        """Get the currently active scenario for a device."""
        device = self.get_device(device_id)
        if not device:
            return None
        active_id = device.get("active_scenario")
        if active_id is not None:
            return self.get_scenario(device_id, active_id)
        return None

    @property
    def devices(self) -> list[dict[str, Any]]:
        """Return all devices."""
        if not self.data:
            return []
        return self.data.get("devices", [])
