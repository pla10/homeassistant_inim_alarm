# INIM Alarm Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/pla10/homeassistant_inim_alarm.svg)](https://github.com/pla10/homeassistant_inim_alarm/releases)
[![License](https://img.shields.io/github/license/pla10/homeassistant_inim_alarm.svg)](LICENSE)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=pla10&repo=homeassistant_inim_alarm&category=integration)

A Home Assistant custom integration for INIM alarm systems (SmartLiving, Prime, etc.) via INIM Cloud.

## Features

- 🔐 **Alarm Control Panel** - Arm/disarm your alarm system
  - Arm Away (full arm)
  - Arm Home (partial arm - e.g., ground floor only, first floor only)
  - Disarm
- 🚪 **Binary Sensors** - Monitor all zones (doors, windows, motion sensors, tamper)
  - Automatic device class detection (door, window, motion, tamper)
  - Zone status (open/closed)
  - Alarm memory and tamper memory attributes
- 📊 **Sensors** - Monitor areas and system status
  - Area armed status (armed, disarmed, partial)
  - System voltage
- 🔄 **Automatic token refresh** - Handles token expiration automatically
- 🌍 **Multi-language** - English and Italian translations

## Supported Devices

This integration works with INIM alarm panels that are connected to INIM Cloud:

- SmartLiving series (515, 1050, 10100, etc.)
- Prime series
- Other INIM panels compatible with the Inim Home app

## Prerequisites

1. An INIM alarm system registered on INIM Cloud
2. The **Inim Home** app credentials (email and password)
3. Home Assistant 2024.1.0 or newer

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots menu (top right) → "Custom repositories"
4. Add this repository URL: `https://github.com/pla10/homeassistant_inim_alarm`
5. Select category: "Integration"
6. Click "Add"
7. Search for "INIM Alarm" and install it
8. Restart Home Assistant

### Manual Installation

1. Download the latest release from [GitHub](https://github.com/pla10/homeassistant_inim_alarm/releases)
2. Extract and copy the `custom_components/inim_alarm` folder to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for "INIM Alarm"
4. Enter your credentials:
   - **Email**: Your INIM Cloud account email (same as Inim Home app)
   - **Password**: Your INIM Cloud account password

## What You Need

| Field | Description | Where to find it |
|-------|-------------|------------------|
| Email | Your INIM Cloud email | Same email used for the Inim Home mobile app |
| Password | Your INIM Cloud password | Same password used for the Inim Home mobile app |

That's it! The integration will automatically discover all your devices, zones, and areas.

## Entities Created

After setup, the integration creates the following entities:

### Alarm Control Panel
- `alarm_control_panel.<device_name>` - Main alarm control

### Binary Sensors (one per zone)
- `binary_sensor.<device_name>_<zone_name>` - Zone status (open/closed)

### Sensors
- `sensor.<device_name>_voltage` - System voltage
- `sensor.<device_name>_<area_name>` - Area armed status

## Services

The integration supports standard Home Assistant alarm services:

```yaml
# Arm in away mode (full arm)
service: alarm_control_panel.alarm_arm_away
target:
  entity_id: alarm_control_panel.your_alarm

# Arm in home mode (partial arm)
service: alarm_control_panel.alarm_arm_home
target:
  entity_id: alarm_control_panel.your_alarm

# Disarm
service: alarm_control_panel.alarm_disarm
target:
  entity_id: alarm_control_panel.your_alarm
```

## Example Automations

### Notify when a window is opened while alarm is armed

```yaml
automation:
  - alias: "Alert: Window opened while armed"
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
          message: "Warning: Window opened while alarm is armed!"
```

### Arm alarm when everyone leaves

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

## Security & Privacy

🔒 **Your credentials are safe:**

- **Credentials stay local** - Your email and password are stored only in your Home Assistant instance (in `.storage/` encrypted files)
- **No third-party servers** - This integration communicates directly with INIM Cloud servers only, no data is sent anywhere else
- **No credential logging** - Passwords and tokens are never written to logs
- **HTTPS only** - All communication with INIM Cloud uses encrypted HTTPS connections

### How it works

1. Your credentials are entered once during setup via Home Assistant's secure config flow
2. Home Assistant stores them encrypted in its internal storage
3. The integration uses them only to authenticate with INIM Cloud
4. A session token (valid for 24 hours) is obtained and used for subsequent API calls
5. Tokens are refreshed automatically when they expire

### Best Practices

- Use a dedicated INIM Cloud account if you're concerned about security
- Regularly check Home Assistant logs for any unusual activity
- Keep your Home Assistant installation up to date

## Troubleshooting

### Cannot connect to INIM Cloud
- Verify your credentials are correct
- Check that you can log in to the Inim Home app
- Ensure your INIM panel is connected to the internet

### Zones not updating
- The integration polls every 30 seconds by default
- Check Home Assistant logs for any errors

### Token expired errors
- The integration should handle token refresh automatically
- If issues persist, try removing and re-adding the integration

## Debug Logging

To enable debug logging, add to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.inim_alarm: debug
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Disclaimer

This integration is not affiliated with, endorsed by, or connected to INIM Electronics S.r.l. in any way. 

This is an independent, community-driven project that uses the publicly available INIM Cloud API (the same API used by the official Inim Home mobile app) to provide Home Assistant integration.

**Use at your own risk.** The authors are not responsible for any issues that may arise from using this integration.

### For INIM Electronics

If you are from INIM Electronics and have any concerns about this integration, please [open an issue](https://github.com/pla10/homeassistant_inim_alarm/issues) or contact the maintainer. We are happy to discuss and address any concerns.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Credits

- Developed by [Placido Falqueto](https://github.com/pla10)
- Inspired by the INIM Home app API
