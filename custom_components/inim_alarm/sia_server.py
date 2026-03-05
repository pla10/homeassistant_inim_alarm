"""SIA-IP TCP Server for Inim Home real-time local updates."""

import asyncio
import logging
import re
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


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
    """Parses a SIA message and extracts key components."""
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
                result["event_class"] = m.group(3)  # e.g., BA
                result["event_zone"] = m.group(4)  # e.g., 18
                result["event_code"] = m.group(3) + m.group(4)
                if m.group(5):
                    result["extra_data"] = m.group(5).strip()

    return result


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
                data = await reader.read(1024)
                if not data:
                    break

                message = data.decode("ascii", errors="ignore").strip()
                if not message:
                    continue

                if message.startswith("\n"):
                    message = message[1:]

                # SIA format starts with CRC(4 bytes) Length(4 bytes) "SIA-DCS"
                if len(message) > 8 and '"SIA-DCS"' in message:
                    parsed = parse_sia_msg(message)

                    msg_account = parsed.get("account")
                    if account_id and msg_account and msg_account != account_id:
                        _LOGGER.warning(
                            "SIA-IP Ignoring message from unknown account %s (expected %s)",
                            msg_account,
                            account_id,
                        )
                        # We still ACK to prevent them spamming, or just continue.
                        # Best effort: ACK but don't process
                        pass
                    else:
                        _LOGGER.debug(
                            "SIA-IP Received Event: %s from account %s",
                            parsed.get("event_code"),
                            msg_account,
                        )

                        # Push updates to Coordinator based on event class
                        # For example: BA (Burglar Alarm), BR (Burglar Restore)
                        zone_id = parsed.get("event_zone")
                        event_class = parsed.get("event_class")

                        if (
                            event_class in ["OA", "OP", "OR", "CG", "CA", "CL", "CP"]
                            and zone_id
                        ):
                            try:
                                # SIA events are 1-indexed, API is 0-indexed
                                area_id_int = int(zone_id) - 1
                                if event_class in ["OA", "OP", "OR"]:  # Disarmed
                                    coordinator.async_on_sia_area_update(
                                        area_id_int,
                                        {"Armed": 4},  # 4 = Disarmed
                                    )
                                else:  # Armed
                                    coordinator.async_on_sia_area_update(
                                        area_id_int,
                                        {"Armed": 1},  # 1 = Armed
                                    )
                            except ValueError as err:
                                _LOGGER.error("Invalid area_id extracted: %s", err)
                        elif zone_id and event_class:
                            try:
                                # SIA is 1-indexed, INIM API is 0-indexed
                                zone_id_int = int(zone_id) - 1

                                if event_class in ["BA", "TA"]:  # Burglar/Tamper Alarm
                                    # We use the method on InimDataUpdateCoordinator
                                    coordinator.async_on_sia_update(
                                        zone_id_int, {"Status": 2, "AlarmMemory": True}
                                    )
                                elif event_class in [
                                    "BR",
                                    "TR",
                                ]:  # Burglar/Tamper Restore
                                    coordinator.async_on_sia_update(
                                        zone_id_int, {"Status": 1}
                                    )
                            except ValueError as err:
                                _LOGGER.error("Invalid zone_id extracted: %s", err)

                    # Acknowledge the packet to the central unit
                    seq = parsed.get("seq", "0000")
                    receiver = parsed.get("receiver", "000000")
                    account = parsed.get("account", "000000")
                    now_str = datetime.now().strftime("%H:%M:%S,%m-%d-%Y")
                    ack_payload = f'"ACK"{seq}{receiver}#{account}[]_{now_str}'
                    ack_lenStr = f"{len(ack_payload):04X}"

                    ack_crc = calculate_crc(f"{ack_lenStr}{ack_payload}")
                    ack_msg = f"\n{ack_crc}{ack_lenStr}{ack_payload}\r"

                    writer.write(ack_msg.encode("ascii"))
                    _LOGGER.debug(
                        "SIA-IP Sent ACK: CRC: %s - Length: %s - Payload: %s",
                        ack_crc,
                        ack_lenStr,
                        ack_payload,
                    )
                    await writer.drain()

        except asyncio.TimeoutError:
            pass
        except Exception as e:
            _LOGGER.error("SIA-IP Error with %s: %s", addr, e)
        finally:
            writer.close()
            await writer.wait_closed()

    # Start the server
    server = await asyncio.start_server(handle_client, "0.0.0.0", port)
    _LOGGER.info("SIA-IP TCP Server listening on port %d", port)

    return server
