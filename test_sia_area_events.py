#!/usr/bin/env python3
"""Focused unit tests for SIA area event routing."""

from __future__ import annotations

from datetime import datetime
import importlib.util
from pathlib import Path
import sys
import types
import unittest


def load_sia_server():
    """Load sia_server.py with minimal Home Assistant module stubs."""
    homeassistant = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    util = types.ModuleType("homeassistant.util")
    dt = types.ModuleType("homeassistant.util.dt")
    core.HomeAssistant = object
    dt.now = datetime.now
    util.dt = dt

    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.util"] = util
    sys.modules["homeassistant.util.dt"] = dt

    path = Path(__file__).parent / "custom_components" / "inim_alarm" / "sia_server.py"
    spec = importlib.util.spec_from_file_location("sia_server_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SIA_SERVER = load_sia_server()


class RecordingCoordinator:
    """Record coordinator callbacks made by the SIA event router."""

    def __init__(self) -> None:
        self.zone_updates: list[tuple[int, dict]] = []
        self.area_updates: list[tuple[int, dict]] = []

    def async_on_sia_update(self, zone_id: int, update: dict) -> None:
        self.zone_updates.append((zone_id, update))

    def async_on_sia_area_update(self, area_id: int, update: dict) -> None:
        self.area_updates.append((area_id, update))


class TestSiaAreaEvents(unittest.TestCase):
    """Verify area events use the partition, not the trailing user ID."""

    def route(self, event_class: str, partition="ri2", event_zone="001") -> RecordingCoordinator:
        coordinator = RecordingCoordinator()
        SIA_SERVER._process_sia_event(
            coordinator,
            {
                "partition": partition,
                "event_class": event_class,
                "event_zone": event_zone,
                "event_code": f"{event_class}{event_zone}",
                "account": "001050",
                "raw": "test",
            },
        )
        return coordinator

    def test_cl_uses_partition_for_fin_area(self) -> None:
        coordinator = self.route("CL")
        self.assertEqual(coordinator.area_updates, [(1, {"Armed": 1})])

    def test_op_uses_partition_for_fin_area(self) -> None:
        coordinator = self.route("OP")
        self.assertEqual(coordinator.area_updates, [(1, {"Armed": 4})])

    def test_pi_partition_without_user_id(self) -> None:
        self.assertEqual(self.route("CL", "pi3", "").area_updates, [(2, {"Armed": 1})])

    def test_invalid_partition_does_not_route_to_user_id(self) -> None:
        for partition in (None, "ri0", "xx2"):
            with self.subTest(partition=partition):
                self.assertEqual(self.route("CL", partition).area_updates, [])

    def test_zone_event_still_uses_zone_id(self) -> None:
        self.assertEqual(
            self.route("BA", "ri2", "3").zone_updates,
            [(2, {"Status": 2, "AlarmMemory": True})],
        )

    def test_real_area_payload_keeps_user_id_separate(self) -> None:
        message = (
            '74E0005D"SIA-DCS"0001L0#001050'
            '[#001050|Nri2CL001^FIN                            ^]'
            '_17:08:21,08-27-2026'
        )
        parsed = SIA_SERVER.parse_sia_msg(message)
        coordinator = RecordingCoordinator()
        SIA_SERVER._process_sia_event(coordinator, parsed)

        self.assertEqual(parsed["partition"], "ri2")
        self.assertEqual(parsed["event_zone"], "001")
        self.assertEqual(coordinator.area_updates, [(1, {"Armed": 1})])


if __name__ == "__main__":
    unittest.main()
