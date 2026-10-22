"""Isolated production container audit persistence check; no external network/models."""
import json,os,pathlib,secrets,subprocess,time
base=['docker','--host=unix:///var/run/docker.sock'];env=os.environ.copy()
for key in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'):env.pop(key,None)
env['SIGNAL_WORKSPACE_PASSWORD']=secrets.token_urlsafe(24)
name='signal-audit-check-'+secrets.token_hex(4);volume=name+'-runtime'
def docker(*args):return subprocess.run(base+list(args),env=env,text=True,capture_output=True,check=True).stdout.strip()
def execute(code):return docker('exec',name,'python3','-c',code)
def healthy():
 for _ in range(80):
  try:
   execute("import urllib.request as u;u.build_opener(u.ProxyHandler({})).open('http://127.0.0.1:8080/healthz',timeout=2).read()");return
  except subprocess.CalledProcessError:time.sleep(.2)
 raise AssertionError('Container not healthy')
try:
 docker('run','-d','--name',name,'--network','none','--mount','type=volume,src='+volume+',dst=/app/runtime','-e','SIGNAL_WORKSPACE_PASSWORD','-e','SIGNAL_PUBLIC_HOST=backend.test','-e','SIGNAL_BAI_API_KEY=',env.get('SIGNAL_TEST_IMAGE','signal-geo-backend:geo-audit-check'))
 healthy()
 probe='''import importlib.metadata,json,os,pathlib,time,urllib.request as u,uuid
assert importlib.metadata.version('protego')=='0.7.0'
assert importlib.metadata.version('trafilatura')=='2.3.1'
op=u.build_opener(u.ProxyHandler({}));headers={'Host':'backend.test','Origin':'https://saml1nhchen-ops.github.io','Content-Type':'application/json'}
def call(path,body=None):
 with op.open(u.Request('http://127.0.0.1:8080'+path,None if body is None else json.dumps(body).encode(),headers),timeout=5) as r:return json.load(r)
login=call('/api/workspace/login',{'password':os.environ['SIGNAL_WORKSPACE_PASSWORD'],'remember':True});headers['Authorization']='Bearer '+login['token']
assert call('/api/geo/state')['remote']['reason']=='missing_bai_key'
a=call('/api/geo/audit',{'website':'https://example.com/','market':'US','request_id':str(uuid.uuid4())})
def done(ident):
 for _ in range(400):
  a=call('/api/geo/audit?id='+ident)
  if a['status'] not in ('running','queued'):return a
  time.sleep(.1)
 raise AssertionError('Audit timed out')
a=done(a['id']);assert a['status']=='awaiting_confirmation'
call('/api/geo/audit-confirm',{'id':a['id'],'confirmed':{'brand':{'name':'','aliases':[]},'products':[],'competitors':[],'context':''}})
a=done(a['id']);export=call('/api/geo/audit-export?id='+a['id']);assert a==export and a['report']['summary']['score'] is None and a['usage']['model_calls']==0
assert call('/api/geo/state')['remote']['budget']['reserved']==0
pathlib.Path('runtime/audit-validation.json').write_text(json.dumps({'id':a['id'],'token':login['token'],'export':a}))
print('Keyless production audit, unknown report and full export passed')
'''
 print(execute(probe));docker('restart','-t','20',name);healthy()
 print(execute('''import json,urllib.request as u
from pathlib import Path
saved=json.loads(Path('runtime/audit-validation.json').read_text());op=u.build_opener(u.ProxyHandler({}));headers={'Host':'backend.test','Origin':'https://saml1nhchen-ops.github.io','Authorization':'Bearer '+saved['token']}
with op.open(u.Request('http://127.0.0.1:8080/api/geo/audit-export?id='+saved['id'],headers=headers),timeout=5) as r:assert json.load(r)==saved['export']
print('Confirmed audit and trusted-device session survived actual container restart; 0 model calls.')
'''))
finally:
 subprocess.run(base+['rm','-f',name],env=env,capture_output=True);subprocess.run(base+['volume','rm',volume],env=env,capture_output=True)
