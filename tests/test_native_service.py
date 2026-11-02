import importlib.util,json,pathlib,sys,threading,unittest,urllib.request,urllib.error
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from unittest.mock import patch
import native_service as service
class Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.server=service.http.server.ThreadingHTTPServer(('127.0.0.1',0),service.Handler)
  service.PORT=cls.server.server_port
  cls.url='http://127.0.0.1:'+str(service.PORT)
  cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
 @classmethod
 def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join()
 def request(self,path,token=None,origin=None,body=None):
  headers={}
  if token:headers['Authorization']='Bearer '+token
  if origin:headers['Origin']=origin
  req=urllib.request.Request(self.url+path,None if body is None else json.dumps(body).encode(),headers)
  try:
   with urllib.request.urlopen(req) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 def test_auth_required(self):self.assertEqual(self.request('/api/tools/health')[0],401)
 def test_ai_api_auth_and_no_key_state(self):
  self.assertEqual(self.request('/api/tools/ai/providers')[0],401)
  code,j=self.request('/api/tools/ai/providers',service.TOKEN)
  providers=json.loads((ROOT/'dist/ai-providers.json').read_text('utf-8'))
  self.assertEqual(len({p['id'] for p in providers}),len(providers))
  self.assertEqual(code,200);self.assertEqual(len(j['providers']),len(providers))
  self.assertFalse(any(p['configured'] for p in j['providers']))
  code,j=self.request('/api/tools/ai/run',service.TOKEN,body={'market':'CN','providers':['deepseek'],'prompts':['question'],'brand_aliases':['Brand'],'skus':[]})
  self.assertEqual(code,400);self.assertIn('not configured',j['error'])
 def test_bad_origin_rejected(self):self.assertEqual(self.request('/api/tools/health',service.TOKEN,'https://evil.example')[0],401)
 def test_health(self):
  code,j=self.request('/api/tools/health',service.TOKEN);self.assertEqual(code,200);self.assertEqual(len(j['tools']),18)
 def test_unknown_tool_rejected(self):self.assertEqual(self.request('/api/tools/run',service.TOKEN,body={'tool':'unknown'})[0],400)
 def test_session_not_public(self):self.assertEqual(self.request('/api/tools/session')[0],403)
 def test_no_local_target(self):
  with self.assertRaises(ValueError):service.public_url('http://127.0.0.1')
  with self.assertRaises(ValueError):service.public_url('file:///C:/Windows/win.ini')
 def test_file_confinement(self):
  with self.assertRaises(ValueError):service.scoped_file(service.JOBS,'../../README.md')
 def test_real_source_and_licenses(self):
  self.assertEqual(len(service.CATALOG),18)
  for r in service.CATALOG:
   self.assertRegex(r['commit'],r'^[a-f0-9]{40}$');self.assertTrue(r['licenses'],r['id'])
   for s in r['skill_documents']:self.assertTrue(s['text']);self.assertEqual(len(s['sha256']),64)
class RunPoolTests(unittest.TestCase):
 def test_ai_run_uses_separate_configured_pool(self):
  self.assertIsNot(service.AI_RUN_POOL,service.POOL)
  self.assertGreaterEqual(service.AI_RUN_POOL._max_workers,service.ai_api.env_int('SIGNAL_GEO_CONCURRENCY',16,1,128))
  self.assertEqual(service.POOL._max_workers,2)
  from io import BytesIO
  from unittest.mock import Mock
  handler=Mock(path='/api/tools/ai/run',headers={'Content-Length':'2'},rfile=BytesIO(b'{}'))
  handler.auth.return_value=True
  with patch.object(service.ai_api,'start_run',return_value={'id':'fixture'}) as start:
   service.Handler.do_POST(handler)
  handler.reply.assert_called_once_with({'id':'fixture'},202)
  start.assert_called_once_with({},service.AI_RUN_POOL)
if __name__=='__main__':unittest.main()
