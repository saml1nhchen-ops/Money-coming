import email.message
import hashlib
import json
import pathlib
import sys
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import geo_flow as flow
import website_inspection as inspection


class Response:
 def __init__(self,text,kind='text/html; charset=utf-8'):
  self.body=text.encode();self.headers=email.message.Message();self.headers['Content-Type']=kind
 def __enter__(self):return self
 def __exit__(self,*args):return False
 def read(self,n):return self.body[:n]


class WebsiteInspectionTests(unittest.TestCase):
 def fetch(self,text,kind='text/html; charset=utf-8',allow_short=True):
  with patch.object(flow.socket,'getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]),patch.object(flow.urllib.request,'build_opener') as opener:
   opener.return_value.open.return_value=Response(text,kind)
   return flow.fetch_website('brand.example',allow_short=allow_short)
 def inspect(self,text,kind='text/html; charset=utf-8'):
  return inspection.inspect_snapshot(self.fetch(text,kind),'US')
 def test_metadata_score_brand_and_provenance(self):
  html='<html><head><title>Actual Brand | Products</title><meta property="og:site_name" content="Actual Brand"><meta name="description" content="Real product scope"></head><body><h1>Products</h1><p>'+('Product description. '*10)+'</p><script>HIDDEN</script></body></html>'
  snapshot=self.fetch(html);result=inspection.inspect_snapshot(snapshot,'CN')
  self.assertEqual(result['diagnosis']['score'],100)
  self.assertIsInstance(result['diagnosis']['methodology'],str)
  self.assertEqual(result['brand'],{'name':'Actual Brand','aliases':['Actual Brand'],'source':'meta[property="og:site_name"]','needs_confirmation':False})
  self.assertEqual(result['website']['content_sha256'],hashlib.sha256(html.encode()).hexdigest())
  self.assertEqual(result['website']['url'],'https://brand.example/')
  self.assertNotIn('HIDDEN',result['context'])
 def test_missing_elements_fail_but_sparse_or_plain_text_is_unknown_score(self):
  result=self.inspect('<html><body>'+('Readable product details '*10)+'</body></html>')
  self.assertEqual(result['diagnosis']['score'],25)
  self.assertEqual([c['status'] for c in result['diagnosis']['checks']],['fail','fail','fail','pass'])
  self.assertEqual(result['brand']['source'],'domain_fallback');self.assertTrue(result['brand']['needs_confirmation'])
  sparse=self.inspect('<title>Just a title</title><script>'+('x'*1000)+'</script>')
  self.assertIsNone(sparse['diagnosis']['score']);self.assertTrue(sparse['warnings'])
  plain=self.inspect('Plain text product details '*20,'text/plain')
  self.assertIsNone(plain['diagnosis']['score'])
  self.assertEqual(plain['diagnosis']['checks'][0]['status'],'unknown')
  with self.assertRaisesRegex(ValueError,'可读内容过少'):self.fetch('<title>Short</title>',allow_short=False)
 def test_structured_brand_and_title_candidates_require_confirmation(self):
  html='<title>Page title | Other</title><script type="application/ld+json">'+json.dumps({'@graph':[{'@type':'Product','name':'Do not use product as brand'},{'@type':'Organization','name':'Declared Company'}]})+'</script>'+('Body content '*20)
  result=self.inspect(html)
  self.assertEqual(result['brand']['name'],'Declared Company');self.assertEqual(result['brand']['source'],'JSON-LD Organization.name');self.assertTrue(result['brand']['needs_confirmation'])
  title=self.inspect('<title>Page Brand | Catalogue</title>'+('Body content '*20))
  self.assertEqual(title['brand']['name'],'Page Brand');self.assertTrue(title['brand']['needs_confirmation'])
 def test_normalization_and_disallowed_targets(self):
  self.assertEqual(inspection.normalize_url(' Example.COM/product?q=x#section '),'https://example.com/product?q=x')
  self.assertEqual(inspection.normalize_url('https://example.com/产品?q=中文'),'https://example.com/%E4%BA%A7%E5%93%81?q=%E4%B8%AD%E6%96%87')
  for value in ('https://user:pass@example.com','file:///etc/passwd','https://example.com:9000','https://exam\nple.com','https://example.com\\@evil.com'):
   with self.assertRaises(ValueError):inspection.normalize_url(value)
  with patch.object(flow.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]),patch.object(flow.urllib.request,'build_opener') as opener:
   with self.assertRaisesRegex(ValueError,'公开网络'):flow.fetch_website('localhost',allow_short=True)
   opener.assert_not_called()
 def test_redirect_revalidated_and_response_size_limited(self):
  public=[(2,1,6,'',('8.8.8.8',443))];private=[(2,1,6,'',('127.0.0.1',443))]
  redirect=urllib.error.HTTPError('https://brand.example/',302,'redirect',{'Location':'http://127.0.0.1/'},None)
  with patch.object(flow.socket,'getaddrinfo',side_effect=[public,private]),patch.object(flow.urllib.request,'build_opener') as opener:
   opener.return_value.open.side_effect=redirect
   with self.assertRaisesRegex(ValueError,'公开网络'):flow.fetch_website('brand.example',allow_short=True)
   self.assertEqual(opener.return_value.open.call_count,1)
  with self.assertRaisesRegex(ValueError,'2 MB'):self.fetch('x'*(2*1024*1024+1))
 def test_inspection_does_not_need_model_catalog_and_failures_are_not_scores(self):
  snapshot=self.fetch('<title>Brand</title>'+('Details '*30))
  with patch.object(flow,'fetch_website',return_value=snapshot) as fetch,patch.object(flow,'catalog') as catalog,patch.object(flow,'bridge') as bridge,patch.object(flow,'direct_bridge') as direct:
   result=flow.inspect_website({'website':'brand.example','market':'US'})
   self.assertEqual(result['diagnosis']['scope'],'website_readiness')
   fetch.assert_called_once_with('https://brand.example/',allow_short=True)
   catalog.assert_not_called();bridge.assert_not_called();direct.assert_not_called()
  with patch.object(flow,'fetch_website',side_effect=ValueError('抓取失败')):
   with self.assertRaisesRegex(ValueError,'抓取失败'):flow.inspect_website({'website':'brand.example','market':'US'})
  with patch.object(flow,'fetch_website',side_effect=urllib.error.URLError('untrusted remote error')):
   with self.assertRaisesRegex(ValueError,'未生成分数') as error:flow.inspect_website({'website':'brand.example','market':'US'})
   self.assertNotIn('untrusted remote error',str(error.exception))
  with self.assertRaises(ValueError):flow.inspect_website({'website':'brand.example','market':'XX'})


