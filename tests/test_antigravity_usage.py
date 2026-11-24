import json
import os
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from antigravity_usage import AntigravityUsage


def sample_raw(
    five_rem=0.872,
    weekly_rem=0.721,
    five_reset="2026-11-24T13:41:00Z",
    weekly_reset="2026-11-30T21:04:23Z",
    plan="Google AI Pro",
    prompt_credits=500,
    flow_credits=100,
    email="secret.user@example.com",
):
    five_bucket = {"window": "5h", "resetTime": five_reset}
    if five_rem is not None:
        five_bucket["remainingFraction"] = five_rem
    weekly_bucket = {"window": "weekly", "resetTime": weekly_reset}
    if weekly_rem is not None:
        weekly_bucket["remainingFraction"] = weekly_rem
    return {
        "summary": {
            "response": {
                "groups": [
                    {
                        "displayName": "Other Group",
                        "description": "Models within this group: Claude Opus",
                        "buckets": [{"window": "5h", "remainingFraction": 0.5}],
                    },
                    {
                        "displayName": "Gemini Pro",
                        "description": "Models within this group: Gemini 4 Hydrogen, Gemini 3.8 Flash.",
                        "buckets": [five_bucket, weekly_bucket],
                    },
                ]
            }
        },
        "status": {
            "userStatus": {
                "email": email,
                "name": "Secret Name",
                "userTier": {"name": plan},
                "planStatus": {
                    "planInfo": {"planName": "Fallback Plan"},
                    "availablePromptCredits": prompt_credits,
                    "availableFlowCredits": flow_credits,
                },
            }
        },
    }


class AntigravityUsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.path.dirname(__file__))
        self.addCleanup(self.tmp.cleanup)
        self.daemon_dir = Path(self.tmp.name)

    def _write_hub(self, name, payload, mtime=None):
        path = self.daemon_dir / name
        if isinstance(payload, str):
            path.write_text(payload, encoding="utf-8")
        else:
            path.write_text(json.dumps(payload), encoding="utf-8")
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def test_read_hub_candidates_orders_newest_first_and_filters_invalid(self):
        now = time.time()
        self._write_hub("hub_1.json", {"httpPort": 50001, "csrfToken": "tok-old"}, now - 100)
        self._write_hub("hub_2.json", {"httpPort": 50002, "csrfToken": "tok-new"}, now - 10)
        self._write_hub("hub_bad_bool.json", {"httpPort": True, "csrfToken": "tok"})
        self._write_hub("hub_bad_port.json", {"httpPort": 70000, "csrfToken": "tok"})
        self._write_hub("hub_bad_csrf.json", {"httpPort": 50003, "csrfToken": "   "})
        self._write_hub("hub_corrupt.json", "{not-json")
        self._write_hub("hub_huge.json", " " * 5000)

        reader = AntigravityUsage(daemon_dir=str(self.daemon_dir))
        candidates = reader._read_hub_candidates()
        self.assertEqual([c["port"] for c in candidates], [50002, 50001])

    def test_fetch_falls_back_across_closed_hubs_and_returns_ide_closed(self):
        now = time.time()
        self._write_hub("hub_1.json", {"httpPort": 50001, "csrfToken": "secret-csrf-1"}, now - 50)
        self._write_hub("hub_2.json", {"httpPort": 50002, "csrfToken": "secret-csrf-2"}, now - 10)

        calls = []

        def poster(port, csrf, timeout):
            calls.append(port)
            if port == 50002:
                raise ConnectionRefusedError("closed")
            return sample_raw()

        logs = []
        reader = AntigravityUsage(daemon_dir=str(self.daemon_dir), log=logs.append, poster=poster)
        raw = reader.fetch()
        self.assertEqual(calls, [50002, 50001])
        self.assertNotIn("_error", raw)
        joined_logs = "\n".join(logs)
        self.assertNotIn("secret-csrf", joined_logs)

        # All hubs closed -> ide_closed
        def all_closed(port, csrf, timeout):
            raise ConnectionRefusedError("closed")

        reader2 = AntigravityUsage(daemon_dir=str(self.daemon_dir), poster=all_closed)
        self.assertEqual(reader2.fetch(), {"_error": "ide_closed"})

    def test_fetch_maps_http_and_json_errors(self):
        self._write_hub("hub_1.json", {"httpPort": 50010, "csrfToken": "tok"})

        def http_err(port, csrf, timeout):
            raise urllib.error.HTTPError("http://127.0.0.1:50010", 500, "err", {}, None)

        reader = AntigravityUsage(daemon_dir=str(self.daemon_dir), poster=http_err)
        self.assertEqual(reader.fetch(), {"_error": "no_response"})

        def bad_json(port, csrf, timeout):
            raise ValueError("bad json")

        reader2 = AntigravityUsage(daemon_dir=str(self.daemon_dir), poster=bad_json)
        self.assertEqual(reader2.fetch(), {"_error": "invalid_response"})

    def test_post_status_uses_loopback_and_disables_proxy(self):
        captured = []

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit=-1):
                return json.dumps(self._payload).encode("utf-8")

        class FakeOpener:
            def open(self, req, timeout=None):
                captured.append((req.full_url, dict(req.header_items()), timeout))
                if req.full_url.endswith("RetrieveUserQuotaSummary"):
                    return FakeResp(sample_raw()["summary"])
                return FakeResp(sample_raw()["status"])

        with patch("urllib.request.ProxyHandler") as mock_proxy, patch(
            "urllib.request.build_opener", return_value=FakeOpener()
        ):
            res = AntigravityUsage._post_status(51234, "csrf-xyz", 4.5)

        mock_proxy.assert_called_once_with({})
        self.assertEqual(len(captured), 2)
        for url, headers, timeout in captured:
            self.assertTrue(url.startswith("http://127.0.0.1:51234/exa.language_server_pb.LanguageServerService/"))
            self.assertEqual(headers.get("X-codeium-csrf-token"), "csrf-xyz")
            self.assertEqual(timeout, 4.5)
        self.assertIn("summary", res)
        self.assertIn("status", res)

    def test_parse_extracts_windows_plan_credits_and_omits_pii(self):
        parsed = AntigravityUsage.parse(sample_raw())
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["five_hour_pct"], 12.8)
        self.assertEqual(parsed["seven_day_pct"], 27.9)
        self.assertEqual(parsed["plan_type"], "Google AI Pro")
        self.assertEqual(parsed["credits_text"], "500 prompt · 100 flow")
        self.assertFalse(parsed["limit_reached"])
        self.assertIn("Gemini 4 Hydrogen", parsed["models"])
        dumped = json.dumps(parsed, ensure_ascii=False)
        self.assertNotIn("secret.user@example.com", dumped)
        self.assertNotIn("Secret Name", dumped)

    def test_parse_handles_omitted_zero_remaining_fraction_as_100_used(self):
        parsed = AntigravityUsage.parse(sample_raw(five_rem=None, weekly_rem=0.5))
        self.assertEqual(parsed["five_hour_pct"], 100.0)
        self.assertEqual(parsed["seven_day_pct"], 50.0)
        self.assertTrue(parsed["limit_reached"])

    def test_parse_rejects_missing_target_group_or_error_payload(self):
        self.assertIsNone(AntigravityUsage.parse({"_error": "ide_closed"}))
        self.assertIsNone(AntigravityUsage.parse({"summary": {"response": {"groups": []}}}))


if __name__ == "__main__":
    unittest.main()
