"""Durable diagnostics via actual gateway HTTP and real offline parsers.
Model API is a test double with the existing geo_flow job/sample shape.
"""
import copy,http.client,json,os,pathlib,sqlite3,sys,tempfile,threading,time,unittest,uuid
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
from test_geo_audit import Synthetic
import audit_fetch as f,geo_analysis
from geo_audit import AuditManager
from geo_diagnose import DiagnosticManager,DiagnosticError,score,RULES,flow_failure
from remote_gateway import Workspace,Budget,Server
class FlowAPI:
 def __init__(self):self.calls=[];self.jobs={};self.hold=False;self.busy=False
 def call(self,service,path,body=None):
  if path=='diagnostic-start':
   delay=min(5,max(0,float(os.environ.get('SIGNAL_TEST_START_DELAY','0'))))
   if delay:time.sleep(delay)
   path='start';body=body['config']
  self.calls.append((service,path,copy.deepcopy(body)))
  if service!='geo':raise AssertionError('No vendor API in tests')
  if path=='state':return {'runner':{},'busy':self.busy,'runs':[]}
  if path=='plan':return {'maximum_calls':(0 if body.get('manual') else 3)+30*len(body['providers'])}
  if path in ('start','sample'):
   rid=str(uuid.uuid4());prompts=[{'text':q,'family':'discovery'} for q in body.get('prompts',[f'Which tea choices meet need {n}?' for n in range(30)])]
   samples=[{'id':str(uuid.uuid4()),'provider':p,'prompt':q['text'],'question_index':n,'repeat':1,'status':'complete','answer':('1. Acme Tea\n2. Rival Tea' if n%2==0 else 'Other tea choices'),'citations':[],'model_requested':'test-model','created_at':'2026-10-22T12:00:00Z'} for p in body['providers'] for n,q in enumerate(prompts)]
   job={'id':rid,'status':'running' if self.hold else 'finished','stage':'sampling','created_at':'2026-10-22T12:00:00Z','config':copy.deepcopy(body),'prompts':prompts,'samples':samples,'report':geo_analysis.analyze(samples,body,prompts)};self.jobs[rid]=job;return copy.deepcopy(job)
  if path.startswith('run?id='):return copy.deepcopy(self.jobs[path.split('=',1)[1]])
  raise AssertionError('Unexpected legacy API '+path)