class InspectionHTTPTests(unittest.TestCase):
 def test_authenticated_endpoint_and_failure_status(self):
  server=flow.http.server.ThreadingHTTPServer(('127.0.0.1',0),flow.Handler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  url='http://127.0.0.1:'+str(server.server_port)+'/api/geo/inspect'
  def request(token=None,origin=None):
   headers={'Host':'127.0.0.1:8772','Content-Type':'application/json'}
   if token:headers['Authorization']='Bearer '+token
   if origin:headers['Origin']=origin
   return urllib.request.Request(url,json.dumps({'website':'brand.example','market':'US'}).encode(),headers)
  try:
   for req in (request(),request(flow.TOKEN,'https://evil.example')):
    with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(req)
    self.assertEqual(error.exception.code,401)
   with patch.object(flow,'inspect_website',return_value={'diagnosis':{'score':None}}) as inspect:
    with urllib.request.urlopen(request(flow.TOKEN)) as response:
     self.assertEqual(response.status,200);self.assertIsNone(json.load(response)['diagnosis']['score'])
    inspect.assert_called_once_with({'website':'brand.example','market':'US'})
   with patch.object(flow,'inspect_website',side_effect=ValueError('抓取失败')):
    with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request(flow.TOKEN))
    self.assertEqual(error.exception.code,400);self.assertEqual(json.load(error.exception),{'error':'抓取失败'})
  finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
