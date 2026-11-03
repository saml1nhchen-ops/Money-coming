import os,pathlib,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import ai_api as a

class SamplingBodies(unittest.TestCase):
 def body(self,pid,route='official',model=None):
  p=a.provider(pid);r=next(r for r in p['routes'] if r['id']==route)
  c={'base_url':r['base_url'],'key':'fixture','model':model or r['default_model'],'protocol':r['protocol'],'search':False,'route':route}
  return a.request_for(p,c,'Question')[2]
 def test_token_defaults_all_protocols(self):
  with patch.dict(os.environ,{},clear=True):
   for pid,field in [('qwen','max_tokens'),('openai','max_output_tokens'),('anthropic','max_tokens')]:self.assertEqual(self.body(pid)[field],3000)
   self.assertEqual(self.body('gemini')['generationConfig']['maxOutputTokens'],3000)
   self.assertEqual(a.call_timeout(),90)
 def test_thinking_settings_and_override(self):
  with patch.dict(os.environ,{},clear=True):
   self.assertFalse(self.body('qwen')['enable_thinking'])
   for pid,route in [('doubao','official'),('zhipu','official'),('deepseek','tokenhub'),('hunyuan','tokenhub')]:self.assertEqual(self.body(pid,route)['thinking'],{'type':'disabled'})
   self.assertEqual(self.body('minimax','tokenhub')['reasoning_effort'],'low')
   self.assertEqual(self.body('zhipu','tokenhub',model='glm-5.3-flash')['reasoning_effort'],'low')
   self.assertNotIn('thinking',self.body('zhipu','tokenhub',model='glm-5.3-flash'))
   for model in ('kimi-k3.1-pro','kimi-k3.0'):
    self.assertEqual(self.body('kimi','tokenhub',model=model)['thinking'],{'type':'disabled'})
    self.assertEqual(self.body('kimi','official',model=model)['thinking'],{'type':'disabled'})
   self.assertEqual(self.body('deepseek',model='deepseek-reasoner')['model'],'deepseek-chat')
   self.assertEqual(self.body('gemini')['generationConfig']['thinkingConfig'],{'thinkingLevel':'minimal'})
   self.assertEqual(self.body('openai')['reasoning'],{'effort':'none'})
   self.assertNotIn('reasoning',self.body('openai',model='gpt-4.1'))
  with patch.dict(os.environ,{'SIGNAL_GEO_THINKING':'1'}):
   self.assertFalse(self.body('qwen')['enable_thinking'])
   self.assertEqual(self.body('kimi','tokenhub',model='kimi-k3.1-pro')['thinking'],{'type':'disabled'})
   self.assertEqual(self.body('zhipu','tokenhub',model='glm-5.3-flash')['reasoning_effort'],'low')
 def test_gemini_default(self):self.assertEqual(a.provider('gemini')['default_model'],'gemini-3.5-flash')
 def test_clamps_and_invalid_values(self):
  for value,expected in [('invalid',3000),('0',128),('1000000',32768),('2000',2000)]:
   with patch.dict(os.environ,{'SIGNAL_MAX_TOKENS':value}):self.assertEqual(a.max_output_tokens(),expected)
 def test_timeout_clamps_and_invalid_values(self):
  for value,expected in [('invalid',90),('0',1),('1000000',600),('17',17)]:
   with patch.dict(os.environ,{'SIGNAL_CALL_TIMEOUT':value}):self.assertEqual(a.call_timeout(),expected)
 def test_http_timeout_is_configured(self):
  with patch.dict(os.environ,{'SIGNAL_CALL_TIMEOUT':'17'}),patch.object(a.socket,'getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]),patch.object(a.urllib.request,'build_opener') as opener:
   opener.return_value.open.return_value.__enter__.return_value.read.return_value=b'{}'
   a.http_json('https://fixture.example',{},{});self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'],17)
 def test_plan_uses_configured_tokens(self):
  import geo_plan
  from test_geo_flow import config
  with patch.dict(os.environ,{},clear=True):
   plan=geo_plan.plan(config());self.assertEqual(plan['estimated_output_tokens'],plan['generation_calls']*2000+plan['answer_calls']*3000)
  with patch.dict(os.environ,{'SIGNAL_MAX_TOKENS':'2000'}):
   plan=geo_plan.plan(config());self.assertEqual(plan['estimated_output_tokens'],plan['generation_calls']*2000+plan['answer_calls']*2000)
 def test_benchmark_uses_real_adapter_path_and_prints_timing_only(self):
  import contextlib,io,bench_geo_collect
  output=io.StringIO();raw={'choices':[{'message':{'content':'answer fixture-secret'},'finish_reason':'stop'}]}
  with patch.dict(os.environ,{'SIGNAL_QWEN_API_KEY':'fixture-secret'},clear=True),patch.object(sys,'argv',['bench','--questions','2','--providers','qwen']),patch.object(a,'http_json',return_value=raw) as http,contextlib.redirect_stdout(output):
   self.assertEqual(bench_geo_collect.main(),0)
  self.assertEqual(http.call_count,2);self.assertIn('wall=',output.getvalue());self.assertNotIn('fixture-secret',output.getvalue());self.assertNotIn('answer',output.getvalue())
