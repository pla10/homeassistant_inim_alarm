"""WebSocket client for INIM Cloud."""

import asyncio
import json
import logging
from typing import Any, Callable
from urllib.parse import quote

import aiohttp

from .api import InimApi

_LOGGER = logging.getLogger(__name__)

WS_URL = "wss://ws.inimcloud.com/events"
PING_INTERVAL = 115  # Polling is done every 2 minutes (120s), so pinging a bit earlier


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
        """Construct the connection URL."""
        # Ensure we are authenticated and have a token
        if not self._api.is_authenticated:
            await self._api.authenticate()

        # Build the exact request params found in Burp Suite
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
        """Main listening loop for the WebSocket connection."""
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
                            text = msg.data
                            _LOGGER.debug("Received WS message: %s", text)
                            
                            try:
                                data = json.loads(text)
                                msg_type = data.get("Type")
                                
                                if msg_type == "EVENT":
                                    # Pushed events have double JSON encoded data payload
                                    event_data = data.get("Data", {})
                                    inner_data_str = event_data.get("Data")
                                    
                                    if inner_data_str and isinstance(inner_data_str, str):
                                        try:
                                            inner_data = json.loads(inner_data_str)
                                            # Notify the coordinator of the event payload
                                            self._on_event(inner_data)
                                        except json.JSONDecodeError as err:
                                            _LOGGER.error("Failed to parse inner WS payload: %s", err)
                                            
                                elif msg_type == "PONG":
                                    _LOGGER.debug("Received PONG from INIM WS")
                                else:
                                    _LOGGER.debug("Unknown WS message type: %s", msg_type)

                            except json.JSONDecodeError as err:
                                _LOGGER.error("Failed to parse WS message: %s - Data: %s", err, text)
                                
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            _LOGGER.warning("WebSocket connection closed or error: %s", msg)
                            break
                            
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.warning("WebSocket connection error: %s. Reconnecting in 10s...", err)
            except Exception as err:
                _LOGGER.exception("Unexpected error in WebSocket loop: %s", err)
            finally:
                self._ws = None

            # Add a backoff before trying to reconnect
            if self._is_running:
                await asyncio.sleep(10)

    async def _ping_loop(self) -> None:
        """Periodically send the keep-alive ping."""
        while self._is_running:
            await asyncio.sleep(PING_INTERVAL)
            if self._ws and not self._ws.closed:
                try:
                    # Inim's keep-alive ping is simply sending the string "@ " over the socket
                    _LOGGER.debug("Sending INIM WS Ping '@ '")
                    await self._ws.send_str("@ ")
                except Exception as err:
                    _LOGGER.warning("Failed to send WS ping: %s", err)
                    if not self._ws.closed:
                        await self._ws.close()
