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
def login(remember=None):
 body={'password':env['SIGNAL_WORKSPACE_PASSWORD']}
 if remember is not None:body['remember']=remember
 status,result=request('/api/workspace/login',body)
 assert status==200 and result['remembered']==bool(remember)
 return result['token']
try:
 docker('run','-d','--name',name,'--network','bridge','-p','127.0.0.1:18880:8080','--mount','type=volume,src='+volume+',dst=/app/runtime','-e','SIGNAL_WORKSPACE_PASSWORD','-e','SIGNAL_PUBLIC_HOST=backend.test','-e','SIGNAL_BAI_API_KEY=',os.environ.get('SIGNAL_TEST_IMAGE','signal-geo-backend:team'))
 for _ in range(60):
  try:
   if request('/healthz')[0]==200:break
  except OSError:pass
  time.sleep(.2)
 else:raise AssertionError('Container health failed')
 status,health=request('/healthz')
 assert status==200 and health['ok'] is True
 assert health['capabilities']=={'remember_login':True,'remember_login_max_age_seconds':2592000,'diagnostics_v1':True,'claude_available':False,'analysis_manufacturers':[],'analysis_all_models':True,'analysis_max_models':0}
 assert request('/api/geo/state')[0]==401
 durable=login(True);other_device=login(True)
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
 assert request('/api/geo/state',token=durable)[0]==200
 assert request('/api/geo/state',token=other_device)[0]==200
 assert request('/api/workspace/logout',{},durable)==(200,{'ok':True})
 assert request('/api/geo/state',token=durable)[0]==401
 assert request('/api/geo/state',token=other_device)[0]==200
 fresh=login();assert request('/api/geo/state',token=fresh)[1]['remote']['budget']['reserved']==63
 assert request('/api/workspace/logout',{},fresh)[0]==200
 assert request('/api/geo/state',token=fresh)[0]==401
 print('PASS: real container health, three private services, nonroot UID, loopback-only public mapping, authentication/logout, missing-key fail closed, persistent daily budget and trusted device sessions after restart, legacy sessions invalidated, one-device durable logout. No model calls.')
finally:
 subprocess.run(base+['rm','-f',name],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 subprocess.run(base+['volume','rm',volume],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
