"""Actual nonroot production container: durable diagnosis/share/session restart.

The container has no network or vendor key. Unreadable pages stay unknown.
"""
import os
import secrets
import subprocess
import time

BASE = ['docker', '--host=unix:///var/run/docker.sock']
ENV = os.environ.copy()
for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
    ENV.pop(key, None)
ENV['SIGNAL_WORKSPACE_PASSWORD'] = secrets.token_urlsafe(24)
NAME = 'signal-diagnostic-check-' + secrets.token_hex(4)
VOLUME = NAME + '-runtime'


def docker(*args):
    return subprocess.run(BASE + list(args), env=ENV, text=True, capture_output=True, check=True).stdout.strip()


def execute(code):
    return docker('exec', NAME, 'python3', '-c', code)


def healthy():
    for _ in range(240):
        try:
            execute("import urllib.request as u;u.build_opener(u.ProxyHandler({})).open('http://127.0.0.1:8080/healthz',timeout=2).read()")
            return
        except subprocess.CalledProcessError:
            time.sleep(.2)
    raise AssertionError('Container not healthy')


PRELUDE = '''import json,os,pathlib,time,urllib.request as u,urllib.error,uuid
op=u.build_opener(u.ProxyHandler({}));headers={'Host':'backend.test','Origin':'https://saml1nhchen-ops.github.io','Content-Type':'application/json'}
def call(path,body=None):
 with op.open(u.Request('http://127.0.0.1:8080'+path,None if body is None else json.dumps(body).encode(),headers),timeout=10) as r:return json.load(r)
def done(path):
 for _ in range(600):
  value=call(path)
  if value['status'] not in ('queued','running'):return value
  time.sleep(.1)
 raise AssertionError('Diagnostic timed out')
'''

try:
    docker('run', '-d', '--name', NAME, '--network', 'none', '--mount', 'type=volume,src=' + VOLUME + ',dst=/app/runtime', '-e', 'SIGNAL_WORKSPACE_PASSWORD', '-e', 'SIGNAL_PUBLIC_HOST=backend.test', '-e', 'SIGNAL_BAI_API_KEY=', ENV.get('SIGNAL_TEST_IMAGE', 'signal-geo-backend:diagnostic-check'))
    healthy()
    print(execute(PRELUDE + '''
assert os.getuid()==10001
login=call('/api/workspace/login',{'password':os.environ['SIGNAL_WORKSPACE_PASSWORD'],'remember':True});headers['Authorization']='Bearer '+login['token']
clients=call('/api/clients',{'name':'Container verification'})['clients'];cid=next(c['id'] for c in clients if not c['internal'])
projects=call('/api/projects',{'client_id':cid,'name':'Durable report'})['projects'];pid=next(p['id'] for p in projects if not p['internal'])
a=call('/api/geo/audit',{'website':'https://example.com/','market':'US','request_id':str(uuid.uuid4())});a=done('/api/geo/audit?id='+a['id'])
payload={'audit_id':a['id'],'project_id':pid,'request_id':str(uuid.uuid4()),'profile_ids':[],'mode':'website','confirmed':{'brand':{'name':'Container brand','aliases':['Container brand']},'products':[],'competitors':[],'context':''}}
d=call('/api/diagnostics',payload);assert call('/api/diagnostics',payload)['id']==d['id'];d=done('/api/diagnostics/detail?id='+d['id'])
assert d['bundle']['schema_version']=='v0.1' and d['summary']['total'] is None and not d['bundle']['answers']
assert d['plan']['maximum_calls']==0
share=call('/api/diagnostics/share',{'id':d['id']})
pathlib.Path('runtime/diagnostic-validation.json').write_text(json.dumps({'id':d['id'],'token':login['token'],'share':share,'bundle':d['bundle']}))
print('Real production container: keyless bounded diagnostic, project, unknown scores and immutable share created; zero model calls.')
'''))
    docker('restart', '-t', '20', NAME)
    healthy()
    print(execute(PRELUDE + '''
saved=json.loads(pathlib.Path('runtime/diagnostic-validation.json').read_text());headers['Authorization']='Bearer '+saved['token']
d=call('/api/diagnostics/detail?id='+saved['id']);assert d['bundle']==saved['bundle']
assert any(v['id']==d['id'] for v in call('/api/diagnostics')['diagnostics'])
headers.pop('Authorization');shared=call('/api/shared-report?token='+saved['share']['share_token']);assert shared['diagnostic']['brand']=='Container brand'
assert 'project_id' not in shared['diagnostic'] and 'config' not in shared['diagnostic']
headers['Authorization']='Bearer '+saved['token'];call('/api/diagnostics/revoke',{'share_id':saved['share']['share_id']});headers.pop('Authorization')
try:call('/api/shared-report?token='+saved['share']['share_token']);raise AssertionError('Revoked report accessible')
except urllib.error.HTTPError as e:assert e.code==404
print('Actual container restart preserves report, project, share and device session; anonymous view is scoped and revocation works.')
'''))
finally:
    subprocess.run(BASE + ['rm', '-f', NAME], env=ENV, capture_output=True)
    subprocess.run(BASE + ['volume', 'rm', VOLUME], env=ENV, capture_output=True)
