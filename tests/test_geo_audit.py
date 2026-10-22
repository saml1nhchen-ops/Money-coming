"""Actual Protego/Trafilatura with synthetic captured HTTP; no model/network calls."""
import copy,http.client,json,pathlib,socket,sys,tempfile,threading,time,unittest,uuid
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import geo_audit as a
import audit_fetch as f
from remote_gateway import Workspace,Budget,Server
HTML='''<html><head><title>Acme Tea | Products</title><meta property="og:site_name" content="Acme Tea"><meta name="robots" content="noindex"><script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Acme Tea"}</script><script type="application/ld+json">{"@type":"Product","name":"Green Tea"}</script><link rel="alternate" type="text/markdown" href="/index.md"></head><body><main><article><h1>Fresh tea products</h1><p>'''+('Tea leaves and brewing information for customers. '*100)+'''</p><p>Compare our tea versus <a href="https://other.example/">Rival Tea</a>.</p><a href="https://partner.example">Partner Company</a><a href="/contact">Contact us</a><a href="/privacy">Privacy policy</a><a href="/about">About us</a><p>support@acme.example</p></article></main></body></html>'''
ROBOTS='User-agent: GPTBot\nDisallow: /\n\nUser-agent: OAI-SearchBot\nDisallow: /private\nAllow: /private/open\n\nUser-agent: *\nAllow: /\n'
class Pipe:
 def send(self,value):self.value=value
 def close(self):pass
def actual_tool(operation,args):
 pipe=Pipe()
 with patch.object(socket.socket,'connect',side_effect=AssertionError('Tools must not access network')):f._worker(pipe,operation,args)
 if not pipe.value['ok']:raise f.AuditFetchError(pipe.value['error'])
 return pipe.value['value']
class Synthetic:
 def __init__(self):self.calls=[];self.robots=ROBOTS;self.robots_status=200;self.seed_error=None;self.seed_status=200;self.seed_html=HTML;self.slow=False
 def __call__(self,operation,args,timeout):
  self.calls.append((operation,args,timeout));assert 0<timeout<=10
  if operation=='dns':return [(2,1,6,'',('93.184.216.34',443))]
  if operation in ('parse','robots'):return actual_tool(operation,args)
  url,addresses,limit,accept,request_timeout=args;path=__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(url).path
  if self.seed_error and path=='/':raise f.AuditFetchError(self.seed_error)
  status=200;kind='text/plain';body='';headers={'Content-Type':kind}
  if path=='/':body=self.seed_html;kind='text/html';status=self.seed_status;headers={'Content-Type':kind,'Retry-After':'120'} if status==429 else {'Content-Type':kind}
  elif path=='/robots.txt':body=self.robots;status=self.robots_status
  elif path=='/index.md':body='# Acme Tea\nPublic products';kind='text/markdown'
  elif path=='/llms.txt':body='# Acme Tea\nSupplemental website information'
  elif path=='/about':body='<html><h1>About</h1><p>Public company details</p></html>';kind='text/html'
  else:status=404
  return {'status':status,'headers':{**headers,**({'X-Robots-Tag':'googlebot: noindex'} if path=='/' and status==200 else {})},'raw':body.encode()[:limit+1]}
class API:
 def __init__(self):self.busy=False
 def call(self,service,path,body=None):
  if service!='geo' or path!='state':raise AssertionError('No model or legacy task calls allowed')
  return {'runner':{},'busy':self.busy,'runs':[]}
