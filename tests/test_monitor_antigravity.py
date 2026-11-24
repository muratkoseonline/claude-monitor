import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import claude_monitor as app
from generate_icon import make_tray_icon


def ag_raw(five_used=20.0, weekly_used=35.0, five_reset="2026-11-24T15:00:00Z", weekly_reset="2026-11-30T21:00:00Z"):
    return {
        "summary": {
            "response": {
                "groups": [
                    {
                        "displayName": "Gemini Pro",
                        "description": "Models within this group: Gemini 4 Hydrogen, Gemini 3.8 Flash.",
                        "buckets": [
                            {
                                "window": "5h",
                                "remainingFraction": max(0.0, (100.0 - five_used) / 100.0),
                                "resetTime": five_reset,
                            },
                            {
                                "window": "weekly",
                                "remainingFraction": max(0.0, (100.0 - weekly_used) / 100.0),
                                "resetTime": weekly_reset,
                            },
                        ],
                    }
                ]
            }
        },
        "status": {
            "userStatus": {
                "email": "private@example.com",
                "userTier": {"name": "Google AI Pro"},
                "planStatus": {
                    "availablePromptCredits": 500,
                    "availableFlowCredits": 100,
                },
            }
        },
    }


class MonitorAntigravityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=os.path.dirname(__file__))
        self.addCleanup(self.directory.cleanup)
        for name, value in (
            ("CONFIG_DIR", self.directory.name),
            ("CONFIG_FILE", os.path.join(self.directory.name, "config.json")),
            ("LOG_FILE", os.path.join(self.directory.name, "monitor.log")),
        ):
            patcher = patch.object(app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        snap_patch = patch.object(
            app.ClaudeMonitor,
            "SNAPSHOT_FILE",
            os.path.join(self.directory.name, "usage-snapshot.json"),
        )
        snap_patch.start()
        self.addCleanup(snap_patch.stop)
        self.monitor = app.ClaudeMonitor()
        self.monitor.send_notification = Mock()
        self.monitor.antigravity.fetch = Mock(return_value=ag_raw())
        self.monitor.opencode.fetch = Mock(return_value={"_error": "no_auth"})
        self.monitor.codex.fetch = Mock(return_value={"_error": "no_auth"})

    def test_windows_notify_once_and_rearm_on_drop_or_new_period(self):
        m = self.monitor
        m.antigravity.fetch.return_value = ag_raw(80.0, 85.0)
        m._refresh_antigravity()
        m._refresh_antigravity()
        self.assertEqual(m.send_notification.call_count, 2)

        # New 5h reset period re-arms even without an intermediate low sample.
        m.antigravity.fetch.return_value = ag_raw(82.0, 85.0, five_reset="2026-11-24T20:00:00Z")
        m._refresh_antigravity()
        self.assertEqual(m.send_notification.call_count, 3)

        # Drop below threshold then rise again -> notifies both.
        m.antigravity.fetch.return_value = ag_raw(10.0, 10.0, five_reset="2026-11-24T20:00:00Z")
        m._refresh_antigravity()
        m.antigravity.fetch.return_value = ag_raw(90.0, 90.0, five_reset="2026-11-24T20:00:00Z")
        m._refresh_antigravity()
        self.assertEqual(m.send_notification.call_count, 5)

    def test_ide_closed_preserves_last_sample_and_marks_stale(self):
        m = self.monitor
        m._refresh_antigravity()
        previous = m.antigravity_data.copy()
        updated = m.antigravity_updated
        self.assertEqual(previous["five_hour_pct"], 20.0)
        self.assertEqual(previous["plan_type"], "Google AI Pro")

        m.antigravity.fetch.return_value = {"_error": "ide_closed"}
        m._refresh_antigravity()
        self.assertEqual(m.antigravity_data, previous)
        self.assertEqual(m.antigravity_updated, updated)
        self.assertIn("açık değil", m.antigravity_error)
        self.assertIn("AG 5s %20|7g %35*", m.build_tooltip())

        m.antigravity.fetch.return_value = ag_raw(25.0, 40.0)
        m._refresh_antigravity()
        self.assertIsNone(m.antigravity_error)
        self.assertEqual(m.antigravity_data["five_hour_pct"], 25.0)

    def test_disabled_antigravity_never_fetches_or_appears_in_tooltip(self):
        m = self.monitor
        m.config["antigravity_enabled"] = False
        m._refresh_antigravity()
        m.antigravity.fetch.assert_not_called()
        self.assertNotIn("AG", m.build_tooltip())

    def test_antigravity_refreshes_without_claude_key_and_writes_clean_snapshot(self):
        m = self.monitor
        m.config["codex_enabled"] = False
        m.config["opencode_enabled"] = False
        m._do_refresh()
        self.assertEqual(m.antigravity_data["seven_day_pct"], 35.0)
        self.assertIsInstance(m.antigravity_updated, datetime)

        snap_path = app.ClaudeMonitor.SNAPSHOT_FILE
        self.assertTrue(os.path.isfile(snap_path))
        with open(snap_path, encoding="utf-8") as f:
            snap_text = f.read()
        self.assertNotIn("private@example.com", snap_text)
        snap = json.loads(snap_text)
        self.assertEqual(snap["antigravity"]["five_hour_pct"], 20.0)
        self.assertEqual(snap["antigravity"]["seven_day_pct"], 35.0)

    def test_tooltip_fits_127_chars_with_all_four_providers_at_100_percent(self):
        m = self.monitor
        m.config["session_key"] = "test"
        m.usage_data = {"five_hour_pct": 100, "seven_day_pct": 100}
        m.codex_data = {"five_hour_pct": 100, "seven_day_pct": 100}
        m.opencode_data = {"five_hour_pct": 100, "seven_day_pct": 100, "monthly_pct": 100}
        m.antigravity_data = {"five_hour_pct": 100, "seven_day_pct": 100}
        text = m.build_tooltip()
        self.assertLessEqual(len(text), 127)
        for token in ("CL ", "CX ", "Go ", "AG "):
            self.assertIn(token, text)

    def test_quadrant_tray_icon_renders_all_four_providers(self):
        img = make_tray_icon(
            64, 25, codex_percent=60, opencode_percent=85, antigravity_percent=40
        )
        self.assertEqual(img.size, (64, 64))
        self.assertEqual(img.mode, "RGBA")
        # Each quadrant should contain colored arc pixels (green/orange/red).
        px = img.load()
        # Top-right (Claude 25% -> green), Bottom-right (Codex 60% -> orange),
        # Bottom-left (OpenCode 85% -> red), Top-left (Antigravity 40% -> green)
        def has_color(xs, ys, predicate):
            return any(predicate(px[x, y]) for x in xs for y in ys)

        is_green = lambda c: c[1] > 180 and c[0] < 140
        is_orange = lambda c: c[0] > 200 and 130 < c[1] < 210
        is_red = lambda c: c[0] > 200 and c[1] < 110
        self.assertTrue(has_color(range(32, 62), range(2, 32), is_green))
        self.assertTrue(has_color(range(32, 62), range(32, 62), is_orange))
        self.assertTrue(has_color(range(2, 32), range(32, 62), is_red))
        self.assertTrue(has_color(range(2, 32), range(2, 32), is_green))


if __name__ == "__main__":
    unittest.main()
