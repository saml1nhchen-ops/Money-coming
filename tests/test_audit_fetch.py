"""Finite crawler boundary checks with synthetic transport and no network."""
import multiprocessing,pathlib,socket,sys,time,unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import audit_fetch as f
PUBLIC=[(2,1,6,'',('93.184.216.34',443))]
class BoundaryTests(unittest.TestCase):
 def setUp(self):
  p=patch('pinned_http.urllib.request.getproxies',return_value={});p.start();self.addCleanup(p.stop)
 def worker(self,operation,args,timeout):
  if operation=='dns':return PUBLIC
  if operation=='parse':return {'metadata':{'readable_characters':200},'text':'text','extracted_text':'x'*600}
  return {'status':200,'headers':{'Content-Type':'text/html' if '/robots' not in args[0] else 'text/plain'},'raw':b'<title>Public</title>'}
 def test_redirect_robots_guard_precedes_dns_and_http(self):
  calls=[]
  def worker(operation,args,timeout):
   calls.append((operation,args))
   if operation=='dns':return PUBLIC
   return {'status':302,'headers':{'Location':'/private/secret'},'raw':b''}
  result=f.FetchBudget(worker=worker).fetch('https://example.com/llms.txt','llms','https://example.com',permitted=lambda url:'/private/' not in url)
  self.assertEqual(result['error'],'robots_disallowed');self.assertEqual([v[0] for v in calls],['dns','http']);self.assertTrue(result['diagnostics']['redirects'])
 def test_timeout_reservation_survives_confirmation_budget_restore(self):
  capacities=[]
  def worker(operation,args,timeout):
   if operation=='dns':return PUBLIC
   capacities.append(args[2]);raise f.AuditFetchError('operation_timeout')
  budget=f.FetchBudget(worker=worker);budget.fetch('https://example.com/')
  restored=f.FetchBudget(budget.finish(),worker=worker);restored.fetch('https://example.com/second');result=restored.fetch('https://example.com/third')
  self.assertEqual(capacities,[2*1024*1024,2*1024*1024]);self.assertEqual(result['error'],'bytes_budget_exceeded');self.assertEqual(restored.usage['bytes_received'],0);self.assertEqual(restored.usage['bytes_budget_used'],f.MAX_BYTES)
 def test_private_mixed_dns_is_rejected_before_any_http(self):
  calls=[]
  def worker(operation,args,timeout):
   calls.append(operation);return PUBLIC+[(2,1,6,'',('127.0.0.1',443))]
  result=f.FetchBudget(worker=worker).fetch('https://public.example/');self.assertEqual(result['error'],'unsafe_address');self.assertEqual(calls,['dns'])
 def test_only_canonical_seed_redirects_and_strict_aux_origin(self):
  for location,allowed in [('https://www.example.com/product',True),('https://evil.example/product',False),('http://example.com/product',False)]:
   calls=[]
   def worker(operation,args,timeout):
    if operation=='dns':return PUBLIC
    if operation=='parse':return self.worker(operation,args,timeout)
    calls.append(args[0]);return {'status':302,'headers':{'Location':location},'raw':b''} if len(calls)==1 else self.worker(operation,args,timeout)
   result=f.FetchBudget(worker=worker).fetch('https://example.com/');self.assertEqual(result['error'] is None,allowed)
  result=f.FetchBudget(worker=self.worker).fetch('https://other.example/llms.txt','llms','https://example.com');self.assertEqual(result['error'],'cross_origin_redirect')
 def test_https_upgrade_cannot_then_downgrade_even_from_initial_http(self):
  self.assertTrue(f.same_seed_redirect('http://example.com/','https://www.example.com/','http://example.com/'))
  self.assertFalse(f.same_seed_redirect('https://www.example.com/','http://example.com/','http://example.com/'))
  self.assertFalse(f.same_seed_redirect('https://example.com/','https://evil.example/','http://example.com/'))
  self.assertFalse(f.same_seed_redirect('https://example.com/','https://example.com:80/','https://example.com/'))
 def test_http_byte_resource_limits_and_deadline_do_not_reset(self):
  budget=f.FetchBudget({'http_requests':10,'resources_requested':0,'bytes_received':0,'active_duration_ms':0,'model_calls':0},worker=self.worker);self.assertEqual(budget.fetch('https://example.com/')['error'],'http_budget_exceeded');self.assertEqual(budget.usage['http_requests'],10)
  budget=f.FetchBudget({'http_requests':0,'resources_requested':6,'bytes_received':0,'active_duration_ms':0,'model_calls':0},worker=self.worker);self.assertEqual(budget.fetch('https://example.com/')['error'],'resource_budget_exceeded')
  budget=f.FetchBudget({'http_requests':0,'resources_requested':0,'bytes_received':f.MAX_BYTES,'active_duration_ms':0,'model_calls':0},worker=self.worker);self.assertEqual(budget.fetch('https://example.com/')['error'],'bytes_budget_exceeded')
  budget=f.FetchBudget({'http_requests':0,'resources_requested':0,'bytes_received':0,'active_duration_ms':60000,'model_calls':0},worker=self.worker);self.assertEqual(budget.fetch('https://example.com/')['error'],'deadline_exceeded')
 def test_proxy_never_direct_connects_and_tls_fail_is_not_success(self):
  worker=Mock()
  with patch('pinned_http.urllib.request.getproxies',return_value={'https':'http://proxy.test'}):result=f.FetchBudget(worker=worker).fetch('https://example.com/')
  self.assertEqual(result['error'],'proxy_unsupported');worker.assert_not_called()
  def bad(operation,args,timeout):
   if operation=='dns':return PUBLIC
   raise f.AuditFetchError('tls_certificate_failed')
  result=f.FetchBudget(worker=bad).fetch('https://example.com/');self.assertEqual(result['error'],'tls_certificate_failed');self.assertFalse(any(c['id']=='tls' and c['status']=='passed' for c in result['diagnostics']['checks']))
 def test_truncated_resource_and_challenge_never_parsed_as_site(self):
  def oversized(operation,args,timeout):
   if operation=='dns':return PUBLIC
   return {'status':200,'headers':{'Content-Type':'text/html'},'raw':b'x'*args[2],'truncated':True}
  budget=f.FetchBudget(worker=oversized);self.assertEqual(budget.fetch('https://example.com/')['error'],'content_too_large');self.assertEqual(budget.usage['bytes_received'],2*1024*1024)
 def test_non_success_status_does_not_read_large_error_body(self):
  import io
  class Response:
   status=429;headers={'Content-Type':'text/html','Retry-After':'60','Content-Length':'999999999'}
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self,n):raise AssertionError('Error body must not be drained')
  class Pipe:
   def send(self,value):self.value=value
   def close(self):pass
  pipe=Pipe()
  with patch.object(f.urllib.request,'build_opener') as opener:
   opener.return_value.open.return_value=Response();f._worker(pipe,'http',('https://example.com/',PUBLIC,512*1024,'text/html',1))
  self.assertTrue(pipe.value['ok']);self.assertEqual(pipe.value['value']['status'],429);self.assertEqual(pipe.value['value']['raw'],b'')
 def test_isolated_worker_timeout_kills_only_owned_process(self):
  parent,child=Mock(),Mock();parent.poll.return_value=False;process=Mock();process.is_alive.return_value=True;context=Mock();context.Pipe.return_value=(parent,child);context.Process.return_value=process
  with patch.object(f.multiprocessing,'get_context',return_value=context):
   with self.assertRaises(f.AuditFetchError):f.isolated('parse',('html','https://example.com'),.01)
  process.terminate.assert_called_once();process.kill.assert_called_once();parent.close.assert_called_once()
if __name__=='__main__':unittest.main()
