"""Constants for the INIM Alarm integration."""

from datetime import timedelta

DOMAIN = "inim_alarm"

# Configuration
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ARM_AWAY_SCENARIO = "arm_away_scenario"
CONF_ARM_HOME_SCENARIO = "arm_home_scenario"
CONF_DISARM_SCENARIO = "disarm_scenario"
CONF_USER_CODE = "user_code"
CONF_ALARM_CODE = "alarm_code"  # Code shown on panel (code_arm_required)

# API
API_BASE_URL = "https://api.inimcloud.com/"
API_HEADERS = {
    "Host": "api.inimcloud.com",
    "Accept": "*/*",
    "Accept-Language": "it-it",
    "Accept-Encoding": "identity",
    "User-Agent": "Inim Home/5 CFNetwork/1329 Darwin/21.3.0",
}

# API Methods
METHOD_REGISTER_CLIENT = "RegisterClient"
METHOD_GET_DEVICES_EXTENDED = "GetDevicesExtended"
METHOD_ACTIVATE_SCENARIO = "ActivateScenario"
METHOD_REQUEST_POLL = "RequestPoll"
METHOD_INSERT_ZONE = "InsertZone"

# Default values
DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)
DEFAULT_CLIENT_NAME = "HomeAssistant"

# Zone Status (from API, subtract 1 for binary state)
ZONE_STATUS_CLOSED = 1  # After -1 = 0 (False/Closed)
ZONE_STATUS_OPEN = 2    # After -1 = 1 (True/Open)

# Area Armed Status
AREA_ARMED_DISARMED = 4
AREA_ARMED_ARMED = 1

# Scenario IDs (these are common defaults, actual values come from API)
SCENARIO_TOTAL = 0      # Arm all
SCENARIO_DISARMED = 1   # Disarm all

# Device info
MANUFACTURER = "INIM Electronics"

# Platforms
PLATFORMS = ["alarm_control_panel", "binary_sensor", "button", "sensor", "switch"]

# Attributes
ATTR_DEVICE_ID = "device_id"
ATTR_ZONE_ID = "zone_id"
ATTR_AREA_ID = "area_id"
ATTR_SCENARIO_ID = "scenario_id"
ATTR_SERIAL_NUMBER = "serial_number"
ATTR_MODEL = "model"
ATTR_FIRMWARE = "firmware"
ATTR_VOLTAGE = "voltage"
ATTR_ALARM_MEMORY = "alarm_memory"
ATTR_TAMPER_MEMORY = "tamper_memory"
ATTR_BYPASSED = "bypassed"

# Bypass modes
BYPASS_MODE_NORMAL = 0    # Reinserisci zona (toglie bypass)
BYPASS_MODE_BYPASS = 3    # Bypassa zona

# Service names
SERVICE_BYPASS_ZONE = "bypass_zone"
SERVICE_ACTIVATE_SCENARIO = "activate_scenario"

# Event names
EVENT_ALARM_TRIGGERED = "inim_alarm_triggered"
