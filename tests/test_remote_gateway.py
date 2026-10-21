import concurrent.futures,http.client,json,os,pathlib,sys,tempfile,threading,time,unittest,uuid
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
from remote_gateway import Budget,Failure,LocalAPI,Server,Workspace,ORIGIN
class FakeAPI:
 def __init__(self):self.busy=False;self.starts=0;self.fail=False
 def call(self,service,path,body=None):
  if path=='state':return {'runner':{'profiles':[]},'busy':self.busy,'runs':[]}
  if path=='plan':return {'maximum_calls':(0 if body.get('manual') else 3)+(0 if body.get('generate_only') else 30*len(body['providers']))}
  if path in ('start','sample'):
   self.starts+=1
   if self.fail:raise Failure(502,'upstream_failed')
   self.busy=True;return {'id':str(uuid.uuid4()),'status':'queued','config':body}
  if path.startswith(('run?','export?')):return {'status':'running','error':'raw secret provider error','headers':{'Authorization':'vendor-key'}}
  return {'status':'stop_requested'}
class HTTPTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.api=FakeAPI();self.w=Workspace('sixteen-character-password','public.example',Budget(pathlib.Path(self.tmp.name)/'budget.json',126),self.api);self.w.ready=True;self.w.reason=None;self.w.profiles=[{'id':'gpt'},{'id':'gemini'}]
  self.server=Server(('127.0.0.1',0),self.w);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
 def request(self,path,body=None,token=None,origin=ORIGIN,method=None,extra=None):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3);headers={'Host':'public.example'}
  if origin is not None:headers['Origin']=origin
  if token:headers['Authorization']='Bearer '+token
  if body is not None:headers['Content-Type']='application/json'
  headers.update(extra or {});c.request(method or ('POST' if body is not None else 'GET'),path,None if body is None else json.dumps(body),headers);r=c.getresponse();raw=r.read();h=dict(r.getheaders());c.close();return r.status,json.loads(raw) if raw else {},h
 def login(self):
  status,d,_=self.request('/api/workspace/login',{'password':'sixteen-character-password'});self.assertEqual(status,200);return d['token']
 def payload(self):return {'website':'https://cremocompany.com/','market':'US','brand_aliases':['Cremo'],'providers':['gpt','gemini'],'generator':'gpt','count':30,'repeats':1}
 def test_auth_origin_and_routes(self):
  for path in ('state','run?id='+str(uuid.uuid4()),'export?id='+str(uuid.uuid4())):self.assertEqual(self.request('/api/geo/'+path)[0],401)
  t=self.login();self.assertEqual(self.request('/api/geo/state',token=t,origin='null')[0],403);self.assertEqual(self.request('/api/geo/state',token=t,origin=None)[0],200)
  for path in ('/api/geo/session','/api/bai/state','/api/tools/session','/api/geo/resume'):self.assertEqual(self.request(path,{},t)[0],404)
  self.assertEqual(self.request('/api/geo/state?x=1',token=t)[0],400)
  self.assertEqual(self.request('/api/workspace/logout',{},t)[0],200);self.assertEqual(self.request('/api/geo/state',token=t)[0],401)
 def test_preflight_and_host(self):
  status,d,h=self.request('/api/geo/state',method='OPTIONS',extra={'Access-Control-Request-Method':'GET','Access-Control-Request-Headers':'Authorization'});self.assertEqual(status,204);self.assertNotIn('token',str(d));self.assertEqual(h['Access-Control-Allow-Origin'],ORIGIN)
  self.assertEqual(self.request('/healthz',extra={'Host':'evil.example'})[0],403)
 def test_limits_and_expiration(self):
  t=self.login();self.w.sessions[t]=time.time()-1;self.assertEqual(self.request('/api/geo/state',token=t)[0],401)
  for _ in range(4):self.assertEqual(self.request('/api/workspace/login',{'password':'wrong'})[0],401)
  self.assertEqual(self.request('/api/workspace/login',{'password':'wrong'})[0],429)
 def test_validation_concurrency_budget(self):
  t=self.login()
  for change in ({'count':31},{'repeats':2},{'providers':['gpt','gemini','third']},{'generator':'bad'},{'configuration':{}},{'market':'invalid'}):self.assertEqual(self.request('/api/geo/start',{**self.payload(),**change},t)[0],400)
  def start(_):return self.request('/api/geo/start',self.payload(),t)[0]
  with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(start,range(8)))
  self.assertEqual(results.count(202),1);self.assertEqual(results.count(409),7);self.assertEqual(self.api.starts,1);self.assertEqual(self.w.budget.state()['reserved'],63)
  reload=Budget(self.w.budget.path,126);self.assertEqual(reload.state()['reserved'],63)
 def test_failure_not_refunded_and_corruption_closed(self):
  t=self.login();self.api.fail=True
  self.assertEqual(self.request('/api/geo/start',self.payload(),t)[0],502);self.assertEqual(self.w.budget.state()['reserved'],63)
  self.w.budget.path.write_text('broken');self.assertEqual(self.request('/api/geo/start',self.payload(),t)[0],503);self.assertEqual(self.api.starts,1)
 def test_export_redacts_and_shared_tokens(self):
  a=self.login();b=self.login();rid=str(uuid.uuid4());status,d,_=self.request('/api/geo/export?id='+rid,token=b);self.assertEqual(status,200);self.assertNotIn('raw secret',str(d));self.assertNotIn('vendor-key',str(d));self.assertEqual(self.request('/api/geo/stop',{'id':rid},a)[0],200)
 def test_sample_and_budget_exhaustion(self):
  t=self.login();p={**self.payload(),'prompts':['question '+str(i) for i in range(30)]}
  self.assertEqual(self.request('/api/geo/sample',{**p,'prompts':p['prompts']+['extra']},t)[0],400)
  self.assertEqual(self.request('/api/geo/sample',p,t)[0],202);self.assertEqual(self.w.budget.state()['reserved'],60)
  self.api.busy=False;self.w.active=None;self.w.budget.reserve(66)
  self.assertEqual(self.request('/api/geo/start',self.payload(),t)[0],429)
 def test_shutdown_during_plan_never_reserves_or_submits(self):
  entered=threading.Event();release=threading.Event();original=self.api.call
  def blocked(service,path,body=None):
   if path=='plan':entered.set();self.assertTrue(release.wait(2))
   return original(service,path,body)
  self.api.call=blocked;t=self.login();result=[]
  request=threading.Thread(target=lambda:result.append(self.request('/api/geo/start',self.payload(),t)[0]));request.start();self.assertTrue(entered.wait(2))
  self.w.shutdown_requested.set();closed=threading.Event()
  close=threading.Thread(target=lambda:(self.w.begin_shutdown(),closed.set()));close.start()
  self.assertFalse(closed.wait(.05));release.set();request.join(2);close.join(2)
  self.assertEqual(result,[503]);self.assertTrue(closed.is_set());self.assertEqual(self.api.starts,0);self.assertEqual(self.w.budget.state()['reserved'],0)
 def test_shutdown_waits_for_submitted_job_publication(self):
  entered=threading.Event();release=threading.Event();original=self.api.call
  def blocked(service,path,body=None):
   if path=='start':entered.set();self.assertTrue(release.wait(2))
   return original(service,path,body)
  self.api.call=blocked;t=self.login();result=[]
  request=threading.Thread(target=lambda:result.append(self.request('/api/geo/start',self.payload(),t)[0]));request.start();self.assertTrue(entered.wait(2));self.w.shutdown_requested.set();observed=[]
  def close():
   self.w.begin_shutdown();observed.append((self.w.active,self.api.busy))
  closer=threading.Thread(target=close);closer.start();self.assertEqual(observed,[]);release.set();request.join(2);closer.join(2)
  self.assertEqual(result,[202]);self.assertTrue(observed[0][0]);self.assertTrue(observed[0][1]);self.assertEqual(self.w.budget.state()['reserved'],63)
 def test_cn_and_us_admission_without_market_fallback(self):
  t=self.login()
  for market in ('CN','US'):
   self.api.busy=False;self.w.active=None
   status,d,_=self.request('/api/geo/start',{**self.payload(),'market':market},t)
   self.assertEqual(status,202);self.assertEqual(d['config']['market'],market)
  self.assertEqual(self.w.budget.state()['reserved'],126)
 def test_export_redacts_secret_case_and_encoding_variants(self):
  import base64,urllib.parse
  secret='Synthetic-Key/Plus+Value=';password='Synthetic-Team-Password'
  variants=[secret,secret.upper(),urllib.parse.quote(secret,safe=''),urllib.parse.quote(urllib.parse.quote(secret,safe=''),safe=''),''.join('%%%02x'%b for b in secret.encode()),base64.b64encode(secret.encode()).decode(),base64.b64encode(secret.encode()).decode().rstrip('='),password.upper()]
  original=self.api.call
  def evidence(service,path,body=None):
   if path.startswith('export?'):return {'raw_evidence':{'values':variants,'apiKey':secret,'AUTHORIZATION':secret,'request-headers':{'k':secret},'encoded-key-'+secret.upper():'safe'},'usage':{'prompt_tokens':3}}
   return original(service,path,body)
  self.api.call=evidence;t=self.login()
  with patch.dict(os.environ,{'SIGNAL_BAI_API_KEY':secret,'SIGNAL_WORKSPACE_PASSWORD':password}):
   status,d,_=self.request('/api/geo/export?id='+str(uuid.uuid4()),token=t)
  self.assertEqual(status,200);text=json.dumps(d)
  for value in variants:self.assertNotIn(value.lower(),text.lower())
  self.assertNotIn('apiKey',d['raw_evidence']);self.assertNotIn('AUTHORIZATION',d['raw_evidence']);self.assertNotIn('request-headers',d['raw_evidence']);self.assertEqual(d['usage']['prompt_tokens'],3)
 def test_maintenance_blocks_admission_but_keeps_running_task(self):
  t=self.login();self.w.maintenance_requested.set()
  status,state,_=self.request('/api/geo/state',token=t);remote=state['remote']
  self.assertEqual(status,200);self.assertEqual(remote['deployment_gate'],'signals-v1');self.assertTrue(remote['model_ready']);self.assertFalse(remote['ready']);self.assertTrue(remote['maintenance']);self.assertEqual(remote['reason'],'maintenance')
  for path in ('start','plan','sample'):
   payload=self.payload()
   if path=='sample':payload['prompts']=['question '+str(i) for i in range(30)]
   self.assertEqual(self.request('/api/geo/'+path,payload,t)[0],503)
  self.assertEqual(self.w.budget.state()['reserved'],0);self.assertEqual(self.api.starts,0)
  self.w.maintenance_requested.clear();self.assertEqual(self.request('/api/geo/start',self.payload(),t)[0],202)
  self.w.maintenance_requested.set();state=self.request('/api/geo/state',token=t)[1];self.assertTrue(state['busy']);self.assertTrue(state['remote']['maintenance']);self.assertEqual(self.api.starts,1)
 def test_maintenance_state_waits_for_plan_and_submit_publication(self):
  t=self.login()
  for blocking in ('plan','start'):
   with self.subTest(blocking=blocking):
    self.w.maintenance_requested.clear();self.api.busy=False;self.w.active=None
    entered=threading.Event();release=threading.Event();state_done=threading.Event();original=self.api.call
    def blocked(service,path,body=None):
     if path==blocking:entered.set();self.assertTrue(release.wait(2))
     return original(service,path,body)
    self.api.call=blocked;results=[];states=[]
    request=threading.Thread(target=lambda:results.append(self.request('/api/geo/start',self.payload(),t)[0]));request.start();self.assertTrue(entered.wait(2));self.w.maintenance_requested.set()
    def read_state():states.append(self.request('/api/geo/state',token=t)[1]);state_done.set()
    reader=threading.Thread(target=read_state);reader.start();self.assertFalse(state_done.wait(.05));release.set();request.join(2);reader.join(2);self.api.call=original
    self.assertTrue(states[0]['remote']['maintenance'])
    if blocking=='plan':self.assertEqual(results,[503]);self.assertFalse(states[0]['busy']);self.assertEqual(self.w.budget.state()['reserved'],0)
    else:self.assertEqual(results,[202]);self.assertTrue(states[0]['busy']);self.assertIsNotNone(self.w.active);self.assertEqual(self.w.budget.state()['reserved'],63)
 def test_health_metadata_is_optional_and_safe(self):
  with patch.dict(os.environ,{'SIGNAL_BUILD_REVISION':'','SIGNAL_BUILD_VERSION':''}):self.assertEqual(self.request('/healthz')[1],{'ok':True})
  with patch.dict(os.environ,{'SIGNAL_BUILD_REVISION':'a'*40,'SIGNAL_BUILD_VERSION':'v1.2.3'}):self.assertEqual(self.request('/healthz')[1],{'ok':True,'revision':'a'*40,'version':'v1.2.3'})
 def test_body_and_session_cap(self):
  self.assertEqual(self.request('/api/workspace/login',{'password':'x'*5000})[0],413)
  self.assertEqual(self.request('/api/workspace/login',[],extra={})[0],400)
  self.w.sessions={str(i):time.time()+3600 for i in range(32)};self.assertEqual(self.request('/api/workspace/login',{'password':'sixteen-character-password'})[0],429)
