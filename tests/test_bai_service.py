import concurrent.futures,json,pathlib,sys,tempfile,threading,unittest,urllib.error,urllib.request
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import bai_service as b
class BaiTests(unittest.TestCase):
 def tearDown(self):b.clear()
 def connect(self):
  with patch.object(b,'remote',return_value={'data':[{'id':'test-gpt'},{'id':'deepseek-test'},{'id':'auto'}]}):return b.connect({'key':'fixture-private-key'})
 def add(self,model='test-gpt',protocol='chat',market='US'):
  b.profile({'model':model,'protocol':protocol,'markets':[market],'name':'Model name'})
  return next(p['id'] for p in b.state()['profiles'] if p['model']==model and p['protocol']==protocol)
 def test_key_is_private_and_failed_refresh_preserves_state(self):
  s=self.connect();self.assertEqual(len(s['models']),3);self.assertNotIn('fixture-private-key',json.dumps(s))
  with patch.object(b,'remote',side_effect=ValueError('HTTP 401')):
   with self.assertRaises(ValueError):b.connect({'key':'another-key'})
  self.assertTrue(b.state()['configured']);self.assertEqual(b.KEY,'fixture-private-key')
 def test_fixed_models_and_market_constraints(self):
  self.connect();pid=self.add()
  with self.assertRaises(ValueError):self.add('auto')
  with self.assertRaises(ValueError):self.add('unknown-model')
  with self.assertRaises(ValueError):b.profile({'model':'deepseek-test','protocol':'responses','markets':['CN'],'search':True})
  with self.assertRaises(ValueError):b.prepare({'market':'CN','providers':[pid],'prompts':['question'],'brand_aliases':['Brand'],'skus':[]})
 def test_batch_protocols_are_separate_and_secret_free(self):
  self.connect();a=self.add();c=self.add(protocol='responses')
  d={'market':'US','providers':[a,c],'prompts':['question'],'brand_aliases':['Brand'],'skus':[{'name':'Serum','aliases':['Serum 123']}]}
  responses=[{'model':'test-gpt','choices':[{'message':{'content':'Brand Serum 123'},'finish_reason':'stop'}]}, {'status':'completed','model':'test-gpt','output':[{'type':'message','content':[{'type':'output_text','text':'Brand Serum 123'}]}]}]
  with tempfile.TemporaryDirectory() as folder,patch.object(b,'run_path',side_effect=lambda rid:pathlib.Path(folder)/rid),patch.object(b,'remote',side_effect=responses) as remote:
   with concurrent.futures.ThreadPoolExecutor(1) as pool:r=b.start(d,pool)
   result=b.get_run(r['id'],True);self.assertEqual(result['status'],'finished');self.assertEqual(len(result['samples']),2)
   self.assertEqual(len(result['raw_evidence']),2);self.assertTrue(all(s['brand_mention_score']==100 for s in result['summary']))
   self.assertEqual(remote.call_args_list[0].args[0],'/chat/completions');self.assertEqual(remote.call_args_list[1].args[0],'/responses');self.assertNotIn('store',remote.call_args_list[1].args[2])
   for p in pathlib.Path(folder).rglob('*.json'):self.assertNotIn('fixture-private-key',p.read_text('utf-8'))
 def test_failures_and_truncation_do_not_become_zero_scores(self):
  self.connect();pid=self.add();d={'market':'US','providers':[pid],'prompts':['one','two'],'brand_aliases':['Brand'],'skus':[]}
  with tempfile.TemporaryDirectory() as folder,patch.object(b,'run_path',side_effect=lambda rid:pathlib.Path(folder)/rid),patch.object(b,'remote',side_effect=[ValueError('HTTP 429'),{'choices':[{'message':{'content':'Brand'},'finish_reason':'length'}]}]) as remote:
   with concurrent.futures.ThreadPoolExecutor(1) as pool:r=b.start(d,pool)
   result=b.get_run(r['id']);self.assertEqual([s['status'] for s in result['samples']],['failed','incomplete']);self.assertIsNone(result['summary'][0]['brand_mention_score']);self.assertEqual(remote.call_count,2)
 def test_auth_and_read_only_model_discovery(self):
  server=b.http.server.ThreadingHTTPServer(('127.0.0.1',0),b.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   url='http://127.0.0.1:'+str(server.server_port)+'/api/bai/state'
   with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(url)
   self.assertEqual(err.exception.code,401)
   req=urllib.request.Request(url,headers={'Authorization':'Bearer '+b.TOKEN})
   with urllib.request.urlopen(req) as r:self.assertFalse(json.load(r)['configured'])
   req=urllib.request.Request(url,headers={'Authorization':'Bearer '+b.TOKEN,'Origin':'https://evil.example'})
   with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(req)
  finally:server.shutdown();server.server_close();thread.join()
 def test_path_and_endpoint_confinement(self):
  with self.assertRaises(ValueError):b.run_path('../../secrets')
  with self.assertRaises(ValueError):b.remote('/purchase','key')
if __name__=='__main__':unittest.main()
