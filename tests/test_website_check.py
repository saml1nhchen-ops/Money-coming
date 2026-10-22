"""Synthetic pinned-fetch diagnostics; no external network or model requests."""
import email.message,io,json,pathlib,socket,ssl,sys,unittest,urllib.error
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import geo_flow as flow
import website_check as c
PUBLIC=[(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('93.184.216.34',443))]
class Response:
 def __init__(self,body,kind='text/html; charset=utf-8',status=200):self.body=body.encode();self.status=status;self.headers=email.message.Message();self.headers['Content-Type']=kind
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def read(self,n):return self.body[:n]
class WebsiteCheckTests(unittest.TestCase):
 def setUp(self):
  for patcher in (patch('pinned_http.urllib.request.getproxies',return_value={}),patch.object(flow.socket,'getaddrinfo',return_value=PUBLIC)):
   patcher.start();self.addCleanup(patcher.stop)
 def failed(self,error):
  with patch.object(flow.urllib.request,'build_opener') as opener:
   opener.return_value.open.side_effect=error
   with self.assertRaises(c.WebsiteCheckError) as caught:flow.fetch_website('https://example.com/',allow_short=True)
   self.assertEqual(opener.return_value.open.call_count,1)
   return caught.exception.diagnostics
 def test_429_is_limited_not_claimed_bot_and_no_retry_or_body_leak(self):
  diagnostic=self.failed(urllib.error.HTTPError('https://example.com/',429,'SECRET',{'Retry-After':'120','Set-Cookie':'SECRET','X-Private':'SECRET'},io.BytesIO(b'SECRET')))
  self.assertEqual(diagnostic['outcome'],'limited');self.assertEqual(diagnostic['http_status'],429);self.assertEqual(diagnostic['retry_after'],'120');self.assertTrue(diagnostic['possible_access_restriction']);self.assertIn('不能据此确定反爬',diagnostic['findings'][0]['message']);self.assertNotIn('SECRET',json.dumps(diagnostic))
 def test_403_is_blocked_and_retry_after_is_strict(self):
  d=self.failed(urllib.error.HTTPError('https://example.com/',403,'SECRET',{'Retry-After':'SECRET'},None));self.assertEqual(d['outcome'],'blocked');self.assertIsNone(d['retry_after']);self.assertTrue(d['possible_access_restriction'])
  self.assertEqual(c.safe_retry_after('Wed, 21 Oct 2026 07:28:00 GMT'),'Wed, 21 Oct 2026 07:28:00 GMT')
  for value in ('1\nSECRET','x'*101,'-1','2026-01-01','Wed, 99 Oct 2026 07:28:00 GMT'):self.assertIsNone(c.safe_retry_after(value))
 def test_readable_response_has_real_http_tls_content_observations(self):
  html='<title>Public Brand</title><h1>Products</h1><p>'+'Product scope. '*30+'</p>'
  with patch.object(flow.urllib.request,'build_opener') as opener:
   opener.return_value.open.return_value=Response(html);snapshot=flow.fetch_website('https://example.com/',allow_short=True)
  d=snapshot['diagnostics'];self.assertEqual(d['outcome'],'readable');self.assertEqual(d['http_status'],200);self.assertGreaterEqual(d['readable_characters'],100);self.assertEqual(d['bytes'],len(html.encode()));self.assertEqual(d['content_type'],'text/html');self.assertEqual([r['status'] for r in d['checks']],['passed']*5);self.assertFalse(d['possible_access_restriction']);self.assertGreaterEqual(d['duration_ms'],0)
 def test_200_challenge_is_not_normal_readable_content(self):
  html='<title>Just a moment...</title><h1>Verify you are human</h1><script src="/cdn-cgi/challenge-platform/test.js"></script>'
  with patch.object(flow.urllib.request,'build_opener') as opener:
   opener.return_value.open.return_value=Response(html)
   with self.assertRaises(c.WebsiteCheckError) as error:flow.fetch_website('https://example.com/',allow_short=True)
  self.assertEqual(error.exception.code,'website_challenge');self.assertEqual(error.exception.diagnostics['outcome'],'challenge');self.assertEqual(error.exception.diagnostics['http_status'],200);self.assertTrue(error.exception.diagnostics['possible_access_restriction'])
 def test_captcha_word_on_normal_product_page_is_not_challenge(self):
  html='<title>Real Products</title><p>'+('Products; captcha support information. '*100)+'</p><div class="g-recaptcha"></div>'
  with patch.object(flow.urllib.request,'build_opener') as opener:
   opener.return_value.open.return_value=Response(html);self.assertEqual(flow.fetch_website('https://example.com/',allow_short=True)['diagnostics']['outcome'],'readable')
 def test_tls_failure_does_not_claim_verification_success(self):
  d=self.failed(urllib.error.URLError(ssl.SSLCertVerificationError('SECRET certificate data')));self.assertEqual(d['outcome'],'unreachable');self.assertEqual(next(r['status'] for r in d['checks'] if r['id']=='tls'),'failed');self.assertIsNone(d['http_status']);self.assertNotIn('SECRET',str(d))
 def test_empty_dns_results_fail_diagnostics_without_opening_request(self):
  with patch.object(flow.socket,'getaddrinfo',return_value=[]),patch.object(flow.urllib.request,'build_opener') as opener:
   with self.assertRaises(c.WebsiteCheckError) as error:flow.fetch_website('https://example.com/',allow_short=True)
  self.assertEqual(error.exception.code,'dns_failed');self.assertEqual(error.exception.diagnostics['outcome'],'unreachable');self.assertEqual(next(r['status'] for r in error.exception.diagnostics['checks'] if r['id']=='dns'),'failed');opener.assert_not_called()
 def test_dns_timeout_private_and_proxy_have_distinct_safe_reasons(self):
  with patch.object(flow.socket,'getaddrinfo',side_effect=socket.gaierror('SECRET')):
   with self.assertRaises(c.WebsiteCheckError) as error:flow.fetch_website('https://example.com/',allow_short=True)
   self.assertEqual(error.exception.code,'dns_failed');self.assertEqual(next(r['status'] for r in error.exception.diagnostics['checks'] if r['id']=='tls'),'unknown')
  self.assertEqual(self.failed(TimeoutError('SECRET'))['findings'][0]['code'],'connection_timeout')
  with patch.object(flow.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
   with self.assertRaises(c.WebsiteCheckError) as error:flow.fetch_website('https://example.com/',allow_short=True)
   self.assertEqual(error.exception.diagnostics['outcome'],'unsafe');self.assertEqual(error.exception.code,'unsafe_address')
  with patch('pinned_http.urllib.request.getproxies',return_value={'https':'http://proxy.test'}),patch.object(flow.socket,'getaddrinfo') as dns:
   with self.assertRaises(c.WebsiteCheckError) as error:flow.fetch_website('https://example.com/',allow_short=True)
   self.assertEqual(error.exception.code,'proxy_unsupported');dns.assert_not_called()
 def test_redirect_chain_is_bounded_and_each_hop_checked(self):
  redir=urllib.error.HTTPError('https://example.com/',302,'SECRET',{'Location':'/products/'},None)
  with patch.object(flow.urllib.request,'build_opener') as opener:
   opener.return_value.open.side_effect=[redir,Response('<title>Brand</title><p>'+'Scope '*30+'</p>')];d=flow.fetch_website('https://example.com/',allow_short=True)['diagnostics']
   self.assertEqual(d['redirects'],[{'url':'https://example.com/','status':302,'location':'https://example.com/products/'}]);self.assertEqual(d['final_url'],'https://example.com/products/')
  with patch.object(flow.urllib.request,'build_opener') as opener:
   opener.return_value.open.side_effect=[urllib.error.HTTPError('https://example.com/',302,'',{'Location':'/'},None) for _ in range(5)]
   with self.assertRaises(c.WebsiteCheckError) as error:flow.fetch_website('https://example.com/',allow_short=True)
   self.assertEqual(error.exception.code,'redirect_limit');self.assertEqual(len(error.exception.diagnostics['redirects']),5);self.assertEqual(opener.return_value.open.call_count,5)
 def test_non_text_size_and_sparse_are_unsupported_and_http_skips_tls(self):
  for response,code in [(Response('SECRET','application/pdf'),'unsupported_content'),(Response('x'*(2*1024*1024+1)),'content_too_large')]:
   with patch.object(flow.urllib.request,'build_opener') as opener:
    opener.return_value.open.return_value=response
    with self.assertRaises(c.WebsiteCheckError) as error:flow.fetch_website('http://example.com/',allow_short=True)
    self.assertEqual(error.exception.code,code);self.assertEqual(next(r['status'] for r in error.exception.diagnostics['checks'] if r['id']=='tls'),'skipped')
  with patch.object(flow.urllib.request,'build_opener') as opener:
   opener.return_value.open.return_value=Response('<title>Brand</title>');d=flow.fetch_website('https://example.com/',allow_short=True)['diagnostics'];self.assertEqual(d['outcome'],'unsupported');self.assertEqual(d['readable_characters'],0)
if __name__=='__main__':unittest.main()
