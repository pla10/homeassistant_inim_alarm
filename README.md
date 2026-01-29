# INIM Alarm Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/pla10/homeassistant_inim_alarm.svg)](https://github.com/pla10/homeassistant_inim_alarm/releases)
[![License](https://img.shields.io/github/license/pla10/homeassistant_inim_alarm.svg)](LICENSE)

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=inim_alarm)

A Home Assistant custom integration for INIM alarm systems (SmartLiving, Prime, etc.) via INIM Cloud.

## ✨ Features

- 🔐 **Alarm Control Panel** - Arm/disarm your alarm system
  - Arm Away (full arm)
  - Arm Home (partial arm)
  - Disarm
  - Configurable scenarios for each action
- 🚪 **Zone Sensors** - Monitor all zones (doors, windows, motion sensors, tamper)
  - Automatic device class detection
  - Alarm memory, tamper memory, bypass status
- 📊 **Area Sensors** - Monitor area armed status
- 🔋 **Peripheral Sensors** - Monitor voltage of keypads, expanders, and modules
- 📶 **GSM/Nexus Sensor** - Monitor cellular module (operator, signal strength, 4G status)
- ⚙️ **Configurable Options** - Customize polling interval and scenarios
- 🔄 **Automatic token refresh** - Handles token expiration automatically
- 🌍 **Multi-language** - English and Italian translations

## 📋 Supported Devices

This integration works with INIM alarm panels connected to INIM Cloud:

- SmartLiving series (515, 1050, 10100, etc.)
- Prime series
- Other INIM panels compatible with the Inim Home app

## 📦 Prerequisites

1. An INIM alarm system registered on INIM Cloud
2. The **Inim Home** app credentials (email and password)
3. Home Assistant 2024.1.0 or newer

## 🚀 Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots menu (⋮) → "Custom repositories"
4. Add repository URL: `https://github.com/pla10/homeassistant_inim_alarm`
5. Select category: "Integration" → Click "Add"
6. Search for "INIM Alarm" and click "Download"
7. Restart Home Assistant
8. Go to **Settings** → **Devices & Services** → **+ Add Integration** → Search "INIM Alarm"

### Manual Installation

1. Download the latest release from [GitHub Releases](https://github.com/pla10/homeassistant_inim_alarm/releases)
2. Extract `inim_alarm.zip`
3. Copy the contents to `config/custom_components/inim_alarm/`
4. Restart Home Assistant

## ⚙️ Configuration

### Initial Setup

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for "INIM Alarm"
4. Enter your INIM Cloud credentials (same as Inim Home app)

### Options (After Setup)

Go to **Settings** → **Devices & Services** → **INIM Alarm** → **Configure**

| Option | Description | Default |
|--------|-------------|---------|
| **Polling Interval** | How often to update (10-300 seconds) | 30 seconds |
| **Arm Away Scenario** | Scenario for full arm | Auto-detect (TOTALE) |
| **Arm Home Scenario** | Scenario for partial arm | Auto-detect (first partial) |
| **Disarm Scenario** | Scenario for disarm | Auto-detect (SPENTO) |

**Auto-detect** automatically finds the right scenario based on common names (TOTALE, SPENTO).
If your scenarios have custom names, select them manually.

## 🏠 Entities Created

### Alarm Control Panel
| Entity | Description |
|--------|-------------|
| `alarm_control_panel.<name>` | Main alarm control (arm/disarm) |

**Attributes include:**
- Current scenario (active_scenario_name)
- Configured scenarios (arm_away, arm_home, disarm)
- Polling interval
- System voltage, faults, network status

### Binary Sensors (Zones)
| Entity | Description |
|--------|-------------|
| `binary_sensor.<name>_<zone>` | Zone status (open/closed) |

**Attributes:** alarm_memory, tamper_memory, bypassed, output_on

### Sensors (Areas)
| Entity | Description |
|--------|-------------|
| `sensor.<name>_<area>` | Area armed status |
| `sensor.<name>_voltage` | Central unit voltage |

### Sensors (Peripherals) ⭐ NEW
| Entity | Description |
|--------|-------------|
| `sensor.<name>_<peripheral>_voltage` | Peripheral voltage (keypads, expanders) |
| `sensor.<name>_nexus_gsm` | GSM module info |

**GSM Attributes:** signal_strength, operator, IMEI, is_4g, has_gprs, battery_charge

## 📖 Services

```yaml
# Arm Away (full)
service: alarm_control_panel.alarm_arm_away
target:
  entity_id: alarm_control_panel.your_alarm

# Arm Home (partial)
service: alarm_control_panel.alarm_arm_home
target:
  entity_id: alarm_control_panel.your_alarm

# Disarm
service: alarm_control_panel.alarm_disarm
target:
  entity_id: alarm_control_panel.your_alarm
```

## 🤖 Example Automations

### Arm when everyone leaves
```yaml
automation:
  - alias: "Arm alarm when leaving"
    trigger:
      - platform: state
        entity_id: zone.home
        to: "0"
    action:
      - service: alarm_control_panel.alarm_arm_away
        target:
          entity_id: alarm_control_panel.your_alarm
```

### Alert on window open while armed
```yaml
automation:
  - alias: "Window opened while armed"
    trigger:
      - platform: state
        entity_id: binary_sensor.your_alarm_living_room_window
        to: "on"
    condition:
      - condition: not
        conditions:
          - condition: state
            entity_id: alarm_control_panel.your_alarm
            state: disarmed
    action:
      - service: notify.mobile_app
        data:
          message: "Window opened while alarm is armed!"
```

### Monitor low voltage
```yaml
automation:
  - alias: "Low voltage warning"
    trigger:
      - platform: numeric_state
        entity_id: sensor.your_alarm_voltage
        below: 12
    action:
      - service: notify.mobile_app
        data:
          message: "Alarm system voltage is low: {{ states('sensor.your_alarm_voltage') }}V"
```

## 🔒 Security & Privacy

- **Credentials stay local** - Stored encrypted in Home Assistant only
- **No third-party servers** - Direct communication with INIM Cloud only
- **No credential logging** - Passwords/tokens never in logs
- **HTTPS only** - All communication encrypted

## 🐛 Troubleshooting

### Cannot connect
- Verify credentials work in Inim Home app
- Check internet connection

### Entities not updating
- Check polling interval in options
- Enable debug logging (see below)

### Debug Logging
```yaml
logger:
  logs:
    custom_components.inim_alarm: debug
```

## 🤝 Contributing

Contributions welcome! Please open issues or pull requests.

## ⚠️ Disclaimer

This integration is **not affiliated with INIM Electronics S.r.l.**

This is a community project using the publicly available INIM Cloud API.
Use at your own risk.

## 📄 License

MIT License - see [LICENSE](LICENSE)

## 👏 Credits

- Developed by [Placido Falqueto](https://github.com/pla10)
- Thanks to the Home Assistant community