class LocalAPIErrorTests(unittest.TestCase):
 def test_http_status_semantics_body_private_and_no_paid_replay(self):
  import io,urllib.error
  for status,expected,code in [(400,400,'invalid_request'),(404,404,'not_found'),(409,409,'busy'),(429,429,'rate_limited'),(401,502,'upstream_failed'),(500,502,'upstream_failed')]:
   with self.subTest(status=status):
    api=LocalAPI();api.tokens['geo']='internal-token'
    body=io.BytesIO(b'{"error":"private vendor-key and upstream headers"}')
    error=urllib.error.HTTPError('http://127.0.0.1:8772/api/geo/start',status,'private vendor-key',{},body)
    with patch('remote_gateway.urllib.request.urlopen',side_effect=error) as outbound:
     with self.assertRaises(Failure) as caught:api.call('geo','start',{'providers':['fixed']})
    self.assertEqual((caught.exception.status,caught.exception.code),(expected,code));self.assertEqual(outbound.call_count,1);self.assertEqual(body.tell(),0)
    self.assertNotIn('vendor-key',str(caught.exception))
    if status==401:self.assertNotIn('geo',api.tokens)
 def test_public_http_preserves_safe_error_only(self):
  # Exercise the complete authenticated HTTP edge with an actual LocalAPI error.
  import io,urllib.error
  with tempfile.TemporaryDirectory() as tmp:
   api=LocalAPI();api.tokens['geo']='internal-token';w=Workspace('long-enough-password','public.example',Budget(pathlib.Path(tmp)/'b',126),api)
   token=w.login('long-enough-password','local')['token'];server=Server(('127.0.0.1',0),w);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    for status,code in [(400,'invalid_request'),(404,'not_found'),(409,'busy'),(429,'rate_limited')]:
     error=urllib.error.HTTPError('http://loopback',status,'secret-error',{},io.BytesIO(b'secret-body'))
     with patch('remote_gateway.urllib.request.urlopen',side_effect=error):
      c=http.client.HTTPConnection('127.0.0.1',server.server_port);c.request('GET','/api/geo/run?id='+str(uuid.uuid4()),headers={'Host':'public.example','Authorization':'Bearer '+token});r=c.getresponse();result=json.loads(r.read());c.close()
     self.assertEqual(r.status,status);self.assertEqual(result,{'error':code,'code':code});self.assertNotIn('secret',str(result))
   finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':unittest.main()
