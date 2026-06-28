"""Alarm Control Panel platform for INIM Alarm."""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import InimApi
from .const import (
    AREA_ARMED_DISARMED,
    ATTR_ALARM_MEMORY,
    ATTR_AREA_ID,
    ATTR_BYPASSED,
    ATTR_DEVICE_ID,
    ATTR_FIRMWARE,
    ATTR_LAST_CHANGED_AT,
    ATTR_LAST_CHANGED_BY,
    ATTR_MODEL,
    ATTR_SERIAL_NUMBER,
    ATTR_TAMPER_MEMORY,
    ATTR_VOLTAGE,
    ATTR_ZONE_ID,
    CONF_ARM_AWAY_SCENARIO,
    CONF_ARM_HOME_SCENARIO,
    CONF_AWAY_ONLY_AREAS,
    CONF_DISARM_SCENARIO,
    CONF_EXCLUDED_ALARM_MEMORY_ZONES,
    CONF_SCAN_INTERVAL,
    CONF_USER_CODE,
    CONF_ZONE_ALARM_MEMORY_EXPOSURE,
    DEFAULT_ZONE_ALARM_MEMORY_EXPOSURE,
    DOMAIN,
    MANUFACTURER,
    ZONE_ALARM_MEMORY_EXPOSURE_ALARM_PANEL,
    ZONE_ALARM_MEMORY_EXPOSURE_BOTH,
)
from .coordinator import InimDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PENDING_TARGET_TIMEOUT_SECONDS = 20


def _coerce_int(value: Any) -> int | None:
    """Return value as int, or None when unset/invalid."""
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _configured_scenario(options: dict[str, Any], conf_key: str) -> int | None:
    """Return a configured scenario ID from options."""
    value = options.get(conf_key)
    scenario_id = _coerce_int(value)

    if scenario_id is None and value not in (None, ""):
        _LOGGER.warning("Invalid scenario configured for %s: %r", conf_key, value)

    return scenario_id


def _active_scenario_mode(
    device: dict[str, Any],
    options: dict[str, Any],
) -> str | None:
    """Infer home/away mode from the active configured scenario."""
    active_scenario = _coerce_int(device.get("active_scenario"))
    if active_scenario is None:
        return None

    away_scenario = _configured_scenario(options, CONF_ARM_AWAY_SCENARIO)
    if away_scenario is not None and active_scenario == away_scenario:
        return "away"

    home_scenario = _configured_scenario(options, CONF_ARM_HOME_SCENARIO)
    if home_scenario is not None and active_scenario == home_scenario:
        return "home"

    return None


def _is_zone_output(zone: dict[str, Any]) -> bool:
    """Return true when the item represents an output instead of an alarm zone."""
    return zone.get("Type") == 4


def _is_alarm_memory_zone_excluded(
    zone_id: int | None,
    options: dict[str, Any],
) -> bool:
    """Return true when a zone was manually excluded from alarm memory exposure."""
    if zone_id is None:
        return True

    excluded = {
        str(value)
        for value in options.get(CONF_EXCLUDED_ALARM_MEMORY_ZONES, [])
    }
    return str(zone_id) in excluded


