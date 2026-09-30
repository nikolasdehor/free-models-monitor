import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from free_models_monitor import monitor

INFO = {"name": "A", "context_length": 100000}


class PartialTests(unittest.TestCase):
    def run_check(self, tmp, previous, router, groq, extra=()):
        path = os.path.join(tmp, "snapshot.json")
        if previous is not None:
            monitor.save_json_safe(path, previous)
        out = io.StringIO()
        with patch.object(monitor, "fetch_openrouter_free", return_value=router), \
             patch.object(monitor, "fetch_groq_free", return_value=groq), \
             patch.object(monitor.notify_mod, "notify") as notify, \
             redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = monitor.main(["--state-dir", tmp, "--format", "json", *extra])
        notify.assert_not_called()
        return code, json.loads(out.getvalue()), monitor.load_json_safe(path)

    def test_failed_provider_preserved_without_false_removal(self):
        previous = {"openrouter/a": INFO, "groq/g": INFO}
        with tempfile.TemporaryDirectory() as tmp:
            code, report, saved = self.run_check(tmp, previous, (None, "down"),
                                                ({"groq/g": INFO}, None))
        self.assertEqual(code, 1)
        self.assertFalse(report["complete"])
        self.assertEqual(report["changes"], [])
        self.assertEqual(saved, previous)
        self.assertEqual(report["provider_status"]["openrouter"], "cached")

    def test_empty_success_removes_but_failed_provider_stays(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, report, saved = self.run_check(tmp, {"openrouter/a": INFO, "groq/g": INFO},
                                                ({}, None), (None, "down"))
        self.assertEqual(code, 1)
        self.assertEqual([x["model_id"] for x in report["changes"]], ["openrouter/a"])
        self.assertEqual(saved, {"groq/g": INFO})
        self.assertIsNone(report["switches"][0]["to"])

    def test_all_failed_preserves_snapshot_and_no_notification(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, report, saved = self.run_check(tmp, {"openrouter/a": INFO},
                                                (None, "down"), (None, "down"),
                                                ("--notify", "webhook", "--notify-always"))
        self.assertEqual(code, 1)
        self.assertEqual(saved, {"openrouter/a": INFO})
        self.assertEqual(report["changes"], [])

    def test_disabled_provider_preserved_without_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, report, saved = self.run_check(tmp, {"openrouter/a": INFO, "groq/g": INFO},
                                                ({"a": INFO}, None), ({}, None),
                                                ("--providers", "openrouter"))
        self.assertEqual(code, 0)
        self.assertEqual(report["changes"], [])
        self.assertIn("groq/g", saved)

    def test_partial_first_run_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, report, saved = self.run_check(tmp, None, (None, "down"), ({}, None))
        self.assertEqual(code, 1)
        self.assertFalse(report["complete"])
        self.assertEqual(saved, {})

    def test_empty_snapshot_is_existing_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, report, _ = self.run_check(tmp, {}, ({"a": INFO}, None), ({}, None))
        self.assertEqual(code, 2)
        self.assertEqual(report["changes"][0]["type"], "added")

    def test_unknown_provider_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                monitor.main(["--state-dir", tmp, "--providers", "unknown"])

class RecoveryTests(unittest.TestCase):
    run_check = PartialTests.run_check
    def test_recovery_records_legitimate_removal_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = {"openrouter/a": INFO, "groq/g": INFO}
            _, first, _ = self.run_check(tmp, previous, (None, "down"), ({"groq/g": INFO}, None))
            self.assertFalse(first["changed"])
            code, second, _ = self.run_check(tmp, None, ({}, None), ({"groq/g": INFO}, None))
            self.assertEqual(code, 2)
            self.assertEqual(second["changes"][0]["model_id"], "openrouter/a")
            code, third, _ = self.run_check(tmp, None, ({}, None), ({"groq/g": INFO}, None))
            self.assertEqual(code, 0)
            self.assertFalse(third["changed"])

    def test_unverified_groq_not_suggested(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, report, _ = self.run_check(tmp, {"openrouter/a": INFO}, ({}, None),
                                         ({"groq/g": {**INFO, "free_tier_verified": False}}, None))
        self.assertIsNone(report["switches"][0]["to"])
