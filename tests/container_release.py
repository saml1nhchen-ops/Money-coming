"""Optional isolated Docker maintenance/restart integration; never calls models."""
import json,os,pathlib,secrets,subprocess,tempfile,time
base=['docker','--host=unix:///var/run/docker.sock'];env=os.environ.copy()
for name in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'):env.pop(name,None)
image=env.get('SIGNAL_TEST_IMAGE','signal-geo-backend:release-check');suffix=secrets.token_hex(4);name='signal-release-check-'+suffix;volume=name+'-runtime';nonce='a'*32;revision='a'*40
# This password is synthetic, ephemeral and never printed or passed as argv.
env['SIGNAL_WORKSPACE_PASSWORD']=secrets.token_urlsafe(24)
def docker(*args,check=True):return subprocess.run(base+list(args),env=env,text=True,capture_output=True,check=check)
def execute(code):return docker('exec',name,'python3','-c',code)
def wait_health():
 code="import json,urllib.request as u;op=u.build_opener(u.ProxyHandler({}));r=op.open(u.Request('http://127.0.0.1:8080/healthz',headers={'Host':'backend.test'}),timeout=2);print(r.read().decode())"
 for _ in range(100):
  r=docker('exec',name,'python3','-c',code,check=False)
  if r.returncode==0:return json.loads(r.stdout)
  time.sleep(.15)
 raise AssertionError('Isolated service did not start')
def state():
 code="""import os,json,urllib.request as u
op=u.build_opener(u.ProxyHandler({}));base='http://127.0.0.1:8080';headers={'Host':'backend.test','Content-Type':'application/json'}
def call(path,body=None):
 with op.open(u.Request(base+path,None if body is None else json.dumps(body).encode(),headers),timeout=3) as r:return json.load(r)
token=call('/api/workspace/login',{'password':os.environ['SIGNAL_WORKSPACE_PASSWORD']})['token'];headers['Authorization']='Bearer '+token
s=call('/api/geo/state');print(json.dumps({'maintenance':s['remote']['maintenance'],'gate':s['remote']['deployment_gate'],'model_ready':s['remote']['model_ready']}));call('/api/workspace/logout',{})
"""
 return json.loads(execute(code).stdout)
def send(value):
 code="""import os,pathlib,signal
pids=[]
for p in pathlib.Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:a=(p/'cmdline').read_bytes().split(b'\\0')
 except OSError:continue
 if len(a)>1 and pathlib.PurePath(os.fsdecode(a[0])).name.startswith('python') and a[1] in (b'tools/remote_service.py',b'/app/tools/remote_service.py'):pids.append(int(p.name))
assert len(pids)==1
os.kill(pids[0],signal."""+value+")"
 execute(code);time.sleep(.1)
with tempfile.TemporaryDirectory(prefix='signal-admission-') as folder:
 p=pathlib.Path(folder);p.chmod(0o755)
 try:
  docker('run','-d','--init','--name',name,'--network','none','--mount','type=volume,src='+volume+',dst=/app/runtime','--mount','type=bind,src='+folder+',dst=/run/signal-deploy,readonly','-e','SIGNAL_WORKSPACE_PASSWORD','-e','SIGNAL_BAI_API_KEY=','-e','SIGNAL_PUBLIC_HOST=backend.test','-e','SIGNAL_DEPLOY_MAINTENANCE=1','-e','SIGNAL_DEPLOY_NONCE='+nonce,image)
  h=wait_health();assert h=={'ok':True,'revision':revision,'version':'release-check','capabilities':{'remember_login':True,'remember_login_max_age_seconds':2592000,'diagnostics_v1':True,'claude_available':False,'analysis_manufacturers':[]}},h
  assert state()=={'maintenance':True,'gate':'signals-v1','model_ready':False}
  probe=docker('exec',name,'python3','tools/deploy_control.py','probe');assert json.loads(probe.stdout)['maintenance']
  health=docker('exec',name,'python3','tools/deploy_control.py','health','--timeout','.2',check=False);assert health.returncode!=0 and json.loads(health.stdout)=={'ok':False,'code':'health_timeout'},health.stdout
  send('SIGUSR2');assert state()['maintenance'] is False
  send('SIGUSR1');assert state()['maintenance'] is True
  receipt=p/'healthy.json'
  def reboot(value):
   receipt.write_text(json.dumps(value));receipt.chmod(0o644);docker('restart','-t','20',name);wait_health();return state()['maintenance']
  assert reboot({'status':'healthy','nonce':'b'*32,'revision':revision}) is True
  assert reboot({'status':'healthy','nonce':nonce,'revision':revision}) is False
  assert reboot({'status':'healthy','nonce':nonce,'revision':'b'*40}) is True
  print('PASS: isolated real Docker init/supervisor signals, startup maintenance, private gate, missing-key health rejection, wrong nonce/revision rejection and healthy-receipt reboot recovery. No network or model calls.')
 finally:
  docker('rm','-f',name,check=False);docker('volume','rm',volume,check=False)
