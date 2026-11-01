"""Exercise installed hooks and CI against disposable, source-bound Git fixtures."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / ".engineering-guard/engineering_guard.py"
POLICY = ROOT / ".engineering-guard/policy.json"


class Fixture:
    def __init__(self, approved=True, source=None, issue="9"):
        self.issue = issue
        self.branch = f"issue/{issue}-engineering-guard"
        self.temp = tempfile.TemporaryDirectory(prefix="yuling-guard-test-")
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.home = self.root / "private-fixture"
        self.script = self.root / "engineering_guard.py"
        self.script.write_bytes(CHECKER.read_bytes() if source is None else source)
        self.policy = json.loads(POLICY.read_text(encoding="utf-8"))
        self.policy["checker_sha256"] = hashlib.sha256(self.script.read_bytes()).hexdigest()
        if not approved:
            self.policy["lifecycle"]["issues"] = {}
        self.policy_file = self.root / "policy.json"
        self.policy_file.write_text(json.dumps(self.policy), encoding="utf-8")
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Guard fixture")
        self.git("config", "user.email", "guard-fixture@example.invalid")
        self.git("config", "core.autocrlf", "false")
        (self.repo / "README.md").write_text("Disposable guard fixture\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-m", "fixture base")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "-b", self.branch)
        approved_issue = json.loads(POLICY.read_text(encoding="utf-8"))["lifecycle"]["issues"][issue]
        for name in filter(None, (approved_issue["plan"], approved_issue.get("adr"))):
            file = self.repo / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes((ROOT / name).read_bytes().replace(b"\r\n", b"\n"))
        self.git("add", "docs")
        self.guard("init")
        self.guard("install", "--repo", self.repo, "--policy", self.policy_file)
        self.hooks = Path(self.git("config", "--get", "core.hooksPath").stdout.strip())

    def close(self):
        self.temp.cleanup()

    def run(self, args, check=True, data=None):
        environment = {k: v for k, v in os.environ.items()
                       if not k.startswith("GIT_") and k not in ("PYTHONPATH", "PYTHONHOME")}
        environment["PYTHONUTF8"] = "1"
        result = subprocess.run([str(x) for x in args], cwd=self.repo, env=environment,
                                input=data, capture_output=True, text=True, encoding="utf-8", timeout=60)
        if check and result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return result

    def git(self, *args, **kwargs):
        return self.run(["git", "-C", self.repo, *args], **kwargs)

    def guard(self, *args, **kwargs):
        return self.run([sys.executable, self.script, *args, "--home", self.home], **kwargs)

    def commit(self):
        self.git("commit", "-m", f"fixture accepted Issue {self.issue}")
        return self.git("rev-parse", "HEAD").stdout.strip()

    def precommit(self):
        return self.git("hook", "run", "pre-commit", check=False)

    def push(self, destination, deleting=False):
        head = self.git("rev-parse", "HEAD").stdout.strip()
        source = "0" * 40 if deleting else head
        data = f"refs/heads/{self.branch} {source} refs/heads/{destination} {self.base}\n"
        # Execute the installed pre-push entry with Git's exact stdin protocol;
        # no network push or remote main write is attempted by this test.
        input_file = self.root / "push-refs.txt"
        input_file.write_text(data, encoding="utf-8")
        return self.git("hook", "run", "--to-stdin=" + str(input_file), "pre-push",
                        "--", "origin", "https://example.invalid/repo", check=False)

    def event(self, body):
        head = self.commit()
        event = {"pull_request": {"head": {"sha": head, "ref": self.branch},
                                   "base": {"sha": self.base}, "created_at": "2026-10-26T12:00:00Z",
                                   "body": body}}
        file = self.root / "event.json"
        file.write_text(json.dumps(event), encoding="utf-8")
        return file


class GuardEntries(unittest.TestCase):
    def fixture(self, **kwargs):
        value = Fixture(**kwargs)
        self.addCleanup(value.close)
        return value

    def rejected(self, result, reason):
        self.assertNotEqual(result.returncode, 0, "Invalid source was accepted")
        self.assertIn(reason, result.stderr)

    def test_snapshot_hash_and_frozen_policy(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(CHECKER.read_bytes()).hexdigest(), policy["checker_sha256"])
        self.assertEqual(policy["lifecycle"]["effective_at"], "2026-10-22T04:50:03.733426+00:00")
        self.assertEqual(set(policy["lifecycle"]["issues"]), {"8", "9", "12", "14", "16", "18", "20", "22", "24", "26", "28", "30", "32", "34", "36", "38", "40", "42", "44", "46"})
        self.assertEqual(policy["lifecycle"]["grandfathered"], {})

    def test_accepted_stage_commit_and_push_entry_pass(self):
        f = self.fixture()
        self.assertEqual(f.precommit().returncode, 0)
        f.commit()  # Actual Git commit invokes the installed hook.
        self.assertEqual(f.push("issue/9-engineering-guard").returncode, 0)

    def test_issue_8_approved_stage_and_ci(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        self.assertIn("8", policy["lifecycle"]["issues"])
        f = self.fixture(issue="8")
        self.assertEqual(f.precommit().returncode, 0)
        event = f.event("Closes #9")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text(encoding="utf-8"))
        value["pull_request"]["body"] = "Closes #8"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)

    def test_unapproved_issue_is_rejected(self):
        f = self.fixture()
        f.git("checkout", "-b", "issue/10-unapproved")
        self.rejected(f.precommit(), "approval receipt missing")

    def test_issue_12_real_entries_require_matching_approved_source(self):
        f = self.fixture(issue="12")
        name = f.policy["lifecycle"]["issues"]["12"]["plan"]
        file = f.repo / name
        accepted = file.read_bytes()
        file.write_bytes(accepted.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        file.write_bytes(accepted)
        self.rejected(f.precommit(), "plan/base mismatch")
        f.git("add", name)
        self.assertEqual(f.precommit().returncode, 0)
        event = f.event("Closes #8")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text())
        value["pull_request"]["body"] = "Closes #12"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)
        self.assertEqual(f.push(f.branch).returncode, 0)

    def test_issue_14_real_entries_require_matching_approved_source(self):
        f = self.fixture(issue="14")
        name = f.policy["lifecycle"]["issues"]["14"]["plan"]
        file = f.repo / name
        accepted = file.read_bytes()
        file.write_bytes(accepted.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        file.write_bytes(accepted)
        self.rejected(f.precommit(), "plan/base mismatch")
        f.git("add", name)
        self.assertEqual(f.precommit().returncode, 0)
        event = f.event("Closes #8")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text())
        value["pull_request"]["body"] = "Closes #14"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)
        self.assertEqual(f.push(f.branch).returncode, 0)

    def test_issue_16_real_entries_require_matching_approved_source(self):
        f = self.fixture(issue="16")
        name = f.policy["lifecycle"]["issues"]["16"]["plan"]
        file = f.repo / name
        accepted = file.read_bytes()
        file.write_bytes(accepted.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        file.write_bytes(accepted)
        self.rejected(f.precommit(), "plan/base mismatch")
        f.git("add", name)
        self.assertEqual(f.precommit().returncode, 0)
        event = f.event("Closes #14")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text())
        value["pull_request"]["body"] = "Closes #16"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)
        self.assertEqual(f.push(f.branch).returncode, 0)

    def test_issue_18_real_entries_require_matching_approved_source(self):
        f = self.fixture(issue="18")
        name = f.policy["lifecycle"]["issues"]["18"]["plan"]
        file = f.repo / name
        accepted = file.read_bytes()
        file.write_bytes(accepted.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        file.write_bytes(accepted)
        self.rejected(f.precommit(), "plan/base mismatch")
        f.git("add", name)
        self.assertEqual(f.precommit().returncode, 0)
        event = f.event("Closes #16")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text())
        value["pull_request"]["body"] = "Closes #18"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)
        self.assertEqual(f.push(f.branch).returncode, 0)

    def test_issue_20_real_entries_require_matching_approved_source(self):
        f = self.fixture(issue="20")
        name = f.policy["lifecycle"]["issues"]["20"]["plan"]
        file = f.repo / name
        accepted = file.read_bytes()
        file.write_bytes(accepted.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        file.write_bytes(accepted)
        self.rejected(f.precommit(), "plan/base mismatch")
        f.git("add", name)
        self.assertEqual(f.precommit().returncode, 0)
        event = f.event("Closes #18")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text())
        value["pull_request"]["body"] = "Closes #20"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)
        self.assertEqual(f.push(f.branch).returncode, 0)

    def test_issue_22_real_entries_require_matching_approved_source(self):
        f = self.fixture(issue="22")
        name = f.policy["lifecycle"]["issues"]["22"]["plan"]
        file = f.repo / name
        accepted = file.read_bytes()
        file.write_bytes(accepted.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        file.write_bytes(accepted)
        self.rejected(f.precommit(), "plan/base mismatch")
        f.git("add", name)
        self.assertEqual(f.precommit().returncode, 0)
        event = f.event("Closes #20")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text())
        value["pull_request"]["body"] = "Closes #22"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)
        self.assertEqual(f.push(f.branch).returncode, 0)

    def test_issue_24_real_entries_require_matching_approved_source(self):
        f = self.fixture(issue="24")
        name = f.policy["lifecycle"]["issues"]["24"]["plan"]
        file = f.repo / name
        accepted = file.read_bytes()
        file.write_bytes(accepted.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        file.write_bytes(accepted)
        self.rejected(f.precommit(), "plan/base mismatch")
        f.git("add", name)
        self.assertEqual(f.precommit().returncode, 0)
        event = f.event("Closes #22")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text())
        value["pull_request"]["body"] = "Closes #24"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)
        self.assertEqual(f.push(f.branch).returncode, 0)

    def test_issue_26_real_entries_require_matching_approved_source(self):
        f = self.fixture(issue="26")
        name = f.policy["lifecycle"]["issues"]["26"]["plan"]
        file = f.repo / name
        accepted = file.read_bytes()
        file.write_bytes(accepted.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        file.write_bytes(accepted)
        self.rejected(f.precommit(), "plan/base mismatch")
        f.git("add", name)
        self.assertEqual(f.precommit().returncode, 0)
        event = f.event("Closes #22")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text())
        value["pull_request"]["body"] = "Closes #26"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)
        self.assertEqual(f.push(f.branch).returncode, 0)

    def test_issue_28_real_entries_require_matching_approved_source(self):
        f = self.fixture(issue="28")
        name = f.policy["lifecycle"]["issues"]["28"]["plan"]
        file = f.repo / name
        accepted = file.read_bytes()
        file.write_bytes(accepted.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        file.write_bytes(accepted)
        self.rejected(f.precommit(), "plan/base mismatch")
        f.git("add", name)
        self.assertEqual(f.precommit().returncode, 0)
        event = f.event("Closes #26")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text())
        value["pull_request"]["body"] = "Closes #28"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)
        self.assertEqual(f.push(f.branch).returncode, 0)

    def test_issue_30_real_entries_require_matching_approved_source(self):
        f = self.fixture(issue="30")
        name = f.policy["lifecycle"]["issues"]["30"]["plan"]
        file = f.repo / name
        accepted = file.read_bytes()
        file.write_bytes(accepted.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        file.write_bytes(accepted)
        self.rejected(f.precommit(), "plan/base mismatch")
        f.git("add", name)
        self.assertEqual(f.precommit().returncode, 0)
        event = f.event("Closes #26")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text())
        value["pull_request"]["body"] = "Closes #30"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)
        self.assertEqual(f.push(f.branch).returncode, 0)

    def test_issue_44_real_entries_require_matching_approved_source(self):
        f = self.fixture(issue="44")
        name = f.policy["lifecycle"]["issues"]["44"]["plan"]
        file = f.repo / name
        accepted = file.read_bytes()
        file.write_bytes(accepted.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        file.write_bytes(accepted)
        self.rejected(f.precommit(), "plan/base mismatch")
        f.git("add", name)
        self.assertEqual(f.precommit().returncode, 0)
        event = f.event("Closes #42")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text())
        value["pull_request"]["body"] = "Closes #44"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)
        self.assertEqual(f.push(f.branch).returncode, 0)

    def test_wrong_branch_is_rejected(self):
        f = self.fixture()
        f.git("checkout", "-b", "feature/no-issue")
        self.rejected(f.precommit(), "Branch must identify")

    def test_issue_32_real_entries_require_matching_approved_source(self):
        f = self.fixture(issue="32")
        name = f.policy["lifecycle"]["issues"]["32"]["plan"]
        file = f.repo / name
        accepted = file.read_bytes()
        file.write_bytes(accepted.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        file.write_bytes(accepted)
        self.rejected(f.precommit(), "plan/base mismatch")
        f.git("add", name)
        self.assertEqual(f.precommit().returncode, 0)
        event = f.event("Closes #26")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text())
        value["pull_request"]["body"] = "Closes #32"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)
        self.assertEqual(f.push(f.branch).returncode, 0)

    def test_issue_34_real_entries_require_matching_approved_source(self):
        f = self.fixture(issue="34")
        name = f.policy["lifecycle"]["issues"]["34"]["plan"]
        file = f.repo / name
        accepted = file.read_bytes()
        file.write_bytes(accepted.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        file.write_bytes(accepted)
        self.rejected(f.precommit(), "plan/base mismatch")
        f.git("add", name)
        self.assertEqual(f.precommit().returncode, 0)
        event = f.event("Closes #26")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text())
        value["pull_request"]["body"] = "Closes #34"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)
        self.assertEqual(f.push(f.branch).returncode, 0)

    def test_issue_36_real_entries_require_matching_approved_source(self):
        f = self.fixture(issue="36")
        name = f.policy["lifecycle"]["issues"]["36"]["plan"]
        file = f.repo / name
        accepted = file.read_bytes()
        file.write_bytes(accepted.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        file.write_bytes(accepted)
        self.rejected(f.precommit(), "plan/base mismatch")
        f.git("add", name)
        self.assertEqual(f.precommit().returncode, 0)
        event = f.event("Closes #26")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text())
        value["pull_request"]["body"] = "Closes #36"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)
        self.assertEqual(f.push(f.branch).returncode, 0)

    def test_issue_38_real_entries_require_matching_approved_source(self):
        f = self.fixture(issue="38")
        name = f.policy["lifecycle"]["issues"]["38"]["plan"]
        file = f.repo / name
        accepted = file.read_bytes()
        file.write_bytes(accepted.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        file.write_bytes(accepted)
        self.rejected(f.precommit(), "plan/base mismatch")
        f.git("add", name)
        self.assertEqual(f.precommit().returncode, 0)
        event = f.event("Closes #26")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text())
        value["pull_request"]["body"] = "Closes #38"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)
        self.assertEqual(f.push(f.branch).returncode, 0)

    def test_issue_40_real_entries_require_matching_approved_source(self):
        f = self.fixture(issue="40")
        name = f.policy["lifecycle"]["issues"]["40"]["plan"]
        file = f.repo / name
        accepted = file.read_bytes()
        file.write_bytes(accepted.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        file.write_bytes(accepted)
        self.rejected(f.precommit(), "plan/base mismatch")
        f.git("add", name)
        self.assertEqual(f.precommit().returncode, 0)
        event = f.event("Closes #26")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text())
        value["pull_request"]["body"] = "Closes #40"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)
        self.assertEqual(f.push(f.branch).returncode, 0)

    def test_issue_42_real_entries_require_matching_approved_source(self):
        f = self.fixture(issue="42")
        name = f.policy["lifecycle"]["issues"]["42"]["plan"]
        file = f.repo / name
        accepted = file.read_bytes()
        file.write_bytes(accepted.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        file.write_bytes(accepted)
        self.rejected(f.precommit(), "plan/base mismatch")
        f.git("add", name)
        self.assertEqual(f.precommit().returncode, 0)
        event = f.event("Closes #26")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text())
        value["pull_request"]["body"] = "Closes #42"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)
        self.assertEqual(f.push(f.branch).returncode, 0)

    def test_wrong_branch_is_rejected(self):
        f = self.fixture()
        f.git("checkout", "-b", "feature/no-issue")
        self.rejected(f.precommit(), "Branch must identify")

    def test_missing_owner_approval_is_rejected(self):
        f = self.fixture(approved=False)
        self.rejected(f.precommit(), "approval receipt missing")

    def test_plan_and_adr_must_be_accepted(self):
        for field, reason in (("plan", "plan/base mismatch"), ("adr", "ADR not accepted")):
            with self.subTest(field=field):
                f = self.fixture()
                name = f.policy["lifecycle"]["issues"]["9"][field]
                file = f.repo / name
                original = file.read_bytes()
                file.write_bytes(original.replace(b"status: accepted", b"status: proposed"))
                f.git("add", name)
                self.rejected(f.precommit(), reason)
                file.write_bytes(original)
                f.git("add", name)
                self.assertEqual(f.precommit().returncode, 0)

    def test_unstaged_fix_cannot_mask_bad_staged_plan(self):
        f = self.fixture()
        name = f.policy["lifecycle"]["issues"]["9"]["plan"]
        file = f.repo / name
        original = file.read_bytes()
        file.write_bytes(original.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        file.write_bytes(original)
        self.rejected(f.precommit(), "plan/base mismatch")
        f.git("add", name)
        self.assertEqual(f.precommit().returncode, 0)

    def test_direct_main_push_and_delete_are_rejected(self):
        f = self.fixture()
        f.commit()
        for name in ("main", "master"):
            for deletion in (False, True):
                self.rejected(f.push(name, deletion), "Direct push/delete")

    def test_ci_actual_event_requires_matching_closes(self):
        f = self.fixture()
        event = f.event("Closes #8")
        self.rejected(f.guard("ci", "--policy", f.policy_file, "--file", event, check=False),
                      "PR must close the same Issue")
        value = json.loads(event.read_text(encoding="utf-8"))
        value["pull_request"]["body"] = "Closes #9"
        event.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(f.guard("ci", "--policy", f.policy_file, "--file", event).returncode, 0)

    def test_codex_adapter_denies_invalid_stage_then_allows_recovery(self):
        f = self.fixture()
        name = f.policy["lifecycle"]["issues"]["9"]["plan"]
        file = f.repo / name
        original = file.read_bytes()
        file.write_bytes(original.replace(b"status: accepted", b"status: proposed"))
        f.git("add", name)
        command = 'git -C "' + str(f.repo) + '" commit --dry-run'
        payload = json.dumps({"tool_input": {"cmd": command}})
        result = json.loads(f.guard("agent", data=payload).stdout)
        self.assertIn("hookSpecificOutput", result, "Invalid source was accepted by adapter")
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        file.write_bytes(original)
        f.git("add", name)
        self.assertEqual(json.loads(f.guard("agent", data=payload).stdout), {})

    def test_deliberately_disabled_lifecycle_fails_the_rejection_assertion(self):
        # Mutate only a disposable checker, never the installed/shared snapshot.
        original = CHECKER.read_bytes()
        marker = b"def lifecycle(repo, tree, branch, policy, pr=None):\n"
        self.assertEqual(original.count(marker), 1)
        mutant = original.replace(marker, marker + b"    return 'deliberate fixture fault'\n")
        f = self.fixture(source=mutant)
        f.git("checkout", "-b", "feature/no-issue")
        with self.assertRaisesRegex(AssertionError, "Invalid source was accepted"):
            self.rejected(f.precommit(), "Branch must identify")


if __name__ == "__main__":
    unittest.main()
