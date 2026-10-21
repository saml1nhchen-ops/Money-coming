import pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
from remote_service import choose_models,bootstrap,prepare_dependencies,Services,install_maintenance_signals,should_hold_maintenance,read_deployment_receipt
from remote_gateway import Workspace,Budget,Failure
class BootstrapTests(unittest.TestCase):
 def test_real_catalog_selection(self):
  catalog=[{'id':i} for i in ('gpt-4.1','gpt-auto','gpt-latest','gemini-2.5-flash','gemini-image','unrelated')]
  self.assertEqual(choose_models(catalog,{}),['gpt-4.1','gemini-2.5-flash'])
  with self.assertRaises(Failure):choose_models(catalog,{'SIGNAL_GPT_MODEL':'invented'})
 def test_missing_key_no_outbound(self):
  class API:
   def call(self,*args):raise AssertionError('Unexpected outbound')
  with tempfile.TemporaryDirectory() as tmp:
   w=Workspace('long-enough-password','public.example',Budget(pathlib.Path(tmp)/'b',126),API());bootstrap(w,{})
   self.assertFalse(w.ready);self.assertEqual(w.reason,'missing_bai_key')
 def test_catalog_and_runtime_readiness(self):
  class API:
   def __init__(self):self.calls=[];self.profiles=[]
   def call(self,service,path,body):
    self.calls.append((path,body))
    if path=='profile':self.profiles.append({'id':body['model'],'model':body['model'],'protocol':'chat','search':False,'markets':['CN','US']})
    return {'models':[{'id':'gpt-4.1'},{'id':'gemini-2.5-flash'}],'profiles':self.profiles,'fetched_at':'actual-time'}
  with tempfile.TemporaryDirectory() as tmp:
   api=API();w=Workspace('long-enough-password','public.example',Budget(pathlib.Path(tmp)/'b',126),api)
   with patch('remote_service.prepare_dependencies',return_value=False):bootstrap(w,{'SIGNAL_BAI_API_KEY':'synthetic-key'})
   self.assertFalse(w.ready);self.assertEqual(w.reason,'runtime_unavailable');self.assertEqual(len(api.calls),3);self.assertEqual(w.profiles[0]['manufacturer'],'OpenAI');self.assertTrue(all(body['markets']==['CN','US'] for path,body in api.calls if path=='profile'))
 def test_existing_listener_not_disturbed(self):
  with patch('remote_service.socket.socket') as mock:
   mock.return_value.__enter__.return_value.connect_ex.return_value=0
   services=Services()
   with self.assertRaises(RuntimeError):services.start()
   self.assertEqual(services.children,[])
 def test_persistent_volume_seed_and_existing_data(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp)/'app';seed=pathlib.Path(tmp)/'seed';cli=seed/'node_modules/tsx/dist/cli.mjs';cli.parent.mkdir(parents=True);cli.write_text('synthetic')
   with patch.dict('os.environ',{'SIGNAL_UPSTREAM_SEED':str(seed)}),patch('remote_service.shutil.which',return_value='/usr/bin/node'):
    self.assertTrue(prepare_dependencies(root));self.assertEqual((root/'runtime/upstreams/niubigeo').resolve(),seed)
    other=pathlib.Path(tmp)/'other';other.mkdir()
    with patch.dict('os.environ',{'SIGNAL_UPSTREAM_SEED':str(other)}):
     self.assertTrue(prepare_dependencies(root));self.assertEqual((root/'runtime/upstreams/niubigeo').resolve(),seed)
 def test_shutdown_only_owns_children(self):
  from unittest.mock import Mock
  services=Services();child=Mock();child.poll.return_value=None;services.children=[child];services.stop();child.terminate.assert_called_once();child.wait.assert_called_once_with(timeout=5)
 def test_maintenance_startup_and_signal_handlers_only_change_event(self):
  import signal
  with tempfile.TemporaryDirectory() as tmp:
   w=Workspace('long-enough-password','public.example',Budget(pathlib.Path(tmp)/'b',126))
   with patch('remote_service.signal.signal') as register,patch.object(w.api,'call') as network:
    install_maintenance_signals(w,{'SIGNAL_DEPLOY_MAINTENANCE':'1'});self.assertTrue(w.maintenance_requested.is_set())
    handlers={call.args[0]:call.args[1] for call in register.call_args_list}
    handlers[signal.SIGUSR2](None,None);self.assertFalse(w.maintenance_requested.is_set());handlers[signal.SIGUSR1](None,None);self.assertTrue(w.maintenance_requested.is_set());network.assert_not_called()
 def test_restart_receipt_only_releases_matching_healthy_deployment(self):
  env={'SIGNAL_DEPLOY_MAINTENANCE':'1','SIGNAL_DEPLOY_NONCE':'a'*32,'SIGNAL_BUILD_REVISION':'b'*40}
  healthy={'status':'healthy','nonce':'a'*32,'revision':'b'*40}
  self.assertFalse(should_hold_maintenance(env,healthy))
  for receipt in (None,[],{},dict(healthy,status='pending'),dict(healthy,nonce='c'*32),dict(healthy,revision='c'*40)):
   self.assertTrue(should_hold_maintenance(env,receipt))
  self.assertTrue(should_hold_maintenance({'SIGNAL_DEPLOY_MAINTENANCE':'1'},healthy))
  self.assertFalse(should_hold_maintenance({},None))
  unknown={**env,'SIGNAL_BUILD_REVISION':''};self.assertFalse(should_hold_maintenance(unknown,{**healthy,'revision':'unknown'}))
  with tempfile.TemporaryDirectory() as tmp:
   w=Workspace('long-enough-password','public.example',Budget(pathlib.Path(tmp)/'b',126))
   with patch('remote_service.signal.signal'),patch('remote_service.read_deployment_receipt',return_value=healthy):install_maintenance_signals(w,env)
   self.assertFalse(w.maintenance_requested.is_set())
   with patch('remote_service.signal.signal'),patch('remote_service.read_deployment_receipt',return_value={**healthy,'nonce':'c'*32}):install_maintenance_signals(w,env)
   self.assertTrue(w.maintenance_requested.is_set())
 def test_receipt_read_is_bounded_and_corrupt_missing_fail_closed(self):
  import io
  for raw in (b'x'*4096,b'not json'):
   with patch('remote_service.pathlib.Path.open',return_value=io.BytesIO(raw)):self.assertIsNone(read_deployment_receipt())
  with patch('remote_service.pathlib.Path.open',side_effect=PermissionError):self.assertIsNone(read_deployment_receipt())
  with patch('remote_service.pathlib.Path.open',return_value=io.BytesIO(b'{"status":"healthy"}')):self.assertEqual(read_deployment_receipt(),{'status':'healthy'})
if __name__=='__main__':unittest.main()
