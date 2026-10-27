import importlib.util
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "phone_request", Path(__file__).with_name("phone-request.py"))
phone = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phone)


class RequestTests(unittest.TestCase):
    def test_only_owner_main_and_fixed_operation(self):
        good = {"GITHUB_REPOSITORY": "damascenosteven-oss/YULING-mini-app",
                "GITHUB_ACTOR": "damascenosteven-oss", "GITHUB_REF": "refs/heads/main",
                "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "42",
                "GITHUB_RUN_ATTEMPT": "1", "OPERATION": "publish"}
        self.assertEqual(phone.identity(good)["operation"], "publish")
        for changed in ({"GITHUB_ACTOR": "intruder"}, {"GITHUB_REF": "refs/heads/dev"},
                        {"GITHUB_SHA": "bad"}, {"OPERATION": "shell"}):
            with self.assertRaises(ValueError):
                phone.identity({**good, **changed})

    def test_actual_request_entry_waits_for_workstation_result(self):
        env = {"GITHUB_REPOSITORY": "damascenosteven-oss/YULING-mini-app",
               "GITHUB_ACTOR": "damascenosteven-oss", "GITHUB_REF": "refs/heads/main",
               "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "42",
               "GITHUB_RUN_ATTEMPT": "1", "OPERATION": "publish", "GITHUB_TOKEN": "fixture"}
        class FakeAPI:
            def __init__(self, token):
                self.calls = []
            def call(self, route, data=None):
                self.calls.append((route, data))
                if route == "/deployments":
                    return {"id": 8, "sha": "a" * 40}
                if route.endswith("?per_page=1"):
                    return [{"state": "success"}]
                return {}
        with patch.dict(os.environ, env), patch.object(phone, "GitHub", FakeAPI), \
                patch.object(phone.signal, "signal"), patch.object(phone.time, "sleep"):
            phone.main()
        self.assertEqual(phone.api.calls[0][0], "/deployments")
        self.assertEqual(phone.api.calls[0][1]["payload"]["run_id"], 42)
        self.assertEqual(phone.api.calls[1][1]["state"], "pending")
        self.assertEqual(phone.api.calls[2][0], "/deployments/8/statuses?per_page=1")

    def test_offline_workstation_fails_phone_workflow(self):
        env = {"GITHUB_REPOSITORY": "damascenosteven-oss/YULING-mini-app",
               "GITHUB_ACTOR": "damascenosteven-oss", "GITHUB_REF": "refs/heads/main",
               "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "42",
               "GITHUB_RUN_ATTEMPT": "1", "OPERATION": "rollback", "GITHUB_TOKEN": "fixture"}
        class FakeAPI:
            def __init__(self, token):
                self.states = []
            def call(self, route, data=None):
                if data and "state" in data:
                    self.states.append(data["state"])
                if route == "/deployments":
                    return {"id": 8, "sha": "a" * 40}
                if route.endswith("?per_page=1"):
                    return [{"state": "pending"}]
                return {}
        start = datetime(2026, 10, 27, tzinfo=timezone.utc)
        class Clock:
            calls = 0
            @classmethod
            def now(cls, zone):
                cls.calls += 1
                return start if cls.calls == 1 else start + timedelta(minutes=111)
        with patch.dict(os.environ, env), patch.object(phone, "GitHub", FakeAPI), \
                patch.object(phone, "datetime", Clock), patch.object(phone.signal, "signal"):
            with self.assertRaisesRegex(RuntimeError, "offline"):
                phone.main()
        self.assertEqual(phone.api.states, ["pending", "failure"])


if __name__ == "__main__":
    unittest.main()