class AuditWorkflowTests(unittest.TestCase):
 def setUp(self):
  policy=patch('pinned_http.urllib.request.getproxies',return_value={});policy.start();self.addCleanup(policy.stop)
  self.tmp=tempfile.TemporaryDirectory();self.path=pathlib.Path(self.tmp.name);self.api=API();self.w=Workspace('synthetic-password-long','public.example',Budget(self.path/'unused-budget',0),self.api);self.synthetic=Synthetic();self.factory=lambda usage=None:f.FetchBudget(usage,worker=self.synthetic)
  self.manager=a.AuditManager(self.w,self.path/'audits/index.sqlite3',self.factory);self.w.auditor=self.manager
  self.server=Server(('127.0.0.1',0),self.w);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.token=self.w.login('synthetic-password-long','test')['token']
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.manager.pool.shutdown(wait=True);self.tmp.cleanup()
 def request(self,method,path,body=None,token=True):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5);headers={'Host':'public.example','Origin':'https://saml1nhchen-ops.github.io'}
  if token:headers['Authorization']='Bearer '+self.token
  if body is not None:headers['Content-Type']='application/json'
  c.request(method,path,None if body is None else json.dumps(body),headers);r=c.getresponse();d=json.loads(r.read());c.close();return r.status,d
 def start(self,**changes):return self.request('POST','/api/geo/audit',{'website':'https://acme.example/','market':'US','request_id':str(uuid.uuid4()),**changes})
 def done(self,ident,preview=True):
  for _ in range(1000):
   j=self.manager.get(ident)
   if j['status'] not in ('running','queued') and self.w.audit_active is None:return j
   time.sleep(.005)
  self.fail('audit did not finish')
 def confirm(self,j,brand=None):
  candidate=j['candidates']['brand'];name=brand if brand is not None else candidate['name'] if candidate else ''
  return self.request('POST','/api/geo/audit-confirm',{'id':j['id'],'confirmed':{'brand':{'name':name,'aliases':[name] if name else []},'products':[],'competitors':[],'context':''}})
 def test_complete_url_confirm_report_export_without_models_and_fixture(self):
  code,j=self.start();self.assertEqual(code,202);self.assertEqual(j['phase'],'preview');preview=self.done(j['id']);self.assertEqual(preview['status'],'awaiting_confirmation');self.assertIsNone(preview['report']);self.assertEqual(preview['candidates']['brand']['name'],'Acme Tea');self.assertEqual(preview['candidates']['products'][0]['name'],'Green Tea');self.assertEqual([c['name'] for c in preview['candidates']['competitors']],['Rival Tea']);self.assertTrue(preview['evidence']);self.assertEqual(self.request('GET','/api/geo/audit-export?id='+j['id'])[0],409)
  code,queued=self.confirm(preview);self.assertEqual(code,202);self.assertEqual(queued['phase'],'report');full=self.done(j['id'],False);self.assertIn(full['status'],('finished','partial'));self.assertIsNotNone(full['report']);self.assertEqual(full['usage']['model_calls'],0);self.assertLessEqual(full['usage']['resources_requested'],6);self.assertLessEqual(full['usage']['http_requests'],10);self.assertLessEqual(full['usage']['bytes_received'],4*1024*1024);self.assertFalse((self.path/'unused-budget').exists());self.assertEqual(self.request('GET','/api/geo/audit-export?id='+j['id'])[1],full);self.assertFalse(any(k.startswith('_') for k in full));self.assertEqual(full['report']['model_analysis']['status'],'not_tested');self.assertEqual(full['report']['summary']['total_weight'],100)
  self.assertIn('noindex',' '.join(full['report']['summary']['conclusions']));pathlib.Path('/tmp/audit-contract-fixture.json').write_text(json.dumps(full,ensure_ascii=False,indent=2));pathlib.Path('/tmp/audit-preview-fixture.json').write_text(json.dumps(preview,ensure_ascii=False,indent=2))
  evidence_ids={e['id'] for e in preview['evidence']};self.assertTrue(set(preview['candidates']['brand']['evidence_ids'])<=evidence_ids)
 def test_auxiliary_redirect_cannot_enter_robots_disallowed_path(self):
  self.synthetic.robots='User-agent: SignalGEO\nDisallow: /private/\n\nUser-agent: *\nAllow: /'
  original=self.synthetic.__call__;requests=[]
  def redirected(operation,args,timeout):
   if operation=='http':
    requests.append(args[0])
    if args[0].endswith('/llms.txt'):return {'status':302,'headers':{'Location':'/private/secret'},'raw':b''}
   return original(operation,args,timeout)
  self.manager.budget_factory=lambda usage=None:f.FetchBudget(usage,worker=redirected)
  _,j=self.start();preview=self.done(j['id']);self.confirm(preview);full=self.done(j['id'],False)
  self.assertNotIn('https://acme.example/private/secret',requests)
  self.assertIn('robots_disallowed',json.dumps(full))
 def test_failure_still_confirms_empty_brand_and_exports_unknown_report(self):
  self.synthetic.seed_error='dns_failed';self.synthetic.robots_status=503;_,j=self.start();preview=self.done(j['id']);self.assertIsNone(preview['candidates']['brand']);self.assertEqual(self.confirm(preview)[0],202);full=self.done(j['id'],False);self.assertIsNone(full['report']['summary']['score']);self.assertIsNone(full['report']['summary']['partial_score']);self.assertEqual(full['report']['target']['brand'],'');self.assertEqual(self.request('GET','/api/geo/audit-export?id='+j['id'])[0],200)
 def test_seed_429_retry_after_does_not_retry_seed_as_markdown(self):
  self.synthetic.seed_status=429;_,j=self.start();preview=self.done(j['id']);self.assertIsNone(preview['candidates']['brand']);self.assertEqual(preview['access']['http_status'],429);self.assertIsNotNone(preview['access']['retry_after']);seed_urls=[c[1][0] for c in self.synthetic.calls if c[0]=='http' and c[1][0]=='https://acme.example/'];self.assertEqual(seed_urls,['https://acme.example/'])
  start=len(self.synthetic.calls);self.assertEqual(self.confirm(preview)[0],202);full=self.done(j['id'],False);report=full['report'];requested=[c[1][0] for c in self.synthetic.calls[start:] if c[0]=='http']
  self.assertNotIn('https://acme.example/',requested);self.assertIn('https://acme.example/robots.txt',requested);self.assertIn('https://acme.example/llms.txt',requested);self.assertEqual(sum(url=='https://acme.example/' for url in [c[1][0] for c in self.synthetic.calls if c[0]=='http']),1)
  self.assertIsNone(report['summary']['score']);self.assertIsNone(report['summary']['partial_score']);checks={c['id']:c for section in report['sections'] for c in section['checks']};self.assertEqual(checks['response']['status'],'unknown');self.assertEqual(checks['extraction']['status'],'unknown');self.assertEqual(checks['markdown']['status'],'unknown');self.assertEqual(full['usage']['model_calls'],0);self.assertEqual(self.request('GET','/api/geo/audit-export?id='+j['id'])[0],200)
 def test_confirm_idempotence_revision_and_manual_evidence_separation(self):
  _,j=self.start();preview=self.done(j['id']);self.confirm(preview);first=self.done(j['id'],False);calls=len(self.synthetic.calls);self.assertEqual(self.confirm(preview)[0],200);self.assertEqual(self.confirm(preview,brand='User Changed')[0],202);second=self.done(j['id'],False);self.assertEqual(second['revision'],first['revision']+1);self.assertEqual(len(self.synthetic.calls),calls);self.assertEqual(second['confirmed']['brand']['basis'],'user_modified');self.assertEqual(second['confirmed']['brand']['evidence_ids'],[]);self.assertEqual(second['candidates'],preview['candidates'])
 def test_real_http_manual_empty_aliases_are_normalized_without_evidence_theft(self):
  _,j=self.start();preview=self.done(j['id']);product=preview['candidates']['products'][0]
  payload={'id':j['id'],'confirmed':{'brand':{'name':'Manually Edited','aliases':[]},'products':[{'name':'Manual Product','aliases':[],'source_candidate_id':product['id']}],'competitors':[{'name':'Manual Competitor','aliases':[],'domains':['manual.example']}],'context':''}}
  code,queued=self.request('POST','/api/geo/audit-confirm',payload);self.assertEqual(code,202);full=self.done(j['id'],False);c=full['confirmed'];self.assertEqual(c['brand']['aliases'],['Manually Edited']);self.assertEqual(c['brand']['basis'],'user_modified');self.assertEqual(c['brand']['evidence_ids'],[]);self.assertEqual(c['products'][0]['aliases'],['Manual Product']);self.assertEqual(c['products'][0]['basis'],'user_modified');self.assertEqual(c['products'][0]['evidence_ids'],[]);self.assertEqual(c['competitors'][0]['aliases'],['Manual Competitor']);self.assertEqual(c['competitors'][0]['basis'],'user_provided');self.assertEqual(self.request('POST','/api/geo/audit-confirm',payload)[0],200)
 def test_cache_refresh_limits_and_no_automatic_network(self):
  _,j=self.start();self.done(j['id']);calls=len(self.synthetic.calls);code,reused=self.start();self.assertEqual(code,200);self.assertEqual(reused['id'],j['id']);self.assertEqual(len(self.synthetic.calls),calls);code,new=self.start(refresh=True);self.assertEqual(code,202);self.assertNotEqual(new['id'],j['id']);self.done(new['id'])
  for _ in range(8):_,j=self.start(refresh=True);self.done(j['id'])
  self.assertEqual(self.start(refresh=True)[0],429)
 def test_auth_query_schema_and_maintenance_without_model_ready(self):
  self.assertEqual(self.request('POST','/api/geo/audit',{},False)[0],401);self.assertEqual(self.start(model='gemini')[0],400);self.assertEqual(self.request('GET','/api/geo/audit?id='+str(uuid.uuid4())+'&id='+str(uuid.uuid4()))[0],400);self.w.maintenance_requested.set();self.assertEqual(self.start()[0],503);self.w.maintenance_requested.clear();self.assertFalse(self.w.ready);self.assertEqual(self.start()[0],202)
 def test_training_not_search_and_robots_404_vs_failures(self):
  for status,decision in [(404,'not_found'),(403,'unknown'),(429,'unknown'),(503,'unknown')]:
   self.synthetic.robots_status=status;_,j=self.start(refresh=True);j=self.done(j['id']);self.confirm(j);full=self.done(j['id'],False);report=full['report'];self.assertEqual(report['robots']['fetch_status'],decision)
   search=[c for s in report['sections'] for c in s['checks'] if c['id'].startswith('search-')];self.assertTrue(all(c['status']==('pass' if status==404 else 'unknown') for c in search));self.assertTrue(all(a['decision']==decision for a in report['robots']['agents']))
 def test_robots_unknown_and_signal_disallow_skip_auxiliary_without_retries(self):
  for body in ('<html>Temporary error</html>','User-agent: SignalGEO\nDisallow: /\n\nUser-agent: *\nAllow: /'):
   self.synthetic.robots=body;_,j=self.start(refresh=True);j=self.done(j['id']);start=len(self.synthetic.calls);self.confirm(j);full=self.done(j['id'],False);requested=[c[1][0] for c in self.synthetic.calls[start:] if c[0]=='http'];self.assertEqual(requested,['https://acme.example/robots.txt']);self.assertEqual(full['usage']['http_requests'],2)
 def test_changed_product_or_competitor_cannot_reuse_source_evidence(self):
  _,j=self.start();j=self.done(j['id']);source=j['candidates']['competitors'][0]
  confirmed=a.validate_confirmation({'brand':{'name':'Acme Tea','aliases':[]},'products':[],'competitors':[{'name':source['name'],'aliases':[],'source_candidate_id':source['id'],'domains':['unverified.example']} ]},j)
  self.assertEqual(confirmed['competitors'][0]['basis'],'user_modified');self.assertEqual(confirmed['competitors'][0]['evidence_ids'],[])
 def test_busy_is_visible_without_network_holding_workspace_lock(self):
  entered=threading.Event();release=threading.Event();original=self.synthetic.__call__
  def blocked(operation,args,timeout):
   if operation=='http':entered.set();release.wait(2)
   return original(operation,args,timeout)
  self.manager.budget_factory=lambda usage=None:f.FetchBudget(usage,worker=blocked);_,j=self.start();self.assertTrue(entered.wait(1));self.assertTrue(self.request('GET','/api/geo/state')[1]['busy']);self.assertEqual(self.start(website='https://other.example/',refresh=True)[0],409);self.w.maintenance_requested.set();release.set();self.done(j['id']);self.assertFalse(self.request('GET','/api/geo/state')[1]['busy'])
