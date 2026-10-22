import concurrent.futures,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import geo_flow as flow
import geo_analysis as a

def config():return {'market':'US','website':'https://brand.test','brand_aliases':['Brand'],'providers':['p'],'generator':'p','count':2,'repeats':1,'skus':[{'name':'Serum X','aliases':['Serum X']}],'competitors':[{'name':'Rival','aliases':['Rival'],'domains':['rival.test']}],'configuration':{'p':{'id':'p'}}}
def sample(answer,prompt='Best products?',status='complete',**extra):return {'id':'s','provider':'p','status':status,'answer':answer,'prompt':prompt,'citations':[],'retrieved_sources':[],**extra}

class AnalysisTests(unittest.TestCase):
 def test_rank_requires_numbered_lead_and_not_body_or_negative(self):
  c=config();s=sample('Brand appears in discussion.\n1. Rival: a product. Brand is another option.\n2. Serum X: description.\n3. Avoid Brand')
  r=a.analyze([s],c);b=r['models'][0]['brands'];self.assertIsNone(b[0]['average_rank']);self.assertEqual(b[1]['average_rank'],1);self.assertEqual(r['models'][0]['skus'][0]['average_rank'],2)
 def test_unknown_rank_and_failed_answers_do_not_become_zero(self):
  r=a.analyze([sample('Brand'),sample('',status='failed',id='f')],config());b=r['models'][0]['brands'][0];self.assertEqual(b['score'],100);self.assertIsNone(b['average_rank']);self.assertEqual(b['denominator'],1)
 def test_prompted_competitor_and_sku_excluded(self):
  r=a.analyze([sample('Brand','Rival alternatives?'),sample('Brand','Serum X benefits?')],config());self.assertEqual(r['models'][0]['eligible'],0);self.assertIsNone(r['models'][0]['brands'][0]['score'])
 def test_citation_gap_and_provenance_not_answer_links(self):
  s=sample('See Rival and https://brand.test/page',citations=[{'url':'https://rival.test/product'}],retrieved_sources=[{'url':'https://brand.test/page'}]);r=a.analyze([s],config());self.assertEqual(len(r['gaps']),1)
  s['citations'].append({'url':'https://shop.brand.test/product'});r=a.analyze([s],config());self.assertEqual(len(r['gaps']),0);self.assertEqual(r['models'][0]['brands'][0]['citation_answers'],1)
 def test_unsafe_urls_and_similar_domains_not_own(self):
  self.assertFalse(a.host('javascript:alert(1)'));self.assertFalse(a.owned('evilbrand.test',['brand.test']));self.assertTrue(a.owned('shop.brand.test',['brand.test']))
 def test_sources_count_answers_not_duplicate_links(self):
  s=sample('Rival',citations=[{'url':'https://rival.test/a'},{'url':'https://rival.test/a'},{'url':'https://rival.test/b'}]);r=a.analyze([s],config());self.assertEqual(r['sources'][0]['answer_count'],1);self.assertEqual(len(r['sources'][0]['urls']),2)

