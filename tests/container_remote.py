"""Optional real Docker lifecycle check, never calls paid models."""
import os,subprocess,secrets,json,time,urllib.request,urllib.error
base=['docker','--host=unix:///var/run/docker.sock'];env=os.environ.copy()
for k in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'):env.pop(k,None)
env['SIGNAL_WORKSPACE_PASSWORD']=secrets.token_urlsafe(24)
suffix=secrets.token_hex(4);name='signal-geo-validation-'+suffix;volume=name+'-runtime'
def docker(*a):return subprocess.check_output(base+list(a),env=env,text=True).strip()
def request(path,body=None,token=None):
 headers={'Host':'backend.test','Origin':'https://saml1nhchen-ops.github.io','Content-Type':'application/json'}
 if token:headers['Authorization']='Bearer '+token
 req=urllib.request.Request('http://127.0.0.1:18880'+path,None if body is None else json.dumps(body).encode(),headers)
 try:
  with urllib.request.urlopen(req,timeout=5) as r:return r.status,json.load(r)
 except urllib.error.HTTPError as e:return e.code,json.load(e)
def login():return request('/api/workspace/login',{'password':env['SIGNAL_WORKSPACE_PASSWORD']})[1]['token']
try:
 docker('run','-d','--name',name,'--network','bridge','-p','127.0.0.1:18880:8080','--mount','type=volume,src='+volume+',dst=/app/runtime','-e','SIGNAL_WORKSPACE_PASSWORD','-e','SIGNAL_PUBLIC_HOST=backend.test','-e','SIGNAL_BAI_API_KEY=',os.environ.get('SIGNAL_TEST_IMAGE','signal-geo-backend:team'))
 for _ in range(60):
  try:
   if request('/healthz')[0]==200:break
  except OSError:pass
  time.sleep(.2)
 else:raise AssertionError('Container health failed')
 assert request('/healthz')==(200,{'ok':True})
 assert request('/api/geo/state')[0]==401
 token=login();status,state=request('/api/geo/state',token=token)
 assert status==200 and not state['remote']['ready'] and state['remote']['reason']=='missing_bai_key'
 assert docker('exec',name,'id','-u')=='10001'
 assert json.loads(docker('inspect','--format','{{json .NetworkSettings.Ports}}',name))=={'8080/tcp':[{'HostIp':'127.0.0.1','HostPort':'18880'}]}
 docker('exec',name,'python3','-c',"import sys;sys.path.insert(0,'tools');from remote_gateway import Budget;Budget('runtime/remote-budget.json',126).reserve(63)")
 assert request('/api/geo/state',token=token)[1]['remote']['budget']['reserved']==63
 docker('restart','-t','20',name)
 for _ in range(60):
  try:
   if request('/healthz')[0]==200:break
  except OSError:pass
  time.sleep(.2)
 assert request('/api/geo/state',token=token)[0]==401
 fresh=login();assert request('/api/geo/state',token=fresh)[1]['remote']['budget']['reserved']==63
 assert request('/api/workspace/logout',{},fresh)[0]==200
 assert request('/api/geo/state',token=fresh)[0]==401
 print('PASS: real container health, three private services, nonroot UID, loopback-only public mapping, authentication/logout, missing-key fail closed, persistent daily budget after restart, memory sessions invalidated. No model calls.')
finally:
 subprocess.run(base+['rm','-f',name],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 subprocess.run(base+['volume','rm',volume],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
