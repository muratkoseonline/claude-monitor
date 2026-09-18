#!/usr/bin/env python3
"""
Codex (ChatGPT) kota okuyucu.
~/.codex/auth.json içindeki OAuth token ile chatgpt.com usage API'sini sorgular.
Codex CLI / Codex uygulaması giriş yapmışsa ek ayar gerekmez.
"""

import os
import json
import time
import base64
import requests

DEFAULT_AUTH_PATH = os.path.join(os.path.expanduser("~"), ".codex", "auth.json")
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"   # Codex CLI public client id


class CodexUsage:
    def __init__(self, auth_path=None, log=None):
        self.auth_path = auth_path or DEFAULT_AUTH_PATH
        self._log = log or (lambda m: None)
        self._access_token = None
        self._account_id = None
        self._refresh_token = None
        self._auth_mtime = None

    # ── Auth ───────────────────────────────────────────────────────────────────

    def _load_auth(self):
        """auth.json'u oku; dosya değiştiyse token'ı yenile."""
        if not os.path.exists(self.auth_path):
            return False
        try:
            mtime = os.path.getmtime(self.auth_path)
            if mtime == self._auth_mtime and self._access_token:
                return True
            with open(self.auth_path, encoding="utf-8") as f:
                data = json.load(f)
            tokens = data.get("tokens") or {}
            self._access_token = tokens.get("access_token") or ""
            self._refresh_token = tokens.get("refresh_token") or ""
            self._account_id = tokens.get("account_id") or ""
            self._auth_mtime = mtime
            return bool(self._access_token)
        except Exception as e:
            self._log(f"Codex auth okuma hatası: {e}")
            return False

    @staticmethod
    def _jwt_exp(token):
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            return int(json.loads(base64.urlsafe_b64decode(payload)).get("exp", 0))
        except Exception:
            return 0

    def _refresh(self):
        """Refresh token ile yeni access token al (sadece bellekte tutulur)."""
        if not self._refresh_token:
            return False
        try:
            resp = requests.post(
                TOKEN_URL,
                json={
                    "grant_type": "refresh_token",
                    "client_id": CLIENT_ID,
                    "refresh_token": self._refresh_token,
                },
                timeout=15,
            )
            self._log(f"POST {TOKEN_URL} → {resp.status_code}")
            if resp.status_code == 200:
                d = resp.json()
                if d.get("access_token"):
                    self._access_token = d["access_token"]
                    if d.get("refresh_token"):
                        self._refresh_token = d["refresh_token"]
                    return True
        except Exception as e:
            self._log(f"Codex token yenileme hatası: {e}")
        return False

    def _headers(self):
        return {
            "Authorization": f"Bearer {self._access_token}",
            "ChatGPT-Account-Id": self._account_id,
            "User-Agent": "claude-monitor",
            "Accept": "application/json",
        }

    # ── Fetch ──────────────────────────────────────────────────────────────────

    def fetch(self):
        """Ham JSON döner, hata durumunda {"_error": ...}."""
        if not self._load_auth():
            return {"_error": "no_auth"}

        # Süresi dolmuşsa önce yenile
        exp = self._jwt_exp(self._access_token)
        if exp and exp < time.time() + 60:
            self._refresh()

        try:
            resp = requests.get(USAGE_URL, headers=self._headers(), timeout=15)
            self._log(f"GET {USAGE_URL} → {resp.status_code}")
            if resp.status_code == 401 and self._refresh():
                resp = requests.get(USAGE_URL, headers=self._headers(), timeout=15)
                self._log(f"GET {USAGE_URL} (retry) → {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                self._log(f"Codex response: {json.dumps(data)[:300]}")
                return data
            if resp.status_code in (401, 403):
                return {"_error": "auth"}
        except Exception as e:
            self._log(f"Codex fetch hatası: {e}")
        return {"_error": "no_response"}

    @staticmethod
    def parse(data):
        """
        Gerçek format:
        {rate_limit: {primary_window: {used_percent, limit_window_seconds, reset_at},
                      secondary_window: {...}}, plan_type, ...}
        primary = 5 saatlik, secondary = haftalık pencere.
        """
        if not data or data.get("_error"):
            return None
        rl = data.get("rate_limit") or {}
        pw = rl.get("primary_window") or {}
        sw = rl.get("secondary_window") or {}

        def reset_iso(win):
            ts = win.get("reset_at")
            if not ts:
                return None
            try:
                from datetime import datetime, timezone
                return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
            except Exception:
                return None

        return {
            "percent": int(pw.get("used_percent", 0) or 0),
            "five_hour_pct": int(pw.get("used_percent", 0) or 0),
            "seven_day_pct": int(sw.get("used_percent", 0) or 0),
            "five_hour_window": int(pw.get("limit_window_seconds", 0) or 0),
            "seven_day_window": int(sw.get("limit_window_seconds", 0) or 0),
            "five_hour_reset": reset_iso(pw),
            "seven_day_reset": reset_iso(sw),
            "limit_reached": bool(rl.get("limit_reached")),
            "plan_type": data.get("plan_type") or "",
            "email": data.get("email") or "",
        }


if __name__ == "__main__":
    c = CodexUsage(log=print)
    raw = c.fetch()
    print(json.dumps(CodexUsage.parse(raw), indent=2))
