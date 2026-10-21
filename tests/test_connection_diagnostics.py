"""Mock-only diagnostics: no external requests, credentials or production changes."""
import base64,importlib.util,io,json,pathlib,ssl,unittest,urllib.error
from unittest.mock import Mock,patch
ROOT=pathlib.Path(__file__).resolve().parents[1];spec=importlib.util.spec_from_file_location('diag',ROOT/'deploy/connection_diagnostics.py');d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
class Response:
 def __init__(self,status,body,headers=None):self.status=status;self.body=json.dumps(body).encode();self.headers=headers or {}
 def read(self,n):return self.body[:n]
 def __enter__(self):return self
 def __exit__(self,*args):return False
class DiagnosticsTests(unittest.TestCase):
 def test_health_body_is_strictly_whitelisted(self):
  body={'ok':True,'revision':'a'*40,'version':'v0.3.1','capabilities':{'remember_login':True,'remember_login_max_age_seconds':2592000,'private':'SECRET'},'token':'SECRET','password':'SECRET','runs':[{'answer':'SECRET'}]}
  safe=d.safe_body(json.dumps(body),True);self.assertNotIn('SECRET',str(safe));self.assertEqual(set(safe),{'ok','revision','version','capabilities'});self.assertNotIn('private',safe['capabilities'])
  self.assertEqual(d.safe_body(json.dumps({'code':'unauthorized','error':'SECRET'})),{'code':'unauthorized'});self.assertEqual(d.safe_body(json.dumps({'code':'SECRET'})),{'code':'unavailable'})
 def test_cors_and_preflight_checks_without_credentials(self):
  headers={'Access-Control-Allow-Origin':d.ORIGIN,'Access-Control-Allow-Methods':'GET, POST, OPTIONS','Access-Control-Allow-Headers':'Content-Type, Authorization','Set-Cookie':'SECRET'}
  opener=Mock();opener.open.return_value=Response(204,{},headers);result=d.probe(opener,'OPTIONS','/api/workspace/login',True,'POST');self.assertTrue(result['expected_status']);self.assertTrue(result['cors_origin_matches']);self.assertTrue(result['preflight_headers_allowed']);self.assertNotIn('SECRET',str(result))
  req=opener.open.call_args.args[0];self.assertIsNone(req.data);self.assertIsNone(req.get_header('Authorization'));self.assertEqual(req.full_url,d.BASE+'/api/workspace/login');self.assertEqual(req.method,'OPTIONS')
 def test_anonymous_401_is_read_as_expected_without_error_body(self):
  opener=Mock();opener.open.side_effect=urllib.error.HTTPError(d.BASE,401,'SECRET',{'Access-Control-Allow-Origin':d.ORIGIN},io.BytesIO(b'{"code":"unauthorized","private":"SECRET"}'))
  result=d.probe(opener,'GET','/api/geo/state',True);self.assertTrue(result['expected_status']);self.assertEqual(result['body'],{'code':'unauthorized'});self.assertNotIn('SECRET',str(result))
 def test_connection_errors_are_safe_classified_and_no_retry(self):
  for error,code in [(ssl.SSLCertVerificationError('SECRET'),'tls_verification_failed'),(TimeoutError('SECRET'),'timeout'),(OSError('SECRET'),'connection_failed')]:
   opener=Mock();opener.open.side_effect=error;result=d.probe(opener,'GET','/healthz');self.assertEqual(result['error'],code);self.assertEqual(opener.open.call_count,1);self.assertNotIn('SECRET',str(result))
 def test_collect_uses_only_five_fixed_readonly_endpoints(self):
  context=ssl.create_default_context();self.assertTrue(context.check_hostname);self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
  raw=Mock();tls=Mock();tls.getpeercert.return_value={'notBefore':'Nov 1 00:00:00 2026 GMT','notAfter':'Feb 1 00:00:00 2027 GMT'};tls.version.return_value='TLSv1.3';wrapped=Mock();wrapped.__enter__=Mock(return_value=tls);wrapped.__exit__=Mock(return_value=False)
  socket_context=Mock();socket_context.__enter__=Mock(return_value=raw);socket_context.__exit__=Mock(return_value=False)
  with patch.object(d.socket,'getaddrinfo',return_value=[(2,1,6,'',('43.154.242.184',443))]),patch.object(d.urllib.request,'getproxies',return_value={}),patch.object(d.ssl,'create_default_context',return_value=Mock(wrap_socket=Mock(return_value=wrapped))) as factory,patch.object(d.socket,'create_connection',return_value=socket_context),patch.object(d,'probe',return_value={'synthetic':True}) as probe:
   report=d.collect();self.assertTrue(report['tls']['verified']);factory.return_value.wrap_socket.assert_called_once_with(raw,server_hostname=d.HOST)
   self.assertEqual([(c.args[1],c.args[2]) for c in probe.call_args_list],[('GET','/healthz'),('GET','/healthz'),('OPTIONS','/api/workspace/login'),('OPTIONS','/api/geo/state'),('GET','/api/geo/state')])
 def test_proxy_configuration_never_falls_back_to_direct_tls(self):
  with patch.object(d.socket,'getaddrinfo',return_value=[]),patch.object(d.urllib.request,'getproxies',return_value={'https':'http://proxy.test'}),patch.object(d.socket,'create_connection') as connect,patch.object(d,'probe',return_value={}):
   report=d.collect();connect.assert_not_called();self.assertEqual(report['tls']['error'],'proxy_configured_direct_tls_probe_skipped')
 def test_report_publication_only_creates_diagnostic_result_branch_and_file(self):
  env={'GITHUB_REPOSITORY':'saml1nhchen-ops/Money-coming','GITHUB_RUN_ID':'12345','GITHUB_SHA':'a'*40,'GH_TOKEN':'SECRET'};report={'schema':1,'target':d.BASE}
  with patch.object(d,'api') as api:
   self.assertEqual(d.publish(report,env),'diagnostic-results/12345');self.assertEqual(api.call_count,2);first,second=api.call_args_list
   self.assertEqual(first.args[3:5],('POST','/git/refs'));self.assertEqual(first.args[5],{'ref':'refs/heads/diagnostic-results/12345','sha':'a'*40})
   self.assertEqual(second.args[3:5],('PUT','/contents/connection-report.json'));self.assertEqual(second.args[5]['branch'],'diagnostic-results/12345');self.assertEqual(json.loads(base64.b64decode(second.args[5]['content'])),report)
  with patch.object(d,'api') as api:
   with self.assertRaises(RuntimeError):d.publish(report,{**env,'GITHUB_RUN_ID':'main'})
   api.assert_not_called()
 def test_workflow_is_separate_branch_trigger_and_pinned_checkout(self):
  import yaml
  w=yaml.load((ROOT/'.github/workflows/connection-diagnostics.yml').read_text(),Loader=yaml.BaseLoader);self.assertEqual(w['on'],{'push':{'branches':['diagnose/connection-*']}});job=w['jobs']['diagnose'];self.assertIn('deleted == false',job['if']);self.assertIn('forced == false',job['if']);self.assertEqual(job['permissions'],{'contents':'write'});self.assertRegex(job['steps'][0]['uses'],r'^actions/checkout@[a-f0-9]{40}$')
if __name__=='__main__':unittest.main()
