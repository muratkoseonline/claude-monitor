# Claude Monitor

Windows 11 system tray app that tracks your [Claude.ai](https://claude.ai) and [Codex](https://chatgpt.com/codex) (ChatGPT) usage quotas in real time.

![Claude Monitor detail window](screenshot.png)

## Features

- **System tray icon** — shows Claude 5-hour quota % at a glance; outer arc = Claude, inner arc = Codex, both color-coded (green → orange → red)
- **Codex / ChatGPT quota** — reads the OAuth token from `~/.codex/auth.json` (no extra setup if Codex CLI or the Codex app is logged in) and shows the 5-hour and weekly windows
- **Hover tooltip** — Claude and Codex 5-hour / weekly utilization + reset times
- **Click to open** — detailed usage window with progress bars, model-specific limits, and reset timestamps
- **Desktop notification** — Windows 11 toast when Claude or Codex usage crosses configurable threshold (default 75%)
- **Auto-refresh** — polls every 2 minutes; manual refresh button in detail window
- **Auto-start** — optional Windows startup shortcut

## Requirements

- Windows 10/11
- Python 3.10+
- Claude.ai account (Free, Pro, or Max plan)
- Optional: Codex CLI or Codex app logged in with a ChatGPT account (for Codex quota)

## Installation

```bat
git clone https://github.com/muratkoseonline/claude-monitor.git
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

### Codex (ChatGPT) quota

Nothing to configure. If Codex CLI or the Codex desktop app is logged in, the token in `%USERPROFILE%\.codex\auth.json` is used automatically. If the Codex section shows an auth error, run `codex login` again. You can disable it or point to a different `auth.json` in Settings.

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
| `codex_enabled` | `true` | Also track Codex (ChatGPT) quota |
| `codex_auth_path` | `""` | Path to Codex `auth.json`; empty = `~/.codex/auth.json` |

## How it works

Authenticates with `sessionKey` cookie and calls the internal Claude.ai API:

```
GET https://claude.ai/api/organizations/{org_uuid}/usage
```

Response includes `five_hour.utilization` (0–100%) and `seven_day.utilization`, both used directly as percentages.

For Codex it uses the ChatGPT OAuth access token (Bearer) plus the `ChatGPT-Account-Id` header:

```
GET https://chatgpt.com/backend-api/wham/usage
```

Response includes `rate_limit.primary_window.used_percent` (5-hour) and `rate_limit.secondary_window.used_percent` (weekly), plus `reset_at` epoch timestamps. Expired tokens are refreshed in memory via the refresh token; the Codex `auth.json` is never written.

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
