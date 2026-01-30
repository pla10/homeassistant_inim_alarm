#!/usr/bin/env python3
"""Interactive test script for INIM API polling."""

import asyncio
import json
import uuid
from urllib.parse import quote
from datetime import datetime

import aiohttp

# === CONFIGURATION ===
USERNAME = "planora@hotmail.com"
PASSWORD = "qyhqik-tydpok-Sugde2"
DEVICE_ID = 248944  # From your Burp capture
DELAY_SECONDS = 5  # Delay between RequestPoll and GetDevicesExtended

API_BASE_URL = "https://api.inimcloud.com/"
API_HEADERS = {
    "Host": "api.inimcloud.com",
    "Accept": "*/*",
    "Accept-Language": "it-it",
    "User-Agent": "Inim Home/5 CFNetwork/1329 Darwin/21.3.0",
}


class InimTester:
    def __init__(self):
        self.token = None
        self.client_id = f"ha-test-{uuid.uuid4()}"
        self.session = None
    
    async def _request(self, request_data: dict) -> dict:
        """Make API request."""
        req_json = json.dumps(request_data, separators=(",", ":"))
        url = f"{API_BASE_URL}?req={quote(req_json)}"
        
        async with self.session.get(url, headers=API_HEADERS) as response:
            return await response.json()
    
    async def authenticate(self) -> bool:
        """Authenticate and get token."""
        print("🔐 Authenticating...")
        
        request_data = {
            "Node": "",
            "Name": "",
            "ClientIP": "",
            "Method": "RegisterClient",
            "ClientId": "",
            "Token": "",
            "Params": {
                "Username": USERNAME,
                "Password": PASSWORD,
                "ClientId": self.client_id,
                "ClientName": "TestScript",
                "ClientInfo": "{}",
                "Role": "1",
                "Brand": "0",
            },
        }
        
        response = await self._request(request_data)
        
        if response.get("Status") == 0:
            self.token = response.get("Data", {}).get("Token")
            print(f"✅ Authenticated! Token TTL: {response.get('Data', {}).get('TTL', 0)} seconds")
            return True
        else:
            print(f"❌ Auth failed: {response.get('ErrMsg')}")
            return False
    
    async def request_poll(self) -> bool:
        """Request poll to wake up central unit."""
        request_data = {
            "Params": {"DeviceId": DEVICE_ID, "Type": 5},
            "Node": "",
            "Name": "Test Script",
            "ClientIP": "",
            "Method": "RequestPoll",
            "Token": self.token,
            "ClientId": self.client_id,
            "Context": "intrusion",
        }
        
        response = await self._request(request_data)
        return response.get("Status") == 0
    
    async def get_devices(self) -> list:
        """Get devices with extended info."""
        request_data = {
            "Node": "inimhome",
            "Name": "it.inim.inimutenti",
            "ClientIP": "",
            "Method": "GetDevicesExtended",
            "Token": self.token,
            "ClientId": self.client_id,
            "Context": None,
            "Params": {"Info": "16908287"},
        }
        
        response = await self._request(request_data)
        
        if response.get("Status") == 0:
            return response.get("Data", {}).get("Devices", [])
        return []
    
    def get_zone_status(self, devices: list, zone_id: int = None) -> dict:
        """Get zone status from devices data."""
        for device in devices:
            zones = device.get("Zones", [])
            for zone in zones:
                if zone_id is None or zone.get("ZoneId") == zone_id:
                    return zone
        return {}
    
    def print_zones(self, devices: list):
        """Print all zones with their status."""
        print("\n📋 Zone Status:")
        print("-" * 60)
        for device in devices:
            zones = device.get("Zones", [])
            for zone in sorted(zones, key=lambda z: z.get("ZoneId", 0)):
                zone_id = zone.get("ZoneId")
                name = zone.get("Name", "?")
                status = zone.get("Status", 0)
                status_text = "🟢 CHIUSO" if status == 1 else "🔴 APERTO" if status == 2 else f"❓ {status}"
                print(f"  Zone {zone_id:2d}: {name:20s} → {status_text}")
        print("-" * 60)
    
    async def poll_and_read(self, delay: float = DELAY_SECONDS) -> list:
        """Do RequestPoll, wait, then GetDevicesExtended."""
        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        print(f"\n[{now}] 📡 RequestPoll...", end=" ", flush=True)
        if await self.request_poll():
            print("✅")
        else:
            print("❌")
            return []
        
        if delay > 0:
            print(f"[{now}] ⏳ Waiting {delay}s for central to respond...", flush=True)
            await asyncio.sleep(delay)
        
        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{now}] 📥 GetDevicesExtended...", end=" ", flush=True)
        devices = await self.get_devices()
        print("✅" if devices else "❌")
        
        return devices
    
    async def run_test(self, cycles: int = 5, zone_to_watch: int = None):
        """Run interactive test."""
        async with aiohttp.ClientSession() as session:
            self.session = session
            
            if not await self.authenticate():
                return
            
            # Initial read
            print("\n" + "="*60)
            print("📊 INITIAL STATE")
            print("="*60)
            devices = await self.poll_and_read()
            self.print_zones(devices)
            
            if zone_to_watch:
                zone = self.get_zone_status(devices, zone_to_watch)
                print(f"\n🎯 Watching Zone {zone_to_watch}: {zone.get('Name', '?')}")
            
            print("\n" + "="*60)
            print("🧪 INTERACTIVE TEST")
            print("="*60)
            print(f"Delay between RequestPoll and GetDevices: {DELAY_SECONDS}s")
            
            for cycle in range(1, cycles + 1):
                print(f"\n{'='*60}")
                print(f"📍 CYCLE {cycle}/{cycles}")
                print("="*60)
                
                # Step 1: Ensure CLOSED
                input("\n👉 Assicurati che la finestra sia CHIUSA, poi premi INVIO...")
                devices = await self.poll_and_read()
                
                if zone_to_watch:
                    zone = self.get_zone_status(devices, zone_to_watch)
                    status = zone.get("Status", 0)
                    expected = 1  # CLOSED
                    result = "✅ OK" if status == expected else f"❌ WRONG (got {status}, expected {expected})"
                    print(f"🎯 Zone {zone_to_watch} Status: {status} → {result}")
                else:
                    self.print_zones(devices)
                
                # Step 2: OPEN
                input("\n👉 Ora APRI la finestra, poi premi INVIO...")
                devices = await self.poll_and_read()
                
                if zone_to_watch:
                    zone = self.get_zone_status(devices, zone_to_watch)
                    status = zone.get("Status", 0)
                    expected = 2  # OPEN
                    result = "✅ OK" if status == expected else f"❌ WRONG (got {status}, expected {expected})"
                    print(f"🎯 Zone {zone_to_watch} Status: {status} → {result}")
                else:
                    self.print_zones(devices)
            
            print("\n" + "="*60)
            print("✅ TEST COMPLETED")
            print("="*60)


async def main():
    print("="*60)
    print("🧪 INIM API Polling Test Script")
    print("="*60)
    
    # Ask which zone to watch
    print("\nQuale zona vuoi monitorare?")
    print("(Lascia vuoto per vedere tutte le zone)")
    zone_input = input("Zone ID: ").strip()
    zone_to_watch = int(zone_input) if zone_input else None
    
    # Ask number of cycles
    cycles_input = input("Quanti cicli? [5]: ").strip()
    cycles = int(cycles_input) if cycles_input else 5
    
    tester = InimTester()
    await tester.run_test(cycles=cycles, zone_to_watch=zone_to_watch)


if __name__ == "__main__":
    asyncio.run(main())
