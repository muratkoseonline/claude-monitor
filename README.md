# Claude Monitor

Windows 11 system tray app that tracks your [Claude.ai](https://claude.ai) usage quota in real time.

![Claude Monitor tray icon](icon_preview_13.png)

## Features

- **System tray icon** — shows 5-hour quota usage % at a glance, color-coded (green → orange → red)
- **Hover tooltip** — 5-hour and 7-day utilization + reset times
- **Click to open** — detailed usage window with progress bars, model-specific limits, and reset timestamps
- **Desktop notification** — Windows 11 toast when usage crosses configurable threshold (default 75%)
- **Auto-refresh** — polls every 2 minutes; manual refresh button in detail window
- **Auto-start** — optional Windows startup shortcut

## Requirements

- Windows 10/11
- Python 3.10+
- Claude.ai account (Free, Pro, or Max plan)

## Installation

```bat
git clone https://github.com/murat-kose/claude-monitor.git
cd claude-monitor
setup.bat
```

## Usage

```bat
run_background.bat    # start silently (no console window)
run.bat               # start with console (debug)
```

On first run, right-click the tray icon → **Ayarlar** and enter your session key.

### Getting your session key

1. Open [claude.ai](https://claude.ai) in your browser
2. Press **F12** → Application → Cookies → `https://claude.ai`
3. Copy the value of `sessionKey` (starts with `sk-ant-…`)
4. Paste it into Claude Monitor → Settings

> **Note:** Session keys expire after a few weeks. If the icon shows `ERR`, get a fresh key.

### Auto-start with Windows

```bat
autostart.bat          # add to Windows startup
remove_autostart.bat   # remove from startup
```

## Configuration

Stored at `%USERPROFILE%\.claude-monitor\config.json`:

| Key | Default | Description |
|-----|---------|-------------|
| `session_key` | `""` | claude.ai session cookie value |
| `org_uuid` | `""` | Auto-discovered; cleared on 401 |
| `notify_threshold` | `75` | Notification trigger (%) |
| `poll_interval` | `120` | Polling interval (seconds) |

## How it works

Authenticates with `sessionKey` cookie and calls the internal Claude.ai API:

```
GET https://claude.ai/api/organizations/{org_uuid}/usage
```

Response includes `five_hour.utilization` (0–100%) and `seven_day.utilization`, both used directly as percentages.

## Log

```
%USERPROFILE%\.claude-monitor\monitor.log
```

Every API call is logged with timestamp, status code, and response snippet.

## Dependencies

| Package | Purpose |
|---------|---------|
| `pystray` | Windows system tray |
| `Pillow` | Icon rendering |
| `requests` | HTTP API calls |
| `plyer` | Windows notifications |

## License

MIT
