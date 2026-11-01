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
import sys
import ast
from http_evidence import atomic_json, checker_digest, failure, resources, validate_report

HERE = Path(__file__).resolve().parent
CLIENT = r"""
let fixtureStep='readiness',fixtureHttp=null;const fixtureStarted=Date.now();
async function fixtureFetch(...args){const r=await fetch(...args);fixtureHttp=r.status;return r;}
(async()=>{
 const base='http://127.0.0.1:5000';
 let ready=false;
 for(let i=0;i<45;i++){
  try{if((await fixtureFetch(base+'/api/health',{signal:AbortSignal.timeout(1000)})).ok){ready=true;break;}}catch{}
  await new Promise(resolve=>setTimeout(resolve,500));
 }
 if(!ready)throw Error('fixture readiness');
 const denied=await fixtureFetch(base+'/api/ppt/outline',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
 if(denied.status!==401)throw Error('authentication boundary');
 fixtureStep='ordinary_login';
 const login=await fixtureFetch(base+'/api/ppt/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:process.env.PPT_INVITE_PASSWORD})});
 if(login.status!==200)throw Error('fixture login');
 const cookie=login.headers.getSetCookie().map(value=>value.split(';')[0]).join('; ');
 let adminVerified=false;
 let managedCookie="";
 if(process.env.OUTLINE_FIXTURE_CASE==='admin'){
  const origin={Origin:'https://ppt.fixture','Content-Type':'application/json',Cookie:cookie};
 fixtureStep='model_read';
  const forbidden=await fixtureFetch(base+'/api/ppt/admin/model-settings',{headers:{Cookie:cookie}});if(forbidden.status!==403)throw Error('ordinary user accessed settings');
 fixtureStep='admin_login';
  const loginAdmin=await fixtureFetch(base+'/api/ppt/admin/session',{method:'POST',headers:origin,body:JSON.stringify({password:'fixture-admin-independent-password'})});
  if(loginAdmin.status!==200)throw Error('admin login');
  const managed=cookie+'; '+loginAdmin.headers.getSetCookie().map(x=>x.split(';')[0]).join('; ');
  managedCookie=managed;
  const headers={...origin,Cookie:managed};
 fixtureStep='model_read';
  const view=await(await fixtureFetch(base+'/api/ppt/admin/model-settings',{headers})).json();
  const config={provider:'openai-compatible',baseUrl:'https://fixture-model.example/v1',model:'fixture-compatible',apiKey:'fixture-changed-model-key',tokenLimitField:'max_completion_tokens'};
 fixtureStep='model_test';
  const test=await fixtureFetch(base+'/api/ppt/admin/model-settings/test',{method:'POST',headers,body:JSON.stringify({config})});if(test.status!==200)throw Error('model connection test');
 fixtureStep='model_save';
  const saved=await fixtureFetch(base+'/api/ppt/admin/model-settings',{method:'PUT',headers,body:JSON.stringify({config,revision:view.revision})});
  const text=await saved.text();if(saved.status!==200||text.includes(config.apiKey))throw Error('saved settings or key leak');
  adminVerified=true;
 }
 fixtureStep='outline_generate';
 const started=Date.now();
 const response=await fixtureFetch(base+'/api/ppt/outline',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({prompt:'调查目前宁波就业市场，形成公开来源的十页培训汇报',pageCount:10,motionMode:'auto',skillId:process.env.OUTLINE_FIXTURE_CASE.startsWith('skill-')?'executive-briefing':'auto'}),signal:AbortSignal.timeout(140000)});
 const value=await response.json();
 let built=false;
 if(adminVerified){
  if(response.status!==200)throw Error('admin configured outline failed');
 fixtureStep='motion_refresh';
  const refreshUrl=base+'/api/ppt/design/refresh';
  const deniedRefresh=await fixtureFetch(refreshUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  if(deniedRefresh.status!==401)throw Error('refresh authentication boundary');
  const invalidRefresh=await fixtureFetch(refreshUrl,{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:'{}'});
  if(invalidRefresh.status!==422)throw Error('refresh invalid input boundary');
  const blocked=structuredClone(value);delete blocked.motionPlan;
  blocked.slides[1]={id:blocked.slides[1].id,type:'process',variant:'ladder',theme:'blue',title:'实施步骤',steps:Array.from({length:6},(_,i)=>({title:`步骤${i+1}`,description:'逐项核对'}))};
  const unavailable=await fixtureFetch(refreshUrl,{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({deck:blocked,mode:'balanced'})});
  const unavailableValue=await unavailable.json();
  if(unavailable.status!==502||Object.keys(unavailableValue).join(',')!=='error'||!unavailableValue.error.includes('动效生成失败'))throw Error('refresh bounded failure contract');
  const originalSlides=JSON.stringify(value.slides),originalFingerprint=value.motionPlan.fingerprint;
  const refreshed=await fixtureFetch(base+'/api/ppt/design/refresh',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({deck:value,mode:'balanced'})});
  const refreshValue=await refreshed.json();
  if(refreshed.status!==200||Object.keys(refreshValue).join(',')!=='motionPlan'||refreshValue.motionPlan.fingerprint===originalFingerprint)throw Error('motion refresh contract');
  value.motionPlan=refreshValue.motionPlan;
  if(JSON.stringify(value.slides)!==originalSlides)throw Error('motion refresh changed pages');
  const {createHash}=await import('node:crypto');
  const signature=createHash('sha256').update(`${value.skill.id}@${value.skill.version}|${value.slides.map(s=>`${s.type}:${s.variant}`).join('|')}`).digest('hex').slice(0,12);
  if(value.motionPlan.layoutSignature!==signature)throw Error('motion refresh signature mismatch');
 fixtureStep='python_build';
  const created=await fixtureFetch(base+'/api/ppt/decks',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify(value),signal:AbortSignal.timeout(240000)});
  const result=await created.json();if(created.status!==200)throw Error('Python build or QA failed: '+JSON.stringify(result));
 fixtureStep='preview';
  const viewer=await fixtureFetch(base+result.viewerUrl,{headers:{Cookie:cookie}});if(viewer.status!==200)throw Error('preview failed');
  const html=await viewer.text();if(!html.includes('iframe'))throw Error('preview iframe missing');
  const content=await fixtureFetch(base+'/api/ppt/decks/'+result.code,{headers:{Cookie:cookie}});
  if(content.status!==200||!(await content.text()).includes('培训规划'))throw Error('stored Python HTML preview missing');
  built=true;
 fixtureStep='mobile_page';
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
   fixtureStep='preview';
   const desktop=await browser.newContext({viewport:{width:1920,height:1080},deviceScaleFactor:1});
   const playback=await desktop.newPage();await playback.goto(base+result.viewerUrl);
   const frame=playback.frames().find(f=>f.url().includes('/api/ppt/decks/'));if(!frame)throw Error('ranking preview frame');
   await frame.waitForSelector('.slide');await frame.evaluate(()=>window.show(7,true));
   await frame.waitForFunction(()=>Array.from(document.querySelectorAll('.slide.active [data-a]')).every(el=>Number(getComputedStyle(el).opacity)>=.94),null,{timeout:10000});
   const rankingFit=await frame.evaluate(()=>{
    const slide=document.querySelector('.slide.active');const svg=slide.querySelector('figure[data-chart="ranking"] svg');if(!svg)return false;const bounds=svg.getBoundingClientRect();
    const titles=Array.from(slide.querySelectorAll('.ai-podium-card strong')).every(el=>el.getBoundingClientRect().width>=parseFloat(getComputedStyle(el).fontSize)*2);
    const values=Array.from(svg.querySelectorAll('text')).every(el=>{const box=el.getBoundingClientRect();return box.left>=bounds.left-3&&box.right<=bounds.right+3;});
    return titles&&values&&slide.querySelector('.ai-data-meta').textContent.includes('单位：报名指数（演示）');
   });if(!rankingFit)throw Error('ranking descriptive unit clipping');
   await playback.screenshot({path:'/tmp/ranking-unit-fit.png'});await desktop.close();
   fixtureStep='mobile_playback';
   const {checkMobilePlayback}=await import('/tmp/mobile-playback-check.mjs');
   // The HTTP fixture can choose a deck without step nodes; the golden fixture requires them.
   await checkMobilePlayback(browser,base+result.viewerUrl,'no-preference',false);
   await checkMobilePlayback(browser,base+result.viewerUrl,'reduce',false);

  }finally{await browser.close();}
 }
 console.log(JSON.stringify({http:response.status,code:value.code,pages:value.slides?.length,research:value.research?.status,sources:value.research?.sources?.length,elapsedMs:Date.now()-started,adminVerified,built}));
})().catch(error=>{
 const playbackLine = fixtureStep === 'mobile_playback' && typeof error?.stack === 'string'
   ? error.stack.match(/^\s*at (?:[^\n(]* \()?(?:file:\/\/)?\/tmp\/mobile-playback-check\.mjs:([1-9]\d{0,3}):\d+\)?$/m)
   : null;
 console.log(JSON.stringify({fixture_failure:true,step:fixtureStep,http:fixtureHttp,
  ...(playbackLine ? {playbackLine:Number(playbackLine[1])} : {}),
  kind:error?.name==='TimeoutError'||error?.name==='AbortError'?'timeout':error?.name==='TypeError'?'runtime_error':'assertion',elapsedMs:Date.now()-fixtureStarted}));
 process.exitCode=1;
});
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
    report = {"schema": 1, "checker_sha256": checker_digest(HERE), "simulated_providers": True, "cloud_calls": 0,
              "app_sha": image["Config"].get("Labels", {}).get("org.opencontainers.image.revision"),
              "image_id": image["Id"], "cases": [], "passed": False}
    expected = {
        "repair": (200, None, 2), "invalid": (502, "PPT_OUTLINE_INVALID", 2),
        "timeout": (504, "PPT_MODEL_TIMEOUT", 2), "upstream": (502, None, 2),
        "json": (502, "PPT_OUTLINE_INVALID", 2), "truncated": (502, "PPT_OUTLINE_INVALID", 2),
        "ordinary": (200, None, 1),
        "no-search-key": (200, None, 1),
        "admin": (200, None, 2),
        "highlight-repair": (200, None, 2), "skill-repair": (200, None, 2),
        "skill-invalid": (422, "PPT_SKILL_UNSUPPORTED", 2), "json-repair": (200, None, 2),
    }
    try:
        with tempfile.TemporaryDirectory(prefix="outline-entry-fixture-") as folder:
            fixture = Path(folder) / "fixture.mjs"
            playback = Path(folder) / "mobile-playback-check.mjs"
            # docker cp preserves mode. Only the two test programs in this
            # private staging directory need to be readable by the image UID.
            for source, staged in ((HERE / "outline-entry-fixture.mjs", fixture),
                                   (HERE / playback.name, playback)):
                shutil.copyfile(source, staged)
                os.chmod(staged, 0o644)
            # Test-only reverse map is derived from the canonical source rather
            # than maintaining another copy of the engine instrumentation.
            patches = (HERE.parents[1] / "src/lib/ppt/mobile-playback-lifecycle.ts").read_text()
            pairs = ast.literal_eval('[' + patches.split('export const playbackRewrites:', 1)[1].split('= [', 1)[1].rsplit('];', 1)[0] + ']')
            fixture.write_text("const playbackFixtureRewrites=" + json.dumps(pairs) + ";\n" + fixture.read_text())
            report["fixture_sha256"] = hashlib.sha256(fixture.read_bytes()).hexdigest()
            for case, (status, code, models) in expected.items():
                name = "yuling-outline-entry-" + uuid.uuid4().hex[:12]
                volume = "yuling-model-entry-" + uuid.uuid4().hex[:12] if case == "admin" else None
                mounts = []
                result = {"case": case, "passed": False, "step": "container_start"}
                keep_fixture = False
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
                    if case == "admin":
                        run("docker", "cp", playback, name + ":/tmp/mobile-playback-check.mjs")
                    run("docker", "start", name)
                    result["step"] = "http_client"
                    data = json.loads(run("docker", "exec", name, "node", "-e", CLIENT))
                    result.update(data)
                    result["step"] = "contract_check"
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
                    attempts = [json.loads(line[len("ppt_outline_attempt "):]) for line in raw.splitlines()
                                if line.startswith("ppt_outline_attempt ")]
                    if len(attempts) != models or [a['attempt'] for a in attempts] != list(range(1, models + 1)):
                        raise AssertionError("Missing or duplicated per-attempt accounting")
                    if len({a['requestId'] for a in attempts}) != 1:
                        raise AssertionError("Attempt request identity mismatch")
                    for index, attempt in enumerate(attempts):
                        expected_success = status == 200 and index == models - 1
                        if attempt['outcome'] != ('success' if expected_success else 'failure'):
                            raise AssertionError("Incorrect attempt outcome")
                        unknown_usage = case == 'upstream' or case == 'timeout' and index == 1
                        expected_usage = None if unknown_usage else dict(promptTokens=100, completionTokens=50,
                            totalTokens=150, cacheHitTokens=80, cacheMissTokens=20, reasoningTokens=5)
                        if attempt.get('usage') != expected_usage:
                            raise AssertionError("Provider usage was invented, lost or double counted")
                    if case in ('highlight-repair', 'skill-repair', 'skill-invalid', 'json-repair'):
                        expected_category = {'highlight-repair': 'schema', 'json-repair': 'json'}.get(case, 'skill')
                        if attempts[0].get('category') != expected_category:
                            raise AssertionError("Repair classification mismatch")
                    if status != 200 and data.get('built'):
                        raise AssertionError("Failed outline entered courseware build")
                    if status == 200 and (data.get("pages"), data.get("research")) != (10, "not-required"):
                        raise AssertionError("Response is not a complete ordinary deck")
                    if case == "timeout" and data["elapsedMs"] < 44_000:
                        raise AssertionError("Real 45-second repair deadline was bypassed")
                    result["step"] = "resource_check"
                    result["resources"] = resources(name)
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
                        run("docker", "cp", name + ":/tmp/ranking-unit-fit.png", args.output.with_name("ranking-unit-fit.png"))
                        result["mobile_ui_checked"] = True
                        run("docker", "rm", "-f", name)
                        spec = importlib.util.spec_from_file_location("model_persistence", HERE / "model-persistence-checks.py")
                        persistence = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(persistence)
                        result["step"] = "persistence"
                        def record(detail):
                            result.update(detail)
                            atomic_json(args.output, validate_report(report, report["app_sha"]))
                        result["persistence"] = persistence.check(args.image, fixture, volume, record)
                    result.update({"passed": True, "step": "complete", "searches": 0, "models": models, "network": "none"})
                    print("PASS: final-image HTTP " + case + "; simulated providers", flush=True)
                except Exception as error:
                    result.update(failure(error, result["step"]))
                    if "resources" not in result:
                        result["resources"] = resources(name)
                    raise SystemExit(1) from None
                finally:
                    try:
                        atomic_json(args.output, validate_report(report, report["app_sha"]))
                    except Exception:
                        keep_fixture = True
                        print(json.dumps({"event": "diagnostic_save_failed", "retained_container": name}), file=sys.stderr)
                        raise SystemExit(1) from None
                    finally:
                        if not keep_fixture:
                            subprocess.run(["docker", "container", "rm", "-f", name], capture_output=True)
                            if volume:
                                subprocess.run(["docker", "volume", "rm", volume], capture_output=True)
        report["passed"] = True
    finally:
        atomic_json(args.output, validate_report(report, report["app_sha"]))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print('{"event":"http_evidence_unavailable"}', file=sys.stderr)
        raise SystemExit(1) from None
