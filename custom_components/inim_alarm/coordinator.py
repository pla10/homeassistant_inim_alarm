"""DataUpdateCoordinator for INIM Alarm."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import InimApi, InimApiError, InimAuthError
from .websocket import InimWebSocketClient
from .const import (
    CHANGED_BY_EXTERNAL,
    CHANGED_BY_HOME_ASSISTANT,
    CHANGED_BY_UNKNOWN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_ALARM_TRIGGERED,
    EVENT_STATE_CHANGED,
)

_LOGGER = logging.getLogger(__name__)

SCENARIO_STATE_GUARD_SECONDS = 12


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
        self._ws_client = InimWebSocketClient(api, self._on_websocket_update)
        self._devices: list[dict[str, Any]] = []
        # Track previous alarm state for event triggering
        self._previous_alarm_states: dict[tuple[int, int], bool] = {}
        # Track previous armed states for change detection
        self._previous_armed_states: dict[tuple[int, int], int] = {}
        # Track pending commands from Home Assistant
        self._pending_ha_commands: dict[tuple[int, int | None], datetime] = {}
        # Track scenario states expected after a recent scenario change
        self._expected_area_states: dict[int, dict[int, int]] = {}
        self._expected_area_state_until: dict[int, datetime] = {}
        self._active_scenarios: dict[int, int | None] = {}
        # Track last change info per entity
        self._last_changed_by: dict[str, str] = {}
        self._last_changed_at: dict[str, datetime] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from INIM API."""
        try:
            # First, request poll to wake up the central unit
            # This tells INIM to fetch fresh data from the panel
            poll_requested = False
            for device in self._devices:
                device_id = device.get("DeviceId")
                if device_id:
                    try:
                        await self.api.request_poll(device_id)
                        _LOGGER.debug("Requested poll for device %s", device_id)
                        poll_requested = True
                    except InimAuthError as err:
                        _LOGGER.debug(
                            "RequestPoll auth error for device %s: %s, token was refreshed",
                            device_id, err,
                        )
                        # Token was refreshed inside request_poll, retry once
                        try:
                            await self.api.request_poll(device_id)
                            _LOGGER.debug("Requested poll for device %s after re-auth", device_id)
                            poll_requested = True
                        except Exception as retry_err:
                            _LOGGER.warning("RequestPoll retry failed for device %s: %s", device_id, retry_err)
                    except Exception as err:
                        _LOGGER.debug("RequestPoll failed for device %s: %s", device_id, err)
            
            # Wait for central to send data to cloud (5 seconds required)
            if poll_requested:
                import asyncio
                await asyncio.sleep(5)
            
            # Now get devices with all data (should have fresh state)
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
            self._apply_active_scenario_changes(data)
            self._apply_expected_area_states(data)
            
            # Check for alarm state changes and fire events
            self._check_alarm_triggered(data)
            
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

    def apply_expected_scenario(self, device_id: int, scenario_id: int) -> None:
        """Apply expected area states from a scenario immediately."""
        device = self.get_device(device_id)
        expected_states = self._scenario_area_states_from_device(device, scenario_id)
        if not expected_states:
            _LOGGER.debug(
                "No scenario AreaSet available for device %s scenario %s",
                device_id,
                scenario_id,
            )
            return

        self._set_expected_area_states(device_id, scenario_id, expected_states)

        if not self.data or "devices" not in self.data:
            return

        if self._apply_expected_area_states(self.data, clear_matched=False):
            _LOGGER.debug(
                "Applied expected scenario %s area states for device %s: %s",
                scenario_id,
                device_id,
                expected_states,
            )
            self._check_alarm_triggered(self.data)
            self.async_set_updated_data(self.data)

    def _apply_active_scenario_changes(self, data: dict[str, Any]) -> None:
        """Use ActiveScenario changes from the cloud as scenario intent."""
        for device in data.get("devices", []):
            device_id = device.get("device_id")
            active_scenario = device.get("active_scenario")
            if device_id is None:
                continue

            previous_scenario = self._active_scenarios.get(device_id)
            if previous_scenario == active_scenario:
                continue

            self._active_scenarios[device_id] = active_scenario
            if active_scenario is None:
                continue

            expected_states = self._scenario_area_states_from_device(
                device, active_scenario
            )
            if expected_states:
                self._set_expected_area_states(
                    device_id, active_scenario, expected_states
                )

    def _scenario_area_states_from_device(
        self, device: dict[str, Any] | None, scenario_id: int
    ) -> dict[int, int]:
        """Return area Armed values declared by a scenario AreaSet."""
        if not device:
            return {}

        scenario = None
        for candidate in device.get("scenarios", []):
            if candidate.get("ScenarioId") == scenario_id:
                scenario = candidate
                break
        if not scenario:
            return {}

        area_set = scenario.get("AreaSet")
        if not isinstance(area_set, str):
            return {}

        expected_states: dict[int, int] = {}
        for area in device.get("areas", []):
            area_id = area.get("AreaId")
            if area_id is None or area_id >= len(area_set):
                continue
            try:
                armed = int(area_set[area_id])
            except (TypeError, ValueError):
                continue
            if armed:
                expected_states[area_id] = armed
        return expected_states

    def _set_expected_area_states(
        self, device_id: int, scenario_id: int, expected_states: dict[int, int]
    ) -> None:
        """Store expected states for a recent scenario change."""
        self._expected_area_states[device_id] = expected_states
        self._expected_area_state_until[device_id] = dt_util.now() + timedelta(
            seconds=SCENARIO_STATE_GUARD_SECONDS
        )
        _LOGGER.debug(
            "Expecting scenario %s area states for device %s: %s",
            scenario_id,
            device_id,
            expected_states,
        )

    def _apply_expected_area_states(
        self,
        data: dict[str, Any],
        *,
        clear_matched: bool = True,
    ) -> bool:
        """Keep fresh data aligned with a just-changed scenario while cloud catches up."""
        changed = False
        now = dt_util.now()

        for device in data.get("devices", []):
            device_id = device.get("device_id")
            if device_id is None:
                continue

            expected_states = self._expected_area_states.get(device_id)
            guard_until = self._expected_area_state_until.get(device_id)
            if not expected_states or guard_until is None:
                continue

            if now >= guard_until:
                self._clear_expected_area_states(device_id)
                continue

            areas_by_id = {
                area.get("AreaId"): area for area in device.get("areas", [])
            }
            has_unmatched_state = False
            for area_id, expected_armed in expected_states.items():
                area = areas_by_id.get(area_id)
                if area is None:
                    has_unmatched_state = True
                    continue

                if area.get("Armed") != expected_armed:
                    has_unmatched_state = True
                    area["Armed"] = expected_armed
                    changed = True

            if has_unmatched_state:
                _LOGGER.debug(
                    "Keeping expected scenario area states for device %s: %s",
                    device_id,
                    expected_states,
                )
            elif clear_matched:
                self._clear_expected_area_states(device_id)

        return changed

    def _expected_area_state(self, device_id: int, area_id: int) -> int | None:
        """Return a guarded expected Armed value for an area, if active."""
        guard_until = self._expected_area_state_until.get(device_id)
        if guard_until is None:
            return None

        if dt_util.now() >= guard_until:
            self._clear_expected_area_states(device_id)
            return None

        return self._expected_area_states.get(device_id, {}).get(area_id)

    def _area_update_matches_expected(
        self,
        device_id: int | None,
        area_id: int | None,
        status_update: dict[str, Any],
    ) -> bool:
        """Return False when a realtime area update contradicts a fresh scenario command."""
        if device_id is None or area_id is None or "Armed" not in status_update:
            return True

        expected_armed = self._expected_area_state(device_id, area_id)
        if expected_armed is None:
            return True

        try:
            incoming_armed = int(status_update["Armed"])
        except (TypeError, ValueError):
            return True

        if incoming_armed == expected_armed:
            return True

        _LOGGER.debug(
            "Ignoring stale area update during scenario transition for device %s "
            "area %s: incoming Armed=%s, expected Armed=%s",
            device_id,
            area_id,
            incoming_armed,
            expected_armed,
        )
        return False

    def _clear_expected_area_states(self, device_id: int) -> None:
        """Clear expected states for a device."""
        self._expected_area_states.pop(device_id, None)
        self._expected_area_state_until.pop(device_id, None)

    def _check_alarm_triggered(self, data: dict[str, Any]) -> None:
        """Check for alarm state changes and fire events."""
        for device in data.get("devices", []):
            device_id = device.get("device_id")
            if not device_id:
                continue
            
            for area in device.get("areas", []):
                area_id = area.get("AreaId")
                area_name = area.get("Name", f"Area {area_id}")
                current_alarm = area.get("Alarm", False)
                current_armed = area.get("Armed", 4)  # 4 = disarmed
                
                key = (device_id, area_id)
                previous_alarm = self._previous_alarm_states.get(key, False)
                previous_armed = self._previous_armed_states.get(key)
                
                # Fire event if alarm just triggered (false -> true)
                if current_alarm and not previous_alarm:
                    _LOGGER.warning(
                        "ALARM TRIGGERED! Device: %s, Area: %s (%s)",
                        device_id, area_id, area_name
                    )
                    self.hass.bus.async_fire(
                        EVENT_ALARM_TRIGGERED,
                        {
                            "device_id": device_id,
                            "device_name": device.get("name", "INIM Alarm"),
                            "area_id": area_id,
                            "area_name": area_name,
                        },
                    )
                
                # Check for armed state changes and determine source
                if previous_armed is not None and current_armed != previous_armed:
                    self._handle_armed_state_change(
                        device_id, area_id, area_name, 
                        device.get("name", "INIM Alarm"),
                        previous_armed, current_armed
                    )
                
                # Update state tracking
                self._previous_alarm_states[key] = current_alarm
                self._previous_armed_states[key] = current_armed

    def _handle_armed_state_change(
        self,
        device_id: int,
        area_id: int,
        area_name: str,
        device_name: str,
        previous_armed: int,
        current_armed: int,
    ) -> None:
        """Handle armed state change and determine source."""
        now = dt_util.now()
        
        # Check if we have a pending HA command for this area
        entity_key_area = f"{device_id}_area_{area_id}"
        entity_key_main = f"{device_id}_alarm"
        
        pending_key_area = (device_id, area_id)
        pending_key_main = (device_id, None)
        
        # Check if there's a pending HA command (within last 60 seconds)
        is_ha_command = False
        pending_time = None
        
        if pending_key_area in self._pending_ha_commands:
            pending_time = self._pending_ha_commands[pending_key_area]
            if (now - pending_time).total_seconds() < 60:
                is_ha_command = True
                del self._pending_ha_commands[pending_key_area]
        
        if not is_ha_command and pending_key_main in self._pending_ha_commands:
            pending_time = self._pending_ha_commands[pending_key_main]
            if (now - pending_time).total_seconds() < 60:
                is_ha_command = True
                # Don't delete main panel pending - it might apply to multiple areas
        
        # Determine the source - if HA command pending, it's from HA
        changed_by = CHANGED_BY_HOME_ASSISTANT if is_ha_command else CHANGED_BY_EXTERNAL
        
        # Store change info for both area and main panel entities
        self._last_changed_by[entity_key_area] = changed_by
        self._last_changed_at[entity_key_area] = now
        self._last_changed_by[entity_key_main] = changed_by
        self._last_changed_at[entity_key_main] = now
        
        # Determine state names for logging
        state_from = "armed" if previous_armed != 4 else "disarmed"
        state_to = "armed" if current_armed != 4 else "disarmed"
        
        _LOGGER.info(
            "Alarm state changed: %s -> %s (Area: %s, Device: %s, Source: %s)",
            state_from, state_to, area_name, device_name, changed_by
        )
        
        # Fire event
        self.hass.bus.async_fire(
            EVENT_STATE_CHANGED,
            {
                "device_id": device_id,
                "device_name": device_name,
                "area_id": area_id,
                "area_name": area_name,
                "previous_state": state_from,
                "new_state": state_to,
                "changed_by": changed_by,
                "changed_at": now.isoformat(),
            },
        )

    def register_ha_command(self, device_id: int, area_id: int | None = None) -> None:
        """Register that a command was sent from Home Assistant.
        
        Args:
            device_id: The device ID
            area_id: The area ID (None for main panel affecting all areas)
        """
        key = (device_id, area_id)
        self._pending_ha_commands[key] = dt_util.now()
        _LOGGER.debug("Registered HA command for device %s, area %s", device_id, area_id)

    def clear_main_panel_pending(self, device_id: int) -> None:
        """Clear the pending command for main panel after all areas processed."""
        key = (device_id, None)
        if key in self._pending_ha_commands:
            del self._pending_ha_commands[key]

    def get_last_changed_by(self, entity_key: str) -> str:
        """Get the last changed by value for an entity."""
        return self._last_changed_by.get(entity_key, CHANGED_BY_UNKNOWN)

    def get_last_changed_at(self, entity_key: str) -> datetime | None:
        """Get the last changed at timestamp for an entity."""
        return self._last_changed_at.get(entity_key)

    async def async_start_websocket(self) -> None:
        """Start the WebSocket client for real-time updates."""
        await self._ws_client.start()

    async def async_stop_websocket(self) -> None:
        """Stop the WebSocket client."""
        await self._ws_client.stop()

    def _on_websocket_update(self, event_data: dict[str, Any]) -> None:
        """Handle real-time updates from WebSocket.

        Patches current coordinator data in-place with zone/area updates
        and notifies listeners only when changes are detected.
        Uses Device_Id from the WS payload to match the correct device.
        """
        if not isinstance(event_data, dict):
            _LOGGER.debug("WS event is not a dict, requesting poll for fresh state")
            self.hass.async_create_task(self.async_request_refresh())
            return

        if not self.data or "devices" not in self.data:
            return

        has_changes = False

        def find_device(dev_id: int) -> dict[str, Any] | None:
            for d in self.data.get("devices", []):
                if d.get("device_id") == dev_id:
                    return d
            return None

        for zone_update in event_data.get("ZoneList") or []:
            device_id = zone_update.get("Device_Id")
            zone_id = zone_update.get("ZoneId")
            if not device_id or zone_id is None:
                continue
            device = find_device(device_id)
            if device:
                for idx, zone in enumerate(device.get("zones", [])):
                    if zone.get("ZoneId") == zone_id:
                        device["zones"][idx].update(zone_update)
                        has_changes = True
                        break

        for area_update in event_data.get("AreaList") or []:
            device_id = area_update.get("Device_Id")
            area_id = area_update.get("AreaId")
            if not device_id or area_id is None:
                continue
            if not self._area_update_matches_expected(device_id, area_id, area_update):
                continue
            device = find_device(device_id)
            if device:
                for idx, area in enumerate(device.get("areas", [])):
                    if area.get("AreaId") == area_id:
                        device["areas"][idx].update(area_update)
                        has_changes = True
                        break

        if has_changes:
            _LOGGER.debug("Applying partial updates from WebSocket")
            self._check_alarm_triggered(self.data)
            self.async_set_updated_data(self.data)

    @callback
    def async_on_sia_update(self, zone_id: int, status_update: dict[str, Any]) -> None:
        """Handle real-time zone updates from SIA-IP."""
        if not self.data or "devices" not in self.data:
            return

        has_changes = False
        for device in self.data.get("devices", []):
            for idx, zone in enumerate(device.get("zones", [])):
                z_id = zone.get("ZoneId")
                
                # Ignora le zone senza ID
                if z_id is None:
                    continue
                
                # Handle INIM Cloud 1000 offset for wireless and double zones
                if z_id == zone_id or z_id % 1000 == zone_id:
                    device["zones"][idx].update(status_update)
                    has_changes = True
                    _LOGGER.debug(
                        "SIA update zone %s: %s", zone.get("Name", z_id), status_update
                    )
                    break
            if has_changes:
                break

        if has_changes:
            self._check_alarm_triggered(self.data)
            self.async_set_updated_data(self.data)

    @callback
    def async_on_sia_area_update(
        self, area_id: int, status_update: dict[str, Any]
    ) -> None:
        """Handle real-time area updates from SIA-IP."""
        if not self.data or "devices" not in self.data:
            return

        has_changes = False
        for device in self.data.get("devices", []):
            device_id = device.get("device_id")
            for idx, area in enumerate(device.get("areas", [])):
                if area.get("AreaId") == area_id:
                    if not self._area_update_matches_expected(
                        device_id, area_id, status_update
                    ):
                        continue
                    device["areas"][idx].update(status_update)
                    has_changes = True
                    _LOGGER.debug(
                        "SIA update area %s: %s", area.get("Name", area_id), status_update
                    )
                    break
            if has_changes:
                break

        if has_changes:
            self._check_alarm_triggered(self.data)
            self.async_set_updated_data(self.data)

    @property
    def devices(self) -> list[dict[str, Any]]:
        """Return all devices."""
        if not self.data:
            return []
        return self.data.get("devices", [])
