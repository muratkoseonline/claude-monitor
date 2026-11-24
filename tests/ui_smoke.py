"""Render actual Tk windows with synthetic quotas, without reading real config.

Run from the repository: python tests/ui_smoke.py
"""
import os
import sys
import tempfile
import tkinter as tk
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import claude_monitor as app


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
    with patch.object(app, "CONFIG_DIR", directory), patch.object(app, "CONFIG_FILE", directory + "/config.json"):
        monitor = app.ClaudeMonitor()
    monitor.usage_data = {"five_hour_pct": 25, "seven_day_pct": 60, "seven_day_opus": 35}
    monitor.codex_data = {"five_hour_pct": 40, "seven_day_pct": 80, "plan_type": "plus"}
    monitor.opencode_data = {
        "five_hour_pct": 56, "seven_day_pct": 100, "monthly_pct": 57,
        "five_hour_reset": "2026-10-15T11:00:44Z",
        "seven_day_reset": "2026-10-19T00:00:00Z",
        "monthly_reset": "2026-11-03T12:26:51Z", "limit_reached": True,
    }
    monitor.antigravity_data = {
        "percent": 12.8,
        "five_hour_pct": 12.8,
        "seven_day_pct": 27.9,
        "five_hour_reset": "2026-11-24T13:41:00Z",
        "seven_day_reset": "2026-11-30T21:04:23Z",
        "plan_type": "Google AI Pro",
        "credits_text": "500 prompt · 100 flow",
        "limit_reached": False,
    }
    monitor.opencode_updated = datetime.now()
    monitor.antigravity_updated = datetime.now()
    errors = []
    variant = ["normal"]

    def check_window(root, *args, **kwargs):
        try:
            root.update()
            widgets = list(descendants(root))
            text = [str(w.cget("text")) for w in widgets if isinstance(w, (tk.Label, tk.Button, tk.Checkbutton))]
            settings = "Ayarlar" in root.title()
            expected = (
                ["Kaydet", "OpenCode Go limitlerini izle", "Antigravity (Google) kotasını izle"]
                if settings
                else ["Claude", "Codex", "OpenCode Go", "Antigravity"]
            )
            if not settings and variant[0] != "disabled":
                expected.extend(["Aylık limit", "Google AI Pro", "500 prompt · 100 flow"])
            for label in expected:
                assert label in text, (label, text)
            for widget in widgets:
                if isinstance(widget, tk.Button):
                    assert widget.winfo_height() > 5, widget.cget("text")
                    assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height(), widget.cget("text")
            if not settings:
                columns = [w for w in widgets if w.winfo_name().startswith("provider_")]
                assert len(columns) == 4, len(columns)
                assert len({w.winfo_rootx() for w in columns}) == 2, {w.winfo_rootx() for w in columns}
                assert len({w.winfo_rooty() for w in columns}) == 2, {w.winfo_rooty() for w in columns}
                assert len([w for w in widgets if isinstance(w, tk.Canvas)]) == (2 if variant[0] == "disabled" else 9)
                if variant[0] == "stale":
                    assert any("Güncel değil" in value for value in text)
                if variant[0] == "disabled":
                    assert "Takip kapalı" in text
                for widget in widgets:
                    if isinstance(widget, tk.Label):
                        assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height(), widget.cget("text")
                if "--snapshot" in sys.argv and variant[0] == "normal":
                    from PIL import ImageGrab
                    ImageGrab.grab(bbox=(root.winfo_rootx(), root.winfo_rooty(),
                                        root.winfo_rootx() + root.winfo_width(),
                                        root.winfo_rooty() + root.winfo_height())).save(
                                            os.path.join(os.path.dirname(__file__), "..", "docs", "usage-panel-preview.png"))
            print(root.title() + ": layout OK")
        except Exception as error:
            errors.append(error)
        finally:
            root.destroy()

    with patch.object(tk.Tk, "mainloop", check_window):
        monitor.open_detail_window()
        monitor.open_settings()
        variant[0] = "stale"
        monitor.opencode_error = "OpenCode kullanım API'sine erişilemiyor. Son başarılı ölçüm gösteriliyor."
        monitor.antigravity_error = "Antigravity IDE açık değil; IDE açılınca kota okunur."
        monitor.open_detail_window()
        variant[0] = "disabled"
        monitor.config["opencode_enabled"] = False
        monitor.config["codex_enabled"] = False
        monitor.config["antigravity_enabled"] = False
        monitor.open_detail_window()
    if errors:
        raise AssertionError(errors)
