"""Recreate a disconnected application over its test volume, then prove read-only behavior."""
import json
import subprocess
import uuid

CLIENT = r"""
(async()=>{
 const base='http://127.0.0.1:5000';
 for(let i=0;i<45;i++){
  try{if((await fetch(base+'/api/health')).ok)break;}catch{}
  if(i===44)throw Error('readiness');await new Promise(r=>setTimeout(r,500));
 }
 const ordinary=await fetch(base+'/api/ppt/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:process.env.PPT_INVITE_PASSWORD})});
 const cookie=ordinary.headers.getSetCookie().map(x=>x.split(';')[0]).join('; ');
 const headers={Cookie:cookie,Origin:'https://ppt.fixture','Content-Type':'application/json'};
 const admin=await fetch(base+'/api/ppt/admin/session',{method:'POST',headers,body:JSON.stringify({password:'fixture-admin-independent-password'})});
 if(admin.status!==200)throw Error('admin');
 headers.Cookie+='; '+admin.headers.getSetCookie().map(x=>x.split(';')[0]).join('; ');
 const view=await(await fetch(base+'/api/ppt/admin/model-settings',{headers})).json();
 if(view.model!=='fixture-compatible'||view.source!=='saved'||!view.apiKeyConfigured)throw Error('persisted settings missing');
 const {revision,source,apiKeyConfigured,...config}=view;
 const failed=await fetch(base+'/api/ppt/admin/model-settings',{method:'PUT',headers,body:JSON.stringify({revision,config:{...config,apiKey:''}})});
 if(failed.status!==503)throw Error('read-only write was not rejected');
 const after=await(await fetch(base+'/api/ppt/admin/model-settings',{headers})).json();
 if(after.revision!==revision)throw Error('failed write changed settings');
 const fs=await import('node:fs');const s=fs.statSync('/var/lib/yuling-ppt/model-settings/settings.json');
 if((s.mode&0o777)!==0o600||s.uid!==10001)throw Error('settings file permissions');
 console.log(JSON.stringify({recreated_config_preserved:true,read_only_write_rejected:true,source,key_returned:JSON.stringify(view).includes('fixture-changed-model-key')}));
})().catch(()=>process.exitCode=1);
"""


def check(image, fixture, volume):
    name = 'yuling-settings-recreate-' + uuid.uuid4().hex[:12]
    def run(*args):
        return subprocess.run(list(map(str, args)), check=True, capture_output=True, text=True, timeout=120).stdout
    try:
        run('docker', 'create', '--name', name, '--network', 'none',
            '--cpus', '1', '--memory', '1024m', '--memory-swap', '1024m',
            '--pids-limit', '256', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--mount', 'type=volume,src=' + volume + ',dst=/var/lib/yuling-ppt/model-settings,readonly',
            '-e', 'NODE_OPTIONS=--import=/tmp/outline-entry-fixture.mjs', '-e', 'OUTLINE_FIXTURE_CASE=admin',
            '-e', 'DEEPSEEK_API_KEY=fixture-key-not-a-real-credential',
            '-e', 'PPT_PUBLIC_ORIGIN=https://ppt.fixture', '-e', 'PPT_INVITE_PASSWORD=fixture-invite-for-http-test',
            '-e', 'PPT_SESSION_SECRET=fixture-session-secret-for-http-test', image)
        run('docker', 'cp', fixture, name + ':/tmp/outline-entry-fixture.mjs')
        run('docker', 'start', name)
        result = json.loads(run('docker', 'exec', name, 'node', '-e', CLIENT))
        detail = json.loads(run('docker', 'inspect', name))[0]
        mount = next(x for x in detail['Mounts'] if x['Destination'] == '/var/lib/yuling-ppt/model-settings')
        if mount['RW'] or result.get('key_returned') or detail['State']['OOMKilled']:
            raise AssertionError('Persistent/read-only isolation failed')
        return result
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True)
