import sys, unittest, copy, json, urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import action
class BackendTests(unittest.TestCase):
 def setUp(self):
  self.s={'workspaces':[{'id':'real','demo':False,'brand':'Test','aliases':['Test'],'domains':[]},{'id':'other','demo':False}],**{k:[] for k in ['answers','prompts','facts','projects','artifacts','experiments','audit']},'revision':1}
 def do(self,a,p):return action(self.s,'real',a,p)
 def test_import_dedup_and_scope(self):
  a={'prompt_text':'Which brand?','topic':'Test','market':'us','locale':'en','platform':'Manual test','collected_at':'2026-10-18T12:00:00Z','status':'success','raw_answer':'Test','citations':[{'url':'https://example.com?p=1'}]}
  self.do('import',{'rows':[a,a]});self.do('import',{'rows':[a]});self.assertEqual(len(self.s['answers']),1)
  with self.assertRaises(ValueError):action(self.s,'other','edit_prompt',{'id':self.s['prompts'][0]['id'],'text':'Stolen'})
  a['citations']=[{'url':'javascript:alert(1)'}]
  with self.assertRaises(ValueError):self.do('import',{'rows':[a]})
 def test_approval_edit_invalidation_and_evidence(self):
  self.do('fact',{'title':'Test','text':'Five tablets per pack.','source':'Approved document paragraph 2','market':'us'})
  with self.assertRaises(ValueError):self.do('draft',{'title':'Update','target':'https://example.com','market':'us'})
  f=self.s['facts'][0];self.do('approve_fact',{'id':f['id']});self.do('draft',{'title':'Update','target':'https://example.com','market':'us'});a=self.s['artifacts'][0]
  self.do('artifact_status',{'id':a['id'],'status':'in_review'});self.do('artifact_status',{'id':a['id'],'status':'approved'});self.assertIn('hash',a['approval'])
  self.do('save_artifact',{'id':a['id'],'body':'Invented cure claim.','target':'https://example.com'});self.assertEqual(a['status'],'draft');self.assertIsNone(a['approval'])
  with self.assertRaises(ValueError):self.do('receipt',{'id':a['id'],'url':'https://example.com','date':'2026-10-18','evidence':'changed'})
  with self.assertRaises(ValueError):self.do('artifact_status',{'id':a['id'],'status':'in_review'})
 def test_prompt_version(self):
  self.do('prompt',{'text':'Old','topic':'Test','market':'cn','locale':'zh'});p=self.s['prompts'][0];self.do('edit_prompt',{'id':p['id'],'text':'New'});self.assertEqual(p['version'],2);self.assertEqual(p['history'][0]['text'],'Old')
if __name__=='__main__':unittest.main()