class PipelineTests(unittest.TestCase):
 def setUp(self):flow.BUSY=False;flow.CANCEL.clear()
 def tearDown(self):flow.BUSY=False;flow.CANCEL.clear()
 def test_real_upstream_generator_and_parser(self):
  c=config();built=flow.niubi('build',c,website_text='Serums for dry skin');self.assertIn('Generate 2 monitoring prompts',built['prompt'])
  parsed=flow.niubi('parse',c,text=json.dumps([{'type':'recommendation','topic':'skin','prompt':'Best serum for dry skin?','targetIncluded':False,'auditCategory':'organic_discovery'}]));self.assertEqual(parsed[0]['text'],'Best serum for dry skin?')
 def test_generator_parse_failure_no_answer_calls(self):
  with tempfile.TemporaryDirectory() as t,patch.object(flow,'DATA',pathlib.Path(t)),patch.object(flow,'fetch_website',return_value={'text':'site'}),patch.object(flow,'niubi',side_effect=[{'prompt':'generate'},ValueError('Invalid JSON')]),patch.object(flow,'call',return_value={'id':'gen','samples':[{'answer':'broken','status':'complete'}]}) as call:
   job={'id':'00000000-0000-0000-0000-000000000000','config':config(),'samples':[]};flow.folder(job['id']).mkdir();flow.execute(job);self.assertEqual(job['status'],'failed');self.assertEqual(call.call_count,1);self.assertIn('generation',job)
 def test_generation_only_never_samples(self):
  with tempfile.TemporaryDirectory() as t,patch.object(flow,'DATA',pathlib.Path(t)),patch.object(flow,'fetch_website',return_value={'text':'site'}),patch.object(flow,'niubi',side_effect=[{'prompt':'generate'},[{'text':'question'}]]),patch.object(flow,'call',return_value={'id':'gen','samples':[{'answer':'[]','status':'complete'}]}) as call:
   c=config();c['count']=1;c['generate_only']=True;job={'id':'00000000-0000-0000-0000-000000000000','config':c,'samples':[]};flow.folder(job['id']).mkdir();flow.execute(job);self.assertEqual(job['status'],'finished');self.assertEqual(call.call_count,1)
 def test_answer_failure_retained_and_cancellation_prevents_new_calls(self):
  c=config();job={'id':'x','config':c,'prompts':[{'text':'question'}],'samples':[]}
  with patch.object(flow,'persist'),patch.object(flow,'call',return_value={'id':'r','samples':[sample('',status='failed')]}) as call:
   flow.collect(job);self.assertEqual(job['status'],'partial');self.assertIsNone(job['report']['models'][0]['brands'][0]['score']);self.assertEqual(call.call_count,1)
   flow.CANCEL.add('x')
   with self.assertRaises(ValueError):flow.collect(job)
   self.assertEqual(call.call_count,1)
 def test_local_website_blocked_before_network_request(self):
  with self.assertRaises(ValueError):flow.fetch_website('http://127.0.0.1/')
 def test_validation_accepts_two_actual_profiles_from_same_manufacturer(self):
  profiles=[{'id':pid,'markets':['US'],'model':model,'manufacturer':'OpenAI'} for pid,model in [('gpt-a','gpt-4.1'),('gpt-b','gpt-4.1-mini')]]
  with patch.object(flow,'catalog',return_value={'configured':True,'profiles':profiles}):
   c=config();c.update(providers=['gpt-a','gpt-b'],generator='gpt-a',count=30)
   validated=flow.validate(c);self.assertEqual(validated['providers'],['gpt-a','gpt-b']);self.assertEqual(set(validated['configuration']),{'gpt-a','gpt-b'})
   for ids in (['gpt-a','gpt-a'],['gpt-a','missing'],['gpt-a']*17):
    with self.assertRaises(ValueError):flow.validate({**c,'providers':ids})
 def test_validation_market_budget_and_overlap(self):
  state={'configured':True,'profiles':[{'id':'p','markets':['US'],'model':'gpt-test'}]}
  with patch.object(flow,'catalog',return_value=state):
   c=config();self.assertEqual(flow.validate(c)['market'],'US');c['count']=10;c['repeats']=3;c['providers']=['p','q','r']
   with self.assertRaises(ValueError):flow.validate(c)
   c=config();c['market']='CN'
   with self.assertRaises(ValueError):flow.validate(c)

 def test_reanalysis_preserves_original_and_never_calls_models(self):
  with tempfile.TemporaryDirectory() as t,patch.object(flow,'DATA',pathlib.Path(t)),patch.object(flow,'bridge') as bridge,patch.object(flow,'direct_bridge') as direct:
   rid='00000000-0000-0000-0000-000000000000';flow.folder(rid).mkdir();parent={'id':rid,'config':config(),'samples':[sample('1. Brand Serum X')],'status':'finished','calls':[]};flow.persist(parent)
   child=flow.reanalyze({'id':rid,'skus':[{'name':'New SKU','aliases':['Serum X']}]})
   self.assertEqual(child['report']['models'][0]['skus'][0]['average_rank'],1);self.assertEqual(flow.get(rid)['config']['skus'][0]['name'],'Serum X');self.assertEqual(child['planned_max_calls'],0);bridge.assert_not_called();direct.assert_not_called()

if __name__=='__main__':unittest.main()
