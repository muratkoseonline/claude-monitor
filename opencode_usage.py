"""Read OpenCode Go subscription quotas using the locally connected API key.

Source: anomalyco/opencode, console routes/zen/go/v1/usage.ts.
Credentials stay in OpenCode's auth.json and are never logged or copied.
"""

import json
import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


def _default_auth_path():
    root = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share"
    )
    return os.path.join(root, "opencode", "auth.json")


DEFAULT_AUTH_PATH = _default_auth_path()
DEFAULT_DB_PATH = os.environ.get("OPENCODE_DB") or os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share"),
    "opencode", "opencode.db",
)
USAGE_URL = "https://opencode.ai/zen/go/v1/usage"
CONSOLE_STATUS_URL = "https://opencode.ai/console/api/go/status"


def _nonnegative_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False


class OpenCodeUsage:
    def __init__(self, auth_path=None, log=None, db_path=None):
        self.auth_path = auth_path or _default_auth_path()
        self.db_path = db_path or DEFAULT_DB_PATH
        self._log = log or (lambda message: None)

    def _db_connection(self):
        path = self.db_path
        if path == ":memory:":
            return None
        if not os.path.isabs(path):
            data_root = os.environ.get("XDG_DATA_HOME") or os.path.join(
                os.path.expanduser("~"), ".local", "share"
            )
            path = os.path.join(data_root, path)
        if not os.path.isfile(path):
            return None
        # URI read-only mode lets OpenCode keep ownership of its DB and WAL.
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=2)

    def _load_account_session(self):
        """Return only the active OpenCode Console OAuth session, if present."""
        db = None
        cursor = None
        try:
            db = self._db_connection()
            if db is None:
                return None
            cursor = db.execute(
                "SELECT value FROM credential "
                "WHERE integration_id = ? AND active = 1 "
                "ORDER BY time_updated DESC LIMIT 1",
                ("opencode",),
            )
            row = cursor.fetchone()
            if not row:
                return None
            credential = json.loads(row[0])
            if not isinstance(credential, dict) or credential.get("type") != "oauth":
                return None
            access = credential.get("access")
            metadata = credential.get("metadata")
            if not isinstance(access, str) or not access.strip() or not isinstance(metadata, dict):
                return None
            server = metadata.get("server", "https://opencode.ai/console")
            org_id = metadata.get("orgID")
            if (server.rstrip("/") != "https://opencode.ai/console"
                    or not isinstance(org_id, str) or not org_id.strip()
                    or any(c.isspace() for c in org_id)):
                return None
            return {"access": access, "org_id": org_id}
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
            self._log("OpenCode account credential database unavailable")
            return None
        finally:
            if cursor is not None:
                cursor.close()
            if db is not None:
                db.close()

    def _load_database_keys(self):
        """Read active V2 API-key credentials for legacy API-key mode."""
        db = None
        cursor = None
        try:
            db = self._db_connection()
            if db is None:
                return []
            keys = []
            cursor = db.execute(
                "SELECT integration_id, value FROM credential "
                "WHERE integration_id IN (?, ?) AND active = 1 "
                "ORDER BY time_updated DESC",
                ("opencode-go", "opencode"),
            )
            for row in cursor:
                credential = json.loads(row[1])
                key = credential.get("key") if isinstance(credential, dict) else None
                if (isinstance(key, str) and key.strip() and not any(c.isspace() for c in key)
                        and key not in keys):
                    keys.append(key)
            return keys
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
            self._log("OpenCode credential database unavailable")
            return []
        finally:
            if cursor is not None:
                cursor.close()
            if db is not None:
                db.close()

    def _load_keys(self):
        try:
            with open(self.auth_path, encoding="utf-8") as stream:
                auth = json.load(stream)
            if not isinstance(auth, dict):
                return []
            keys = []
            for provider in ("opencode-go", "opencode"):
                entry = auth.get(provider)
                if not isinstance(entry, dict) or entry.get("type") != "api":
                    continue
                key = entry.get("key")
                if (isinstance(key, str) and key.strip()
                        and not any(c.isspace() for c in key) and key not in keys):
                    keys.append(key)
        except (OSError, ValueError, TypeError):
            return []
        return keys

    def fetch(self):
        account = self._load_account_session()
        if account:
            return self._fetch_account_usage(account)
        keys = self._load_database_keys() + self._load_keys()
        keys = list(dict.fromkeys(keys))
        if not keys:
            return {"_error": "no_auth"}
        last_auth_error = None
        for key in keys:
            try:
                response = requests.get(
                    USAGE_URL,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Accept": "application/json",
                        "User-Agent": "claude-monitor/1.0",
                    },
                    timeout=15,
                    allow_redirects=False,
                )
                self._log(f"OpenCode Go usage HTTP {response.status_code}")
                if response.status_code == 401:
                    last_auth_error = "auth"
                    continue
                if response.status_code == 403:
                    last_auth_error = "no_subscription"
                    continue
                if response.status_code == 429:
                    return {"_error": "rate_limited"}
                if response.status_code != 200:
                    return {"_error": "no_response"}
                try:
                    data = response.json()
                except ValueError:
                    return {"_error": "invalid_response"}
                if self.parse(data) is None:
                    return {"_error": "invalid_response"}
                return data
            except requests.RequestException:
                # Exceptions can embed request headers or credential-bearing URLs.
                self._log("OpenCode Go usage request failed")
                return {"_error": "no_response"}
        return {"_error": last_auth_error or "auth"}

    def _fetch_account_usage(self, account):
        try:
            response = requests.get(
                CONSOLE_STATUS_URL,
                headers={
                    "Authorization": f"Bearer {account['access']}",
                    "x-org-id": account["org_id"],
                    "Accept": "application/json",
                    "User-Agent": "claude-monitor/1.0",
                },
                timeout=15,
                allow_redirects=False,
            )
            self._log(f"OpenCode account usage HTTP {response.status_code}")
            if response.status_code == 401:
                return {"_error": "account_auth"}
            if response.status_code == 403:
                return {"_error": "no_subscription"}
            if response.status_code == 400:
                return {"_error": "account_workspace"}
            if response.status_code == 429:
                return {"_error": "rate_limited"}
            if response.status_code != 200:
                return {"_error": "no_response"}
            try:
                data = response.json()
            except ValueError:
                return {"_error": "invalid_response"}
            normalized = self._parse_console_status(data)
            return normalized if normalized is not None else {"_error": "invalid_response"}
        except requests.RequestException:
            # Exceptions can embed authorization headers; never log their text.
            self._log("OpenCode account usage request failed")
            return {"_error": "no_response"}

    @staticmethod
    def _parse_console_status(data):
        if not isinstance(data, dict):
            return None
        access = data.get("access")
        meters = access.get("meters") if isinstance(access, dict) else None
        if not isinstance(meters, dict):
            return None
        result = {"usage": {}}
        for source, target in (("fiveHour", "rolling"), ("week", "weekly"), ("month", "monthly")):
            meter = meters.get(source)
            if not isinstance(meter, dict):
                return None
            try:
                used = float(meter["usedMicroCents"])
                limit = float(meter["limitMicroCents"])
                if not math.isfinite(used) or not math.isfinite(limit) or used < 0 or limit <= 0:
                    return None
                percent = used / limit * 100
            except (KeyError, TypeError, ValueError, OverflowError):
                return None
            reset = meter.get("resetsAt")
            if not isinstance(reset, str):
                return None
            try:
                parsed_reset = datetime.fromisoformat(reset.replace("Z", "+00:00"))
                if parsed_reset.tzinfo is None or parsed_reset.utcoffset() is None:
                    return None
            except (TypeError, ValueError):
                return None
            result["usage"][target] = {
                "percent": percent,
                "resetsAt": reset,
                "status": "rate-limited" if percent >= 100 else "ok",
            }
        return result

    @staticmethod
    def parse(data):
        if not isinstance(data, dict) or data.get("_error"):
            return None
        current = isinstance(data.get("usage"), dict)
        windows = data["usage"] if current else data
        result = {}
        limited = False
        now = datetime.now(timezone.utc)
        for source, target in (("rolling", "five_hour"), ("weekly", "seven_day"), ("monthly", "monthly")):
            window = windows.get(source if current else source + "Usage")
            if not isinstance(window, dict):
                return None
            status = window.get("status")
            percent = window.get("percent" if current else "usagePercent")
            if status not in ("ok", "rate-limited") or not _nonnegative_number(percent):
                return None
            try:
                if current:
                    raw_reset = window.get("resetsAt")
                    if not isinstance(raw_reset, str):
                        return None
                    reset = datetime.fromisoformat(raw_reset.replace("Z", "+00:00"))
                    if reset.tzinfo is None or reset.utcoffset() is None:
                        return None
                else:
                    seconds = window.get("resetInSec")
                    if not _nonnegative_number(seconds):
                        return None
                    reset = now + timedelta(seconds=seconds)
                result[target + "_reset"] = reset.astimezone(timezone.utc).isoformat()
            except (ValueError, TypeError, OverflowError):
                return None
            result[target + "_pct"] = percent
            limited = limited or status == "rate-limited" or percent >= 100
        result["limit_reached"] = limited
        return result
