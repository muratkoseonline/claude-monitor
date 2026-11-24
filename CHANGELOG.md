# Changelog

All notable changes to Claude Monitor are documented in this file.

## [v1.4.0] - 2026-11-24

### Added
- **Antigravity (Google) quota tracking** (`antigravity_usage.py`): reads 5-hour and weekly quota windows, plan name (`Google AI Pro`), and prompt/flow credit balance from the local Antigravity language server on `127.0.0.1` (proxy disabled; CSRF token and e-mail are never logged or stored).
- **OpenCode Go quota tracking** (`opencode_usage.py`): reads 5-hour, weekly, and monthly Go meters using the signed-in OpenCode V2 Account session (with legacy `auth.json` API-key fallback).
- **4-quadrant system tray icon** (`generate_icon.py`): outer ring split into 4 color-coded quadrant arcs (top-right Claude, bottom-right Codex, bottom-left OpenCode Go, top-left Antigravity) with the Claude 5-hour percentage centered cleanly.
- **2x2 grid detail window** (`detail_window.py`): compact dark four-provider panel with progress bars, remaining quota, reset times in local timezone, plan/credit metadata, stale-data warnings, and `F5`/`Esc` shortcuts.
- **Per-window notifications**: independent threshold notifications per reset period for OpenCode Go and Antigravity.
- **Automated tests**: unit tests for OpenCode Go, Antigravity, monitor refresh/notifications/tooltip/icon, and a Tk UI layout smoke test (`tests/ui_smoke.py`).

### Changed
- Compact tray tooltip labels (`CL / CX / Go / AG`) to stay reliably within Windows' 127-character tooltip limit across all four providers.
- Sanitized local quota snapshot (`~/.claude-monitor/usage-snapshot.json`) now includes `opencode` and `antigravity` numeric/reset summaries without credentials or PII.

## [v1.3.0]

### Added
- Codex (ChatGPT) 5-hour and weekly quota tracking via `~/.codex/auth.json` OAuth token refresh.

## [v1.2.0]

### Added
- Initial Windows system tray monitor for Claude.ai 5-hour and 7-day usage quotas, model-specific limits, and threshold notifications.
