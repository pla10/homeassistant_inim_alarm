"""SIA-IP TCP Server for INIM real-time local updates.

Listens for SIA-DC09 messages from the INIM panel and pushes
zone/area state updates to the coordinator.
"""

import asyncio
import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# Timeout for idle client connections (seconds)
CLIENT_TIMEOUT = 120


def calculate_crc(data: str) -> str:
    """Calculate CRC-16 for SIA-DC09."""
    crc = 0
    for char in data:
        crc ^= ord(char)
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x8408
            else:
                crc >>= 1
    crc ^= 0xFFFF
    return f"{crc:04X}"


def parse_sia_msg(message: str) -> dict:
    """Parse a SIA-DC09 message and extract key components."""
    result = {"raw": message}

    match_header = re.search(r'"SIA-DCS"(\d{4})([^#]+)#(\d+)', message)
    if match_header:
        result["seq"] = match_header.group(1)
        result["receiver"] = match_header.group(2)
        result["account"] = match_header.group(3)

    match_event = re.search(r"\[(.*?)\]", message)
    if match_event:
        event_data = match_event.group(1)
        parts = event_data.split("|")
        if len(parts) >= 2:
            event_core = parts[1]
            m = re.match(
                r"([A-Z])(ri\d+|pi\d+|[a-z]{2}\d+)([A-Z]{2})(\d*)(?:\^(.*?)\^)?",
                event_core,
            )
            if m:
                result["modifier"] = m.group(1)
                result["partition"] = m.group(2)
                result["event_class"] = m.group(3)
                result["event_zone"] = m.group(4)
                result["event_code"] = m.group(3) + m.group(4)
                if m.group(5):
                    result["extra_data"] = m.group(5).strip()

    return result


def _build_ack(parsed: dict) -> str:
    """Build SIA ACK response message."""
    seq = parsed.get("seq", "0000")
    receiver = parsed.get("receiver", "000000")
    account = parsed.get("account", "000000")
    now_str = dt_util.now().strftime("%H:%M:%S,%m-%d-%Y")
    ack_payload = f'"ACK"{seq}{receiver}#{account}[]_{now_str}'
    ack_len_str = f"{len(ack_payload):04X}"
    ack_crc = calculate_crc(f"{ack_len_str}{ack_payload}")
    return f"\n{ack_crc}{ack_len_str}{ack_payload}\r"


# SIA event codes for area arm/disarm
AREA_ARM_CODES = {"CG", "CA", "CL", "CP"}
AREA_DISARM_CODES = {"OA", "OP", "OR"}
AREA_EVENT_CODES = AREA_ARM_CODES | AREA_DISARM_CODES

# SIA event codes for zone alarm/restore
ZONE_ALARM_CODES = {"BA", "TA"}
ZONE_RESTORE_CODES = {"BR", "TR"}


async def async_start_sia_server(
    hass: HomeAssistant, coordinator: Any, port: int, account_id: str | None = None
) -> asyncio.Server:
    """Start the SIA-IP TCP listener as an asyncio Server."""

    async def handle_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle incoming SIA connections."""
        addr = writer.get_extra_info("peername")
        _LOGGER.debug("SIA-IP Connection from %s", addr)

        try:
            while True:
                try:
                    data = await asyncio.wait_for(
                        reader.read(1024), timeout=CLIENT_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    _LOGGER.debug("SIA-IP Client %s timed out", addr)
                    break

                if not data:
                    break

                message = data.decode("ascii", errors="ignore").strip()
                if not message:
                    continue

                if message.startswith("\n"):
                    message = message[1:]

                if len(message) <= 8 or '"SIA-DCS"' not in message:
                    continue

                parsed = parse_sia_msg(message)

                # Filter by account if configured
                msg_account = parsed.get("account")
                if account_id and msg_account and msg_account != account_id:
                    _LOGGER.warning(
                        "SIA-IP Ignoring message from unknown account %s (expected %s)",
                        msg_account,
                        account_id,
                    )
                else:
                    _process_sia_event(coordinator, parsed)

                # Always ACK to prevent retransmission
                ack_msg = _build_ack(parsed)
                writer.write(ack_msg.encode("ascii"))
                _LOGGER.debug("SIA-IP Sent ACK for seq %s", parsed.get("seq"))
                await writer.drain()

        except Exception as err:
            _LOGGER.error("SIA-IP Error with %s: %s", addr, err)
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "0.0.0.0", port)
    _LOGGER.info("SIA-IP TCP Server listening on port %d", port)

    return server


def _process_sia_event(coordinator: Any, parsed: dict) -> None:
    """Route a parsed SIA event to the coordinator."""
    zone_id_str = parsed.get("event_zone")
    event_class = parsed.get("event_class")

    if not event_class or not zone_id_str:
        _LOGGER.debug("SIA-IP Ignoring event without class/zone: %s", parsed.get("raw"))
        return

    _LOGGER.debug(
        "SIA-IP Received Event: %s from account %s",
        parsed.get("event_code"),
        parsed.get("account"),
    )

    try:
        # SIA events are 1-indexed, INIM API is 0-indexed
        id_int = int(zone_id_str) - 1
    except ValueError:
        _LOGGER.error("SIA-IP Invalid zone/area ID: %s", zone_id_str)
        return

    if event_class in AREA_EVENT_CODES:
        armed_value = 4 if event_class in AREA_DISARM_CODES else 1
        coordinator.async_on_sia_area_update(id_int, {"Armed": armed_value})
    elif event_class in ZONE_ALARM_CODES:
        coordinator.async_on_sia_update(id_int, {"Status": 2, "AlarmMemory": True})
    elif event_class in ZONE_RESTORE_CODES:
        coordinator.async_on_sia_update(id_int, {"Status": 1})
    else:
        _LOGGER.debug("SIA-IP Unhandled event class: %s", event_class)
