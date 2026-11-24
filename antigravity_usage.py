#!/usr/bin/env python3
"""Read-only Antigravity (Google) quota reader via local language server.

Antigravity IDE/desktop writes `~/.gemini/antigravity/daemon/hub_<port>.json`
with its local loopback HTTP port and CSRF token. This module queries
`RetrieveUserQuotaSummary` and `GetUserStatus` on 127.0.0.1 only (system proxy
disabled). CSRF tokens, e-mail addresses, and user names are never logged,
cached to disk, or returned.
"""

import json
import math
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DAEMON_DIR = os.path.join(
    os.path.expanduser("~"), ".gemini", "antigravity", "daemon"
)
RPC_BASE = "/exa.language_server_pb.LanguageServerService"
DEFAULT_TIMEOUT = 6.0
MAX_HUB_CANDIDATES = 4
MAX_HUB_FILE_BYTES = 4096
TARGET_MODEL_HINTS = ("hydrogen", "flash")
_MODELS_RE = re.compile(r"Models within this group:\s*(.+)$", re.IGNORECASE)


def _parse_iso_utc(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            return None
        return dt.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def _group_models(group):
    match = _MODELS_RE.search(str(group.get("description") or ""))
    if not match:
        return []
    return [m.strip().rstrip(".") for m in match.group(1).split(",") if m.strip()]


def _pick_group(groups):
    if not isinstance(groups, list):
        return None
    for group in groups:
        if not isinstance(group, dict):
            continue
        text = f"{group.get('displayName') or ''} {group.get('description') or ''}".lower()
        if any(hint in text for hint in TARGET_MODEL_HINTS):
            return group
    return None


def _remaining_fraction(bucket):
    frac = bucket.get("remainingFraction")
    if frac is None and bucket.get("resetTime"):
        # Proto JSON omits zero-valued scalar fields.
        frac = 0.0
    if isinstance(frac, bool) or not isinstance(frac, (int, float)):
        return None
    if not math.isfinite(frac):
        return None
    return max(0.0, min(1.0, float(frac)))


class AntigravityUsage:
    def __init__(self, daemon_dir=None, log=None, timeout=DEFAULT_TIMEOUT, poster=None):
        self.daemon_dir = daemon_dir or DEFAULT_DAEMON_DIR
        self._log = log or (lambda message: None)
        self.timeout = float(timeout)
        self._poster = poster

    def _read_hub_candidates(self):
        """Return newest-first hub entries with valid loopback port and CSRF token."""
        target = Path(self.daemon_dir)
        try:
            files = sorted(
                target.glob("hub_*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return []
        candidates = []
        for path in files:
            try:
                if path.stat().st_size > MAX_HUB_FILE_BYTES:
                    continue
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            port = data.get("httpPort")
            token = data.get("csrfToken")
            if isinstance(port, bool) or not isinstance(port, int) or not (0 < port < 65536):
                continue
            if not isinstance(token, str) or not token.strip():
                continue
            candidates.append({"port": port, "csrf": token})
            if len(candidates) >= MAX_HUB_CANDIDATES:
                break
        return candidates

    @staticmethod
    def _rpc(opener, port, csrf, method, timeout):
        body = json.dumps(
            {
                "metadata": {
                    "ideName": "antigravity",
                    "extensionName": "antigravity",
                    "locale": "tr",
                }
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{RPC_BASE}/{method}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Connect-Protocol-Version": "1",
                "X-Codeium-Csrf-Token": csrf,
            },
        )
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read(1048576).decode("utf-8"))

    @classmethod
    def _post_status(cls, port, csrf, timeout):
        # Never route loopback traffic through a system proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        summary = cls._rpc(opener, port, csrf, "RetrieveUserQuotaSummary", timeout)
        try:
            status = cls._rpc(opener, port, csrf, "GetUserStatus", timeout)
        except (OSError, ValueError):
            status = None
        return {"summary": summary, "status": status}

    def fetch(self):
        """Query the local Antigravity language server; return raw dict or {'_error': ...}."""
        candidates = self._read_hub_candidates()
        if not candidates:
            return {"_error": "ide_closed"}
        poster = self._poster or self._post_status
        saw_http_error = False
        saw_invalid_json = False
        for hub in candidates:
            try:
                data = poster(hub["port"], hub["csrf"], self.timeout)
                if not isinstance(data, dict):
                    saw_invalid_json = True
                    continue
                self._log("Antigravity yerel kota alindi")
                return data
            except urllib.error.HTTPError as exc:
                saw_http_error = True
                self._log(f"Antigravity yerel sunucu HTTP {exc.code}")
            except ValueError:
                saw_invalid_json = True
                self._log("Antigravity yerel sunucu gecersiz JSON dondu")
            except OSError:
                # Stale hub file or closed IDE instance; try next candidate.
                continue
        if saw_invalid_json:
            return {"_error": "invalid_response"}
        if saw_http_error:
            return {"_error": "no_response"}
        return {"_error": "ide_closed"}

    @staticmethod
    def parse(data):
        """Normalize raw {'summary': ..., 'status': ...} into monitor quota fields."""
        if not isinstance(data, dict) or data.get("_error"):
            return None

        summary = data.get("summary")
        response = summary.get("response") if isinstance(summary, dict) else None
        group = _pick_group(response.get("groups") if isinstance(response, dict) else None)
        if group is None:
            return None

        buckets = group.get("buckets") if isinstance(group.get("buckets"), list) else []
        five_hour_pct = None
        five_hour_reset = None
        seven_day_pct = None
        seven_day_reset = None

        for window_key in ("5h", "weekly"):
            bucket = next(
                (b for b in buckets if isinstance(b, dict) and b.get("window") == window_key),
                None,
            )
            if bucket is None:
                continue
            frac = _remaining_fraction(bucket)
            if frac is None:
                continue
            used_pct = round((1.0 - frac) * 100.0, 1)
            reset_iso = _parse_iso_utc(bucket.get("resetTime"))
            if window_key == "5h":
                five_hour_pct = used_pct
                five_hour_reset = reset_iso
            else:
                seven_day_pct = used_pct
                seven_day_reset = reset_iso

        if five_hour_pct is None and seven_day_pct is None:
            return None

        plan_type = ""
        credits_text = ""
        status = (
            (data.get("status") or {}).get("userStatus")
            if isinstance(data.get("status"), dict)
            else None
        )
        if isinstance(status, dict):
            plan_status = status.get("planStatus") if isinstance(status.get("planStatus"), dict) else {}
            plan_info = plan_status.get("planInfo") if isinstance(plan_status.get("planInfo"), dict) else {}
            tier = status.get("userTier") if isinstance(status.get("userTier"), dict) else {}
            plan = tier.get("name") or plan_info.get("planName")
            if isinstance(plan, str) and plan.strip():
                plan_type = plan.strip()[:40]
            prompt = plan_status.get("availablePromptCredits")
            flow = plan_status.get("availableFlowCredits")
            parts = []
            if isinstance(prompt, (int, float)) and not isinstance(prompt, bool) and math.isfinite(prompt):
                parts.append(f"{int(prompt)} prompt")
            if isinstance(flow, (int, float)) and not isinstance(flow, bool) and math.isfinite(flow):
                parts.append(f"{int(flow)} flow")
            if parts:
                credits_text = " · ".join(parts)

        primary_pct = five_hour_pct if five_hour_pct is not None else seven_day_pct
        limit_reached = bool(
            (five_hour_pct is not None and five_hour_pct >= 100)
            or (seven_day_pct is not None and seven_day_pct >= 100)
        )

        return {
            "percent": primary_pct,
            "five_hour_pct": five_hour_pct,
            "seven_day_pct": seven_day_pct,
            "five_hour_reset": five_hour_reset,
            "seven_day_reset": seven_day_reset,
            "plan_type": plan_type,
            "credits_text": credits_text,
            "models": _group_models(group),
            "limit_reached": limit_reached,
        }


if __name__ == "__main__":
    ag = AntigravityUsage(log=print)
    raw = ag.fetch()
    if raw.get("_error"):
        print(json.dumps(raw, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(AntigravityUsage.parse(raw), indent=2, ensure_ascii=False))
