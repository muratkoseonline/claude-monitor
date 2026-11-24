import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import requests

from opencode_usage import CONSOLE_STATUS_URL, OpenCodeUsage, USAGE_URL


def payload():
    return {"usage": {
        name: {"status": "ok", "percent": percent, "resetsAt": "2026-10-16T12:00:00Z"}
        for name, percent in (("rolling", 12.5), ("weekly", 30), ("monthly", 51))
    }}


class ParseTests(unittest.TestCase):
    def test_all_three_quotas_and_utc_resets(self):
        parsed = OpenCodeUsage.parse(payload())
        self.assertEqual([parsed[k] for k in ("five_hour_pct", "seven_day_pct", "monthly_pct")], [12.5, 30, 51])
        self.assertEqual(parsed["monthly_reset"], "2026-10-16T12:00:00+00:00")
        self.assertFalse(parsed["limit_reached"])

    def test_zero_is_valid_and_limit_can_come_from_status_or_percentage(self):
        for percent, status in ((0, "ok"), (0, "rate-limited"), (105, "ok")):
            with self.subTest(percent=percent, status=status):
                raw = payload()
                raw["usage"]["rolling"].update(percent=percent, status=status)
                self.assertEqual(OpenCodeUsage.parse(raw)["limit_reached"], status == "rate-limited" or percent >= 100)

    def test_missing_or_malformed_windows_are_not_zero(self):
        invalid = [None, {}, [], {"_error": "auth"}]
        for name in ("rolling", "weekly", "monthly"):
            for field, value in (("percent", None), ("percent", "0"), ("percent", True),
                                 ("percent", float("nan")), ("percent", float("inf")),
                                 ("percent", -1), ("percent", 10 ** 400), ("resetsAt", None), ("resetsAt", "bad"),
                                 ("resetsAt", "2026-10-16T12:00:00"), ("status", "unknown")):
                raw = payload()
                raw["usage"][name][field] = value
                invalid.append(raw)
            raw = payload()
            del raw["usage"][name]
            invalid.append(raw)
            raw = payload()
            del raw["usage"][name]["percent"]
            invalid.append(raw)
        for raw in invalid:
            with self.subTest(raw=raw):
                self.assertIsNone(OpenCodeUsage.parse(raw))

    def test_previous_official_response_contract(self):
        before = datetime.now(timezone.utc).timestamp()
        raw = {name + "Usage": {"status": "ok", "usagePercent": percent, "resetInSec": 60}
               for name, percent in (("rolling", 10), ("weekly", 20), ("monthly", 30))}
        parsed = OpenCodeUsage.parse(raw)
        self.assertEqual(parsed["monthly_pct"], 30)
        self.assertAlmostEqual(datetime.fromisoformat(parsed["five_hour_reset"]).timestamp(), before + 60, delta=2)
        raw["monthlyUsage"]["resetInSec"] = None
        self.assertIsNone(OpenCodeUsage.parse(raw))


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.path.dirname(__file__))
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, "auth.json")
        self.db_path = os.path.join(self.temp.name, "opencode.db")
        db = sqlite3.connect(self.db_path)
        try:
            db.execute("""CREATE TABLE credential (
                id TEXT, integration_id TEXT, value TEXT, active INTEGER, time_updated INTEGER
            )""")
            db.commit()
        finally:
            db.close()
        self.write_auth({"opencode-go": {"type": "api", "key": "test-go-key"}})
        self.logs = []
        self.reader = OpenCodeUsage(self.path, self.logs.append, self.db_path)

    def write_auth(self, data):
        with open(self.path, "w", encoding="utf-8") as stream:
            json.dump(data, stream)

    def write_db_credential(self, integration, value, active=1):
        db = sqlite3.connect(self.db_path)
        try:
            db.execute("DELETE FROM credential WHERE integration_id = ?", (integration,))
            db.execute(
                "INSERT INTO credential (id, integration_id, value, active, time_updated) "
                "VALUES (?, ?, ?, ?, ?)",
                (integration, integration, json.dumps(value), active, 1),
            )
            db.commit()
        finally:
            db.close()

    @staticmethod
    def console_status():
        return {"access": {"meters": {
            name: {
                "usedMicroCents": used,
                "limitMicroCents": "1000000000",
                "resetsAt": "2026-10-25T12:00:00Z",
            }
            for name, used in (("fiveHour", "250000000"), ("week", "500000000"), ("month", "750000000"))
        }}}

    @patch("opencode_usage.requests.get")
    def test_account_oauth_reads_go_status_without_api_key(self, get):
        self.write_db_credential("opencode", {
            "type": "oauth", "access": "account-session-token", "refresh": "refresh",
            "expires": 1900000000,
            "metadata": {"server": "https://opencode.ai/console", "orgID": "wrk_test"},
        })
        get.return_value = Mock(status_code=200, json=Mock(return_value=self.console_status()))

        parsed = OpenCodeUsage.parse(self.reader.fetch())

        self.assertEqual(parsed["five_hour_pct"], 25)
        self.assertEqual(parsed["seven_day_pct"], 50)
        self.assertEqual(parsed["monthly_pct"], 75)
        args, kwargs = get.call_args
        self.assertEqual(args, (CONSOLE_STATUS_URL,))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer account-session-token")
        self.assertEqual(kwargs["headers"]["x-org-id"], "wrk_test")
        self.assertFalse(kwargs["allow_redirects"])
        self.assertNotIn("account-session-token", " ".join(self.logs))

    @patch("opencode_usage.requests.get")
    def test_account_session_is_only_sent_to_official_console(self, get):
        self.write_db_credential("opencode", {
            "type": "oauth", "access": "account-session-token", "refresh": "refresh",
            "expires": 1900000000,
            "metadata": {"server": "https://other.example/console", "orgID": "wrk_test"},
        })
        get.return_value = Mock(status_code=200, json=Mock(return_value=payload()))

        self.reader.fetch()

        args, _ = get.call_args
        self.assertEqual(args, (USAGE_URL,))

    @patch("opencode_usage.requests.get")
    def test_request_destination_auth_and_redirect_safety(self, get):
        get.return_value = Mock(status_code=200, json=Mock(return_value=payload()))
        self.assertEqual(self.reader.fetch(), payload())
        args, kwargs = get.call_args
        self.assertEqual(args, (USAGE_URL,))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-go-key")
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"], 15)
        self.assertNotIn("test-go-key", " ".join(self.logs))

    @patch("opencode_usage.requests.get")
    def test_status_errors_json_and_transport(self, get):
        for status, error in ((401, "auth"), (403, "no_subscription"), (429, "rate_limited"),
                              (302, "no_response"), (500, "no_response")):
            get.return_value = Mock(status_code=status)
            self.assertEqual(self.reader.fetch(), {"_error": error})
        for raw in (None, {}, {"usage": {}}):
            get.return_value = Mock(status_code=200, json=Mock(return_value=raw))
            self.assertEqual(self.reader.fetch(), {"_error": "invalid_response"})
        get.return_value = Mock(status_code=200, json=Mock(side_effect=ValueError("bad")))
        self.assertEqual(self.reader.fetch(), {"_error": "invalid_response"})
        get.side_effect = requests.ConnectionError("test-go-key")
        self.assertEqual(self.reader.fetch(), {"_error": "no_response"})
        self.assertNotIn("test-go-key", " ".join(self.logs))

    @patch("opencode_usage.requests.get")
    def test_auth_precedence_fallback_and_reload(self, get):
        get.return_value = Mock(status_code=200, json=Mock(return_value=payload()))
        self.write_auth({"opencode-go": {"type": "api", "key": "go"}, "opencode": {"type": "api", "key": "zen"}})
        self.reader.fetch()
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer go")
        self.write_auth({"opencode": {"type": "api", "key": "zen"}})
        self.reader.fetch()
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer zen")
        for auth in ([], {}, {"opencode-go": {"type": "oauth", "key": "x"}},
                     {"opencode-go": {"type": "api", "key": "bad\nkey"}}):
            self.write_auth(auth)
            get.reset_mock()
            self.assertEqual(self.reader.fetch(), {"_error": "no_auth"})
            get.assert_not_called()
        os.remove(self.path)
        self.assertEqual(self.reader.fetch(), {"_error": "no_auth"})
        with open(self.path, "w", encoding="utf-8") as stream:
            stream.write("{broken")
        self.assertEqual(self.reader.fetch(), {"_error": "no_auth"})

    @patch("opencode_usage.requests.get")
    def test_rejected_go_key_falls_back_to_opencode_key(self, get):
        self.write_auth({
            "opencode-go": {"type": "api", "key": "stale-go-key"},
            "opencode": {"type": "api", "key": "active-key"},
        })
        get.side_effect = [Mock(status_code=401), Mock(status_code=200, json=Mock(return_value=payload()))]

        self.assertEqual(self.reader.fetch(), payload())
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].kwargs["headers"]["Authorization"], "Bearer stale-go-key")
        self.assertEqual(get.call_args_list[1].kwargs["headers"]["Authorization"], "Bearer active-key")

    @patch("opencode_usage.requests.get")
    def test_all_rejected_keys_report_auth_error(self, get):
        self.write_auth({
            "opencode-go": {"type": "api", "key": "stale-go-key"},
            "opencode": {"type": "api", "key": "stale-key"},
        })
        get.side_effect = [Mock(status_code=401), Mock(status_code=401)]

        self.assertEqual(self.reader.fetch(), {"_error": "auth"})
        self.assertEqual(get.call_count, 2)

    def test_xdg_data_home(self):
        with patch.dict(os.environ, {"XDG_DATA_HOME": self.temp.name}):
            self.assertEqual(OpenCodeUsage().auth_path, os.path.join(self.temp.name, "opencode", "auth.json"))


if __name__ == "__main__":
    unittest.main()
