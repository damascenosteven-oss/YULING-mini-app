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
import importlib.util

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
 let adminVerified=false;
 let managedCookie="";
 if(process.env.OUTLINE_FIXTURE_CASE==='admin'){
  const origin={Origin:'https://ppt.fixture','Content-Type':'application/json',Cookie:cookie};
  const forbidden=await fetch(base+'/api/ppt/admin/model-settings',{headers:{Cookie:cookie}});if(forbidden.status!==403)throw Error('ordinary user accessed settings');
  const loginAdmin=await fetch(base+'/api/ppt/admin/session',{method:'POST',headers:origin,body:JSON.stringify({password:'fixture-admin-independent-password'})});
  if(loginAdmin.status!==200)throw Error('admin login');
  const managed=cookie+'; '+loginAdmin.headers.getSetCookie().map(x=>x.split(';')[0]).join('; ');
  managedCookie=managed;
  const headers={...origin,Cookie:managed};
  const view=await(await fetch(base+'/api/ppt/admin/model-settings',{headers})).json();
  const config={provider:'openai-compatible',baseUrl:'https://fixture-model.example/v1',model:'fixture-compatible',apiKey:'fixture-changed-model-key',tokenLimitField:'max_completion_tokens'};
  const test=await fetch(base+'/api/ppt/admin/model-settings/test',{method:'POST',headers,body:JSON.stringify({config})});if(test.status!==200)throw Error('model connection test');
  const saved=await fetch(base+'/api/ppt/admin/model-settings',{method:'PUT',headers,body:JSON.stringify({config,revision:view.revision})});
  const text=await saved.text();if(saved.status!==200||text.includes(config.apiKey))throw Error('saved settings or key leak');
  adminVerified=true;
 }
 const started=Date.now();
 const response=await fetch(base+'/api/ppt/outline',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({prompt:'调查目前宁波就业市场，形成公开来源的十页培训汇报',pageCount:10,motionMode:'auto',skillId:'auto'}),signal:AbortSignal.timeout(140000)});
 const value=await response.json();
 let built=false;
 if(adminVerified){
  if(response.status!==200)throw Error('admin configured outline failed');
  const created=await fetch(base+'/api/ppt/decks',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify(value),signal:AbortSignal.timeout(240000)});
  const result=await created.json();if(created.status!==200)throw Error('Python build or QA failed: '+JSON.stringify(result));
  const viewer=await fetch(base+result.viewerUrl,{headers:{Cookie:cookie}});if(viewer.status!==200)throw Error('preview failed');
  const html=await viewer.text();if(!html.includes('iframe'))throw Error('preview iframe missing');
  const content=await fetch(base+'/api/ppt/decks/'+result.code,{headers:{Cookie:cookie}});
  if(content.status!==200||!(await content.text()).includes('培训规划'))throw Error('stored Python HTML preview missing');
  built=true;
  const {chromium}=await import('playwright-core');
  const browser=await chromium.launch({executablePath:process.env.PPT_CHROME_PATH,args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu']});
  try{
   const context=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:1});
   await context.addCookies(managedCookie.split('; ').map(part=>{const i=part.indexOf('=');return {name:part.slice(0,i),value:part.slice(i+1),url:base};}));
   const page=await context.newPage();await page.goto(base+'/ppt/settings');
   await page.getByLabel('API Base URL').waitFor();
   if(await page.getByLabel('API Key',{exact:true}).inputValue()!=='')throw Error('UI key leak');
   if(!await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))throw Error('mobile overflow');
   await page.screenshot({path:'/tmp/model-settings-mobile.png',fullPage:true});
  }finally{await browser.close();}
 }
 console.log(JSON.stringify({http:response.status,code:value.code,pages:value.slides?.length,research:value.research?.status,sources:value.research?.sources?.length,elapsedMs:Date.now()-started,adminVerified,built}));
})().catch(()=>process.exitCode=1);
"""


def run(*args, timeout=360):
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
        "ordinary": (200, None, 1),
        "no-search-key": (200, None, 1),
        "admin": (200, None, 2),
    }
    try:
        with tempfile.TemporaryDirectory(prefix="outline-entry-fixture-") as folder:
            fixture = Path(folder) / "fixture.mjs"
            shutil.copyfile(HERE / "outline-entry-fixture.mjs", fixture)
            os.chmod(fixture, 0o644)
            report["fixture_sha256"] = hashlib.sha256(fixture.read_bytes()).hexdigest()
            for case, (status, code, models) in expected.items():
                name = "yuling-outline-entry-" + uuid.uuid4().hex[:12]
                volume = "yuling-model-entry-" + uuid.uuid4().hex[:12] if case == "admin" else None
                mounts = []
                result = {"case": case, "passed": False}
                report["cases"].append(result)
                try:
                    if volume:
                        run("docker", "volume", "create", "--label", "dev.yuling.test=model-settings", volume)
                        mounts = ["--mount", "type=volume,src=" + volume + ",dst=/var/lib/yuling-ppt/model-settings"]
                    run("docker", "create", "--name", name, "--network", "none",
                        "--cpus", "1", "--memory", "1024m", "--memory-swap", "1024m",
                        "--pids-limit", "256", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                        "-e", "NODE_OPTIONS=--import=/tmp/outline-entry-fixture.mjs",
                        "-e", "OUTLINE_FIXTURE_CASE=" + case,
                        "-e", "DEEPSEEK_API_KEY=fixture-key-not-a-real-credential",
                        "-e", "PPT_PUBLIC_ORIGIN=https://ppt.fixture",
                        "-e", "COS_SECRET_ID=fixture-id", "-e", "COS_SECRET_KEY=fixture-secret",
                        "-e", "COS_BUCKET=fixture-bucket", "-e", "COS_REGION=ap-shanghai",
                        "-e", "PPT_INVITE_PASSWORD=fixture-invite-for-http-test",
                        "-e", "PPT_SESSION_SECRET=fixture-session-secret-for-http-test", *mounts, args.image)
                    run("docker", "cp", fixture, name + ":/tmp/outline-entry-fixture.mjs")
                    run("docker", "start", name)
                    data = json.loads(run("docker", "exec", name, "node", "-e", CLIENT))
                    result.update(data)
                    logs = subprocess.run(["docker", "logs", name], check=True,
                                          capture_output=True, text=True, timeout=20)
                    raw = logs.stdout + logs.stderr
                    if any(value in raw for value in ("PRIVATE_DRAFT_BODY_SENTINEL", "PRIVATE_PROVIDER_BODY_SENTINEL",
                                                       "fixture-key-not-a-real-credential", "fixture-admin-independent-password", "fixture-changed-model-key")):
                        raise AssertionError("Fixture detected sensitive log content")
                    stats = [json.loads(line[len("OUTLINE_FIXTURE "):]) for line in raw.splitlines()
                             if line.startswith("OUTLINE_FIXTURE ")]
                    if not stats or stats[-1] != {"scenario": case, "searches": 0, "models": models, "connections": 1 if case == "admin" else 0}:
                        raise AssertionError("Unexpected search or model invocation count")
                    if data.get("http") != status or data.get("code") != code:
                        raise AssertionError("Public error contract mismatch")
                    if status == 200 and (data.get("pages"), data.get("research")) != (10, "not-required"):
                        raise AssertionError("Response is not a complete ordinary deck")
                    if case == "timeout" and data["elapsedMs"] < 44_000:
                        raise AssertionError("Real 45-second repair deadline was bypassed")
                    container = json.loads(run("docker", "inspect", name))[0]
                    if (container["State"]["OOMKilled"] or container["HostConfig"]["NetworkMode"] != "none"
                            or container["HostConfig"]["Memory"] != 1024**3
                            or container["HostConfig"]["MemorySwap"] != 1024**3
                            or container["Config"]["User"] != "10001:10001"):
                        raise AssertionError("Fixture resource/network boundary failed")
                    if case == "admin" and not (data.get("adminVerified") and data.get("built")):
                        raise AssertionError("Administrator-to-Python-preview chain was not exercised")
                    if case == "admin":
                        shot = args.output.with_name("model-settings-mobile.png")
                        run("docker", "cp", name + ":/tmp/model-settings-mobile.png", shot)
                        result["mobile_ui_checked"] = True
                        run("docker", "rm", "-f", name)
                        spec = importlib.util.spec_from_file_location("model_persistence", HERE / "model-persistence-checks.py")
                        persistence = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(persistence)
                        result["persistence"] = persistence.check(args.image, fixture, volume)
                    result.update({"passed": True, "searches": 0, "models": models, "network": "none"})
                    print("PASS: final-image HTTP " + case + "; simulated providers", flush=True)
                except Exception as error:
                    result["failure"] = {"type": type(error).__name__, "exit_code": getattr(error, "returncode", None)}
                    logs = subprocess.run(["docker", "logs", "--tail", "120", name], capture_output=True, text=True, timeout=20)
                    bounded = (logs.stdout + logs.stderr)[-128000:]
                    for marker in ("PRIVATE_DRAFT_BODY_SENTINEL", "PRIVATE_PROVIDER_BODY_SENTINEL", "fixture-key-not-a-real-credential", "fixture-admin-independent-password", "fixture-changed-model-key", "fixture-session-secret-for-http-test"):
                        bounded = bounded.replace(marker, "[REDACTED_FIXTURE]")
                    args.output.with_name(case + "-failure.log").write_text(bounded, encoding="utf-8")
                    raise
                finally:
                    # Persist status before removing our uniquely named fixture, never another project.
                    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
                    subprocess.run(["docker", "container", "rm", "-f", name], capture_output=True)
                    if volume:
                        subprocess.run(["docker", "volume", "rm", volume], capture_output=True)
        report["passed"] = True
    finally:
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