class PureToolsTests(unittest.TestCase):
 def test_actual_tools_are_offline_and_robots_group_isolation_and_longest_allow(self):
  self.assertTrue(a.tools_available());parsed=actual_tool('parse',(HTML,'https://acme.example/'));self.assertGreaterEqual(len(parsed['extracted_text']),500)
  decisions=actual_tool('robots',(ROBOTS,['https://acme.example/private/x','https://acme.example/private/open/x'],['GPTBot','OAI-SearchBot','Claude-SearchBot']))
  self.assertFalse(decisions['GPTBot']['https://acme.example/private/open/x']);self.assertFalse(decisions['OAI-SearchBot']['https://acme.example/private/x']);self.assertTrue(decisions['OAI-SearchBot']['https://acme.example/private/open/x']);self.assertTrue(decisions['Claude-SearchBot']['https://acme.example/private/x'])
 def test_query_specific_robots_policy_and_score_use_exact_request_target(self):
  synthetic=Synthetic();synthetic.robots='User-agent: OAI-SearchBot\nDisallow: /products?private=1\n\nUser-agent: *\nAllow: /'
  budget=f.FetchBudget(worker=synthetic);resource={'id':'robots','kind':'robots','url':'https://acme.example/robots.txt','captured_at':a.now(),'status':200,'error':None,'text':synthetic.robots,'diagnostics':{},'headers':{}}
  policy=a.robots_policy(resource,budget,'https://acme.example/products?private=1');row=next(v for v in policy['agents'] if v['user_agent']=='OAI-SearchBot' and v['path']=='/products?private=1');self.assertEqual(row['decision'],'disallowed')
  parsed=actual_tool('parse',(HTML,'https://acme.example/products?private=1'));seed={'id':'seed','kind':'seed','url':'https://acme.example/products?private=1','captured_at':a.now(),'status':200,'error':None,'headers':{},'parsed':parsed,'diagnostics':{'checks':[{'id':'tls','status':'passed'}]}}
  audit={'id':'test','market':'US','confirmed':{'brand':{'name':'Acme','aliases':['Acme']}},'evidence':[],'_internal':{'resources':[seed,resource],'robots':policy}}
  report=a.build_report(audit);check=next(v for s in report['sections'] for v in s['checks'] if v['id']=='search-OAI-SearchBot');self.assertEqual(check['status'],'fail')
 def test_real_spawned_parser_is_offline_and_parent_credentials_unchanged(self):
  import os
  with patch.dict(os.environ,{'SIGNAL_BAI_API_KEY':'synthetic-parent-secret','SIGNAL_WORKSPACE_PASSWORD':'synthetic-parent-password'}):
   parsed=f.isolated('parse',(HTML,'https://acme.example/'),10)
   self.assertGreater(len(parsed['extracted_text']),500);self.assertEqual(os.environ['SIGNAL_BAI_API_KEY'],'synthetic-parent-secret')
 def test_score_unknown_threshold_and_no_manual_identity_pass(self):
  parsed=actual_tool('parse',(HTML,'https://acme.example/'));parsed['metadata']['site_name']='';parsed['metadata']['structured_names']=[]
  seed={'id':'r1','kind':'seed','url':'https://acme.example/','captured_at':a.now(),'status':200,'error':None,'headers':{},'parsed':parsed,'diagnostics':{'checks':[{'id':'tls','status':'passed'}]}}
  audit={'id':'test','market':'US','confirmed':{'brand':{'name':'Manual Brand','aliases':['Manual Brand']}},'evidence':[],'_internal':{'resources':[seed]}}
  report=a.build_report(audit);self.assertIsNone(report['summary']['score']);self.assertEqual(report['summary']['known_weight'],80);self.assertIsNotNone(report['summary']['partial_score']);identity=next(c for s in report['sections'] for c in s['checks'] if c['id']=='identity');self.assertEqual(identity['status'],'fail')
  seed['parsed']=None;seed['error']='dns_failed';seed['diagnostics']['checks'][0]['status']='unknown';report=a.build_report(audit);self.assertEqual(report['summary']['known_weight'],0);self.assertIsNone(report['summary']['partial_score']);self.assertIsNone(report['summary']['score'])
if __name__=='__main__':unittest.main()