def _expose_alarm_memory_alarm_panels(options: dict[str, Any]) -> bool:
    """Return true when alarm memories should be exposed as alarm panels."""
    exposure = options.get(
        CONF_ZONE_ALARM_MEMORY_EXPOSURE,
        DEFAULT_ZONE_ALARM_MEMORY_EXPOSURE,
    )
    return exposure in (
        ZONE_ALARM_MEMORY_EXPOSURE_ALARM_PANEL,
        ZONE_ALARM_MEMORY_EXPOSURE_BOTH,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up INIM alarm control panel from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: InimDataUpdateCoordinator = data["coordinator"]
    api: InimApi = data["api"]
    options: dict[str, Any] = data.get("options", {})

    entities = []

    for device in coordinator.devices:
        device_id = device.get("device_id")
        if not device_id:
            continue

        areas = device.get("areas", [])
        area_ids = []

        for area in areas:
            area_id = area.get("AreaId")
            area_name = area.get("Name", f"Area {area_id}")

            if not (area_name.startswith("Area ") and area_name[5:].isdigit()):
                area_ids.append(area_id)

        entities.append(
            InimAlarmControlPanel(
                coordinator=coordinator,
                api=api,
                device_id=device_id,
                area_ids=area_ids,
                options=options,
            )
        )

        for area in areas:
            area_id = area.get("AreaId")
            area_name = area.get("Name", f"Area {area_id}")

            if area_name.startswith("Area ") and area_name[5:].isdigit():
                continue

            entities.append(
                InimAreaAlarmControlPanel(
                    coordinator=coordinator,
                    api=api,
                    device_id=device_id,
                    area_id=area_id,
                    area_name=area_name,
                    options=options,
                )
            )

        if _expose_alarm_memory_alarm_panels(options):
            for zone in device.get("zones", []):
                zone_id = zone.get("ZoneId")
                zone_name = zone.get("Name", f"Zone {zone_id}")

                if zone.get("Visibility", 1) == 0:
                    continue
                if _is_zone_output(zone):
                    continue
                if _is_alarm_memory_zone_excluded(zone_id, options):
                    continue

                entities.append(
                    InimZoneAlarmMemoryAlarmControlPanel(
                        coordinator=coordinator,
                        device_id=device_id,
                        zone_id=zone_id,
                        zone_name=zone_name,
                    )
                )

    async_add_entities(entities)


class InimAlarmControlPanel(
    CoordinatorEntity[InimDataUpdateCoordinator],
    AlarmControlPanelEntity,
):
    """Main INIM alarm control panel."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_AWAY
    )
    _attr_code_format = CodeFormat.NUMBER
    _attr_code_arm_required = False

    def __init__(
        self,
        coordinator: InimDataUpdateCoordinator,
        api: InimApi,
        device_id: int,
        area_ids: list[int],
        options: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the alarm control panel."""
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_id
        self._area_ids = area_ids
        self._options = options or {}
        self._attr_unique_id = f"{device_id}_alarm"
        self._user_code = self._options.get(CONF_USER_CODE, "")

        self._pending_state: AlarmControlPanelState | None = None
        self._armed_mode: str = "home"

        self._pending_target_state: AlarmControlPanelState | None = None
        self._pending_target_until: float | None = None

    def _configured_scenario(self, conf_key: str) -> int | None:
        """Return the scenario ID mapped to an action."""
        return _configured_scenario(self._options, conf_key)

    def _set_pending_target(self, state: AlarmControlPanelState) -> None:
        """Hold the requested target state briefly to ignore stale cloud refreshes."""
        self._pending_target_state = state
        self._pending_target_until = time.monotonic() + PENDING_TARGET_TIMEOUT_SECONDS

    def _clear_pending_target(self) -> None:
        """Clear pending target state."""
        self._pending_target_state = None
        self._pending_target_until = None

    def _pending_target_active(self) -> AlarmControlPanelState | None:
        """Return the pending target state if it is still valid."""
        if self._pending_target_state is None or self._pending_target_until is None:
            return None

        if time.monotonic() <= self._pending_target_until:
            return self._pending_target_state

        self._clear_pending_target()
        return None

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
        """Return the main alarm state."""
        if self._pending_state is not None:
            return self._pending_state

        device = self.coordinator.get_device(self._device_id)
        if not device:
            return None

        pending_target = self._pending_target_active()

        if pending_target == AlarmControlPanelState.DISARMED:
            return AlarmControlPanelState.DISARMED

        areas = device.get("areas", [])

        for area in areas:
            if area.get("Alarm", False):
                return AlarmControlPanelState.TRIGGERED

        if pending_target is not None:
            return pending_target

        any_armed = False

        for area in areas:
            area_id = area.get("AreaId")
            if area_id not in self._area_ids:
                continue

            armed = area.get("Armed", AREA_ARMED_DISARMED)
            if armed != AREA_ARMED_DISARMED:
                any_armed = True

        if any_armed:
            active_mode = _active_scenario_mode(device, self._options)

            if active_mode == "away":
                self._armed_mode = "away"
                return AlarmControlPanelState.ARMED_AWAY

            if active_mode == "home":
                self._armed_mode = "home"
                return AlarmControlPanelState.ARMED_HOME

            if self._armed_mode == "away":
                return AlarmControlPanelState.ARMED_AWAY

            return AlarmControlPanelState.ARMED_HOME

        self._armed_mode = "home"
        return AlarmControlPanelState.DISARMED

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        device = self.coordinator.get_device(self._device_id)
        if not device:
            return {}

        polling_interval = self._options.get(CONF_SCAN_INTERVAL, 30)

        area_names = []
        for area in device.get("areas", []):
            if area.get("AreaId") in self._area_ids:
                area_names.append(area.get("Name", f"Area {area.get('AreaId')}"))

        entity_key = f"{self._device_id}_alarm"
        last_changed_by = self.coordinator.get_last_changed_by(entity_key)
        last_changed_at = self.coordinator.get_last_changed_at(entity_key)

        attrs = {
            ATTR_DEVICE_ID: self._device_id,
            ATTR_SERIAL_NUMBER: device.get("serial_number"),
            ATTR_MODEL: device.get("model"),
            ATTR_FIRMWARE: device.get("firmware"),
            ATTR_VOLTAGE: device.get("voltage"),
            "network_status": device.get("network_status"),
            "faults": device.get("faults"),
            "polling_interval_seconds": polling_interval,
            "controlled_areas": area_names,
            "area_ids": self._area_ids,
            "active_scenario": device.get("active_scenario"),
            "active_scenario_mode": _active_scenario_mode(device, self._options),
            "pending_target_state": (
                self._pending_target_state.value
                if self._pending_target_state is not None
                else None
            ),
            "pending_target_active": self._pending_target_active() is not None,
            ATTR_LAST_CHANGED_BY: last_changed_by,
        }

        if last_changed_at:
            attrs[ATTR_LAST_CHANGED_AT] = last_changed_at.isoformat()

        return attrs

    async def _async_run_action(
        self,
        action: str,
        conf_key: str,
        arm: bool,
    ) -> bool:
        """Run an arm/disarm action via scenario or InsertAreas."""
        scenario_id = self._configured_scenario(conf_key)

        self.coordinator.register_ha_command(self._device_id, None)

        if scenario_id is not None:
            _LOGGER.info(
                "%s device %s via scenario %s",
                action,
                self._device_id,
                scenario_id,
            )
            await self._api.activate_scenario(self._device_id, scenario_id)
            return True

        if not self._user_code:
            _LOGGER.error(
                "Cannot %s: configure a scenario in the integration options "
                "or set the user code.",
                action.lower(),
            )
            return False

        if not self._area_ids:
            _LOGGER.warning("No configured areas to %s", action.lower())
            return False

        _LOGGER.info(
            "%s all areas for device %s (areas: %s)",
            action,
            self._device_id,
            self._area_ids,
        )
        await self._api.insert_areas(
            self._device_id,
            self._area_ids,
            self._user_code,
            arm=arm,
        )
        return True

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command."""
        self._set_pending_target(AlarmControlPanelState.DISARMED)
        self._armed_mode = "home"
        self.async_write_ha_state()

        if not await self._async_run_action(
            "Disarming",
            CONF_DISARM_SCENARIO,
            arm=False,
        ):
            self._clear_pending_target()
            self.async_write_ha_state()
            return

        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm home command."""
        self._pending_state = None
        self._armed_mode = "home"
        self._set_pending_target(AlarmControlPanelState.ARMED_HOME)
        self.async_write_ha_state()

        if not await self._async_run_action(
            "Arming HOME",
            CONF_ARM_HOME_SCENARIO,
            arm=True,
        ):
            self._clear_pending_target()
            self.async_write_ha_state()
            return

        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command."""
        self._pending_state = None
        self._armed_mode = "away"
        self._set_pending_target(AlarmControlPanelState.ARMED_AWAY)
        self.async_write_ha_state()

        if not await self._async_run_action(
            "Arming AWAY",
            CONF_ARM_AWAY_SCENARIO,
            arm=True,
        ):
            self._clear_pending_target()
            self.async_write_ha_state()
            return

        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._pending_state = None
        self.async_write_ha_state()


class InimAreaAlarmControlPanel(
    CoordinatorEntity[InimDataUpdateCoordinator],
    AlarmControlPanelEntity,
):
    """INIM area alarm control panel."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_AWAY
    )
    _attr_code_format = CodeFormat.NUMBER
    _attr_code_arm_required = False

    def __init__(
        self,
        coordinator: InimDataUpdateCoordinator,
        api: InimApi,
        device_id: int,
        area_id: int,
        area_name: str,
        options: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the area alarm control panel."""
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_id
        self._area_id = area_id
        self._area_name = area_name
        self._options = options or {}
        self._attr_unique_id = f"{device_id}_area_{area_id}"
        self._attr_name = area_name
        self._user_code = self._options.get(CONF_USER_CODE, "")
        self._pending_state: AlarmControlPanelState | None = None
        self._armed_mode: str = "home"

        away_only_areas = {
            str(value)
            for value in self._options.get(CONF_AWAY_ONLY_AREAS, [])
        }
        if str(area_id) in away_only_areas:
            self._attr_supported_features = AlarmControlPanelEntityFeature.ARM_AWAY

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
        """Return the state of the area."""
        if self._pending_state is not None:
            return self._pending_state

        area = self.coordinator.get_area(self._device_id, self._area_id)
        if not area:
            return None

        if area.get("Alarm", False):
            return AlarmControlPanelState.TRIGGERED

        armed = area.get("Armed", AREA_ARMED_DISARMED)

        if armed == AREA_ARMED_DISARMED:
            self._armed_mode = "home"
            return AlarmControlPanelState.DISARMED

        device = self.coordinator.get_device(self._device_id)
        if device:
            active_mode = _active_scenario_mode(device, self._options)

            if active_mode == "away":
                self._armed_mode = "away"
                return AlarmControlPanelState.ARMED_AWAY

            if active_mode == "home":
                self._armed_mode = "home"
                return AlarmControlPanelState.ARMED_HOME

        if self._armed_mode == "away":
            return AlarmControlPanelState.ARMED_AWAY

        return AlarmControlPanelState.ARMED_HOME

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        area = self.coordinator.get_area(self._device_id, self._area_id)
        if not area:
            return {}

        device = self.coordinator.get_device(self._device_id)
        active_mode = _active_scenario_mode(device, self._options) if device else None

        entity_key = f"{self._device_id}_area_{self._area_id}"
        last_changed_by = self.coordinator.get_last_changed_by(entity_key)
        last_changed_at = self.coordinator.get_last_changed_at(entity_key)

        attrs = {
            ATTR_DEVICE_ID: self._device_id,
            ATTR_AREA_ID: self._area_id,
            "alarm": area.get("Alarm", False),
            "alarm_memory": area.get("AlarmMemory", False),
            "tamper": area.get("Tamper", False),
            "tamper_memory": area.get("TamperMemory", False),
            "auto_insert": area.get("AutoInsert", False),
            "active_scenario": device.get("active_scenario") if device else None,
            "active_scenario_mode": active_mode,
            ATTR_LAST_CHANGED_BY: last_changed_by,
        }

        if last_changed_at:
            attrs[ATTR_LAST_CHANGED_AT] = last_changed_at.isoformat()

        return attrs

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command for this area."""
        if not self._user_code:
            _LOGGER.error(
                "Cannot disarm area %s: No user code configured.",
                self._area_name,
            )
            return

        self.coordinator.register_ha_command(self._device_id, self._area_id)

        _LOGGER.info(
            "Disarming area '%s' (ID: %s)",
            self._area_name,
            self._area_id,
        )
        await self._api.insert_areas(
            self._device_id,
            [self._area_id],
            self._user_code,
            arm=False,
        )
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm home command for this area."""
        if not self._user_code:
            _LOGGER.error(
                "Cannot arm area %s: No user code configured.",
                self._area_name,
            )
            return

        self._pending_state = AlarmControlPanelState.ARMING
        self._armed_mode = "home"
        self.async_write_ha_state()

        self.coordinator.register_ha_command(self._device_id, self._area_id)

        _LOGGER.info(
            "Arming HOME area '%s' (ID: %s)",
            self._area_name,
            self._area_id,
        )
        await self._api.insert_areas(
            self._device_id,
            [self._area_id],
            self._user_code,
            arm=True,
        )

        self._pending_state = None
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command for this area."""
        if not self._user_code:
            _LOGGER.error(
                "Cannot arm area %s: No user code configured.",
                self._area_name,
            )
            return

        self._pending_state = AlarmControlPanelState.ARMING
        self._armed_mode = "away"
        self.async_write_ha_state()

        self.coordinator.register_ha_command(self._device_id, self._area_id)

        _LOGGER.info(
            "Arming AWAY area '%s' (ID: %s)",
            self._area_name,
            self._area_id,
        )
        await self._api.insert_areas(
            self._device_id,
            [self._area_id],
            self._user_code,
            arm=True,
        )

        self._pending_state = None
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._pending_state = None
        self.async_write_ha_state()


class InimZoneAlarmMemoryAlarmControlPanel(
    CoordinatorEntity[InimDataUpdateCoordinator],
    AlarmControlPanelEntity,
):
    """Read-only alarm panel backed by a zone alarm memory flag."""

    _attr_has_entity_name = True
    _attr_supported_features = AlarmControlPanelEntityFeature(0)
    _attr_code_arm_required = False

    def __init__(
        self,
        coordinator: InimDataUpdateCoordinator,
        device_id: int,
        zone_id: int,
        zone_name: str,
    ) -> None:
        """Initialize the zone alarm memory alarm panel."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._attr_unique_id = f"{device_id}_zone_{zone_id}_alarm_memory_panel"
        self._attr_name = f"Allarme {zone_name}"

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
        """Return triggered when the zone has alarm memory."""
        zone = self.coordinator.get_zone(self._device_id, self._zone_id)
        if not zone:
            return None

        if zone.get("AlarmMemory", 0) > 0:
            return AlarmControlPanelState.TRIGGERED

        return AlarmControlPanelState.DISARMED

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        zone = self.coordinator.get_zone(self._device_id, self._zone_id)
        if not zone:
            return {}

        return {
            ATTR_DEVICE_ID: self._device_id,
            ATTR_ZONE_ID: self._zone_id,
            ATTR_ALARM_MEMORY: zone.get("AlarmMemory", 0) > 0,
            ATTR_TAMPER_MEMORY: zone.get("TamperMemory", 0) > 0,
            ATTR_BYPASSED: zone.get("Bypassed", 0) > 0,
            "source_zone_name": self._zone_name,
            "areas": zone.get("Areas"),
            "type": zone.get("Type"),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
