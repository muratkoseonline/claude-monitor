#!/usr/bin/env python3
"""
Claude Usage Monitor v1.4.0
Windows 11 System Tray - Claude + Codex + OpenCode Go + Antigravity quota tracker
"""

__version__ = "1.4.0"

import sys
import os
import json
import re
import time
import threading
import requests
from datetime import datetime, timezone

try:
    from PIL import Image, ImageDraw, ImageFont
    import pystray
    from pystray import MenuItem as item
except ImportError:
    print("Eksik paket. Çalıştır: pip install pystray pillow requests plyer")
    sys.exit(1)

# Simge modülü — aynı klasörde
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from generate_icon import make_tray_icon, generate_ico
from codex_usage import CodexUsage, DEFAULT_AUTH_PATH as CODEX_AUTH_DEFAULT
from opencode_usage import (
    OpenCodeUsage,
    DEFAULT_AUTH_PATH as OPENCODE_AUTH_DEFAULT,
    DEFAULT_DB_PATH as OPENCODE_DB_DEFAULT,
)
from antigravity_usage import (
    AntigravityUsage,
    DEFAULT_DAEMON_DIR as ANTIGRAVITY_DAEMON_DEFAULT,
)

ICON_FILE = os.path.join(_HERE, "icon.ico")
# İlk çalıştırmada .ico yoksa üret
if not os.path.exists(ICON_FILE):
    try:
        generate_ico(ICON_FILE)
    except Exception:
        ICON_FILE = None

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".claude-monitor")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
LOG_FILE = os.path.join(CONFIG_DIR, "monitor.log")

DEFAULT_CONFIG = {
    "session_key": "",
    "cookie_string": "",       # fallback: full cookie string
    "org_uuid": "",            # auto-discovered from /api/organizations
    "notify_threshold": 75,
    "poll_interval": 120,      # seconds
    "codex_enabled": True,     # Codex (ChatGPT) kotasını da izle
    "codex_auth_path": "",     # boş = ~/.codex/auth.json
    "opencode_enabled": True,
    "opencode_auth_path": "",  # legacy API-key fallback
    "opencode_db_path": "",    # V2 account login DB; boş = varsayılan
    "antigravity_enabled": True,
    "antigravity_daemon_dir": "",  # boş = ~/.gemini/antigravity/daemon
}

ICON_SIZE = 64