class HTTPDiagnostics(unittest.TestCase):
 def setUp(self):
  p=patch('pinned_http.urllib.request.getproxies',return_value={});p.start();self.addCleanup(p.stop)
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.api=FlowAPI();self.synthetic=Synthetic()
  self.w=Workspace('synthetic-password-long','public.example',Budget(self.root/'runtime/budget.json',126),self.api)
  self.w.ready=True;self.w.reason=None;self.w.profiles=[{'id':'gpt','model':'gpt-test','manufacturer':'OpenAI','protocol':'chat','markets':['CN','US'],'search':False}]
  self.a=AuditManager(self.w,self.root/'runtime/audits/index.sqlite3',lambda usage=None:f.FetchBudget(usage,worker=self.synthetic));self.w.auditor=self.a
  self.m=DiagnosticManager(self.w,self.root/'runtime/diagnostics/index.sqlite3',self.root,poll_interval=.005);self.w.diagnostics=self.m
  self.server=Server(('127.0.0.1',0),self.w);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.token=self.w.login('synthetic-password-long','test')['token']
  _,clients=self.req('POST','/api/clients',{'name':'Customer'});self.cid=next(c['id'] for c in clients['clients'] if not c['internal'])
  _,projects=self.req('POST','/api/projects',{'client_id':self.cid,'name':'Tea project'});self.pid=next(p['id'] for p in projects['projects'] if not p['internal'])
 def tearDown(self):
  self.api.hold=False
  for j in self.api.jobs.values():j['status']='finished'
  self.w.shutdown_requested.set();self.m.pool.shutdown(wait=True);self.a.pool.shutdown(wait=True);self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
 def req(self,method,path,body=None,auth=True):
  headers={'Host':'public.example','Origin':'https://saml1nhchen-ops.github.io'}
  if auth:headers['Authorization']='Bearer '+self.token
  if body is not None:headers['Content-Type']='application/json'
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10);c.request(method,path,json.dumps(body) if body is not None else None,headers);r=c.getresponse();result=json.loads(r.read());status=r.status;c.close();return status,result
 def wait_audit(self,aid):
  for _ in range(1000):
   a=self.a.get(aid)
   if a['status'] not in ('queued','running') and self.w.audit_active is None:return a
   time.sleep(.005)
  self.fail('audit timeout')
 def preview(self):
  aid=str(uuid.uuid4());code,a=self.req('POST','/api/geo/audit',{'request_id':aid,'website':'https://acme.example/','market':'US'});self.assertEqual(code,202);return self.wait_audit(aid)
 def payload(self,mode='website'):
  a=self.preview();return {'request_id':str(uuid.uuid4()),'project_id':self.pid,'audit_id':a['id'],'confirmed':{'brand':{'name':'Acme Tea','aliases':[]},'products':[],'competitors':[{'name':'Rival Tea','aliases':[],'domains':['other.example']}],'context':''},'profile_ids':['gpt'] if mode=='full' else [],'mode':mode}
 def done(self,did):
  for _ in range(1500):
   d=self.m.detail(did)
   if d['status'] in ('finished','partial','failed','interrupted') and self.w.diagnostic_active is None:return d
   time.sleep(.005)
  self.fail('diagnostic timeout')
 def test_http_complete_v01_and_share_snapshot_revocation_expiry(self):
  body=self.payload();code,queued=self.req('POST','/api/diagnostics',body);self.assertEqual(code,202);d=self.done(queued['id']);self.assertEqual(d['status'],'partial');self.assertIsNone(d['error_code']);self.assertEqual(d['bundle']['schema_version'],'v0.1');self.assertEqual(d['bundle']['run_manifest']['diagnostic_mode'],'website');self.assertEqual(sum(r['weight'] for r in d['bundle']['rules']),100);self.assertIsNone(d['summary']['total']);self.assertEqual(self.w.budget.state()['reserved'],0)
  self.assertEqual(self.req('POST','/api/diagnostics',body)[0],200);changed={**body,'mode':'full','profile_ids':['gpt']};self.assertEqual(self.req('POST','/api/diagnostics',changed)[0],409)
  self.assertEqual(self.req('GET','/healthz',auth=False)[1]['capabilities']['diagnostics_v1'],True)
  self.assertEqual(self.req('GET','/api/diagnostics',auth=False)[0],401)
  code,share=self.req('POST','/api/diagnostics/share',{'id':d['id']});self.assertEqual(code,201);token=share['share_token'];code,pub=self.req('GET','/api/shared-report?token='+token,auth=False);self.assertEqual(code,200);self.assertNotIn('project_id',json.dumps(pub));self.assertNotIn(d['id'],json.dumps(pub));self.assertNotIn('context',pub['diagnostic']);self.assertEqual(pub['diagnostic']['bundle']['run_manifest']['diagnostic_mode'],'website');self.assertEqual(len(self.req('GET','/api/diagnostics/detail?id='+d['id'])[1]['shares']),1)
  with sqlite3.connect(self.m.path) as c:rows=c.execute('SELECT token_hash,snapshot FROM shares').fetchall();self.assertNotIn(token,json.dumps(rows))
  original=pub['diagnostic'];d['bundle']['rules'][0]['reason']='changed later';self.m.save(d);self.assertEqual(self.req('GET','/api/shared-report?token='+token,auth=False)[1]['diagnostic'],original)
  self.assertEqual(self.req('POST','/api/diagnostics/revoke',{'share_id':share['share_id']})[0],200);self.assertEqual(self.req('GET','/api/shared-report?token='+token,auth=False)[0],404)
  _,share=self.req('POST','/api/diagnostics/share',{'id':d['id']})
  with sqlite3.connect(self.m.path) as c:c.execute('UPDATE shares SET expires=0')
  self.assertEqual(self.req('GET','/api/shared-report?token='+share['share_token'],auth=False)[0],404)
  pathlib.Path('/tmp/diagnostic-contract-fixture.json').write_text(json.dumps(self.m.detail(d['id']),ensure_ascii=False,indent=2))
 def test_real_flow_shape_budget_mentions_rank_and_frozen_retest(self):
  code,d=self.req('POST','/api/diagnostics',self.payload('full'));self.assertEqual(code,202);d=self.done(d['id']);self.assertEqual(d['status'],'partial');self.assertIsNone(d['error_code']);self.assertEqual(self.w.budget.state()['reserved'],33);self.assertEqual(len(d['bundle']['answers']),30);self.assertEqual(d['bundle']['run_manifest']['diagnostic_mode'],'full');self.assertTrue(d['bundle']['answers'][0]['mention']);self.assertFalse(d['bundle']['answers'][1]['mention']);self.assertIsNone(d['bundle']['answers'][0]['recommendation']);self.assertEqual(d['bundle']['answers'][0]['ranking'][0]['rank']['position'],1);self.assertFalse(d['bundle']['answers'][0]['citation_supported']);pathlib.Path('/tmp/diagnostic-full-contract-fixture.json').write_text(json.dumps(d,ensure_ascii=False,indent=2))
  code,r=self.req('POST','/api/diagnostics/retest',{'id':d['id'],'request_id':str(uuid.uuid4())});self.assertEqual(code,202);r=self.done(r['id']);self.assertIsNone(r['error_code']);self.assertEqual(r['frozen_prompts'],d['frozen_prompts']);self.assertEqual(self.w.budget.state()['reserved'],63);self.assertEqual(r['plan']['maximum_calls'],30);self.assertTrue(r['trend']['comparable']);self.assertTrue(any(p=='sample' for _,p,_ in self.api.calls));self.assertEqual([p for _,p,_ in self.api.calls].count('start'),1)
 def test_mutual_exclusion_maintenance_and_rejected_paid_budget(self):
  body=self.payload('full');self.api.hold=True;code,d=self.req('POST','/api/diagnostics',body);self.assertEqual(code,202)
  for _ in range(1000):
   if self.api.jobs:break
   time.sleep(.005)
  self.assertTrue(self.req('GET','/api/geo/state')[1]['busy']);self.assertEqual(self.req('POST','/api/geo/audit',{'request_id':str(uuid.uuid4()),'website':'https://other.example/','market':'US'})[0],409)
  self.assertEqual(self.req('POST','/api/diagnostics',{**body,'request_id':str(uuid.uuid4())})[0],409);self.assertEqual(self.req('POST','/api/diagnostics/share',{'id':d['id']})[0],409)
  self.api.hold=False
  for j in self.api.jobs.values():j['status']='finished'
  self.done(d['id']);self.w.maintenance_requested.set();self.assertEqual(self.req('POST','/api/diagnostics',{**body,'request_id':str(uuid.uuid4())})[0],503);self.w.maintenance_requested.clear();self.w.budget.limit=33
  self.assertEqual(self.req('POST','/api/diagnostics',{**body,'request_id':str(uuid.uuid4())})[0],429);self.assertEqual(sum(p in ('start','sample') for _,p,_ in self.api.calls),1)
 def test_extra_pages_choose_distinct_roles_with_eight_resource_cap(self):
  self.synthetic.seed_html=self.synthetic.seed_html.replace('</article>','<a href="/products/new">New Product</a><a href="/products/second">Second Product</a></article>')
  _,d=self.req('POST','/api/diagnostics',self.payload());d=self.done(d['id']);urls=[p['url'] for p in d['pages']]
  self.assertIn('https://acme.example/products/new',urls);self.assertIn('https://acme.example/contact',urls);self.assertNotIn('https://acme.example/products/second',urls);self.assertLessEqual(d['website_usage']['resources_requested'],8);self.assertLessEqual(d['website_usage']['http_requests'],10);self.assertLessEqual(d['website_usage']['bytes_budget_used'],4*1024*1024)
  access=[r for r in d['bundle']['rules'] if r['dimension']=='access'];self.assertEqual(sum(r['weight'] for r in access),25);self.assertEqual(next(r['weight'] for r in access if r['rule_id']=='R-access-response'),5);self.assertIn('source_snapshot',d['bundle']);self.assertTrue(all(r['action'] for r in d['bundle']['rules']))
 def test_uncertain_paid_submission_is_not_retried_or_refunded(self):
  from remote_gateway import Failure
  original=self.api.call
  def fail(service,path,body=None):
   if path in ('start','diagnostic-start'):self.api.calls.append((service,'start',copy.deepcopy(body)));raise Failure(502,'upstream_failed')
   return original(service,path,body)
  self.api.call=fail;_,d=self.req('POST','/api/diagnostics',self.payload('full'));d=self.done(d['id']);self.assertEqual(d['status'],'partial');self.assertEqual(d['error_code'],'upstream_failed');self.assertEqual(self.w.budget.state()['reserved'],33);self.assertEqual(sum(p=='start' for _,p,_ in self.api.calls),1)
  self.assertEqual(d['progress']['runner_status'],'unknown');self.assertEqual(self.req('POST','/api/diagnostics/share',{'id':d['id']})[0],409);self.assertEqual(self.req('POST','/api/diagnostics/retest',{'id':d['id'],'request_id':str(uuid.uuid4())})[0],409);self.assertEqual(self.w.budget.state()['reserved'],33);self.assertEqual(sum(p=='start' for _,p,_ in self.api.calls),1)
 def test_three_model_diagnostic_exports90_and_frozen_retest_budget_is90(self):
  self.w.profiles.extend([{'id':p,'model':p+'-test','manufacturer':vendor,'protocol':'chat','markets':['US','CN'],'search':False} for p,vendor in [('gemini','Google'),('claude','Anthropic')]])
  body=self.payload('full');body['profile_ids']=['gpt','gemini','claude']
  for bad in ([],['gpt','gpt'],['unknown']):
   self.assertEqual(self.req('POST','/api/diagnostics',{**body,'profile_ids':bad})[0],400)
  code,d=self.req('POST','/api/diagnostics',body);self.assertEqual(code,202);self.assertEqual(d['plan']['maximum_calls'],93);d=self.done(d['id']);self.assertIsNone(d['error_code']);self.assertEqual(len(d['bundle']['answers']),90);self.assertEqual(d['bundle']['run_manifest']['planned'],90);self.assertEqual(self.w.budget.state()['reserved'],93)
  self.assertEqual(self.req('POST','/api/diagnostics',body)[0],200);self.assertEqual(self.w.budget.state()['reserved'],93)
  original_submits=sum(p in ('start','sample') for _,p,_ in self.api.calls)
  self.assertEqual(self.req('POST','/api/diagnostics/retest',{'id':d['id'],'request_id':str(uuid.uuid4())})[0],429);self.assertEqual(self.req('POST','/api/diagnostics',{**body,'request_id':str(uuid.uuid4())})[0],429);self.assertEqual(sum(p in ('start','sample') for _,p,_ in self.api.calls),original_submits);self.assertEqual(self.w.budget.state()['reserved'],93)
  exported=self.req('GET','/api/diagnostics/export?id='+d['id'])[1];self.assertEqual(len(exported['bundle']['answers']),90)
  # Simulate a subsequent UTC day by clearing only the test ledger; production
  # daily limit stays 126 and no budget reset endpoint exists.
  self.w.budget.path.write_text('{}');code,r=self.req('POST','/api/diagnostics/retest',{'id':d['id'],'request_id':str(uuid.uuid4())});self.assertEqual(code,202);self.assertEqual(r['plan']['maximum_calls'],90);self.assertEqual(r['plan']['generation_calls'],0);r=self.done(r['id']);self.assertIsNone(r['error_code']);self.assertEqual(r['frozen_prompts'],d['frozen_prompts']);self.assertEqual(len(r['bundle']['answers']),90);self.assertEqual(self.w.budget.state()['reserved'],90);self.assertEqual(self.w.budget.limit,126)
 def test_detail_authentication_does_not_wait_for_paid_submission_lock(self):
  body=self.payload('full');original=self.api.call;entered=threading.Event();release=threading.Event()
  def blocked(service,path,payload=None):
   if path=='diagnostic-start':entered.set();release.wait(3)
   return original(service,path,payload)
  self.api.call=blocked;_,d=self.req('POST','/api/diagnostics',body);self.assertTrue(entered.wait(2));self.assertTrue(self.w.lock._is_owned() is False)
  try:
   started=time.monotonic();code,current=self.req('GET','/api/diagnostics/detail?id='+d['id']);self.assertEqual(code,200);self.assertLess(time.monotonic()-started,1);self.assertEqual(current['status'],'running');self.assertEqual(current['stage'],'model_submitting');self.assertTrue(current['bundle']);self.assertEqual(current['bundle']['answers'],[]);self.assertEqual(current['config']['mode'],'full');self.assertEqual(current['progress']['answers_planned'],30)
   self.assertEqual(self.req('POST','/api/diagnostics/share',{'id':d['id']})[0],409)
  finally:release.set()
  self.done(d['id'])
 def test_read_only_transient_recovers_and_mirrors_real_progress(self):
  from remote_gateway import Failure
  self.api.hold=True;original=self.api.call;reads=[]
  def transient(service,path,payload=None):
   if path.startswith('run?id='):
    reads.append(path)
    if len(reads)==1:raise Failure(502,'upstream_failed')
   return original(service,path,payload)
  self.api.call=transient
  with patch('geo_diagnose.RUN_READ_BACKOFF',(.01,.01,.01,.01)):
   _,d=self.req('POST','/api/diagnostics',self.payload('full'))
   for _ in range(1000):
    current=self.m.raw(d['id'])
    if current.get('progress',{}).get('answers_complete')==30:break
    time.sleep(.005)
   self.assertEqual(current['status'],'running');self.assertEqual(current['progress']['questions_generated'],30);self.assertEqual(current['progress']['answers_complete'],30);self.assertEqual(len(current['bundle']['answers']),30);self.assertIsNone(current['progress']['last_read_error']);self.assertEqual(sum(p=='start' for _,p,_ in self.api.calls),1)
   for job in self.api.jobs.values():job['status']='finished'
   final=self.done(d['id']);self.assertIsNone(final['error_code']);self.assertEqual(self.w.budget.state()['reserved'],33)
 def test_bounded_read_failure_keeps_unknown_runner_and_manual_get_reconciles_once(self):
  from remote_gateway import Failure
  original=self.api.call;broken=[True];reads=[]
  def transient(service,path,payload=None):
   if path.startswith('run?id='):
    reads.append(path)
    if broken[0]:raise Failure(502,'upstream_failed')
   return original(service,path,payload)
  self.api.call=transient
  with patch('geo_diagnose.RUN_READ_BACKOFF',(.01,.01,.01,.01)):
   _,d=self.req('POST','/api/diagnostics',self.payload('full'))
   for _ in range(1000):
    d=self.m.raw(d['id'])
    if d['status']=='interrupted' and self.w.diagnostic_active is None:break
    time.sleep(.005)
  self.assertEqual(len(reads),5);self.assertEqual(d['status'],'interrupted');self.assertEqual(d['stage'],'reconciliation_required');self.assertEqual(d['progress']['runner_status'],'unknown');self.assertNotIn('completed_at',d);self.assertEqual(self.req('POST','/api/diagnostics/share',{'id':d['id']})[0],409);self.assertEqual(self.w.budget.state()['reserved'],33)
  broken[0]=False;entered=threading.Event();release=threading.Event();reconciles=[];previous=self.api.call
  def blocked(service,path,payload=None):
   if path.startswith('run?id='):reconciles.append(path);entered.set();release.wait(2)
   return previous(service,path,payload)
  self.api.call=blocked;result=[];reader=threading.Thread(target=lambda:result.append(self.req('GET','/api/diagnostics/detail?id='+d['id'])));reader.start();self.assertTrue(entered.wait(1))
  try:
   _,still_unknown=self.req('GET','/api/diagnostics/detail?id='+d['id']);self.assertEqual(still_unknown['status'],'interrupted');self.assertEqual(len(reconciles),1)
  finally:release.set();reader.join(2)
  recovered=result[0][1];self.assertEqual(recovered['status'],'partial');self.assertIsNone(recovered['error_code']);self.assertEqual(len(recovered['bundle']['answers']),30);count=len(reads)
  self.req('GET','/api/diagnostics/detail?id='+d['id']);self.assertEqual(len(reads),count);self.assertEqual(sum(p=='start' for _,p,_ in self.api.calls),1)
 def test_full_retest_rejects_missing_or_invalid_frozen_bank_without_calls(self):
  _,d=self.req('POST','/api/diagnostics',self.payload('full'));d=self.done(d['id']);bank=list(d['frozen_prompts']);reserved=self.w.budget.state()['reserved'];submits=sum(p in ('start','sample') for _,p,_ in self.api.calls)
  for invalid in ([],bank[:-1],['']+bank[1:],[{}]+bank[1:],[bank[1].upper()+'!']+bank[1:],['x'*4001]+bank[1:]):
   with self.subTest(bank_size=len(invalid)):
    changed=copy.deepcopy(d);changed['frozen_prompts']=invalid;self.m.save(changed);code,result=self.req('POST','/api/diagnostics/retest',{'id':d['id'],'request_id':str(uuid.uuid4())});self.assertEqual((code,result['code']),(409,'question_set_unavailable'));self.assertEqual(self.w.budget.state()['reserved'],reserved);self.assertEqual(sum(p in ('start','sample') for _,p,_ in self.api.calls),submits)
  self.m.save(d);code,r=self.req('POST','/api/diagnostics/retest',{'id':d['id'],'request_id':str(uuid.uuid4())});self.assertEqual(code,202);self.assertEqual(r['plan']['maximum_calls'],30);r=self.done(r['id']);self.assertEqual(r['frozen_prompts'],bank);self.assertEqual(sum(p=='start' for _,p,_ in self.api.calls),1);self.assertEqual(sum(p=='sample' for _,p,_ in self.api.calls),1)
 def test_old_incomplete_report_does_not_mislabel_finished_runner_as_failed(self):
  _,d=self.req('POST','/api/diagnostics',self.payload('full'));d=self.done(d['id']);d['error_code']='sampling_incomplete';d.pop('failure',None);d['bundle']['questions']=[];d['bundle']['answers']=[];self.m.save(d)
  bundle=copy.deepcopy(d['bundle']);summary=copy.deepcopy(d['summary']);submits=sum(p in ('start','sample') for _,p,_ in self.api.calls);reserved=self.w.budget.state()['reserved']
  code,observed=self.req('GET','/api/diagnostics/detail?id='+d['id']);self.assertEqual(code,200);self.assertEqual(observed['failure']['code'],'saved_report_incomplete');self.assertEqual(observed['failure']['flow_status'],'finished');self.assertNotIn('部分模型回答未完成',observed['failure']['reason']);self.assertEqual(observed['bundle'],bundle);self.assertEqual(observed['summary'],summary);self.assertEqual(self.w.budget.state()['reserved'],reserved);self.assertEqual(sum(p in ('start','sample') for _,p,_ in self.api.calls),submits)
 def test_failure_detail_only_allows_safe_local_error_vocabulary(self):
  with patch.dict('os.environ',{'SIGNAL_BAI_API_KEY':'synthetic-secret-value'}):
   failure=flow_failure(self.w,{'status':'failed','stage':'generating','prompts':[],'samples':[],'error':'untrusted Authorization: Bearer synthetic-secret-value https://private.example/?token=other-private-value'})
  self.assertNotIn('secret-value',str(failure));self.assertNotIn('other-private-value',str(failure));self.assertNotIn('Authorization',str(failure));self.assertNotIn('private.example',str(failure));self.assertLessEqual(len(failure['detail']),600)
 def test_restart_history_and_store_failure_no_replay(self):
  body=self.payload();_,d=self.req('POST','/api/diagnostics',body);d=self.done(d['id']);d.update(status='running',stage='model_submitting');self.m.save(d);calls=len(self.api.calls)
  second=DiagnosticManager(self.w,self.m.path,self.root);self.addCleanup(second.pool.shutdown,True);self.assertEqual(second.detail(d['id'])['status'],'interrupted');self.assertEqual(len(self.api.calls),calls);history=[x for x in second.listing()['diagnostics'] if x.get('legacy_type')];self.assertTrue(history);self.assertEqual(self.req('POST','/api/diagnostics/share',{'id':history[0]['id']})[0],403)
  self.m.path=self.root/'missing'/'broken.sqlite3';self.assertEqual(self.req('GET','/api/diagnostics')[0],503)
 def test_share_persists_restart_and_bad_queries_fail(self):
  _,d=self.req('POST','/api/diagnostics',self.payload());d=self.done(d['id']);_,share=self.req('POST','/api/diagnostics/share',{'id':d['id']});second=DiagnosticManager(self.w,self.m.path,self.root);self.addCleanup(second.pool.shutdown,True);self.assertEqual(second.shared(share['share_token'])['diagnostic']['brand'],'Acme Tea');self.assertEqual(self.req('GET','/api/shared-report?token=x&token=y',auth=False)[0],400);self.assertEqual(self.req('GET','/api/shared-report?token=x',auth=False)[0],404);self.assertEqual(self.req('GET','/api/diagnostics/detail?id=bad')[0],400)
 def test_incomparable_configuration_does_not_report_lift(self):
  _,d=self.req('POST','/api/diagnostics',self.payload());d=self.done(d['id']);changed=copy.deepcopy(d);changed['comparison_config']['market']='CN';trend=self.m.compare(d,changed);self.assertFalse(trend['comparable']);self.assertIsNone(trend['delta'])
 def test_project_question_reuse_requires_same_brand_site_and_market(self):
  self.w.budget.limit=1000
  body=self.payload('full');_,d=self.req('POST','/api/diagnostics',body);d=self.done(d['id'])
  same={**body,'request_id':str(uuid.uuid4())};code,repeat=self.req('POST','/api/diagnostics',same);self.assertEqual(code,202);repeat=self.done(repeat['id']);self.assertEqual(repeat['plan']['generation_calls'],0)
  changed={**body,'request_id':str(uuid.uuid4()),'confirmed':{**body['confirmed'],'brand':{'name':'Different Brand','aliases':['Different Brand']}}}
  code,other=self.req('POST','/api/diagnostics',changed);self.assertEqual(code,202);other=self.done(other['id']);self.assertEqual(other['plan']['generation_calls'],3)
  for website,market in [('https://different.example/','US'),('https://acme.example/','CN')]:
   aid=str(uuid.uuid4());self.assertEqual(self.req('POST','/api/geo/audit',{'request_id':aid,'website':website,'market':market})[0],202);self.wait_audit(aid)
   code,next_run=self.req('POST','/api/diagnostics',{**body,'audit_id':aid,'request_id':str(uuid.uuid4())});self.assertEqual(code,202);next_run=self.done(next_run['id']);self.assertEqual(next_run['plan']['generation_calls'],3)
 def test_actual_model_conditions_and_incomplete_samples_break_trend(self):
  _,d=self.req('POST','/api/diagnostics',self.payload('full'));d=self.done(d['id'])
  for key,value in [('platform','another-returned-model'),('citation_supported',True),('truncated',True),('cached',True)]:
   changed=copy.deepcopy(d);changed['bundle']['answers'][0][key]=value;trend=self.m.compare(d,changed);self.assertFalse(trend['comparable'],key);self.assertIsNone(trend['delta'])
if __name__=='__main__':unittest.main()
