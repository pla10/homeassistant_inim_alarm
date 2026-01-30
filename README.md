# INIM Alarm Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/pla10/homeassistant_inim_alarm.svg)](https://github.com/pla10/homeassistant_inim_alarm/releases)
[![License](https://img.shields.io/github/license/pla10/homeassistant_inim_alarm.svg)](LICENSE)

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=inim_alarm)

A Home Assistant custom integration for INIM alarm systems (SmartLiving, Prime, etc.) via INIM Cloud.

## ✨ Features

- 🔐 **Alarm Control Panel** - Arm/disarm all areas at once
  - Simple UX: only Armed Away and Disarmed states
  - Uses InsertAreas API directly (no scenarios required)
- 🏠 **Area Control Panels** - Individual control for each configured area
  - Arm/disarm single areas independently
  - Perfect for partial arming (e.g., arm only ground floor)
- 🚪 **Zone Sensors** - Monitor all zones (doors, windows, motion sensors, tamper)
  - Automatic device class detection
  - Alarm memory, tamper memory, bypass status
- 🔀 **Zone Bypass** - Bypass/reinstate zones via switches
- 📊 **Area Status Sensors** - Monitor area armed status (armed, armed_partial, disarmed)
- 🔋 **Peripheral Sensors** - Monitor voltage of keypads, expanders, and modules
- 📶 **GSM/Nexus Sensor** - Monitor cellular module (operator, signal strength, 4G status)
- 🎬 **Scenario Buttons** - Quick buttons to activate any scenario (disabled by default for security)
- ⚙️ **Configurable Options** - Customize polling interval
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
3. Your alarm **User Code** (the PIN you use to arm/disarm)
4. Home Assistant 2024.1.0 or newer

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
4. Enter:
   - **Email** - Your INIM Cloud email (same as Inim Home app)
   - **Password** - Your INIM Cloud password
   - **User Code** - Your alarm PIN code (required for arm/disarm)

### Options (After Setup)

Go to **Settings** → **Devices & Services** → **INIM Alarm** → **Configure**

| Option | Description | Default |
|--------|-------------|---------|
| **Polling Interval** | How often to update (10-300 seconds) | 30 seconds |

## 🏠 Entities Created

### Alarm Control Panels
| Entity | Description |
|--------|-------------|
| `alarm_control_panel.<name>` | Main alarm control (arms/disarms ALL areas) |
| `alarm_control_panel.<area_name>` | Area-specific control (e.g., Perimetrale PT) |

**Main panel** - Arms/disarms all configured areas at once. Simple UX with only Armed Away / Disarmed states.

**Area panels** - Control individual areas independently.

### Binary Sensors (Zones)
| Entity | Description |
|--------|-------------|
| `binary_sensor.<name>_<zone>` | Zone status (open/closed) |

**Attributes:** alarm_memory, tamper_memory, bypassed, output_on

### Switches (Zone Bypass)
| Entity | Description |
|--------|-------------|
| `switch.<name>_bypass_<zone>` | Bypass/reinstate a zone |

### Sensors (Area Status)
| Entity | Description |
|--------|-------------|
| `sensor.<name>_<area>` | Area armed status (armed, armed_partial, disarmed) |

### Sensors (System)
| Entity | Description |
|--------|-------------|
| `sensor.<name>_voltage` | Central unit voltage |
| `sensor.<name>_<peripheral>_voltage` | Peripheral voltage (keypads, expanders) |
| `sensor.<name>_nexus_gsm` | GSM module info |

**GSM Attributes:** signal_strength, operator, IMEI, is_4g, has_gprs, battery_charge

### Buttons (Scenarios) ⚠️
| Entity | Description |
|--------|-------------|
| `button.<name>_scenario_<scenario>` | Activate a specific scenario |

> **⚠️ Security Warning:** Scenario buttons are **disabled by default** because they don't require PIN confirmation. To enable them:
> 1. Go to Settings → Devices & Services → INIM Alarm
> 2. Click on the device
> 3. Show disabled entities
> 4. Enable the scenario buttons you need

## 🔢 Lovelace Keypad

To show a keypad on the alarm panel card (for UI security), use:

```yaml
type: alarm-panel
entity: alarm_control_panel.your_alarm
states:
  - arm_away
require_code: true  # Shows numeric keypad
```

> **Note:** The keypad code is managed by Lovelace, not the integration.
> You can set any code you want for the UI - it doesn't need to match your alarm code.

## 📖 Services

```yaml
# Arm Away (all areas)
service: alarm_control_panel.alarm_arm_away
target:
  entity_id: alarm_control_panel.your_alarm

# Disarm (all areas)
service: alarm_control_panel.alarm_disarm
target:
  entity_id: alarm_control_panel.your_alarm

# Arm specific area
service: alarm_control_panel.alarm_arm_away
target:
  entity_id: alarm_control_panel.perimetrale_pt

# Bypass Zone
service: inim_alarm.bypass_zone
data:
  device_id: 12345
  zone_id: 1
  bypass: true  # false to reinstate

# Activate Scenario (advanced)
service: inim_alarm.activate_scenario
data:
  device_id: 12345
  scenario_id: 2
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

### Arm only ground floor at night
```yaml
automation:
  - alias: "Arm ground floor at night"
    trigger:
      - platform: time
        at: "23:00:00"
    action:
      - service: alarm_control_panel.alarm_arm_away
        target:
          entity_id: alarm_control_panel.perimetrale_pt
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
- **Scenario buttons disabled by default** - No accidental arm/disarm without PIN

## 🐛 Troubleshooting

### Cannot connect
- Verify credentials work in Inim Home app
- Check internet connection

### Entities not updating
- Check polling interval in options
- Enable debug logging (see below)

### Arm/Disarm not working
- Delete and re-add the integration
- Make sure to enter the user code during setup

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
