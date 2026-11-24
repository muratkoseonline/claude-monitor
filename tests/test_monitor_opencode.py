import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import claude_monitor as app


def usage(five=20, weekly=40, monthly=60):
    return {"usage": {key: {"percent": pct, "resetsAt": "2026-10-16T12:00:00Z", "status": "ok"}
                      for key, pct in (("rolling", five), ("weekly", weekly), ("monthly", monthly))}}


class MonitorOpenCodeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=os.path.dirname(__file__))
        self.addCleanup(self.directory.cleanup)
        for name, value in (("CONFIG_DIR", self.directory.name),
                            ("CONFIG_FILE", self.directory.name + "/config.json"),
                            ("LOG_FILE", self.directory.name + "/monitor.log")):
            patcher = patch.object(app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.monitor = app.ClaudeMonitor()
        self.monitor.send_notification = Mock()
        self.monitor.opencode.fetch = Mock(return_value=usage())

    def test_all_windows_notify_once_and_rearm_after_reset(self):
        m = self.monitor
        m.opencode.fetch.return_value = usage(80, 85, 90)
        m._refresh_opencode()
        m._refresh_opencode()
        self.assertEqual(m.send_notification.call_count, 3)
        m.opencode.fetch.return_value = usage(0, 10, 20)
        m._refresh_opencode()
        m.opencode.fetch.return_value = usage(80, 85, 90)
        m._refresh_opencode()
        self.assertEqual(m.send_notification.call_count, 6)

    def test_failure_preserves_last_sample_and_success_clears_error(self):
        m = self.monitor
        m._refresh_opencode()
        previous = m.opencode_data.copy()
        updated = m.opencode_updated
        m.opencode.fetch.return_value = {"_error": "auth"}
        m._refresh_opencode()
        self.assertEqual(m.opencode_data, previous)
        self.assertEqual(m.opencode_updated, updated)
        self.assertIsNotNone(m.opencode_error)
        self.assertIn("Go: HATA", m.build_tooltip())
        m.opencode.fetch.return_value = usage()
        m._refresh_opencode()
        self.assertIsNone(m.opencode_error)

    def test_new_period_notifies_even_when_low_sample_was_missed(self):
        m = self.monitor
        m.opencode.fetch.return_value = usage(80, 0, 0)
        m._refresh_opencode()
        raw = usage(85, 0, 0)
        raw["usage"]["rolling"]["resetsAt"] = "2026-10-16T17:00:00Z"
        m.opencode.fetch.return_value = raw
        m._refresh_opencode()
        self.assertEqual(m.send_notification.call_count, 2)

    def test_disabled_provider_does_not_read_credentials(self):
        m = self.monitor
        m.config["opencode_enabled"] = False
        m._refresh_opencode()
        m.opencode.fetch.assert_not_called()
        self.assertNotIn("Go", m.build_tooltip())

    def test_go_refreshes_without_claude_key(self):
        m = self.monitor
        m.config["codex_enabled"] = False
        m._do_refresh()
        self.assertEqual(m.opencode_data["monthly_pct"], 60)
        self.assertIsInstance(m.opencode_updated, datetime)

    def test_tooltip_fits_windows_and_includes_monthly_limit(self):
        m = self.monitor
        m.config["session_key"] = "test"
        m.usage_data = {"five_hour_pct": 100, "seven_day_pct": 100}
        m.codex_data = {"five_hour_pct": 100, "seven_day_pct": 100}
        m.opencode.fetch.return_value = usage(100, 100, 100)
        m._refresh_opencode()
        text = m.build_tooltip()
        self.assertLessEqual(len(text), 127)
        self.assertIn("ay %100", text)


if __name__ == "__main__":
    unittest.main()
