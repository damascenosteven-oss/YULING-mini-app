"""Real final-image HTTP routes with simulated providers and networking disabled."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

HERE = Path(__file__).resolve().parent
CLIENT = r"""
(async()=>{
 const base='http://127.0.0.1:5000';
 let ready=false;
 for(let i=0;i<45;i++){
  try{if((await fetch(base+'/api/health',{signal:AbortSignal.timeout(1000)})).ok){ready=true;break;}}catch{}
  await new Promise(resolve=>setTimeout(resolve,500));
 }
 if(!ready)throw Error('fixture readiness');
 const denied=await fetch(base+'/api/ppt/outline',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
 if(denied.status!==401)throw Error('authentication boundary');
 const login=await fetch(base+'/api/ppt/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:process.env.PPT_INVITE_PASSWORD})});
 if(login.status!==200)throw Error('fixture login');
 const cookie=login.headers.getSetCookie().map(value=>value.split(';')[0]).join('; ');
 const started=Date.now();
 const response=await fetch(base+'/api/ppt/outline',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({prompt:'调查目前宁波就业市场，形成公开来源的十页培训汇报',pageCount:10,motionMode:'auto',skillId:'auto'}),signal:AbortSignal.timeout(140000)});
 const value=await response.json();
 console.log(JSON.stringify({http:response.status,code:value.code,pages:value.slides?.length,research:value.research?.status,sources:value.research?.sources?.length,elapsedMs:Date.now()-started}));
})().catch(()=>process.exitCode=1);
"""


def run(*args, timeout=180):
    return subprocess.run([str(x) for x in args], check=True, capture_output=True,
                          text=True, timeout=timeout).stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("Use a new HTTP evidence file")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    image = json.loads(run("docker", "image", "inspect", args.image))[0]
    report = {"simulated_providers": True, "cloud_calls": 0,
              "app_sha": image["Config"].get("Labels", {}).get("org.opencontainers.image.revision"),
              "image_id": image["Id"], "cases": [], "passed": False}
    expected = {
        "repair": (200, None, 2), "invalid": (502, "PPT_OUTLINE_INVALID", 2),
        "timeout": (504, "PPT_MODEL_TIMEOUT", 2), "upstream": (502, None, 2),
        "json": (502, "PPT_OUTLINE_INVALID", 2), "truncated": (502, "PPT_OUTLINE_INVALID", 2),
        "search": (503, "PPT_RESEARCH_UNAVAILABLE", 0),
        "insufficient": (422, "PPT_RESEARCH_INSUFFICIENT", 0),
    }
    try:
        with tempfile.TemporaryDirectory(prefix="outline-entry-fixture-") as folder:
            fixture = Path(folder) / "fixture.mjs"
            shutil.copyfile(HERE / "outline-entry-fixture.mjs", fixture)
            os.chmod(fixture, 0o644)
            report["fixture_sha256"] = hashlib.sha256(fixture.read_bytes()).hexdigest()
            for case, (status, code, models) in expected.items():
                name = "yuling-outline-entry-" + uuid.uuid4().hex[:12]
                result = {"case": case, "passed": False}
                report["cases"].append(result)
                try:
                    run("docker", "create", "--name", name, "--network", "none",
                        "--cpus", "1", "--memory", "1024m", "--memory-swap", "1024m",
                        "--pids-limit", "256", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                        "-e", "NODE_OPTIONS=--import=/tmp/outline-entry-fixture.mjs",
                        "-e", "OUTLINE_FIXTURE_CASE=" + case,
                        "-e", "DEEPSEEK_API_KEY=fixture-key-not-a-real-credential",
                        "-e", "BOCHA_API_KEY=fixture-search-not-a-real-credential",
                        "-e", "PPT_INVITE_PASSWORD=fixture-invite-for-http-test",
                        "-e", "PPT_SESSION_SECRET=fixture-session-secret-for-http-test", args.image)
                    run("docker", "cp", fixture, name + ":/tmp/outline-entry-fixture.mjs")
                    run("docker", "start", name)
                    data = json.loads(run("docker", "exec", name, "node", "-e", CLIENT))
                    result.update(data)
                    logs = subprocess.run(["docker", "logs", name], check=True,
                                          capture_output=True, text=True, timeout=20)
                    raw = logs.stdout + logs.stderr
                    if any(value in raw for value in ("PRIVATE_DRAFT_BODY_SENTINEL", "PRIVATE_PROVIDER_BODY_SENTINEL",
                                                       "fixture-key-not-a-real-credential", "fixture-search-not-a-real-credential")):
                        raise AssertionError("Fixture detected sensitive log content")
                    stats = [json.loads(line[len("OUTLINE_FIXTURE "):]) for line in raw.splitlines()
                             if line.startswith("OUTLINE_FIXTURE ")]
                    if not stats or stats[-1] != {"scenario": case, "searches": 3, "models": models}:
                        raise AssertionError("Unexpected search or model invocation count")
                    if data.get("http") != status or data.get("code") != code:
                        raise AssertionError("Public error contract mismatch")
                    if case == "repair" and (data.get("pages"), data.get("research"), data.get("sources")) != (10, "completed", 3):
                        raise AssertionError("Repaired response is not a complete researched deck")
                    if case == "timeout" and data["elapsedMs"] < 44_000:
                        raise AssertionError("Real 45-second repair deadline was bypassed")
                    container = json.loads(run("docker", "inspect", name))[0]
                    if (container["State"]["OOMKilled"] or container["HostConfig"]["NetworkMode"] != "none"
                            or container["HostConfig"]["Memory"] != 1024**3
                            or container["HostConfig"]["MemorySwap"] != 1024**3
                            or container["Config"]["User"] != "10001:10001"):
                        raise AssertionError("Fixture resource/network boundary failed")
                    result.update({"passed": True, "searches": 3, "models": models, "network": "none"})
                    print("PASS: final-image HTTP " + case + "; simulated providers", flush=True)
                finally:
                    # Persist status before removing our uniquely named fixture, never another project.
                    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
                    subprocess.run(["docker", "container", "rm", "-f", name], capture_output=True)
        report["passed"] = True
    finally:
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
