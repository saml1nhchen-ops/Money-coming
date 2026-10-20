import json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import geo_flow as f
import geo_plan as p
import geo_analysis as a
from test_geo_flow import config,sample

class BaselineTests(unittest.TestCase):
 def test_thirty_distinct_questions_one_call_each(self):
  cfg=config();cfg.update(count=30,repeats=1);batches=p.blueprint(30)
  self.assertEqual(len(batches),3);self.assertEqual(sum(s['family']=='discovery' for b in batches for s in b),21)
  self.assertEqual(p.plan(cfg)['maximum_calls'],33)
  job={'id':'fixture','config':cfg,'website':{'text':'Official public product scope'},'prompts':[],'samples':[],'calls':[]}
  def niubi(op,c,**extra):
   if op=='build':return {'prompt':'build'}
   return [{'text':('Brand benefits ' if s['family']=='brand' else 'Brand versus Rival ' if s['family']=='comparison' else 'Product need ')+str(s['index']),'type':'recommendation'} for s in c['question_blueprint']]
  def call(j,pid,qs,kind):
   n=len(j['samples']);return {'id':'r'+str(n),'samples':[sample('1. Brand Serum X',prompt=qs[0])]} if kind=='sampling' else {'id':'g','samples':[{'status':'complete','answer':'[]'}]}
  with patch.object(f,'persist'),patch.object(f,'niubi',side_effect=niubi),patch.object(f,'call',side_effect=call) as called:
   f.generate_bank(job);job['prompt_hash']=p.fingerprint(job['prompts']);f.collect(job)
   self.assertEqual(len(job['prompts']),30);self.assertEqual(len(job['samples']),30);self.assertEqual(called.call_count,33);self.assertEqual(job['status'],'finished');self.assertEqual(job['report']['groups']['discovery']['question_count'],21)
   before=called.call_count;f.collect(job);self.assertEqual(called.call_count,before)
 def test_same_manufacturer_cannot_be_double_counted(self):
  cfg=config();cfg.update(providers=['p','q'],generator='p')
  state={'configured':True,'profiles':[{'id':'p','markets':['US'],'model':'gemini-test','provider':'bai'},{'id':'q','markets':['US'],'model':'gemini-test','provider':'gemini'}]}
  with patch.object(f,'catalog',return_value=state):
   with self.assertRaisesRegex(ValueError,'厂商'):f.validate(cfg)
 def test_repeat_rejected_for_new_jobs(self):
  cfg=config();cfg['repeats']=2
  with self.assertRaisesRegex(ValueError,'只调用一次'):f.validate(cfg)
 def test_normalized_duplicate_questions_are_equal(self):self.assertEqual(p.question_key('Best serum?'),p.question_key(' BEST serum ! '))
 def test_group_scores_separate_discovery_from_prompted_brand(self):
  cfg=config();samples=[sample('No tracked names',id='natural'),sample('Brand','What is Brand?',id='brand')];bank=[{'text':'Best products?'},{'text':'What is Brand?'}]
  report=a.analyze(samples,cfg,bank);self.assertEqual(report['models'][0]['brands'][0]['score'],0);self.assertEqual(report['groups']['brand']['models'][0]['brands'][0]['score'],100)
 def test_real_upstream_build_fits_old_runner_input_budget(self):
  cfg=config();cfg.update(count=10,question_blueprint=p.blueprint(30)[0],previous_questions=['Question '+str(n) for n in range(6)])
  prompt=f.niubi('build',cfg,website_text='Public website evidence '*1000)['prompt'];self.assertLessEqual(len(prompt),4000);self.assertIn('Return questions in this exact order',prompt)
 def test_duplicate_generated_bank_not_silently_sampled(self):
  cfg=config();cfg.update(count=2,generate_only=False)
  with tempfile.TemporaryDirectory() as t,patch.object(f,'DATA',pathlib.Path(t)),patch.object(f,'fetch_website',return_value={'text':'public site'}),patch.object(f,'niubi',side_effect=[{'prompt':'build'},[{'text':'Same question?'},{'text':'same question!'}]]),patch.object(f,'call',return_value={'id':'g','samples':[{'status':'complete','answer':'[]'}]}) as call:
   rid='00000000-0000-0000-0000-000000000000';f.folder(rid).mkdir();job={'id':rid,'config':cfg,'prompts':[],'samples':[]};f.execute(job);self.assertEqual(len(job['prompts']),1);self.assertEqual(call.call_count,1);self.assertEqual(job['status'],'failed')
 def test_blocked_model_stops_remaining_questions(self):
  cfg=config();job={'id':'fixture','config':cfg,'prompts':[{'text':'question one'},{'text':'question two'}],'samples':[]}
  with patch.object(f,'persist'),patch.object(f,'call',return_value={'id':'r','samples':[sample('',status='failed',error='B.AI HTTP 403')]}) as call:
   f.collect(job);self.assertEqual(call.call_count,1);self.assertEqual(job['status'],'partial');self.assertIn('p',job['blocked_models'])

if __name__=='__main__':unittest.main()
