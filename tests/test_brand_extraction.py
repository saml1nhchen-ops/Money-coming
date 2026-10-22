"""Captured public source metadata, not invented brand fixture names."""
import json,pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import geo_audit as a
import audit_fetch as f
from tests import test_geo_audit as fixtures
FIXTURE=json.loads(pathlib.Path(__file__).with_name('fixtures').joinpath('real-brand-metadata.json').read_text())
class BrandMetadataTests(unittest.TestCase):
 def preview(self,url):
  r={'id':'seed','url':url,'captured_at':'2026-10-22T15:25:00Z','status':200,'kind':'seed','headers':{},'diagnostics':{},'parsed':{'metadata':FIXTURE[url]['metadata'],'text':''}}
  audit={'evidence':[],'candidates':{}};a.preview_candidates(audit,r);return audit
 def test_real_nike_navigation_not_mistaken_for_read_failure(self):
  audit=self.preview('https://www.nike.com/');self.assertEqual(audit['candidates']['brand']['name'],'Nike.com');self.assertTrue(audit['candidates']['products']);self.assertTrue(all(c['kind']=='category' for c in audit['candidates']['products']));self.assertNotIn('Sign In',[c['name'] for c in audit['candidates']['products']]);self.assertFalse(audit['candidates']['competitors'])
 def test_real_loreal_us_categories_are_candidates_not_invented_products(self):
  audit=self.preview('https://www.lorealparisusa.com/');self.assertEqual(audit['candidates']['brand']['name'],"L'Oreal Paris");self.assertIn('Makeup',[c['name'] for c in audit['candidates']['products']]);self.assertTrue(all(c['evidence_ids'] and c['kind']=='category' for c in audit['candidates']['products']))
 def test_real_loreal_china_title_is_still_brand_evidence_without_body(self):
  audit=self.preview('https://www.lorealparis.com.cn/');self.assertEqual(audit['candidates']['brand']['name'],'巴黎欧莱雅');self.assertFalse(audit['candidates']['products'])
 def test_product_cards_beyond_large_navigation_and_image_alt_are_retained(self):
  from website_inspection import WebsiteExtractor
  p=WebsiteExtractor();p.feed('<a href="/help">Help</a>'*150+'<a class="product-card__link" href="/catalog/item"><img alt="Real Product" src="x"></a>');meta=p.metadata();self.assertTrue(meta['product_links'][-1]['product_marker']);self.assertEqual(meta['product_links'][-1]['text'],'Real Product')
class MarkdownFallbackTests(unittest.TestCase):
 setUp=fixtures.AuditWorkflowTests.setUp
 tearDown=fixtures.AuditWorkflowTests.tearDown
 request=fixtures.AuditWorkflowTests.request
 start=fixtures.AuditWorkflowTests.start
 done=fixtures.AuditWorkflowTests.done
 confirm=fixtures.AuditWorkflowTests.confirm
 def test_real_cremo_markdown_supplements_failed_home_without_retry_or_false_html_claim(self):
  original=self.synthetic.__call__
  def transport(operation,args,timeout):
   response=original(operation,args,timeout)
   if operation=='http' and args[0].endswith('/llms.txt'):response['raw']=FIXTURE['cremo_markdown']['text'].encode();response['headers']={'Content-Type':'text/markdown'}
   return response
  self.manager.budget_factory=lambda usage=None:f.FetchBudget(usage,worker=transport);self.synthetic.seed_status=429
  _,queued=self.start(website='https://cremocompany.com/');preview=self.done(queued['id']);self.assertEqual(preview['candidates']['brand']['name'],'Cremo');self.assertIn('Shaving Cream',[c['name'] for c in preview['candidates']['products']]);self.assertEqual(preview['access']['http_status'],429)
  self.assertEqual(preview['candidates']['brand']['source_field'],'Markdown H1');self.assertTrue(all(c['source_field']=='Markdown link' for c in preview['candidates']['products']));calls=sum(op=='http' for op,_,_ in self.synthetic.calls)
  self.confirm(preview);full=self.done(queued['id'],False);self.assertEqual(sum(op=='http' for op,_,_ in self.synthetic.calls),calls);self.assertIsNone(full['report']['summary']['score']);self.assertEqual(full['usage']['model_calls'],0);self.assertEqual(full['confirmed']['brand']['basis'],'website_text');self.assertEqual(self.request('GET','/api/geo/audit-export?id='+queued['id'])[0],200)
 def test_unknown_robots_never_fetches_markdown_fallback(self):
  self.synthetic.seed_status=429;self.synthetic.robots_status=503;_,j=self.start();preview=self.done(j['id']);self.assertIsNone(preview['candidates']['brand']);self.assertFalse(any(op=='http' and args[0].endswith('/llms.txt') for op,args,_ in self.synthetic.calls))
if __name__=='__main__':unittest.main()
