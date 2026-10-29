"""Fresh, bounded audits with the pinned pnpm toolchain; no Docker layer cache."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

SEVERITIES = ("info", "low", "moderate", "high", "critical")
NETWORK_CODES = {"ECONNRESET", "ETIMEDOUT", "EAI_AGAIN", "ECONNREFUSED",
                 "ENETUNREACH", "EHOSTUNREACH", "ERR_SOCKET_CLOSED", "ENOTFOUND"}


class AuditFailure(ValueError):
    pass


def check_report(report):
    if not isinstance(report, dict) or "error" in report:
        raise AuditFailure("audit_invalid_report")
    metadata = report.get("metadata")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("vulnerabilities"), dict):
        raise AuditFailure("audit_invalid_report")
    counts = metadata["vulnerabilities"]
    if any(type(counts.get(key)) is not int or counts[key] != 0 for key in SEVERITIES):
        raise AuditFailure("audit_security_or_incomplete_result")


def retryable(error):
    if not isinstance(error, dict):
        return False
    if error.get("code") in NETWORK_CODES:
        return True
    status = error.get("statusCode", error.get("status"))
    if status is None and error.get("code") == "ERR_PNPM_AUDIT_BAD_RESPONSE":
        match = re.search(r"(?:responded with |status(?: code)?[:= ]+)(429|5\d\d)\b", str(error.get("message", "")))
        status = int(match[1]) if match else None
    return type(status) is int and (status == 429 or 500 <= status <= 599)


def audit_command(command, project, env):
    for attempt in range(3):
        try:
            result = subprocess.run(command, cwd=project, env=env, capture_output=True,
                                    text=True, timeout=90)
        except subprocess.TimeoutExpired:
            retry = True
        else:
            try:
                report = json.loads(result.stdout)
            except (ValueError, TypeError):
                raise AuditFailure("audit_invalid_json") from None
            if result.returncode == 0:
                check_report(report)
                return report
            retry = retryable(report.get("error")) if isinstance(report, dict) else False
            if not retry:
                # Do not log arbitrary registry text or subprocess environments.
                raise AuditFailure("audit_security_or_nonretryable_failure")
        if attempt == 2:
            raise AuditFailure("audit_network_exhausted")
        print("Audit transport retry " + str(attempt + 1) + "/3", flush=True)
        time.sleep((2, 5)[attempt])


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run_audits(project, node, pnpm, destination, runtime_sha256):
    destination.mkdir(parents=True, exist_ok=True)
    inputs = {"package_sha256": digest(project / "package.json"),
              "lock_sha256": digest(project / "pnpm-lock.yaml"),
              "runtime_sha256": runtime_sha256}
    env = os.environ.copy()
    env["PATH"] = str(node.parent) + os.pathsep + env.get("PATH", "")
    # Audits intentionally use the network; preparation alone owns this step.
    env.pop("npm_config_offline", None)
    for name, flags in (("full", []), ("prod", ["--prod"])):
        print("Preparing audit: " + name, flush=True)
        report = audit_command([str(node), str(pnpm), "audit", *flags, "--json"], project, env)
        (destination / ("audit-" + name + ".json")).write_text(json.dumps(report))
    receipt = {**inputs, "audited_at": datetime.now(timezone.utc).isoformat()}
    (destination / "audit.json").write_text(json.dumps(receipt))
    return receipt
