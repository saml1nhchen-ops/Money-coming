import io,json,pathlib,sys,unittest,urllib.error
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import free_competitors as f
from tests import test_geo_audit as fixture
class Reply:
 def __init__(self,value):self.raw=json.dumps(value).encode()
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def read(self,n):return self.raw[:n]
def answer(content=None):return {'model':'gpt-oss-20b','user_tier':'anonymous','choices':[{'finish_reason':'stop','message':{'content':json.dumps(content or {'competitors':[{'name':'Example Rival','reason':'Similar products'}]}),'reasoning':'unnecessary private reasoning'}}],'usage':{'total_tokens':50}}
class AdapterTests(unittest.TestCase):
 def test_fixed_anonymous_classic_endpoint_only_public_brand_payload_and_no_reasoning(self):
  with patch.object(f.urllib.request,'build_opener') as opener:
   opener.return_value.open.return_value=Reply(answer());result=f.ClassicCompetitors().suggest('Example','US',['Shave Cream']);request=opener.return_value.open.call_args.args[0]
   self.assertEqual(request.full_url,f.ENDPOINT);self.assertEqual(request.method,'POST');self.assertFalse(request.has_header('Authorization'));self.assertFalse(request.has_header('Cookie'));self.assertNotIn('key',request.full_url);body=json.loads(request.data);self.assertEqual(json.loads(body['messages'][1]['content']),{'brand':'Example','market':'US','products':['Shave Cream']});self.assertNotIn('tools',body);self.assertNotIn('reasoning',json.dumps(result));self.assertEqual(result['competitors'][0]['name'],'Example Rival')
 def test_payment_required_never_pays_or_retries(self):
  with patch.object(f.urllib.request,'build_opener') as opener:
   opener.return_value.open.side_effect=urllib.error.HTTPError(f.ENDPOINT,402,'Free limit',{'Retry-After':'30'},io.BytesIO(b'payment instructions'))
   with self.assertRaises(f.Unavailable) as caught:f.ClassicCompetitors().suggest('Example','US',[])
   self.assertEqual(caught.exception.code,'free_rate_limited');self.assertEqual(caught.exception.retry_after,'30');self.assertEqual(opener.return_value.open.call_count,1)
 def test_invalid_or_tool_output_is_not_adopted(self):
  for content in ({'competitors':['https://evil.example']},{'competitors':['Example']},{'competitors':['<img src=x>']},{'competitors':[]},{'competitors':['Rival'],'unknown_field':True}):
   with patch.object(f.urllib.request,'build_opener') as opener:
    opener.return_value.open.return_value=Reply(answer(content))
    with self.assertRaises(f.Unavailable):f.ClassicCompetitors().suggest('Example','US',[])
class FlowTests(unittest.TestCase):
 setUp=fixture.AuditWorkflowTests.setUp
 tearDown=fixture.AuditWorkflowTests.tearDown
 request=fixture.AuditWorkflowTests.request
 start=fixture.AuditWorkflowTests.start
 done=fixture.AuditWorkflowTests.done
 confirm=fixture.AuditWorkflowTests.confirm
 def test_one_free_attempt_cached_and_kept_separate_from_website_evidence(self):
  class Adapter:
   provider='Pollinations Classic';calls=0
   def suggest(self,brand,market,products):self.calls+=1;return {'competitors':[{'name':'AI Rival','reason':'Unverified idea'}],'model':'gpt-oss-20b','raw_response':answer()}
  adapter=Adapter();self.manager.suggestion_adapter=adapter;_,j=self.start();preview=self.done(j['id']);self.assertEqual(adapter.calls,1);rival=next(c for c in preview['candidates']['competitors'] if c['name']=='AI Rival');self.assertEqual(rival['basis'],'model_inference');self.assertFalse(rival['evidence_ids']);self.assertIsNone(rival['source_url']);self.assertEqual(preview['usage']['model_calls'],0);self.assertEqual(preview['competitor_suggestion']['model_calls'],1);self.start();self.assertEqual(adapter.calls,1)
  body={'id':j['id'],'confirmed':{'brand':{'name':'Acme Tea','aliases':['Acme Tea']},'products':[],'competitors':[{'name':'AI Rival','aliases':['AI Rival'],'source_candidate_id':rival['id']}]}}
  self.assertEqual(self.request('POST','/api/geo/audit-confirm',body)[0],202);full=self.done(j['id'],False);self.assertEqual(full['confirmed']['competitors'][0]['basis'],'model_inference');self.assertFalse(full['confirmed']['competitors'][0]['evidence_ids']);self.assertEqual(full['report']['model_analysis']['status'],'not_tested');self.assertEqual(adapter.calls,1);self.assertEqual(self.request('GET','/api/geo/audit-export?id='+j['id'])[1]['competitor_suggestion']['model'],'gpt-oss-20b')
 def test_restart_marks_inflight_suggestion_interrupted_without_replay(self):
  _,queued=self.start();audit=self.done(queued['id']);audit.update(status='running',phase='preview');audit['competitor_suggestion']={'status':'attempting','model_calls':1};self.manager.write(audit)
  import geo_audit
  restarted=geo_audit.AuditManager(self.w,self.path/'audits/index.sqlite3',self.factory)
  try:
   recovered=restarted.get(queued['id']);self.assertEqual(recovered['status'],'awaiting_confirmation');self.assertEqual(recovered['competitor_suggestion']['status'],'interrupted');self.assertEqual(recovered['competitor_suggestion']['model_calls'],1)
  finally:restarted.pool.shutdown(wait=True)
 def test_free_outage_does_not_lose_page_candidates_or_fallback_to_bai(self):
  class Adapter:
   provider='Pollinations Classic';calls=0
   def suggest(self,*args):self.calls+=1;raise f.Unavailable('free_rate_limited',402,'30')
  adapter=Adapter();self.manager.suggestion_adapter=adapter;_,j=self.start();preview=self.done(j['id']);self.assertEqual(preview['candidates']['brand']['name'],'Acme Tea');self.assertEqual(preview['competitor_suggestion']['status'],'unavailable');self.assertEqual(adapter.calls,1);self.confirm(preview);full=self.done(j['id'],False);self.assertIsNotNone(full['report']);self.assertEqual(adapter.calls,1);self.assertFalse((self.path/'unused-budget').exists())
if __name__=='__main__':unittest.main()
