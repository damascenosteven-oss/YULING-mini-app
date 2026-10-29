"""Only transport errors can retry; invalid/security results fail closed."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from local_bridge_test import load


class AuditTests(unittest.TestCase):
    def setUp(self): self.m = load("release_audit")

    def test_success_requires_all_zero_counts_and_valid_json(self):
        self.m.check_report({"metadata": {"vulnerabilities": {k: 0 for k in self.m.SEVERITIES}}})
        for report in ({}, {"error": {}}, {"metadata": {"vulnerabilities": {"high": 0}}},
                       {"metadata": {"vulnerabilities": {k: int(k == "high") for k in self.m.SEVERITIES}}}):
            with self.subTest(report=report), self.assertRaises(ValueError): self.m.check_report(report)

    def test_network_retries_then_success_but_security_never_retries(self):
        good = {"metadata": {"vulnerabilities": {k: 0 for k in self.m.SEVERITIES}}}
        fail = {"error": {"code": "ECONNRESET"}}
        result = lambda rc, data: subprocess.CompletedProcess([], rc, json.dumps(data), "")
        with patch.object(self.m.subprocess, "run", side_effect=[result(1, fail), result(1, fail), result(0, good)]) as run, \
                patch.object(self.m.time, "sleep") as sleep:
            self.m.audit_command(["node", "pnpm", "audit"], Path("."), {})
            self.assertEqual(run.call_count, 3)
            self.assertEqual([c.args[0] for c in sleep.call_args_list], [2, 5])
            self.assertEqual(run.call_args.kwargs["timeout"], 90)
        for data in ({}, {**good, "advisories": {}}, {"error": {"code": "CERT_HAS_EXPIRED"}}):
            with patch.object(self.m.subprocess, "run", return_value=result(1, data)) as run:
                with self.assertRaises(ValueError): self.m.audit_command([], Path("."), {})
                self.assertEqual(run.call_count, 1)

    def test_exhausted_timeout_and_http_transport_statuses(self):
        for error in (subprocess.TimeoutExpired([], 90),):
            with patch.object(self.m.subprocess, "run", side_effect=error) as run, patch.object(self.m.time, "sleep"):
                with self.assertRaises(ValueError): self.m.audit_command([], Path("."), {})
                self.assertEqual(run.call_count, 3)
        for code in (429, 500, 503): self.assertTrue(self.m.retryable({"statusCode": code}))
        for code in (400, 401, 403): self.assertFalse(self.m.retryable({"statusCode": code}))


if __name__ == "__main__": unittest.main()
