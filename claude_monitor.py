#!/usr/bin/env python3
"""
Claude Usage Monitor v1.2
Windows 11 System Tray - 5-hour quota tracker
"""

import sys
import os
import json
import time
import threading
import requests
from datetime import datetime

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
        return make_tray_icon(ICON_SIZE, percent, error=error, no_key=no_key)

    # ── Tooltip ────────────────────────────────────────────────────────────────

    def build_tooltip(self):
        if not self.config.get("session_key") and not self.config.get("cookie_string"):
            return "Claude Monitor\nSession key yok - Sag tik > Ayarlar"

        if not self.usage_data:
            if self.last_error:
                return f"Claude Monitor\nHata: {self.last_error}"
            return "Claude Monitor\nYukleniyor..."

        d = self.usage_data
        fh = d.get("five_hour_pct", 0)
        sd = d.get("seven_day_pct", 0)
        reset = d.get("five_hour_reset", "") or ""
        updated = self.last_updated.strftime("%H:%M") if self.last_updated else "--:--"

        bar = self._bar(fh)
        lines = [
            "Claude Kullanim Monitoru",
            f"{bar} %{fh}",
            f"5 Saatlik: %{fh}",
            f"7 Gunluk : %{sd}",
        ]
        if reset:
            # ISO → saat:dakika
            try:
                from datetime import timezone
                dt = datetime.fromisoformat(reset.replace("Z", "+00:00"))
                local = dt.astimezone().strftime("%H:%M")
                lines.append(f"Sifirlama: {local}")
            except:
                lines.append(f"Sifirlama: {reset[:16]}")
        lines.append(f"Guncelleme: {updated}")
        return "\n".join(lines)

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
        root.geometry("520x400")
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
            e.pack(fill=tk.X, ipady=5, pady=(2, 10))
            return e

        frame = tk.Frame(root, bg=BG, padx=24, pady=20)
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

        # Buttons
        tk.Frame(frame, bg=BG2, height=1).pack(fill=tk.X, pady=8)
        btn_frame = tk.Frame(frame, bg=BG)
        btn_frame.pack(fill=tk.X)

        def save():
            self.config["session_key"] = sk_var.get().strip()
            self.config["cookie_string"] = ck_var.get().strip()
            self.config["notify_threshold"] = thr_var.get()
            self._save_config()
            self.notified = False
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
        import tkinter as tk

        BG, BG2 = "#1e1e2e", "#313244"
        FG, FG2 = "#cdd6f4", "#6c7086"
        ACC = "#cba6f7"

        root = tk.Tk()
        root.title("Claude Monitor - Kullanım Detayları")
        root.geometry("420x400")
        root.resizable(False, False)
        root.configure(bg=BG)
        root.lift()
        root.focus_force()
        if ICON_FILE:
            try:
                root.iconbitmap(ICON_FILE)
            except Exception:
                pass

        # Sabit başlık + buton satırı
        header = tk.Frame(root, bg=BG, padx=24, pady=20)
        header.pack(fill=tk.X)

        tk.Label(
            header, text="Claude Kullanım Detayları",
            bg=BG, fg=ACC, font=("Segoe UI", 14, "bold")
        ).pack(side=tk.LEFT)

        # Güncelle butonu — sağ üst
        status_lbl = tk.Label(header, text="", bg=BG, fg=FG2, font=("Segoe UI", 8))
        status_lbl.pack(side=tk.RIGHT, padx=(0, 4))

        def fmt_reset(iso):
            if not iso:
                return "—"
            try:
                dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                return dt.astimezone().strftime("%d.%m.%Y %H:%M")
            except:
                return iso[:19]

        # İçerik frame — silinip yeniden çizilir
        content_holder = tk.Frame(root, bg=BG)
        content_holder.pack(fill=tk.BOTH, expand=True, padx=24, pady=8)

        def render_content():
            for w in content_holder.winfo_children():
                w.destroy()

            if not self.usage_data:
                msg = "Veri bulunamadı."
                if not self.config.get("session_key") and not self.config.get("cookie_string"):
                    msg += "\nLütfen önce session key girin (Sağ tık → Ayarlar)"
                elif self.last_error:
                    msg += f"\nHata: {self.last_error}"
                tk.Label(content_holder, text=msg, bg=BG, fg="#f38ba8",
                         font=("Segoe UI", 11), justify="left").pack(anchor="w", pady=10)
                return

            d = self.usage_data
            fh_pct = d.get("five_hour_pct", 0)
            sd_pct = d.get("seven_day_pct", 0)

            def make_bar(parent, pct, label):
                tk.Label(parent, text=label, bg=BG, fg=FG2,
                         font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 1))
                c = tk.Canvas(parent, bg=BG2, height=28, highlightthickness=0)
                c.pack(fill=tk.X)
                def draw(event=None, p=pct, cv=c):
                    cv.delete("all")
                    w = cv.winfo_width() or 360
                    h = 28
                    fw = max(0, int(w * p / 100))
                    color = "#a6e3a1" if p < 50 else ("#fab387" if p < 75 else "#f38ba8")
                    cv.create_rectangle(0, 0, w, h, fill=BG2, outline="")
                    if fw > 0:
                        cv.create_rectangle(0, 0, fw, h, fill=color, outline="")
                    cv.create_text(w // 2, h // 2, text=f"%{p}",
                                   fill="#1e1e2e" if fw > w // 2 else FG,
                                   font=("Segoe UI", 11, "bold"))
                c.bind("<Configure>", draw)
                root.after(60, draw)

            make_bar(content_holder, fh_pct, "5 Saatlik Pencere")
            make_bar(content_holder, sd_pct, "7 Günlük Pencere")

            rows = [
                ("5 Saat Sıfırlanma", fmt_reset(d.get("five_hour_reset"))),
                ("7 Gün Sıfırlanma",  fmt_reset(d.get("seven_day_reset"))),
                ("Son Güncelleme",    self.last_updated.strftime("%H:%M:%S") if self.last_updated else "—"),
                ("Bildirim Eşiği",    f"%{self.config.get('notify_threshold', 75)}"),
            ]
            for key in ("seven_day_opus", "seven_day_sonnet", "seven_day_omelette"):
                if key in d:
                    lbl = key.replace("seven_day_", "7G ").title()
                    rows.insert(2, (lbl, f"%{d[key]}"))

            tk.Frame(content_holder, bg=BG2, height=1).pack(fill=tk.X, pady=8)
            for lbl, val in rows:
                row = tk.Frame(content_holder, bg=BG)
                row.pack(fill=tk.X, pady=2)
                tk.Label(row, text=f"{lbl}:", bg=BG, fg=FG2,
                         font=("Segoe UI", 10), width=20, anchor="w").pack(side=tk.LEFT)
                tk.Label(row, text=val, bg=BG, fg=FG,
                         font=("Segoe UI", 10, "bold"), anchor="w").pack(side=tk.LEFT)

            if self.last_updated:
                status_lbl.config(text=f"Son: {self.last_updated.strftime('%H:%M:%S')}")

        render_content()

        # Alt buton çubuğu
        tk.Frame(root, bg=BG2, height=1).pack(fill=tk.X)
        btn_bar = tk.Frame(root, bg=BG, padx=24, pady=10)
        btn_bar.pack(fill=tk.X)

        refreshing = {"active": False}

        def do_refresh():
            if refreshing["active"]:
                return
            refreshing["active"] = True
            refresh_btn.config(text="Güncelleniyor...", state="disabled")

            def _refresh():
                self._do_refresh()
                root.after(0, lambda: (
                    render_content(),
                    refresh_btn.config(text="↻  Güncelle", state="normal"),
                    refreshing.update({"active": False})
                ))

            threading.Thread(target=_refresh, daemon=True).start()

        refresh_btn = tk.Button(
            btn_bar, text="↻  Güncelle", command=do_refresh,
            bg="#89b4fa", fg=BG, font=("Segoe UI", 10, "bold"),
            relief="flat", padx=14, pady=4, cursor="hand2"
        )
        refresh_btn.pack(side=tk.RIGHT)

        tk.Button(
            btn_bar, text="Kapat", command=root.destroy,
            bg=BG2, fg=FG, font=("Segoe UI", 10),
            relief="flat", padx=14, pady=4, cursor="hand2"
        ).pack(side=tk.RIGHT, padx=(0, 6))

        root.mainloop()

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
