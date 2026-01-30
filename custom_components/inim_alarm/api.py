"""API client for INIM Cloud."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import (
    API_BASE_URL,
    API_HEADERS,
    BYPASS_MODE_BYPASS,
    BYPASS_MODE_NORMAL,
    DEFAULT_CLIENT_NAME,
    METHOD_ACTIVATE_SCENARIO,
    METHOD_GET_DEVICES_EXTENDED,
    METHOD_INSERT_ZONE,
    METHOD_REGISTER_CLIENT,
    METHOD_REQUEST_POLL,
)

_LOGGER = logging.getLogger(__name__)


class InimApiError(Exception):
    """Exception for INIM API errors."""

    def __init__(self, message: str, error_code: int = 0) -> None:
        """Initialize the exception."""
        super().__init__(message)
        self.error_code = error_code


class InimAuthError(InimApiError):
    """Exception for authentication errors."""


class InimApi:
    """Client for INIM Cloud API."""

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize the API client."""
        self._username = username
        self._password = password
        self._session = session
        self._own_session = session is None
        self._token: str | None = None
        self._token_ttl: int = 0
        self._client_id = f"ha-{uuid.uuid4()}"
        self._devices: list[dict[str, Any]] = []

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._own_session = True
        return self._session

    async def close(self) -> None:
        """Close the session if we own it."""
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()

    async def _request(self, request_data: dict[str, Any]) -> dict[str, Any]:
        """Make a request to the INIM API."""
        session = await self._get_session()
        
        # URL encode the JSON request
        req_json = json.dumps(request_data, separators=(",", ":"))
        url = f"{API_BASE_URL}?req={quote(req_json)}"
        
        # Log only method name, never credentials or tokens
        _LOGGER.debug("API Request: %s", request_data.get("Method"))
        
        try:
            async with session.get(url, headers=API_HEADERS) as response:
                response.raise_for_status()
                data = await response.json()
                
                _LOGGER.debug("API Response Status: %s", data.get("Status"))
                
                if data.get("Status") != 0:
                    error_msg = data.get("ErrMsg", "Unknown error")
                    error_code = data.get("Status", 0)
                    
                    # Check for authentication errors
                    if error_code in (18, 19, 20):  # Token expired/invalid
                        raise InimAuthError(error_msg, error_code)
                    
                    raise InimApiError(error_msg, error_code)
                
                return data
                
        except aiohttp.ClientError as err:
            raise InimApiError(f"Connection error: {err}") from err

    async def authenticate(self) -> bool:
        """Authenticate with INIM Cloud and get token."""
        client_info = json.dumps({
            "name": "home_assistant",
            "version": "1.0.0",
            "device": "HomeAssistant",
            "brand": "HomeAssistant",
            "platform": "linux",
        })
        
        request_data = {
            "Node": "",
            "Name": "",
            "ClientIP": "",
            "Method": METHOD_REGISTER_CLIENT,
            "ClientId": "",
            "Token": "",
            "Params": {
                "Username": self._username,
                "Password": self._password,
                "ClientId": self._client_id,
                "ClientName": DEFAULT_CLIENT_NAME,
                "ClientInfo": client_info,
                "Role": "1",
                "Brand": "0",
            },
        }
        
        try:
            response = await self._request(request_data)
            data = response.get("Data", {})
            
            self._token = data.get("Token")
            self._token_ttl = data.get("TTL", 86400)
            
            if not self._token:
                raise InimAuthError("No token received")
            
            _LOGGER.info("Successfully authenticated with INIM Cloud")
            return True
            
        except InimApiError as err:
            _LOGGER.error("Authentication failed: %s", err)
            raise

    async def _ensure_authenticated(self) -> None:
        """Ensure we have a valid token."""
        if not self._token:
            await self.authenticate()

    async def request_poll(self, device_id: int) -> None:
        """Request a poll for updated data."""
        await self._ensure_authenticated()
        
        request_data = {
            "Params": {"DeviceId": device_id, "Type": 5},
            "Node": "",
            "Name": "Home Assistant",
            "ClientIP": "",
            "Method": METHOD_REQUEST_POLL,
            "Token": self._token,
            "ClientId": self._client_id,
            "Context": "intrusion",
        }
        
        try:
            await self._request(request_data)
        except InimAuthError:
            # Token expired, re-authenticate and retry
            await self.authenticate()
            request_data["Token"] = self._token
            await self._request(request_data)

    async def get_devices(self) -> list[dict[str, Any]]:
        """Get all devices with extended information."""
        await self._ensure_authenticated()
        
        request_data = {
            "Node": "inimhome",
            "Name": "it.inim.inimutenti",
            "ClientIP": "",
            "Method": METHOD_GET_DEVICES_EXTENDED,
            "Token": self._token,
            "ClientId": self._client_id,
            "Context": None,
            "Params": {"Info": "16908287"},
        }
        
        try:
            response = await self._request(request_data)
            self._devices = response.get("Data", {}).get("Devices", [])
            return self._devices
        except InimAuthError:
            # Token expired, re-authenticate and retry
            await self.authenticate()
            request_data["Token"] = self._token
            response = await self._request(request_data)
            self._devices = response.get("Data", {}).get("Devices", [])
            return self._devices

    async def activate_scenario(self, device_id: int, scenario_id: int) -> bool:
        """Activate a scenario (arm/disarm)."""
        await self._ensure_authenticated()
        
        request_data = {
            "Node": "inimhome",
            "Name": "it.inim.inimutenti",
            "ClientIP": "",
            "Method": METHOD_ACTIVATE_SCENARIO,
            "Token": self._token,
            "ClientId": self._client_id,
            "Context": None,
            "Params": {
                "ScenarioId": scenario_id,
                "DeviceId": device_id,
            },
        }
        
        try:
            await self._request(request_data)
            _LOGGER.info("Scenario %s activated for device %s", scenario_id, device_id)
            return True
        except InimAuthError:
            # Token expired, re-authenticate and retry
            await self.authenticate()
            request_data["Token"] = self._token
            await self._request(request_data)
            return True

    async def arm_away(self, device_id: int, scenario_id: int = 0) -> bool:
        """Arm the alarm in away mode (total)."""
        return await self.activate_scenario(device_id, scenario_id)

    async def arm_home(self, device_id: int, scenario_id: int) -> bool:
        """Arm the alarm in home mode (partial)."""
        return await self.activate_scenario(device_id, scenario_id)

    async def disarm(self, device_id: int, scenario_id: int = 1) -> bool:
        """Disarm the alarm."""
        return await self.activate_scenario(device_id, scenario_id)

    async def bypass_zone(
        self, device_id: int, zone_id: int, user_code: str, bypass: bool = True
    ) -> bool:
        """Bypass or reinstate a zone.
        
        Args:
            device_id: The device ID
            zone_id: The zone ID to bypass
            user_code: The user code for the alarm
            bypass: True to bypass, False to reinstate
            
        Returns:
            True if successful
        """
        await self._ensure_authenticated()
        
        mode = BYPASS_MODE_BYPASS if bypass else BYPASS_MODE_NORMAL
        
        request_data = {
            "Node": "inimhome",
            "Name": "it.inim.inimutenti",
            "ClientIP": "",
            "Method": METHOD_INSERT_ZONE,
            "Token": self._token,
            "ClientId": self._client_id,
            "Params": {
                "ZoneId": zone_id,
                "Mode": mode,
                "DeviceId": str(device_id),
                "Code": user_code,
                "Value": 0,
            },
        }
        
        try:
            await self._request(request_data)
            action = "bypassed" if bypass else "reinstated"
            _LOGGER.info("Zone %s %s on device %s", zone_id, action, device_id)
            return True
        except InimAuthError:
            # Token expired, re-authenticate and retry
            await self.authenticate()
            request_data["Token"] = self._token
            await self._request(request_data)
            return True

    async def insert_areas(
        self, device_id: int, area_ids: list[int], user_code: str, arm: bool = True
    ) -> bool:
        """Arm or disarm specific areas.
        
        Args:
            device_id: The device ID
            area_ids: List of area IDs to arm/disarm
            user_code: The user code for the alarm
            arm: True to arm, False to disarm
            
        Returns:
            True if successful
        """
        await self._ensure_authenticated()
        
        # Mode: 0 = arm (Armed=1), 3 = disarm (Armed=4)
        mode = 0 if arm else 3
        
        request_data = {
            "Node": "inimhome",
            "Name": "it.inim.inimutenti",
            "ClientIP": "",
            "Method": "InsertAreas",
            "Token": self._token,
            "ClientId": self._client_id,
            "Params": {
                "AreaIds": area_ids,
                "Mode": mode,
                "DeviceId": str(device_id),
                "Code": user_code,
            },
        }
        
        try:
            await self._request(request_data)
            action = "armed" if arm else "disarmed"
            _LOGGER.info("Areas %s %s on device %s", area_ids, action, device_id)
            return True
        except InimAuthError:
            # Token expired, re-authenticate and retry
            await self.authenticate()
            request_data["Token"] = self._token
            await self._request(request_data)
            return True

    @property
    def devices(self) -> list[dict[str, Any]]:
        """Return cached devices."""
        return self._devices

    @property
    def is_authenticated(self) -> bool:
        """Return if we have a valid token."""
        return self._token is not None
