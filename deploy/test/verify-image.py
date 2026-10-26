"""Exercise the final image with the same trial limits as the receiver."""
import argparse
import json
from pathlib import Path
import subprocess
import uuid


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
    try:
        run("docker", "run", "-d", "--name", name, "--cpus", "1", "--memory", "1024m",
            "--memory-swap", "1024m", "--pids-limit", "256", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", info["tag"])
        # Invoke the exact production readiness/static-asset path without publishing a port.
        import importlib.util
        spec = importlib.util.spec_from_file_location("receiver", Path(__file__).with_name("release.py"))
        receiver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(receiver)
        runtime = receiver.DockerRuntime({})
        runtime.call = lambda *args, **kwargs: run("docker", *args)
        runtime.readiness(name)
        print(run("docker", "exec", name, "node", "dist/release-smoke.js", "quick"))
        print(run("docker", "exec", name, "node", "dist/release-smoke.js", "repeat", "/tmp/packaged-candidate"))
        run("docker", "cp", name + ":/tmp/packaged-candidate", evidence)
        stats = run("docker", "exec", name, "sh", "-c",
                    "cat /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory.events")
        (args.build_output / "image-memory.txt").write_text(stats)
        print(stats)
    finally:
        # Only the random container created by this invocation; no images/volumes/prune.
        subprocess.run(["docker", "container", "rm", "-f", name], check=False, capture_output=True)


if __name__ == "__main__":
    main()
