import concurrent.futures,importlib,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import ai_api as a
class APIContracts(unittest.TestCase):
 def tearDown(self):a.CONFIG.clear()
 def cfg(self,p):return {'key':'private-fixture-key','model':'fixture-model','base_url':p['base_url'],'search':False}
 def test_catalog_and_request_contracts(self):
  self.assertEqual(len(a.catalog()),17)
  for p in a.catalog():
   c=self.cfg(p);u,h,b=a.request_for(p,c,'neutral question')
   self.assertTrue(u.startswith('https://'));self.assertNotIn(c['key'],u);self.assertNotIn(c['key'],json.dumps(b))
   if p['protocol']=='gemini':self.assertEqual(h['x-goog-api-key'],c['key']);self.assertEqual(b['contents'][0]['parts'][0]['text'],'neutral question')
   elif p['protocol']=='anthropic':self.assertEqual(h['x-api-key'],c['key']);self.assertEqual(h['anthropic-version'],'2023-06-01')
   elif p['protocol']=='perplexity':self.assertTrue(u.endswith('/v1/agent'));self.assertEqual(b['preset'],c['model'])
   else:self.assertEqual(h['Authorization'],'Bearer '+c['key'])
 def test_native_search_contracts(self):
  for pid in ['openai','gemini','claude','qwen']:
   p=a.provider(pid);c=self.cfg(p);c['search']=True;_,_,b=a.request_for(p,c,'question')
   self.assertTrue(b.get('tools') or b.get('enable_search'))
 def test_endpoint_and_key_security(self):
  for u in ['http://api.deepseek.com','https://evil.example/v1','https://key@api.deepseek.com','https://api.deepseek.com?key=x']:
   with self.assertRaises(ValueError):a.safe_endpoint(a.provider('deepseek'),u)
  a.configure({'provider':'deepseek','key':'secret','model':'test-model'})
  self.assertNotIn('secret',json.dumps(a.config_public()))
  with self.assertRaises(ValueError):a.configure({'provider':'deepseek','key':'x\r\ny','model':'test-model'})
 def test_parsers_and_incomplete_answers(self):
  p=a.provider('deepseek');raw={'choices':[{'message':{'content':'<think>hidden</think>Brand serum'},'finish_reason':'length'}]}
  x=a.parse(p,raw);self.assertFalse(x['complete']);self.assertEqual(x['answer'],'Brand serum');self.assertEqual(x['citations'],[])
  self.assertTrue(a.parse(p,{'choices':[{'message':{'content':'answer'},'finish_reason':'stop'}]})['complete'])
  self.assertFalse(a.parse(p,{'choices':[{'message':{'content':'blocked'},'finish_reason':'content_filter'}]})['complete'])
 def test_all_native_response_formats(self):
  fixtures={
   'openai':{'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'answer','annotations':[{'type':'url_citation','url':'https://official.example/a'}]}]}]},
   'perplexity':{'status':'completed','output':[{'type':'search_results','results':[{'url':'https://source.example'}]},{'type':'message','content':[{'type':'output_text','text':'answer'}]}]},
   'gemini':{'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'answer'}]},'groundingMetadata':{'groundingChunks':[{'web':{'uri':'https://source.example'}}],'groundingSupports':[{'groundingChunkIndices':[0]}]}}]},
   'claude':{'stop_reason':'end_turn','content':[{'type':'text','text':'answer','citations':[{'url':'https://source.example'}]}]}}
  for pid,f in fixtures.items():
   r=a.parse(a.provider(pid),f);self.assertTrue(r['complete']);self.assertEqual(r['answer'],'answer')
  self.assertEqual(len(a.parse(a.provider('perplexity'),fixtures['perplexity'])['citations']),0)
  self.assertEqual(len(a.parse(a.provider('gemini'),fixtures['gemini'])['citations']),1)
 def test_mentions_and_score_denominators(self):
  self.assertIsNone(a.mention('foobranding',['brand']))
  self.assertEqual(a.mention('L’Oréal Paris serum',["L'Oréal Paris"]),"L'Oréal Paris")
  s={'provider':'deepseek','status':'complete','brand_prompted':False,'brand_match':'brand','sku_matches':{'serum':'serum'},'sku_prompted':{'serum':False}}
  r=a.aggregate([s,{**s,'status':'failed'},{**s,'status':'incomplete'},{**s,'brand_prompted':True},{**s,'sku_prompted':{'serum':True}}],['deepseek'],[{'name':'serum'}])[0]
  self.assertEqual(r['brand_mention_score'],100);self.assertEqual(r['complete'],3);self.assertEqual(r['skus'][0]['denominator'],1)
  self.assertIsNone(a.aggregate([{**s,'status':'failed'}],['deepseek'],[])[0]['brand_mention_score'])
 def test_atomic_batch_preflight_and_evidence(self):
  d={'market':'CN','providers':['deepseek'],'prompts':['neutral question'],'brand_aliases':['Brand'],'skus':[{'name':'serum','aliases':['Serum 123']}]}
  with self.assertRaises(ValueError):a.validate_run(d)
  a.configure({'provider':'deepseek','key':'private-fixture-key','model':'test'})
  raw={'model':'returned-model','choices':[{'message':{'content':'Brand Serum 123 private-fixture-key'},'finish_reason':'stop'}]}
  with tempfile.TemporaryDirectory() as folder,patch.object(a,'results_dir',return_value=pathlib.Path(folder)),patch.object(a,'http_json',return_value=raw) as request:
   with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:r=a.start_run(d,pool)
   run=a.get_run(r['id']);self.assertEqual(run['status'],'finished');self.assertEqual(run['summary'][0]['brand_mention_score'],100)
   sample=run['samples'][0];self.assertEqual(sample['model_returned'],'returned-model');self.assertEqual(len(sample['raw_sha256']),64)
   for p in pathlib.Path(folder).rglob('*.json'):self.assertNotIn('private-fixture-key',p.read_text('utf-8'))
   args=request.call_args.args;self.assertEqual(args[2]['messages'],[{'role':'user','content':'neutral question'}])
 def test_provider_failure_stays_unscored(self):
  d={'market':'CN','providers':['deepseek'],'prompts':['neutral question'],'brand_aliases':['Brand'],'skus':[]}
  a.configure({'provider':'deepseek','key':'private-fixture-key','model':'test'})
  with tempfile.TemporaryDirectory() as folder,patch.object(a,'results_dir',return_value=pathlib.Path(folder)),patch.object(a,'http_json',side_effect=ValueError('Provider HTTP 401')):
   with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:r=a.start_run(d,pool)
   run=a.get_run(r['id']);self.assertEqual(run['status'],'finished');self.assertEqual(run['samples'][0]['status'],'failed');self.assertIsNone(run['summary'][0]['brand_mention_score'])
if __name__=='__main__':unittest.main()
