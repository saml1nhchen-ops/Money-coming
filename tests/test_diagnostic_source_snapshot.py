"""Real gateway -> loopback geo handler -> real execute/generate/collect.
Only provider runner responses and pure prompt formatting are substituted.
"""
import contextlib,copy,http.client,http.server,json,pathlib,sys,tempfile,threading,time,unittest,uuid
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import geo_flow as flow
from geo_diagnose import DiagnosticManager
from remote_gateway import Failure
import test_geo_diagnose as diagnosis_tests
class Loopback:
 def __init__(self,port):self.port=port
 def call(self,service,path,body=None):
  if service!='geo':raise AssertionError('No provider requests allowed')
  c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
  c.request('GET' if body is None else 'POST','/api/geo/'+path,None if body is None else json.dumps(body),{'Host':'127.0.0.1:8772','Authorization':'Bearer '+flow.TOKEN,'Content-Type':'application/json'})
  r=c.getresponse();value=json.loads(r.read());status=r.status;c.close()
  if status>=400:raise Failure(502,'upstream_failed')
  return value
class Sources(diagnosis_tests.HTTPDiagnostics):
 def setUp(self):
  super().setUp();self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close);self.materials=[];self.runner_jobs={};self.runner_submits=0
  self.stack.enter_context(patch.object(flow,'DATA',self.root/'runtime/geo-flows'))
  self.stack.enter_context(patch.object(flow,'catalog',return_value={'configured':True,'profiles':copy.deepcopy(self.w.profiles)}))
  self.stack.enter_context(patch.object(flow,'niubi',side_effect=self.format_prompt))
  self.stack.enter_context(patch.object(flow,'bridge',side_effect=self.runner))
  self.fetch=self.stack.enter_context(patch.object(flow,'fetch_website',side_effect=AssertionError('Diagnostic must not refetch website')))
  flow.BUSY=False;flow.CANCEL.clear()
  self.loop_server=http.server.ThreadingHTTPServer(('127.0.0.1',0),flow.Handler);self.loop_thread=threading.Thread(target=self.loop_server.serve_forever,daemon=True);self.loop_thread.start();self.w.api=Loopback(self.loop_server.server_port)
 def tearDown(self):
  super().tearDown();self.loop_server.shutdown();self.loop_server.server_close();self.loop_thread.join();self.stack.close();flow.BUSY=False;flow.CANCEL.clear()
 def format_prompt(self,operation,cfg,**extra):
  if operation=='build':
   self.materials.append(extra['website_text']);return {'prompt':'GENERATE '+str(cfg['batch_index'])}
  if operation=='parse':return json.loads(extra['text'])
  raise AssertionError('Only offline prompt operations')
 def runner(self,path,body=None):
  if path=='run':
   self.runner_submits+=1;rid=str(uuid.uuid4());prompt=body['prompts'][0]
   if prompt.startswith('GENERATE '):
    batch=int(prompt.split()[1]);answer=json.dumps([{'text':f'Which tea suits scenario {batch*10+n}?'} for n in range(10)])
   else:answer='Acme Tea is one possible tea choice.'
   value={'id':rid,'status':'finished','planned':1,'samples':[{'id':rid,'provider':'gpt','status':'complete','prompt':prompt,'answer':answer,'citations':[],'retrieved_sources':[]}]};self.runner_jobs[rid]=value;return copy.deepcopy(value)
  if path.startswith(('run?id=','export?id=')):return copy.deepcopy(self.runner_jobs[path.split('=',1)[1]])
  raise AssertionError('Unexpected provider runner path')
 def test_snapshot_success_real_execute_generates_and_samples_without_second_fetch(self):
  body=self.payload('full');code,d=self.req('POST','/api/diagnostics',body);self.assertEqual(code,202);d=self.done(d['id']);self.assertIsNone(d['error_code']);self.assertEqual(self.runner_submits,33);self.fetch.assert_not_called();self.assertEqual(len(d['bundle']['answers']),30)
  job=flow.get(d['job_id']);self.assertEqual(job['website']['source'],'audited_snapshot');self.assertEqual(job['website']['read_status'],'captured');self.assertEqual(job['source_snapshot']['limits']['resources'],8);self.assertTrue(all('Tea leaves and brewing' in v for v in self.materials));self.assertEqual(self.w.budget.state()['reserved'],33)
 def test_429_real_execute_uses_only_confirmed_scope_and_does_not_retry_website(self):
  original=self.synthetic.__call__;website_attempts=[]
  def limited(operation,args,timeout):
   if operation=='http' and args[0]=='https://acme.example/':website_attempts.append(args[0]);return {'status':429,'headers':{'Content-Type':'text/html'},'raw':b''}
   return original(operation,args,timeout)
  self.a.budget_factory=lambda usage=None:__import__('audit_fetch').FetchBudget(usage,worker=limited)
  body=self.payload('full');_,d=self.req('POST','/api/diagnostics',body);d=self.done(d['id']);self.assertIsNone(d['error_code']);self.fetch.assert_not_called();self.assertEqual(len(website_attempts),1);job=flow.get(d['job_id']);self.assertEqual(job['website']['text'],'');self.assertEqual(job['website']['read_status'],'unavailable');self.assertIn('仅依据用户确认',job['website']['material_note']);self.assertTrue(all('官网未取得可读材料' in m for m in self.materials));self.assertEqual(job['source_snapshot']['resources'][0]['http_status'],429);self.assertEqual(len(d['bundle']['answers']),30)
 def test_public_payload_rejects_snapshot_and_private_route(self):
  cfg={'website':'https://acme.example/','market':'US','brand_aliases':['Acme Tea'],'providers':['gpt'],'generator':'gpt','count':30,'repeats':1}
  for name in ('snapshot','source_snapshot','skip_fetch'):
   self.assertEqual(self.req('POST','/api/geo/start',{**cfg,name:True})[0],400)
  self.assertEqual(self.req('POST','/api/geo/diagnostic-start',{'config':cfg,'source_snapshot':{}})[0],404);self.assertEqual(self.runner_submits,0)
 def test_ordinary_start_preserves_website_fetch(self):
  self.fetch.side_effect=None;self.fetch.return_value={'url':'https://acme.example/','text':'Ordinary live website material'}
  cfg={'website':'https://acme.example/','market':'US','brand_aliases':['Acme Tea'],'providers':['gpt'],'generator':'gpt','count':30,'repeats':1,'skus':[],'competitors':[]}
  code,j=self.req('POST','/api/geo/start',cfg);self.assertEqual(code,202)
  for _ in range(1000):
   job=flow.get(j['id'])
   if job['status'] not in ('queued','running'):break
   time.sleep(.005)
  self.assertEqual(job['status'],'finished');self.fetch.assert_called_once_with(cfg['website']);self.assertNotIn('source_snapshot',job)
# Inherit setup/request helpers, not the base test methods (collected separately).
for name in list(diagnosis_tests.HTTPDiagnostics.__dict__):
 if name.startswith('test_') and name not in Sources.__dict__:setattr(Sources,name,None)
if __name__=='__main__':unittest.main()
