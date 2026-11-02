import concurrent.futures, json, os, pathlib, sys, tempfile, unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import ai_api as api
import model_providers as registry
import geo_flow as flow
import remote_service

class Providers(unittest.TestCase):
 def tearDown(self):api.CONFIG.clear()
 def test_defaults_overrides_and_doubao(self):
  with patch.dict(os.environ,{},clear=True):
   self.assertTrue(all(not p['configured'] for p in api.config_public()))
   os.environ.update(SIGNAL_DOUBAO_API_KEY='secret')
   self.assertIsNone(registry.configuration(registry.provider('doubao')))
   os.environ['SIGNAL_DOUBAO_MODEL']='ep-fixture'
   self.assertEqual(registry.configuration(registry.provider('doubao'))['model'],'ep-fixture')
   os.environ.update(SIGNAL_OPENAI_API_KEY='secret',SIGNAL_OPENAI_MODEL='gpt-fixture',SIGNAL_OPENAI_BASE_URL='https://proxy.example/v1')
   c=registry.configuration(registry.provider('openai'))
   self.assertEqual(c['base_url'],'https://proxy.example/v1')
   self.assertEqual(c['model'],'gpt-fixture')
   self.assertNotIn('secret',json.dumps(api.config_public()))
 def test_route_priority_shared_keys_and_explicit_selection(self):
  env={'SIGNAL_NVIDIA_API_KEY':'shared-fixture','SIGNAL_SILICONFLOW_API_KEY':'silicon-fixture','SIGNAL_OPENROUTER_API_KEY':'router-fixture','SIGNAL_QWEN_API_KEY':'official-fixture'}
  resolve=lambda pid:registry.configuration(registry.provider(pid),env)
  self.assertEqual(resolve('qwen')['route'],'siliconflow')
  self.assertEqual(resolve('deepseek')['key'],resolve('kimi')['key'])
  self.assertEqual(resolve('minimax')['route'],'openrouter')
  env['SIGNAL_ZHIPU_API_KEY']='official-fixture'
  self.assertEqual(resolve('zhipu')['route'],'official')
  env['SIGNAL_QWEN_ROUTE']='official'
  self.assertFalse(resolve('qwen')['free'])
  env['SIGNAL_QWEN_ROUTE']='nvidia_nim';env['SIGNAL_QWEN_NVIDIA_NIM_MODEL']='fixture/model'
  self.assertEqual(resolve('qwen')['model'],'fixture/model')
  env['SIGNAL_OPENAI_ROUTE']='nvidia_nim'
  self.assertIsNone(resolve('openai'))
  env['SIGNAL_KIMI_ROUTE']='unknown'
  self.assertIsNone(resolve('kimi'))
 def test_official_paid_fallback_and_paid_override(self):
  p=registry.provider('zhipu')
  env={'SIGNAL_ZHIPU_API_KEY':'fixture','SIGNAL_ZHIPU_MODEL':'glm-4.6'}
  self.assertFalse(registry.configuration(p,env)['free'])
  env['SIGNAL_SILICONFLOW_API_KEY']='shared-fixture'
  self.assertEqual(registry.configuration(p,env)['route'],'siliconflow')
  env['SIGNAL_ZHIPU_ROUTE']='official'
  self.assertEqual(registry.configuration(p,env)['model'],'glm-4.6')
  self.assertIsNone(registry.configuration(registry.provider('deepseek'),{'SIGNAL_DEEPSEEK_ROUTE':'nvidia_nim','SIGNAL_DEEPSEEK_API_KEY':'fixture'}))
 def test_routed_mock_request_and_public_status(self):
  with patch.dict(os.environ,{'SIGNAL_NVIDIA_API_KEY':'shared-fixture'},clear=True),tempfile.TemporaryDirectory() as t,patch.object(api,'results_dir',return_value=pathlib.Path(t)),patch.object(api,'http_json',return_value={'choices':[{'message':{'content':'Brand'},'finish_reason':'stop'}]}) as http:
   status=api.config_public();deep=next(p for p in status if p['id']=='deepseek')
   self.assertEqual(deep['configuration']['route'],'nvidia_nim');self.assertTrue(deep['configuration']['free'])
   self.assertNotIn('shared-fixture',json.dumps(status))
   with concurrent.futures.ThreadPoolExecutor() as pool:
    run=api.start_run({'market':'US','providers':['deepseek'],'routes':{'deepseek':'nvidia_nim'},'prompts':['Question'],'brand_aliases':['Brand']},pool)
   self.assertEqual(http.call_args.args[0],'https://integrate.api.nvidia.com/v1/chat/completions')
   self.assertEqual(http.call_args.args[1]['Authorization'],'Bearer shared-fixture')
   self.assertEqual(api.get_run(run['id'])['samples'][0]['route'],'nvidia_nim')
   for file in pathlib.Path(t).rglob('*.json'):self.assertNotIn('shared-fixture',file.read_text())
 def test_blank_compose_route_defaults_to_auto_and_official_paid_fallback(self):
  c=registry.configuration(registry.provider('deepseek'),{'SIGNAL_DEEPSEEK_ROUTE':'','SIGNAL_DEEPSEEK_API_KEY':'fixture'})
  self.assertEqual(c['route'],'official');self.assertFalse(c['free'])
 def test_geo_selected_route_reaches_direct_runner(self):
  config={'market':'US','brand_aliases':['Brand'],'skus':[],'website':'https://brand.example','configuration':{'direct:qwen':{'model':'Qwen/Qwen3-8B','route':'siliconflow','protocol':'chat'}}}
  job={'id':'fixture','config':config}
  with patch.object(flow,'direct_bridge',side_effect=ValueError('fixture-stop')) as bridge:
   with self.assertRaisesRegex(ValueError,'fixture-stop'):flow.call(job,'direct:qwen',['Question'],'sampling')
  self.assertEqual(bridge.call_args.args[1]['routes'],{'qwen':'siliconflow'})
 def test_all_protocols_and_region_contracts(self):
  expected={'openai':('responses','gpt-5'),'anthropic':('anthropic','claude-sonnet-4-5'),'gemini':('gemini','gemini-2.5-flash'),'perplexity':('chat','sonar'),'deepseek':('chat','deepseek-chat'),'zhipu':('chat','glm-4.7-flash')}
  for pid,(style,model) in expected.items():
   p=registry.provider(pid);self.assertEqual(p['api_style'],style);self.assertEqual(p['default_model'],model)
   self.assertIn(p['region'],['us','cn'])
 def test_all_configured_and_subset_skip_no_network(self):
  raw={'choices':[{'message':{'content':'Brand secret'},'finish_reason':'stop'}]}
  with patch.dict(os.environ,{'SIGNAL_DEEPSEEK_API_KEY':'secret','SIGNAL_QWEN_API_KEY':'secret'},clear=True),tempfile.TemporaryDirectory() as t,patch.object(api,'results_dir',return_value=pathlib.Path(t)),patch.object(api,'http_json',return_value=raw) as http:
   d={'market':'US','prompts':['Question'],'brand_aliases':['Brand'],'skus':[]}
   with concurrent.futures.ThreadPoolExecutor() as pool:r=api.start_run(d,pool)
   self.assertEqual(http.call_count,2)
   http.reset_mock()
   with concurrent.futures.ThreadPoolExecutor() as pool:r=api.start_run({**d,'providers':['deepseek','doubao'],'models':{'deepseek':'override'}},pool)
   run=api.get_run(r['id'])
   self.assertEqual(http.call_count,1);self.assertEqual(run['provider_status']['doubao'],'not configured')
   self.assertEqual(http.call_args.args[2]['model'],'override')
   for p in pathlib.Path(t).rglob('*.json'):self.assertNotIn('secret',p.read_text())
 def test_empty_configuration_finishes_without_calls(self):
  with patch.dict(os.environ,{},clear=True),tempfile.TemporaryDirectory() as t,patch.object(api,'results_dir',return_value=pathlib.Path(t)),patch.object(api,'http_json') as http:
   d={'market':'CN','prompts':['Question']*10,'brand_aliases':['Brand'],'skus':[]}
   with concurrent.futures.ThreadPoolExecutor() as pool:r=api.start_run(d,pool)
   run=api.get_run(r['id']);self.assertEqual(run['status'],'finished');self.assertEqual(run['planned'],0)
   self.assertEqual(run['samples'],[]);self.assertTrue(all(x=='not configured' for x in run['provider_status'].values()));http.assert_not_called()
   self.assertEqual(set(run['skipped_providers']),{p['id'] for p in registry.catalog()})
   self.assertEqual(set(run['provider_status']),set(run['skipped_providers']))
   with concurrent.futures.ThreadPoolExecutor() as pool:
    with self.assertRaisesRegex(ValueError,'not configured'):api.start_run({**d,'providers':['deepseek']},pool)
 def test_sonar_uses_chat_completions(self):
  p=registry.provider('perplexity')
  c={'base_url':p['base_url'],'model':p['default_model'],'key':'fixture','search':False}
  url,headers,body=api.request_for(p,c,'Question')
  self.assertEqual(url,'https://api.perplexity.ai/chat/completions');self.assertEqual(body['model'],'sonar')
  self.assertEqual(body['messages'],[{'role':'user','content':'Question'}])
 def test_geo_catalog_keeps_unconfigured_status(self):
  with patch.dict(os.environ,{},clear=True),patch.object(flow,'bridge',side_effect=ValueError()),patch.object(flow,'direct_bridge',return_value={'providers':api.config_public()}):
   c=flow.catalog();self.assertFalse(c['configured']);self.assertTrue(c['providers'])
 def test_bootstrap_direct_does_not_connect_bai(self):
  class API:
   def call(self,service,path):
    assert (service,path)==('geo','state')
    return {'runner':{'profiles':[{'id':'direct:deepseek','model':'deepseek-chat'}]}}
  class Workspace:api=API()
  w=Workspace()
  with patch.object(remote_service,'prepare_dependencies',return_value=True):
   remote_service.bootstrap(w,{'SIGNAL_DEEPSEEK_API_KEY':'secret'})
  self.assertTrue(w.ready)

if __name__=='__main__':unittest.main()
