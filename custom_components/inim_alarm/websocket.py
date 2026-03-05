"""WebSocket client for INIM Cloud real-time updates."""

import asyncio
import json
import logging
from typing import Any, Callable
from urllib.parse import quote

import aiohttp

from .api import InimApi

_LOGGER = logging.getLogger(__name__)

WS_URL = "wss://ws.inimcloud.com/events"
PING_INTERVAL = 115  # Server timeout is ~120s, ping a bit earlier
RECONNECT_DELAY = 10


class InimWebSocketClient:
    """Client for INIM Cloud WebSocket events."""

    def __init__(
        self,
        api: InimApi,
        on_event: Callable[[dict[str, Any]], None],
    ) -> None:
        """Initialize the WebSocket client."""
        self._api = api
        self._on_event = on_event
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._run_task: asyncio.Task | None = None
        self._ping_task: asyncio.Task | None = None
        self._is_running = False

    async def start(self) -> None:
        """Start the WebSocket client."""
        if self._is_running:
            return
        self._is_running = True
        self._run_task = asyncio.create_task(self._listen_loop())
        self._ping_task = asyncio.create_task(self._ping_loop())

    async def stop(self) -> None:
        """Stop the WebSocket client."""
        self._is_running = False

        if self._ping_task:
            self._ping_task.cancel()
            self._ping_task = None

        if self._ws and not self._ws.closed:
            await self._ws.close()

        if self._run_task:
            self._run_task.cancel()
            self._run_task = None

    async def _get_ws_url(self) -> str:
        """Construct the WebSocket connection URL with auth."""
        if not self._api.is_authenticated:
            await self._api.authenticate()

        req_data = {
            "Node": "inimhome",
            "Name": "it.inim.inimutenti",
            "ClientIP": "",
            "Method": "WebSocketStart",
            "Token": self._api.token,
            "ClientId": self._api.client_id,
            "Context": None,
            "Params": {"Brand": 0},
        }

        req_json = json.dumps(req_data, separators=(",", ":"))
        return f"{WS_URL}?req={quote(req_json)}"

    async def _listen_loop(self) -> None:
        """Main listening loop with auto-reconnect."""
        while self._is_running:
            try:
                session = await self._api.get_session()
                url = await self._get_ws_url()

                _LOGGER.debug("Connecting to INIM WebSocket")
                async with session.ws_connect(url, heartbeat=None) as ws:
                    self._ws = ws
                    _LOGGER.info("Connected to INIM WebSocket")

                    async for msg in ws:
                        if not self._is_running:
                            break

                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self._handle_message(msg.data)
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            _LOGGER.warning("WebSocket closed/error: %s", msg)
                            break

            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.warning(
                    "WebSocket connection error: %s. Reconnecting in %ds...",
                    err,
                    RECONNECT_DELAY,
                )
            except Exception:
                _LOGGER.exception("Unexpected error in WebSocket loop")
            finally:
                self._ws = None

            if self._is_running:
                await asyncio.sleep(RECONNECT_DELAY)

    def _handle_message(self, text: str) -> None:
        """Parse and dispatch a WebSocket message."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as err:
            _LOGGER.error("Failed to parse WS message: %s", err)
            return

        msg_type = data.get("Type")

        if msg_type == "EVENT":
            event_data = data.get("Data", {})
            inner_data_str = event_data.get("Data")

            if inner_data_str and isinstance(inner_data_str, str):
                try:
                    inner_data = json.loads(inner_data_str)
                    self._on_event(inner_data)
                except json.JSONDecodeError as err:
                    _LOGGER.error("Failed to parse inner WS payload: %s", err)
        elif msg_type == "PONG":
            _LOGGER.debug("Received PONG from INIM WS")
        else:
            _LOGGER.debug("Unknown WS message type: %s", msg_type)

    async def _ping_loop(self) -> None:
        """Send keep-alive pings at regular intervals."""
        while self._is_running:
            await asyncio.sleep(PING_INTERVAL)
            if self._ws and not self._ws.closed:
                try:
                    await self._ws.send_str("@ ")
                    _LOGGER.debug("Sent INIM WS ping")
                except Exception as err:
                    _LOGGER.warning("Failed to send WS ping: %s", err)