class ClaudeMonitor:
    def __init__(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        self.config = self._load_config()
        self.usage_percent = 0
        self.usage_data = {}
        self.notified = False
        self.icon = None
        self.running = True
        self.last_error = None
        self.last_updated = None
        # Codex
        self.codex = CodexUsage(self._codex_auth_path(), log=self._log)
        self.codex_data = {}
        self.codex_error = None
        self.codex_notified = False
        self.codex_updated = None
        self.opencode = OpenCodeUsage(
            self._opencode_auth_path(), log=self._log, db_path=self._opencode_db_path()
        )
        self.opencode_data = {}
        self.opencode_error = None
        self.opencode_updated = None
        self.opencode_notified = set()
        self.opencode_periods = {}
        self.antigravity = AntigravityUsage(
            self._antigravity_daemon_dir(), log=self._log
        )
        self.antigravity_data = {}
        self.antigravity_error = None
        self.antigravity_updated = None
        self.antigravity_notified = set()
        self.antigravity_periods = {}
        self._refresh_lock = threading.Lock()

    def _antigravity_daemon_dir(self):
        return (self.config.get("antigravity_daemon_dir") or "").strip() or ANTIGRAVITY_DAEMON_DEFAULT

    def _opencode_auth_path(self):
        return (self.config.get("opencode_auth_path") or "").strip() or OPENCODE_AUTH_DEFAULT

    def _opencode_db_path(self):
        return (self.config.get("opencode_db_path") or "").strip() or OPENCODE_DB_DEFAULT

    def _codex_auth_path(self):
        return (self.config.get("codex_auth_path") or "").strip() or CODEX_AUTH_DEFAULT

    # ── Config ─────────────────────────────────────────────────────────────────

    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, encoding="utf-8") as f:
                    return {**DEFAULT_CONFIG, **json.load(f)}
            except Exception as e:
                self._log(f"Config hata: {e}")
        return DEFAULT_CONFIG.copy()

    def _save_config(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

    def _log(self, msg):
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except:
            pass

    # ── API ────────────────────────────────────────────────────────────────────

    def _build_headers(self):
        cookie = self.config.get("cookie_string", "").strip()
        if not cookie:
            sk = self.config.get("session_key", "").strip()
            if sk:
                cookie = f"sessionKey={sk}"
        if not cookie:
            return None
        return {
            "Cookie": cookie,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, */*",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
            "Referer": "https://claude.ai/",
        }

    def _get_org_uuid(self, headers):
        """Org UUID'yi cache'den al ya da API'den keşfet."""
        cached = self.config.get("org_uuid", "").strip()
        if cached:
            return cached
        try:
            resp = requests.get("https://claude.ai/api/organizations", headers=headers, timeout=12)
            if resp.status_code == 200:
                orgs = resp.json()
                if orgs and isinstance(orgs, list):
                    uuid = orgs[0].get("uuid", "")
                    if uuid:
                        self.config["org_uuid"] = uuid
                        self._save_config()
                        self._log(f"Org UUID keşfedildi: {uuid}")
                        return uuid
            elif resp.status_code == 401:
                return None
        except Exception as e:
            self._log(f"Org UUID hatası: {e}")
        return None

    def fetch_usage(self):
        headers = self._build_headers()
        if not headers:
            return None

        org_uuid = self._get_org_uuid(headers)
        if not org_uuid:
            self._log("Org UUID alınamadı - session key geçersiz olabilir")
            return {"_error": "auth"}

        url = f"https://claude.ai/api/organizations/{org_uuid}/usage"
        try:
            resp = requests.get(url, headers=headers, timeout=12)
            self._log(f"GET {url} → {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                self._log(f"Response: {json.dumps(data)[:300]}")
                return data
            elif resp.status_code == 401:
                self.config["org_uuid"] = ""  # cache'i sıfırla
                return {"_error": "auth"}
        except Exception as e:
            self._log(f"Fetch hatası: {e}")

        return {"_error": "no_response"}

    def parse_usage(self, data):
        if not data:
            return None

        if data.get("_error") == "auth":
            self.last_error = "Oturum süresi dolmuş (401) - yeni session key girin"
            return None

        if data.get("_error") == "no_response":
            self.last_error = "API erişilemiyor"
            return None

        # Gerçek format: {five_hour: {utilization, resets_at}, seven_day: {...}, ...}
        result = {
            "percent": 0,
            "five_hour_pct": 0,
            "seven_day_pct": 0,
            "five_hour_reset": None,
            "seven_day_reset": None,
            "extra_usage_enabled": False,
        }

        fh = data.get("five_hour") or {}
        sd = data.get("seven_day") or {}

        result["five_hour_pct"] = int(fh.get("utilization", 0) or 0)
        result["seven_day_pct"] = int(sd.get("utilization", 0) or 0)
        result["five_hour_reset"] = fh.get("resets_at")
        result["seven_day_reset"] = sd.get("resets_at")

        eu = data.get("extra_usage") or {}
        result["extra_usage_enabled"] = bool(eu.get("is_enabled"))

        # Model bazlı limitler
        for key in ("seven_day_opus", "seven_day_sonnet", "seven_day_omelette"):
            v = data.get(key) or {}
            if v and v.get("utilization") is not None:
                result[key] = int(v.get("utilization", 0) or 0)

        result["percent"] = result["five_hour_pct"]
        return result

    # ── Icon ───────────────────────────────────────────────────────────────────

    def create_icon_image(self, percent, error=False, no_key=False):
        codex_pct = None
        if self.config.get("codex_enabled") and self.codex_data:
            codex_pct = self.codex_data.get("five_hour_pct", 0)
        ag_pct = None
        if self.config.get("antigravity_enabled") and self.antigravity_data:
            ag_pct = self.antigravity_data.get("five_hour_pct")
            if ag_pct is None:
                ag_pct = self.antigravity_data.get("seven_day_pct")
        return make_tray_icon(
            ICON_SIZE,
            percent,
            error=error,
            no_key=no_key,
            codex_percent=codex_pct,
            opencode_percent=(
                self.opencode_data.get("five_hour_pct")
                if self.config.get("opencode_enabled") and self.opencode_data
                else None
            ),
            antigravity_percent=ag_pct,
        )

    # ── Tooltip ────────────────────────────────────────────────────────────────

    def build_tooltip(self):
        """Windows tepsi ipucu en fazla 127 karakter; kompakt CL/CX/Go/AG etiketleri kullan."""
        lines = []
        if not self.config.get("session_key") and not self.config.get("cookie_string"):
            lines.append("CL: key yok (Ayarlar)")
        elif not self.usage_data:
            lines.append("CL: HATA" if self.last_error else "CL: yukleniyor")
        else:
            d = self.usage_data
            lines.append(f"CL 5s %{d.get('five_hour_pct', 0)}|7g %{d.get('seven_day_pct', 0)}")
        lines.extend(self._codex_tooltip_lines())
        if self.config.get("opencode_enabled"):
            if self.opencode_error:
                lines.append("Go: HATA")
            elif self.opencode_data:
                g = self.opencode_data
                lines.append(
                    f"Go 5s %{g['five_hour_pct']:g}|7g %{g['seven_day_pct']:g}|ay %{g['monthly_pct']:g}"
                )
            else:
                lines.append("Go: yukleniyor")
        lines.extend(self._antigravity_tooltip_lines())
        return "\n".join(lines)[:127]

    @staticmethod
    def _reset_suffix(iso):
        if not iso:
            return ""
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return f" ({dt.astimezone().strftime('%H:%M')})"
        except Exception:
            return ""

    def _codex_tooltip_lines(self):
        if not self.config.get("codex_enabled"):
            return []
        if not self.codex_data:
            return ["CX: HATA" if self.codex_error else "CX: yukleniyor"]
        c = self.codex_data
        return [f"CX 5s %{c.get('five_hour_pct', 0)}|7g %{c.get('seven_day_pct', 0)}"]

    def _antigravity_tooltip_lines(self):
        if not self.config.get("antigravity_enabled"):
            return []
        if self.antigravity_error and not self.antigravity_data:
            return ["AG: IDE kapali" if "açık değil" in self.antigravity_error else "AG: HATA"]
        if not self.antigravity_data:
            return ["AG: yukleniyor"]
        a = self.antigravity_data
        parts = []
        if a.get("five_hour_pct") is not None:
            parts.append(f"5s %{a['five_hour_pct']:g}")
        if a.get("seven_day_pct") is not None:
            parts.append(f"7g %{a['seven_day_pct']:g}")
        suffix = "*" if self.antigravity_error else ""
        return [f"AG {'|'.join(parts)}{suffix}"]

    @staticmethod
    def _bar(percent, width=12):
        filled = int(width * percent / 100)
        return "[" + "#" * filled + "-" * (width - filled) + "]"

    # ── Notification ───────────────────────────────────────────────────────────

    def send_notification(self, title, msg):
        try:
            from plyer import notification as notif
            notif.notify(
                title=title,
                message=msg,
                app_name="Claude Monitor",
                timeout=15,
            )
            self._log(f"Bildirim gönderildi: {title}")
        except Exception as e:
            self._log(f"Bildirim hatası: {e}")

    # ── Poll loop ──────────────────────────────────────────────────────────────

    def poll_loop(self):
        time.sleep(2)
        while self.running:
            try:
                self._do_refresh()
            except Exception as e:
                self._log(f"Poll döngü hatası: {e}")
                self.last_error = str(e)
                self._update_icon()

            interval = self.config.get("poll_interval", 120)
            for _ in range(interval):
                if not self.running:
                    break
                time.sleep(1)

    def _do_refresh(self):
        # Tepsi, detay penceresi ve periyodik yenileme aynı anda istek atmasın.
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            self._refresh_all()
        finally:
            self._refresh_lock.release()

    SNAPSHOT_FILE = os.path.join(CONFIG_DIR, "usage-snapshot.json")
    _SNAP_KEY = re.compile(r"(pct|percent|reset|window)", re.I)

    @classmethod
    def _snap_part(cls, d):
        """Yalniz sayisal/zaman alanlari (yuzde, reset, pencere). Token ve kimlik alanlari asla yazilmaz."""
        out = {}
        for k, v in (d or {}).items():
            if cls._SNAP_KEY.search(str(k)) and isinstance(v, (int, float, str)) and not isinstance(v, bool):
                out[k] = v
        return out

    def _write_snapshot(self):
        """Hook'lar ve ajanlar icin sirsiz limit ozeti: ~/.claude-monitor/usage-snapshot.json"""
        try:
            snap = {
                "updated": datetime.now(timezone.utc).isoformat(),
                "claude": self._snap_part(self.usage_data),
                "codex": self._snap_part(self.codex_data),
                "opencode": self._snap_part(self.opencode_data),
                "antigravity": self._snap_part(self.antigravity_data),
            }
            tmp = self.SNAPSHOT_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False)
            os.replace(tmp, self.SNAPSHOT_FILE)
        except Exception as e:
            self._log(f"Snapshot yazilamadi: {e}")

    def _refresh_all(self):
        try:
            self._refresh_all_inner()
        finally:
            self._write_snapshot()

    def _refresh_all_inner(self):
        self._refresh_antigravity()
        self._refresh_opencode()
        self._refresh_codex()
        has_key = bool(self.config.get("session_key") or self.config.get("cookie_string"))
        if not has_key:
            self.last_error = None
            self.usage_data = {}
            self._update_icon(no_key=True)
            return

        data = self.fetch_usage()
        parsed = self.parse_usage(data)

        if parsed:
            self.usage_data = parsed
            self.usage_percent = parsed["percent"]
            self.last_error = None
            self.last_updated = datetime.now()

            threshold = self.config.get("notify_threshold", 75)
            if self.usage_percent >= threshold and not self.notified:
                self.notified = True
                self.send_notification(
                    "⚠️ Claude Limit Uyarisi",
                    f"5 saatlik kota %{threshold} sinirini gecti!\n"
                    f"Kullanim: %{self.usage_percent}\n"
                    f"Kalan: {parsed.get('remaining', '?')} istek",
                )
            elif self.usage_percent < threshold:
                self.notified = False

            self._update_icon()
        else:
            self._update_icon(error=True)

    def _refresh_codex(self):
        if not self.config.get("codex_enabled"):
            self.codex_data = {}
            self.codex_error = None
            return
        self.codex.auth_path = self._codex_auth_path()
        raw = self.codex.fetch()
        err = (raw or {}).get("_error")
        if err == "no_auth":
            self.codex_error = "Codex girişi yok (auth.json bulunamadı) - 'codex login' çalıştırın"
        elif err == "auth":
            self.codex_error = "Codex oturumu geçersiz - 'codex login' ile yeniden girin"
        elif err == "no_response":
            self.codex_error = "Codex API erişilemiyor"
        else:
            self.codex_error = None

        parsed = CodexUsage.parse(raw)
        if not parsed:
            return
        self.codex_data = parsed
        self.codex_updated = datetime.now()

        threshold = self.config.get("notify_threshold", 75)
        pct = parsed["five_hour_pct"]
        if pct >= threshold and not self.codex_notified:
            self.codex_notified = True
            self.send_notification(
                "⚠️ Codex Limit Uyarisi",
                f"Codex 5 saatlik kota %{threshold} sinirini gecti!\n"
                f"Kullanim: %{pct}  |  Haftalik: %{parsed['seven_day_pct']}",
            )
        elif pct < threshold:
            self.codex_notified = False

    def _refresh_opencode(self):
        if not self.config.get("opencode_enabled"):
            self.opencode_data = {}
            self.opencode_error = None
            self.opencode_updated = None
            self.opencode_notified.clear()
            self.opencode_periods.clear()
            return
        path = self._opencode_auth_path()
        if self.opencode.auth_path != path:
            self.opencode_data = {}
            self.opencode_updated = None
            self.opencode_notified.clear()
            self.opencode_periods.clear()
        self.opencode.auth_path = path
        raw = self.opencode.fetch()
        errors = {
            "no_auth": "OpenCode hesabı bulunamadı. OpenCode'da OpenCode Go → Account ile bağlanın.",
            "account_auth": "OpenCode Account oturumu reddedildi. OpenCode'da hesabı yeniden bağlayıp yenileyin.",
            "account_workspace": "OpenCode hesabının Go çalışma alanı okunamadı. OpenCode'da Go hesabını kontrol edin.",
            "auth": "OpenCode Go API anahtarı reddedildi. OpenCode'da Account bağlantısını kullanın veya anahtarı yenileyin.",
            "no_subscription": "Bu anahtarın çalışma alanında etkin Go aboneliği bulunamadı.",
            "no_response": "OpenCode kullanım API'sine erişilemiyor.",
            "rate_limited": "OpenCode kullanım API'si istek sınırına ulaştı; daha sonra yenilenecek.",
            "invalid_response": "OpenCode kullanım yanıtı beklenen biçimde değil.",
        }
        err = (raw or {}).get("_error")
        parsed = OpenCodeUsage.parse(raw)
        if not parsed:
            self.opencode_error = errors.get(err, errors["invalid_response"])
            return
        self.opencode_data = parsed
        self.opencode_error = None
        self.opencode_updated = datetime.now()
        threshold = self.config.get("notify_threshold", 75)
        for key, label in (("five_hour", "5 saatlik"), ("seven_day", "Haftalık"), ("monthly", "Aylık")):
            # Sıfırlanmayı sorgular arasında kaçırmış olsak da yeni dönem uyarabilsin.
            reset = parsed.get(f"{key}_reset")
            if reset and key in self.opencode_periods:
                previous = datetime.fromisoformat(self.opencode_periods[key])
                current = datetime.fromisoformat(reset)
                # Legacy API'nin göreli resetinden gelen küçük saat farklarını yok say.
                if abs((current - previous).total_seconds()) > 60:
                    self.opencode_notified.discard(key)
            self.opencode_periods[key] = reset
            pct = parsed[f"{key}_pct"]
            if pct >= threshold and key not in self.opencode_notified:
                self.opencode_notified.add(key)
                self.send_notification("OpenCode Go Limit Uyarısı", f"{label} kullanım %{pct:g} (eşik %{threshold}).")
            elif pct < threshold:
                self.opencode_notified.discard(key)

    def _refresh_antigravity(self):
        if not self.config.get("antigravity_enabled"):
            self.antigravity_data = {}
            self.antigravity_error = None
            self.antigravity_updated = None
            self.antigravity_notified.clear()
            self.antigravity_periods.clear()
            return
        daemon_dir = self._antigravity_daemon_dir()
        if self.antigravity.daemon_dir != daemon_dir:
            self.antigravity_data = {}
            self.antigravity_updated = None
            self.antigravity_notified.clear()
            self.antigravity_periods.clear()
        self.antigravity.daemon_dir = daemon_dir
        raw = self.antigravity.fetch()
        errors = {
            "ide_closed": "Antigravity IDE açık değil; IDE açılınca kota okunur.",
            "no_response": "Antigravity yerel dil sunucusuna erişilemiyor.",
            "invalid_response": "Antigravity kota yanıtı beklenen biçimde değil.",
            "empty_rate_limits": "Antigravity kota penceresi bulunamadı.",
        }
        err = (raw or {}).get("_error")
        parsed = AntigravityUsage.parse(raw)
        if not parsed:
            self.antigravity_error = errors.get(err, errors["invalid_response"])
            return
        self.antigravity_data = parsed
        self.antigravity_error = None
        self.antigravity_updated = datetime.now()
        threshold = self.config.get("notify_threshold", 75)
        for key, label in (("five_hour", "5 saatlik"), ("seven_day", "Haftalık")):
            pct = parsed.get(f"{key}_pct")
            if pct is None:
                continue
            reset = parsed.get(f"{key}_reset")
            if reset and key in self.antigravity_periods and self.antigravity_periods[key]:
                try:
                    previous = datetime.fromisoformat(self.antigravity_periods[key])
                    current = datetime.fromisoformat(reset)
                    if abs((current - previous).total_seconds()) > 60:
                        self.antigravity_notified.discard(key)
                except ValueError:
                    pass
            self.antigravity_periods[key] = reset
            if pct >= threshold and key not in self.antigravity_notified:
                self.antigravity_notified.add(key)
                self.send_notification(
                    "Antigravity Limit Uyarısı",
                    f"{label} kullanım %{pct:g} (eşik %{threshold}).",
                )
            elif pct < threshold:
                self.antigravity_notified.discard(key)

    def _update_icon(self, error=False, no_key=False):
        if not self.icon:
            return
        if no_key:
            img = self.create_icon_image(0, no_key=True)
        elif error:
            img = self.create_icon_image(self.usage_percent, error=True)
        else:
            img = self.create_icon_image(self.usage_percent)
        self.icon.icon = img
        self.icon.title = self.build_tooltip()

    # ── Settings window ────────────────────────────────────────────────────────

    def open_settings(self):
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.title("Claude Monitor - Ayarlar")
        root.geometry("560x820")
        root.resizable(False, False)
        root.configure(bg="#1e1e2e")
        if ICON_FILE:
            try:
                root.iconbitmap(ICON_FILE)
            except Exception:
                pass
        root.lift()
        root.focus_force()

        BG = "#1e1e2e"
        BG2 = "#313244"
        FG = "#cdd6f4"
        FG2 = "#6c7086"
        ACC = "#cba6f7"
        BTN = "#89b4fa"

        def label(parent, text, size=10, color=FG, bold=False):
            font = ("Segoe UI", size, "bold" if bold else "normal")
            tk.Label(parent, text=text, bg=BG, fg=color, font=font).pack(anchor="w")

        def entry_field(parent, var, show=None):
            e = tk.Entry(
                parent, textvariable=var, show=show or "",
                bg=BG2, fg=FG, insertbackground=FG,
                relief="flat", font=("Segoe UI", 9), bd=0
            )
            e.pack(fill=tk.X, ipady=4, pady=(2, 7))
            return e

        frame = tk.Frame(root, bg=BG, padx=22, pady=14)
        frame.pack(fill=tk.BOTH, expand=True)

        label(frame, "Claude Monitor Ayarlari", size=14, color=ACC, bold=True)
        tk.Frame(frame, bg=BG2, height=1).pack(fill=tk.X, pady=8)

        # Session Key
        label(frame, "Session Key (onerilen):")
        label(frame, "claude.ai → F12 → Application → Cookies → sessionKey degeri", size=8, color=FG2)
        sk_var = tk.StringVar(value=self.config.get("session_key", ""))
        sk_entry = entry_field(frame, sk_var, show="•")

        # Show/hide toggle
        def toggle_show():
            if sk_entry.cget("show") == "•":
                sk_entry.config(show="")
                toggle_btn.config(text="Gizle")
            else:
                sk_entry.config(show="•")
                toggle_btn.config(text="Göster")

        toggle_btn = tk.Button(
            frame, text="Göster", command=toggle_show,
            bg=BG2, fg=FG2, relief="flat",
            font=("Segoe UI", 8), cursor="hand2"
        )
        toggle_btn.pack(anchor="e", pady=(0, 8))

        # Full cookie string (alternative)
        label(frame, "Tam Cookie Dizisi (alternatif, boş bırakılabilir):")
        label(frame, "Birden fazla cookie gerekiyorsa buraya yapıştır", size=8, color=FG2)
        ck_var = tk.StringVar(value=self.config.get("cookie_string", ""))
        entry_field(frame, ck_var, show="•")

        # Threshold slider
        label(frame, "Bildirim Esigi (%):")
        thr_var = tk.IntVar(value=self.config.get("notify_threshold", 75))
        thr_frame = tk.Frame(frame, bg=BG)
        thr_frame.pack(fill=tk.X, pady=(0, 12))

        thr_lbl = tk.Label(thr_frame, text=f"%{thr_var.get()}", bg=BG, fg=FG,
                           font=("Segoe UI", 10, "bold"), width=4)
        thr_lbl.pack(side=tk.RIGHT)

        def update_thr(val):
            thr_lbl.config(text=f"%{int(float(val))}")

        thr_scale = tk.Scale(
            thr_frame, from_=50, to=95, orient=tk.HORIZONTAL,
            variable=thr_var, command=update_thr,
            bg=BG, fg=FG, troughcolor=BG2,
            highlightthickness=0, showvalue=False, length=380
        )
        thr_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Codex
        tk.Frame(frame, bg=BG2, height=1).pack(fill=tk.X, pady=8)
        codex_var = tk.BooleanVar(value=bool(self.config.get("codex_enabled", True)))
        tk.Checkbutton(
            frame, text="Codex (ChatGPT) kotasını da izle", variable=codex_var,
            bg=BG, fg=FG, selectcolor=BG2, activebackground=BG, activeforeground=FG,
            font=("Segoe UI", 10), cursor="hand2"
        ).pack(anchor="w")
        label(frame, "Codex CLI / uygulaması ile giriş yapılmış olmalı. Token ~/.codex/auth.json'dan okunur.",
              size=8, color=FG2)
        label(frame, "auth.json yolu (boş = varsayılan):", size=9)
        cx_var = tk.StringVar(value=self.config.get("codex_auth_path", ""))
        entry_field(frame, cx_var)

        tk.Frame(frame, bg=BG2, height=1).pack(fill=tk.X, pady=8)
        go_var = tk.BooleanVar(value=bool(self.config.get("opencode_enabled", True)))
        tk.Checkbutton(
            frame, text="OpenCode Go limitlerini izle", variable=go_var,
            bg=BG, fg=FG, selectcolor=BG2, activebackground=BG, activeforeground=FG,
            font=("Segoe UI", 10), cursor="hand2"
        ).pack(anchor="w")
        label(frame, "Account girişi OpenCode V2 veritabanından okunur; anahtar buraya yapıştırılmaz.",
              size=8, color=FG2)
        label(frame, "OpenCode V2 DB yolu (boş = varsayılan):", size=9)
        go_db_var = tk.StringVar(value=self.config.get("opencode_db_path", ""))
        entry_field(frame, go_db_var)
        label(frame, "Eski API-key kurulumu için auth.json yolu (boş = varsayılan):", size=9)
        go_path_var = tk.StringVar(value=self.config.get("opencode_auth_path", ""))
        entry_field(frame, go_path_var)

        tk.Frame(frame, bg=BG2, height=1).pack(fill=tk.X, pady=6)
        ag_var = tk.BooleanVar(value=bool(self.config.get("antigravity_enabled", True)))
        tk.Checkbutton(
            frame, text="Antigravity (Google) kotasını izle", variable=ag_var,
            bg=BG, fg=FG, selectcolor=BG2, activebackground=BG, activeforeground=FG,
            font=("Segoe UI", 10), cursor="hand2"
        ).pack(anchor="w")
        label(frame, "Antigravity IDE açıkken yerel dil sunucusundan (127.0.0.1) okunur.",
              size=8, color=FG2)
        label(frame, "Daemon dizini (boş = ~/.gemini/antigravity/daemon):", size=9)
        ag_dir_var = tk.StringVar(value=self.config.get("antigravity_daemon_dir", ""))
        entry_field(frame, ag_dir_var)

        # Buttons
        tk.Frame(frame, bg=BG2, height=1).pack(fill=tk.X, pady=6)
        btn_frame = tk.Frame(frame, bg=BG)
        btn_frame.pack(fill=tk.X)

        def save():
            self.config["session_key"] = sk_var.get().strip()
            self.config["cookie_string"] = ck_var.get().strip()
            self.config["notify_threshold"] = thr_var.get()
            self.config["codex_enabled"] = bool(codex_var.get())
            self.config["codex_auth_path"] = cx_var.get().strip()
            self.config["opencode_enabled"] = bool(go_var.get())
            self.config["opencode_db_path"] = go_db_var.get().strip()
            self.config["opencode_auth_path"] = go_path_var.get().strip()
            self.config["antigravity_enabled"] = bool(ag_var.get())
            self.config["antigravity_daemon_dir"] = ag_dir_var.get().strip()
            self.opencode.db_path = self._opencode_db_path()
            self.opencode.auth_path = self._opencode_auth_path()
            self.antigravity.daemon_dir = self._antigravity_daemon_dir()
            self._save_config()
            self.notified = False
            self.codex_notified = False
            self.opencode_notified.clear()
            self.antigravity_notified.clear()
            threading.Thread(target=self._do_refresh, daemon=True).start()
            messagebox.showinfo("Kaydedildi", "Ayarlar kaydedildi!\nVeriler güncelleniyor...", parent=root)
            root.destroy()

        tk.Button(
            btn_frame, text="Kaydet", command=save,
            bg=BTN, fg=BG, font=("Segoe UI", 10, "bold"),
            relief="flat", padx=16, pady=4, cursor="hand2"
        ).pack(side=tk.RIGHT, padx=(4, 0))

        tk.Button(
            btn_frame, text="İptal", command=root.destroy,
            bg=BG2, fg=FG, font=("Segoe UI", 10),
            relief="flat", padx=16, pady=4, cursor="hand2"
        ).pack(side=tk.RIGHT)

        root.mainloop()

    # ── Detail window ──────────────────────────────────────────────────────────

    def open_detail_window(self):
        from detail_window import open_usage_window
        open_usage_window(self, ICON_FILE)

    # ── Log window ─────────────────────────────────────────────────────────────

    def open_log_window(self):
        import tkinter as tk

        root = tk.Tk()
        root.title("Claude Monitor - Log")
        root.geometry("600x400")
        root.configure(bg="#1e1e2e")
        root.lift()
        if ICON_FILE:
            try:
                root.iconbitmap(ICON_FILE)
            except Exception:
                pass

        txt = tk.Text(root, bg="#11111b", fg="#cdd6f4",
                      font=("Consolas", 9), relief="flat", padx=8, pady=8)
        txt.pack(fill=tk.BOTH, expand=True)

        try:
            with open(LOG_FILE, encoding="utf-8") as f:
                content = f.read()
        except:
            content = "(log boş)"

        txt.insert("1.0", content)
        txt.see(tk.END)
        txt.config(state="disabled")
        root.mainloop()

    # ── Main ───────────────────────────────────────────────────────────────────

    def quit_app(self):
        self.running = False
        if self.icon:
            self.icon.stop()

    def run(self):
        poll_thread = threading.Thread(target=self.poll_loop, daemon=True)
        poll_thread.start()

        menu = pystray.Menu(
            item("Kullanım Detayları", lambda: threading.Thread(
                target=self.open_detail_window, daemon=True).start(),
                default=True),
            item("Şimdi Güncelle", lambda: threading.Thread(
                target=self._do_refresh, daemon=True).start()),
            pystray.Menu.SEPARATOR,
            item("Ayarlar", lambda: threading.Thread(
                target=self.open_settings, daemon=True).start()),
            item("Log Görüntüle", lambda: threading.Thread(
                target=self.open_log_window, daemon=True).start()),
            pystray.Menu.SEPARATOR,
            item("Çıkış", self.quit_app),
        )

        has_key = bool(self.config.get("session_key") or self.config.get("cookie_string"))
        initial_img = self.create_icon_image(0, no_key=not has_key)

        self.icon = pystray.Icon(
            "claude-monitor",
            initial_img,
            self.build_tooltip(),
            menu,
        )

        self._log("Uygulama başlatıldı")
        self.icon.run()


if __name__ == "__main__":
    monitor = ClaudeMonitor()
    monitor.run()
