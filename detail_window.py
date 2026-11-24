"""Compact, 2x2 grid presentation of the monitor's four-provider usage state."""

import threading
import tkinter as tk
from datetime import datetime


BG = "#19191c"
CARD = "#252529"
TRACK = "#39393f"
TEXT = "#f0f0f2"
MUTED = "#94949f"
GREEN = "#40d878"
AMBER = "#eeb55c"
RED = "#ff626b"
FONT = "Segoe UI"


def open_usage_window(monitor, icon_file=None):
    root = tk.Tk()
    root.title("Claude Monitor - Kullanım Detayları")
    root.geometry("820x780")
    root.minsize(740, 700)
    root.configure(bg=BG)
    if icon_file:
        try:
            root.iconbitmap(icon_file)
        except tk.TclError:
            pass

    def label(parent, text, size=9, color=TEXT, bold=False, **kwargs):
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color,
                        font=(FONT, size, "bold" if bold else "normal"), **kwargs)

    def button(parent, text, command, primary=False):
        base, hover = ("#333b35", "#414f44") if primary else (CARD, "#333338")
        widget = tk.Button(parent, text=text, command=command, bg=base, fg=TEXT,
                           activebackground=hover, activeforeground=TEXT,
                           font=(FONT, 9), relief="flat", bd=0, padx=13, pady=6,
                           cursor="hand2", highlightthickness=1,
                           highlightbackground=TRACK, highlightcolor=GREEN)
        widget.bind("<Enter>", lambda e: widget.configure(bg=hover))
        widget.bind("<Leave>", lambda e: widget.configure(bg=base))
        return widget

    header = tk.Frame(root, bg=BG, padx=18, pady=12)
    header.pack(fill=tk.X)
    label(header, "Kullanım paneli", 13, bold=True).pack(side=tk.LEFT)
    label(header, "Claude Monitor", 9, MUTED).pack(side=tk.RIGHT)
    tk.Frame(root, bg=TRACK, height=1).pack(fill=tk.X, padx=18)

    body = tk.Frame(root, bg=BG, padx=12, pady=10)
    for col in range(2):
        body.columnconfigure(col, weight=1, uniform="provider")
    for row in range(2):
        body.rowconfigure(row, weight=1)

    footer = tk.Frame(root, bg=BG, padx=18, pady=10)
    footer.pack(fill=tk.X, side=tk.BOTTOM)
    body.pack(fill=tk.BOTH, expand=True)
    label(footer, "Çubuklar kullanılan kotayı gösterir.", 8, MUTED).pack(side=tk.LEFT)
    button(footer, "Kapat", root.destroy).pack(side=tk.RIGHT)
    busy = threading.Event()

    def refresh():
        if busy.is_set():
            return
        busy.set()
        refresh_button.configure(text="Güncelleniyor…", state="disabled")

        def worker():
            try:
                monitor._do_refresh()
            finally:
                busy.clear()

        threading.Thread(target=worker, daemon=True).start()

    refresh_button = button(footer, "↻  Güncelle", refresh, primary=True)
    refresh_button.pack(side=tk.RIGHT, padx=(0, 8))

    def fmt_reset(value):
        if not value:
            return "Sıfırlanma bilgisi yok"
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
            return "Sıfırlanma · " + dt.strftime("%d.%m · %H:%M")
        except (TypeError, ValueError):
            return "Sıfırlanma · " + str(value)[:19]

    def card(parent):
        frame = tk.Frame(parent, bg=CARD, padx=10, pady=8)
        frame.pack(fill=tk.X, pady=(0, 6))
        return frame

    def quota(parent, title, pct, reset):
        frame = card(parent)
        color = GREEN if pct < 50 else AMBER if pct < 75 else RED
        top = tk.Frame(frame, bg=CARD)
        top.pack(fill=tk.X)
        label(top, title, 9, bold=True).pack(side=tk.LEFT)
        label(top, f"%{pct:g}", 10, color, bold=True).pack(side=tk.RIGHT)
        bar = tk.Canvas(frame, height=6, bg=TRACK, highlightthickness=0)
        bar.pack(fill=tk.X, pady=(6, 5))

        def draw(event):
            bar.delete("all")
            bar.create_rectangle(0, 0, event.width * max(0, min(100, pct)) / 100,
                                 6, fill=color, outline="")

        bar.bind("<Configure>", draw)
        bottom = tk.Frame(frame, bg=CARD)
        bottom.pack(fill=tk.X)
        label(bottom, fmt_reset(reset), 8, MUTED).pack(side=tk.LEFT)
        label(
            bottom,
            "Limit doldu" if pct >= 100 else f"%{max(0, round(100 - pct, 1)):g} kaldı",
            8,
            color if pct >= 100 else MUTED,
        ).pack(side=tk.RIGHT)

    def metadata(parent, title, rows):
        frame = card(parent)
        label(frame, title, 9, bold=True).pack(anchor="w", pady=(0, 4))
        for key, value in rows:
            row = tk.Frame(frame, bg=CARD)
            row.pack(fill=tk.X, pady=1)
            label(row, key, 8, MUTED).pack(side=tk.LEFT)
            label(row, value, 8).pack(side=tk.RIGHT)

    def render():
        for child in body.winfo_children():
            child.destroy()
        providers = (
            ("Claude", "ANTHROPIC", monitor.usage_data, monitor.last_error, monitor.last_updated, True),
            ("Codex", "OPENAI", monitor.codex_data, monitor.codex_error, monitor.codex_updated,
             monitor.config.get("codex_enabled")),
            ("OpenCode Go", "OPENCODE", monitor.opencode_data, monitor.opencode_error,
             monitor.opencode_updated, monitor.config.get("opencode_enabled")),
            ("Antigravity", "GOOGLE", monitor.antigravity_data, monitor.antigravity_error,
             monitor.antigravity_updated, monitor.config.get("antigravity_enabled")),
        )
        for index, (name, subtitle, data, error, updated, enabled) in enumerate(providers):
            row_idx, col_idx = divmod(index, 2)
            column = tk.Frame(body, bg=BG, padx=8, pady=4, name=f"provider_{index}")
            column.grid(row=row_idx, column=col_idx, sticky="nsew")
            title = tk.Frame(column, bg=BG)
            title.pack(fill=tk.X, pady=(0, 7))
            label(title, name, 11, bold=True).pack(side=tk.LEFT)
            label(title, subtitle, 7, MUTED).pack(side=tk.RIGHT)
            if not enabled:
                message = card(column)
                label(message, "Takip kapalı", 9, MUTED).pack(anchor="w")
                label(message, "Ayarlar menüsünden açabilirsiniz.", 8, MUTED).pack(anchor="w", pady=(4, 0))
                continue
            if not data:
                message = card(column)
                text = error or ("Session key girin · Sağ tık → Ayarlar" if index == 0 and not (
                    monitor.config.get("session_key") or monitor.config.get("cookie_string")) else "Kullanım verisi bekleniyor…")
                label(message, "Veri alınamadı" if error else "Bağlantı bekleniyor", 9, RED if error else MUTED,
                      bold=True).pack(anchor="w")
                label(message, text, 8, MUTED, wraplength=320, justify="left").pack(anchor="w", pady=(6, 0))
                continue
            if index == 3:
                if data.get("five_hour_pct") is not None:
                    quota(column, "5 saatlik oturum", data["five_hour_pct"], data.get("five_hour_reset"))
                if data.get("seven_day_pct") is not None:
                    quota(column, "Haftalık limit", data["seven_day_pct"], data.get("seven_day_reset"))
                rows = [("Plan", data.get("plan_type") or "—")]
                if data.get("credits_text"):
                    rows.append(("Kredi", data["credits_text"]))
                rows.append(("Durum", "Limit doldu" if data.get("limit_reached") else "Kullanılabilir"))
                metadata(column, "Abonelik", rows)
            else:
                quota(column, "5 saatlik oturum", data.get("five_hour_pct", 0), data.get("five_hour_reset"))
                quota(column, "Haftalık limit", data.get("seven_day_pct", 0), data.get("seven_day_reset"))
                if index == 2:
                    quota(column, "Aylık limit", data["monthly_pct"], data.get("monthly_reset"))
                elif index == 0:
                    rows = [(key.removeprefix("seven_day_").title(), f"%{data[key]:g}")
                            for key in ("seven_day_opus", "seven_day_sonnet", "seven_day_omelette") if key in data]
                    metadata(column, "Model limitleri", rows or [("Ek model limiti", "—")])
                else:
                    metadata(column, "Abonelik", [("Plan", (data.get("plan_type") or "—").upper()),
                                                 ("Durum", "Limit doldu" if data.get("limit_reached") else "Kullanılabilir")])
            if error:
                label(column, "Güncel değil · " + error, 8, RED, wraplength=320,
                      justify="left").pack(anchor="w", pady=(0, 4))
            label(column, "Son ölçüm · " + (updated.strftime("%d.%m · %H:%M:%S") if updated else "—"),
                  8, MUTED).pack(anchor="w", pady=(1, 0))
        root.update_idletasks()
        required_height = header.winfo_reqheight() + body.winfo_reqheight() + footer.winfo_reqheight() + 4
        max_h = max(700, root.winfo_screenheight() - 80)
        target_h = min(max(700, required_height), max_h)
        root.minsize(740, target_h)
        if root.winfo_height() < target_h:
            root.geometry(f"{max(820, root.winfo_width())}x{target_h}")

    previous = [None]
    timer = [None]

    def tick():
        # Yalnız sunumu yeniler; veri toplama ve kota hesapları monitöre aittir.
        state = repr((
            monitor.usage_data, monitor.codex_data, monitor.opencode_data, monitor.antigravity_data,
            monitor.last_error, monitor.codex_error, monitor.opencode_error, monitor.antigravity_error,
            monitor.last_updated, monitor.codex_updated, monitor.opencode_updated, monitor.antigravity_updated,
            monitor.config.get("codex_enabled"), monitor.config.get("opencode_enabled"),
            monitor.config.get("antigravity_enabled"),
        ))
        if state != previous[0]:
            render()
            previous[0] = state
        if not busy.is_set():
            refresh_button.configure(text="↻  Güncelle", state="normal")
        timer[0] = root.after(350, tick)

    def cleanup(event):
        if event.widget is root and timer[0] is not None:
            root.after_cancel(timer[0])
            timer[0] = None

    root.bind("<Destroy>", cleanup)
    root.bind("<Escape>", lambda event: root.destroy())
    root.bind("<F5>", lambda event: refresh())
    tick()
    root.lift()
    root.focus_force()
    root.mainloop()
