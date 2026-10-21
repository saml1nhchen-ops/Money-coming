"""Synthetic loopback only: no signals, model calls, or external services."""
import contextlib,http.server,io,json,pathlib,sys,threading,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import deploy_control as dc

class ControlTests(unittest.TestCase):
 def setUp(self):
  self.login_count=0;self.states=0;self.paths=[];self.observations=[]
  self.state={'busy':False,'remote':{'deployment_gate':'signals-v1','maintenance':True,'model_ready':True,'budget':{'limit':126,'reserved':63,'remaining':63}}};self.health={'ok':True,'revision':'a'*40,'version':'v1.2.3'}
  test=self
  class Handler(http.server.BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    test.paths.append(self.path);test.assertEqual(self.path,'/api/workspace/login');test.assertEqual(self.headers['Host'],'public.example');d=json.loads(self.rfile.read(int(self.headers['Content-Length'])));test.assertEqual(d,{'password':'synthetic-team-password'});test.login_count+=1;self.reply({'token':'synthetic-bearer'})
   def do_GET(self):
    test.paths.append(self.path);test.assertEqual(self.headers['Host'],'public.example')
    if self.path=='/healthz':return self.reply(test.health)
    test.assertEqual(self.path,'/api/geo/state');test.assertEqual(self.headers['Authorization'],'Bearer synthetic-bearer');test.states+=1
    self.reply(test.observations.pop(0) if test.observations else test.state)
   def reply(self,d):
    raw=json.dumps(d).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
  self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.env={'SIGNAL_PUBLIC_HOST':'public.example','SIGNAL_WORKSPACE_PASSWORD':'synthetic-team-password','PORT':str(self.server.server_port)}
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
 def test_probe_health_safe_metadata_single_login(self):
  c=dc.Control(self.env);probe=c.probe();self.assertEqual(probe,{'ok':True,'host':'public.example','deployment_gate':'signals-v1','model_ready':True,'maintenance':True,'busy':False,'revision':'a'*40,'version':'v1.2.3'});self.assertEqual(c.health(),probe);self.assertEqual(self.login_count,1);self.assertNotIn('synthetic',str(probe));self.assertNotIn('SIGNAL',str(probe))
 def test_wait_idle_uses_one_session_and_no_side_effects(self):
  import copy
  busy=copy.deepcopy(self.state);busy['busy']=True;self.observations=[busy,busy,self.state]
  c=dc.Control(self.env)
  with patch('deploy_control.time.sleep'):self.assertTrue(c.wait_idle(2)['maintenance'])
  self.assertEqual(self.login_count,1);self.assertEqual(self.states,3);self.assertEqual(set(self.paths),{'/api/workspace/login','/api/geo/state','/healthz'})
 def test_gate_missing_fails_before_any_control_action(self):
  self.state['remote'].pop('deployment_gate')
  with self.assertRaises(dc.ControlError) as error:dc.Control(self.env).probe()
  self.assertEqual(error.exception.code,'deployment_gate_unavailable');self.assertEqual(self.paths,['/api/workspace/login','/api/geo/state'])
 def test_health_checks_model_gate_and_idle(self):
  for field,value,code in [('model_ready',False,'model_not_ready'),('maintenance',False,'maintenance_required')]:
   self.state['remote'][field]=value
   with self.assertRaises(dc.ControlError) as error:dc.Control(self.env).health()
   self.assertEqual(error.exception.code,code);self.state['remote'][field]=True
  self.state['busy']=True
  with self.assertRaises(dc.ControlError) as error:dc.Control(self.env).health()
  self.assertEqual(error.exception.code,'backend_busy')
 def test_wait_timeout_is_bounded_and_health_unknown_compatible(self):
  self.state['busy']=True
  with self.assertRaises(dc.ControlError) as error:dc.Control(self.env).wait_idle(.01)
  self.assertEqual(error.exception.code,'idle_timeout');self.assertEqual(self.login_count,1)
  self.state['busy']=False;self.health={'ok':True};self.assertEqual(dc.Control(self.env).health()['revision'],'unknown')
 def test_health_timeout_reuses_login_through_readiness_changes(self):
  import copy
  not_ready=copy.deepcopy(self.state);not_ready['remote']['model_ready']=False
  busy=copy.deepcopy(self.state);busy['busy']=True
  unmaintained=copy.deepcopy(self.state);unmaintained['remote']['maintenance']=False
  self.observations=[not_ready,busy,unmaintained,self.state]
  c=dc.Control(self.env)
  with patch('deploy_control.time.sleep'):self.assertTrue(c.health(timeout=2)['model_ready'])
  self.assertEqual(self.login_count,1);self.assertEqual(self.states,4)
 def test_health_retries_network_only_with_same_authenticated_token(self):
  c=dc.Control(self.env);c.probe();original=c.request;failed=[]
  def flaky(path,body=None):
   if path=='/api/geo/state' and not failed:failed.append(True);raise dc.ControlError('control_unavailable')
   return original(path,body)
  with patch.object(c,'request',side_effect=flaky),patch('deploy_control.time.sleep'):self.assertTrue(c.health(timeout=2)['ok'])
  self.assertEqual(self.login_count,1)
 def test_health_terminal_errors_and_bounded_timeout(self):
  c=dc.Control(self.env)
  for code in ('authentication_failed','deployment_gate_unavailable','rate_limited','access_forbidden','budget_unavailable','invalid_response'):
   with self.subTest(code=code),patch.object(c,'observe',side_effect=dc.ControlError(code)) as observe:
    with self.assertRaises(dc.ControlError) as error:c.health(timeout=2)
    self.assertEqual(error.exception.code,code);self.assertEqual(observe.call_count,1)
  self.state['remote']['model_ready']=False
  with self.assertRaises(dc.ControlError) as error:c.health(timeout=.01)
  self.assertEqual(error.exception.code,'health_timeout');self.assertEqual(self.login_count,1)
 def test_health_cli_accepts_optional_timeout(self):
  with patch.dict('os.environ',self.env,clear=True),contextlib.redirect_stdout(io.StringIO()) as output:self.assertEqual(dc.main(['health','--timeout','180']),0)
  self.assertTrue(json.loads(output.getvalue())['model_ready']);self.assertEqual(self.login_count,1)
 def test_cli_errors_do_not_print_credentials(self):
  output=io.StringIO()
  with patch.dict('os.environ',self.env,clear=True),patch.object(dc.Control,'probe',side_effect=RuntimeError('synthetic-team-password synthetic-bearer')),contextlib.redirect_stdout(output):self.assertEqual(dc.main(['probe']),1)
  self.assertEqual(json.loads(output.getvalue()),{'ok':False,'code':'control_unavailable'})
if __name__=='__main__':unittest.main()
