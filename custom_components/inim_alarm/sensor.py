"""Sensor platform for INIM Alarm."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricPotential, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    AREA_ARMED_ARMED,
    AREA_ARMED_DISARMED,
    ATTR_ALARM_MEMORY,
    ATTR_AREA_ID,
    ATTR_DEVICE_ID,
    ATTR_TAMPER_MEMORY,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import InimDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Armed status mapping
ARMED_STATUS_MAP = {
    1: "armed",
    2: "armed_partial",
    3: "armed_partial",
    4: "disarmed",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up INIM sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: InimDataUpdateCoordinator = data["coordinator"]

    entities: list[SensorEntity] = []
    
    for device in coordinator.devices:
        device_id = device.get("device_id")
        device_name = device.get("name", "INIM Alarm")
        
        if not device_id:
            continue
        
        # Create voltage sensor for the device
        entities.append(
            InimVoltageSensor(
                coordinator=coordinator,
                device_id=device_id,
                device_name=device_name,
            )
        )
        
        # Create faults sensor for the device
        entities.append(
            InimFaultsSensor(
                coordinator=coordinator,
                device_id=device_id,
                device_name=device_name,
            )
        )
        
        # Create sensors for each area (only for areas that seem to be in use)
        for area in device.get("areas", []):
            area_id = area.get("AreaId")
            area_name = area.get("Name", f"Area {area_id}")
            
            # Skip generic/unused areas (those with default names like "Area 3", "Area 4", etc.)
            if area_name.startswith("Area ") and area_name[5:].isdigit():
                continue
            
            entities.append(
                InimAreaSensor(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=device_name,
                    area_id=area_id,
                    area_name=area_name,
                )
            )
        
        # Create sensors for peripherals (voltage and status)
        for peripheral in device.get("peripherals", []):
            peripheral_name = peripheral.get("Name", "Unknown")
            item_id = peripheral.get("ItemId", 0)
            peripheral_type = peripheral.get("Type", 0)
            voltage = peripheral.get("Voltage", 0)
            
            # Skip peripherals without meaningful voltage (like Smartlogos)
            if voltage > 0.5:
                entities.append(
                    InimPeripheralVoltageSensor(
                        coordinator=coordinator,
                        device_id=device_id,
                        device_name=device_name,
                        peripheral_type=peripheral_type,
                        item_id=item_id,
                        peripheral_name=peripheral_name,
                    )
                )
            
            # Create GSM/Nexus sensor with extra data
            if peripheral_type == 32768:  # Nexus GSM module
                entities.append(
                    InimGsmSensor(
                        coordinator=coordinator,
                        device_id=device_id,
                        device_name=device_name,
                        peripheral_type=peripheral_type,
                        item_id=item_id,
                        peripheral_name=peripheral_name,
                    )
                )
        
        # Create temperature sensors for thermostats (JOY MAX keyboards, etc.)
        for thermostat in device.get("thermostats", []):
            thermostat_id = thermostat.get("ThermostatId")
            thermostat_name = thermostat.get("Name", f"Thermostat {thermostat_id}")
            
            if thermostat_id is not None:
                entities.append(
                    InimTemperatureSensor(
                        coordinator=coordinator,
                        device_id=device_id,
                        device_name=device_name,
                        thermostat_id=thermostat_id,
                        thermostat_name=thermostat_name,
                    )
                )

    async_add_entities(entities)


class InimVoltageSensor(
    CoordinatorEntity[InimDataUpdateCoordinator], SensorEntity
):
    """Representation of an INIM Voltage sensor."""

    _attr_has_entity_name = True
    _attr_name = "Voltage"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT

    def __init__(
        self,
        coordinator: InimDataUpdateCoordinator,
        device_id: int,
        device_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._attr_unique_id = f"{device_id}_voltage"

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
    def native_value(self) -> float | None:
        """Return the voltage value."""
        device = self.coordinator.get_device(self._device_id)
        if not device:
            return None
        
        voltage = device.get("voltage")
        if voltage is not None:
            return round(voltage, 2)
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class InimFaultsSensor(
    CoordinatorEntity[InimDataUpdateCoordinator], SensorEntity
):
    """Representation of an INIM Faults sensor."""

    _attr_has_entity_name = True
    _attr_name = "Faults"
    _attr_icon = "mdi:alert-circle"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: InimDataUpdateCoordinator,
        device_id: int,
        device_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._attr_unique_id = f"{device_id}_faults"

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
    def native_value(self) -> int | None:
        """Return the faults count."""
        device = self.coordinator.get_device(self._device_id)
        if not device:
            return None

        return device.get("faults", 0)

    @property
    def icon(self) -> str:
        """Return icon based on faults state."""
        device = self.coordinator.get_device(self._device_id)
        if not device:
            return "mdi:alert-circle-outline"

        faults = device.get("faults", 0)
        if faults and faults > 0:
            return "mdi:alert-circle"
        return "mdi:check-circle"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class InimTemperatureSensor(
    CoordinatorEntity[InimDataUpdateCoordinator], SensorEntity
):
    """Representation of an INIM Temperature sensor (JOY MAX keyboards, etc.)."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: InimDataUpdateCoordinator,
        device_id: int,
        device_name: str,
        thermostat_id: int,
        thermostat_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._thermostat_id = thermostat_id
        self._thermostat_name = thermostat_name
        self._attr_unique_id = f"{device_id}_thermostat_{thermostat_id}"
        self._attr_name = f"{thermostat_name} Temperature"

    def _get_thermostat(self) -> dict[str, Any] | None:
        """Get the thermostat data."""
        device = self.coordinator.get_device(self._device_id)
        if not device:
            return None
        for thermostat in device.get("thermostats", []):
            if thermostat.get("ThermostatId") == self._thermostat_id:
                return thermostat
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
    def native_value(self) -> float | None:
        """Return the current temperature."""
        thermostat = self._get_thermostat()
        if not thermostat:
            return None

        temperature = thermostat.get("Temperature")
        if temperature is not None:
            return round(float(temperature), 1)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        thermostat = self._get_thermostat()
        if not thermostat:
            return {}

        attrs: dict[str, Any] = {
            ATTR_DEVICE_ID: self._device_id,
            "thermostat_id": self._thermostat_id,
            "thermostat_name": thermostat.get("Name"),
        }

        # Add setpoint if available
        setpoint = thermostat.get("SetPoint")
        if setpoint is not None:
            attrs["setpoint"] = round(float(setpoint), 1)

        # Add mode if available
        mode = thermostat.get("Mode")
        if mode is not None:
            attrs["mode"] = mode

        # Add enabled status if available
        enabled = thermostat.get("Enabled")
        if enabled is not None:
            attrs["enabled"] = enabled > 0

        # Add humidity if available
        humidity = thermostat.get("Humidity")
        if humidity is not None:
            attrs["humidity"] = humidity

        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class InimPeripheralVoltageSensor(
    CoordinatorEntity[InimDataUpdateCoordinator], SensorEntity
):
    """Representation of an INIM Peripheral Voltage sensor."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT

    def __init__(
        self,
        coordinator: InimDataUpdateCoordinator,
        device_id: int,
        device_name: str,
        peripheral_type: int,
        item_id: int,
        peripheral_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._peripheral_type = peripheral_type
        self._item_id = item_id
        self._peripheral_name = peripheral_name
        self._attr_unique_id = f"{device_id}_peripheral_{peripheral_type}_{item_id}_voltage"
        self._attr_name = f"{peripheral_name} Voltage"

    def _get_peripheral(self) -> dict[str, Any] | None:
        """Get the peripheral data."""
        device = self.coordinator.get_device(self._device_id)
        if not device:
            return None
        for peripheral in device.get("peripherals", []):
            if (peripheral.get("Type") == self._peripheral_type and 
                peripheral.get("ItemId") == self._item_id):
                return peripheral
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
    def native_value(self) -> float | None:
        """Return the voltage value."""
        peripheral = self._get_peripheral()
        if not peripheral:
            return None
        
        voltage = peripheral.get("Voltage")
        if voltage is not None:
            return round(voltage, 2)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        peripheral = self._get_peripheral()
        if not peripheral:
            return {}
        
        return {
            "peripheral_name": peripheral.get("Name"),
            "firmware": peripheral.get("Firmware"),
            "tamper": peripheral.get("Tamper", 0) > 0,
            "missing": peripheral.get("Missing", 0) > 0,
            "enabled": peripheral.get("Enabled", 0) > 0,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class InimGsmSensor(
    CoordinatorEntity[InimDataUpdateCoordinator], SensorEntity
):
    """Representation of an INIM GSM/Nexus sensor."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:signal-cellular-3"

    def __init__(
        self,
        coordinator: InimDataUpdateCoordinator,
        device_id: int,
        device_name: str,
        peripheral_type: int,
        item_id: int,
        peripheral_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._peripheral_type = peripheral_type
        self._item_id = item_id
        self._peripheral_name = peripheral_name
        self._attr_unique_id = f"{device_id}_peripheral_{peripheral_type}_{item_id}_gsm"
        self._attr_name = f"{peripheral_name} GSM"

    def _get_peripheral(self) -> dict[str, Any] | None:
        """Get the peripheral data."""
        device = self.coordinator.get_device(self._device_id)
        if not device:
            return None
        for peripheral in device.get("peripherals", []):
            if (peripheral.get("Type") == self._peripheral_type and 
                peripheral.get("ItemId") == self._item_id):
                return peripheral
        return None

    def _parse_data(self, peripheral: dict[str, Any]) -> dict[str, Any]:
        """Parse the Data JSON field."""
        import json
        data_str = peripheral.get("Data")
        if data_str:
            try:
                return json.loads(data_str)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

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
    def native_value(self) -> str | None:
        """Return the operator name."""
        peripheral = self._get_peripheral()
        if not peripheral:
            return None
        
        data = self._parse_data(peripheral)
        operator = data.get("Operator", "Unknown")
        return operator if operator else "Unknown"

    @property
    def icon(self) -> str:
        """Return icon based on signal strength."""
        peripheral = self._get_peripheral()
        if not peripheral:
            return "mdi:signal-cellular-outline"
        
        data = self._parse_data(peripheral)
        field = data.get("Field", 0)
        
        if field >= 75:
            return "mdi:signal-cellular-3"
        elif field >= 50:
            return "mdi:signal-cellular-2"
        elif field >= 25:
            return "mdi:signal-cellular-1"
        return "mdi:signal-cellular-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        peripheral = self._get_peripheral()
        if not peripheral:
            return {}
        
        data = self._parse_data(peripheral)
        
        return {
            "signal_strength": data.get("Field", 0),
            "operator": data.get("Operator"),
            "imei": data.get("IMEI"),
            "is_4g": data.get("Is4G", 0) > 0,
            "has_gprs": data.get("HasGPRS", 0) > 0,
            "volte_present": data.get("VoLTEPresent", 0) > 0,
            "battery_present": data.get("BatteryPresent", 0) > 0,
            "battery_charge": data.get("BatteryCharge", 0),
            "firmware": peripheral.get("Firmware"),
            "voltage": round(peripheral.get("Voltage", 0), 2),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class InimAreaSensor(
    CoordinatorEntity[InimDataUpdateCoordinator], SensorEntity
):
    """Representation of an INIM Area sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: InimDataUpdateCoordinator,
        device_id: int,
        device_name: str,
        area_id: int,
        area_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._area_id = area_id
        self._area_name = area_name
        self._attr_unique_id = f"{device_id}_area_{area_id}"
        self._attr_name = area_name
        self._attr_icon = "mdi:shield-home"

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
    def native_value(self) -> str | None:
        """Return the area status."""
        area = self.coordinator.get_area(self._device_id, self._area_id)
        if not area:
            return None
        
        armed = area.get("Armed", AREA_ARMED_DISARMED)
        return ARMED_STATUS_MAP.get(armed, "unknown")

    @property
    def icon(self) -> str:
        """Return the icon based on state."""
        area = self.coordinator.get_area(self._device_id, self._area_id)
        if not area:
            return "mdi:shield-off"
        
        armed = area.get("Armed", AREA_ARMED_DISARMED)
        alarm = area.get("Alarm", 0)
        
        if alarm > 0:
            return "mdi:shield-alert"
        if armed == AREA_ARMED_DISARMED:
            return "mdi:shield-off"
        return "mdi:shield-check"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        area = self.coordinator.get_area(self._device_id, self._area_id)
        if not area:
            return {}
        
        return {
            ATTR_DEVICE_ID: self._device_id,
            ATTR_AREA_ID: self._area_id,
            "armed_value": area.get("Armed"),
            "alarm": area.get("Alarm", 0) > 0,
            ATTR_ALARM_MEMORY: area.get("AlarmMemory", 0) > 0,
            "tamper": area.get("Tamper", 0) > 0,
            ATTR_TAMPER_MEMORY: area.get("TamperMemory", 0) > 0,
            "auto_insert": area.get("AutoInsert", 0) > 0,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
