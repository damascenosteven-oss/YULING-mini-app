"""Exercise the final image with the same trial limits as the receiver."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid
from runtime_permissions import CHECK


def run(*args):
    return subprocess.run([str(a) for a in args], check=True, capture_output=True, text=True).stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-output", required=True, type=Path)
    args = parser.parse_args()
    info = json.loads((args.build_output / "image.json").read_text())
    name = "yuling-image-check-" + uuid.uuid4().hex[:12]
    evidence = args.build_output / "packaged-candidate"
    if evidence.exists():
        raise RuntimeError("Use a fresh evidence directory")
    stage = "container_start"
    try:
        run("docker", "run", "-d", "--name", name, "--cpus", "1", "--memory", "1024m",
            "--memory-swap", "1024m", "--pids-limit", "256", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", info["tag"])
        stage = "runtime_permissions"
        print(run("docker", "exec", name, "python", "-c", CHECK))
        # Invoke the exact production readiness/static-asset path without publishing a port.
        import importlib.util
        spec = importlib.util.spec_from_file_location("receiver", Path(__file__).with_name("release.py"))
        receiver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(receiver)
        runtime = receiver.DockerRuntime({})
        runtime.call = lambda *args, **kwargs: run("docker", *args)
        stage = "readiness"
        runtime.readiness(name)
        stage = "quick_smoke"
        quick = run("docker", "exec", name, "node", "dist/release-smoke.js", "quick")
        print(quick)
        checked = json.loads(quick)
        expected_source = {"app_sha": info["app_sha"],
                           "engine_sha": "be73ccd4e811bd877fb2635fd7dfc3ca3ad8e192", "source_dirty": False}
        if checked.get("status") != "passed" or checked.get("pages") != 12 or checked.get("source") != expected_source:
            raise RuntimeError("Final image source or smoke result mismatch")
        stage = "repeatability"
        print(run("docker", "exec", name, "node", "dist/release-smoke.js", "repeat", "/tmp/packaged-candidate"))
        run("docker", "cp", name + ":/tmp/packaged-candidate", evidence)
        stage = "memory_and_evidence"
        stats = run("docker", "exec", name, "sh", "-c",
                    "cat /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory.events")
        (args.build_output / "image-memory.txt").write_text(stats)
        print(stats)
        if any(int(line.split()[1]) != 0 for line in stats.splitlines()[1:] if line.startswith(("oom ", "oom_kill "))):
            raise RuntimeError("Final image exceeded its memory budget")
        result = json.loads((evidence / "result.json").read_text())
        if result.get("source") != expected_source or result.get("pages") != 12 or result.get("differences") != []:
            raise RuntimeError("Final image repeatability evidence mismatch")
        manifest = json.loads((args.build_output / "release.json").read_text())
        (args.build_output / "verification.json").write_text(json.dumps({"schema": 1,
            "app_sha": info["app_sha"], "engine_sha": expected_source["engine_sha"],
            "image_id": manifest["image_id"], "source_dirty": False,
            "pages": 12, "captures": 2, "differences": 0}))
    except Exception as error:
        # Classify captured child output but never print it: it may contain secrets.
        detail = str(getattr(error, "stderr", "") or "")
        denied = any(value in detail for value in ("EACCES", "PermissionError", "permission denied"))
        diagnostic = {"schema": 1, "stage": stage,
                      "code": "image_permission_denied" if denied else "image_check_failed",
                      "exit_code": getattr(error, "returncode", 1)}
        (args.build_output / "image-check-error.json").write_text(json.dumps(diagnostic))
        print(json.dumps(diagnostic), file=sys.stderr, flush=True)
        raise SystemExit(5 if denied else 6) from None
    finally:
        # Only the random container created by this invocation; no images/volumes/prune.
        subprocess.run(["docker", "container", "rm", "-f", name], check=False, capture_output=True)


if __name__ == "__main__":
    main()
