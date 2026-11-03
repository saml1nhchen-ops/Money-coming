import concurrent.futures, json, os, pathlib, sys, tempfile, unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import ai_api as api
import model_providers as registry
import geo_flow as flow
import remote_service

class Providers(unittest.TestCase):
 def setUp(self):
  isolation=patch.object(registry,"LOAD_SECRETS",False);isolation.start();self.addCleanup(isolation.stop)
 def test_http_json_fake_ip_dns_default_deny(self):
  for value in (None,'0','true','yes'):
   env={} if value is None else {'SIGNAL_ALLOW_FAKE_IP_DNS':value}
   for address in ('198.18.0.0','198.18.1.2','198.19.255.255'):
    with self.subTest(value=value,address=address),patch.dict(os.environ,env,clear=True),patch.object(api.socket,'getaddrinfo',return_value=[(2,1,6,'',(address,443))]),patch.object(api.urllib.request,'build_opener') as opener:
     with self.assertRaisesRegex(ValueError,'API host must resolve to public addresses'):api.http_json('https://api.example/v1',{},{})
     opener.assert_not_called()
 def test_http_json_fake_ip_dns_opt_in(self):
  for address in ('198.18.0.0','198.18.1.2','198.19.255.255','8.8.8.8','2606:4700:4700::1111'):
   for enabled in ('0','1') if address in ('8.8.8.8','2606:4700:4700::1111') else ('1',):
    with self.subTest(address=address,enabled=enabled),patch.dict(os.environ,{'SIGNAL_ALLOW_FAKE_IP_DNS':enabled},clear=True),patch.object(api.socket,'getaddrinfo',return_value=[(2,1,6,'',(address,443))]),patch.object(api.urllib.request,'build_opener') as opener:
     opener.return_value.open.return_value.__enter__.return_value.read.return_value=b'{"ok":true}'
     self.assertEqual(api.http_json('https://api.example/v1',{},{}),{'ok':True})
     opener.return_value.open.assert_called_once()
 def test_http_json_fake_ip_dns_keeps_other_non_global_addresses_blocked(self):
  for address in ('10.0.0.1','172.16.0.1','192.168.0.1','127.0.0.1','169.254.1.1','0.0.0.0','192.0.2.1','::1','fc00::1','fe80::1','::ffff:198.18.0.1'):
   with self.subTest(address=address),patch.dict(os.environ,{'SIGNAL_ALLOW_FAKE_IP_DNS':'1'},clear=True),patch.object(api.socket,'getaddrinfo',return_value=[(2,1,6,'',('198.18.1.2',443)),(2,1,6,'',(address,443))]),patch.object(api.urllib.request,'build_opener') as opener:
    with self.assertRaisesRegex(ValueError,'API host must resolve to public addresses'):api.http_json('https://api.example/v1',{},{})
    opener.assert_not_called()
 def test_tokenhub_priority_models_and_hosts(self):
  defaults={'hunyuan':'hy3','deepseek':'deepseek-v4-flash-202605','kimi':'kimi-k3.1-pro','zhipu':'glm-5.3-flash','minimax':'minimax-m3.1-flash'}
  env={'SIGNAL_TOKENHUB_API_KEY':'fixture','SIGNAL_NVIDIA_API_KEY':'fixture','SIGNAL_ZHIPU_API_KEY':'fixture'}
  for pid,model in defaults.items():
   p=registry.provider(pid);c=registry.configuration(p,env)
   self.assertEqual((c['route'],c['model']),('tokenhub',model))
   self.assertFalse(c['free'])
   self.assertEqual(api.safe_endpoint(p,c['base_url']),'https://tokenhub.tencentmaas.com/v1')
   env[p['env_route_var']]='official'
   self.assertNotEqual((registry.configuration(p,env) or {}).get('route'),'tokenhub')
   del env[p['env_route_var']]
   env[f'SIGNAL_{pid.upper()}_TOKENHUB_MODEL']='fixture-model'
   self.assertEqual(registry.configuration(p,env)['model'],'fixture-model')
  self.assertEqual(registry.configuration(registry.provider('deepseek'),{'SIGNAL_TOKENHUB_API_KEY':'','SIGNAL_NVIDIA_API_KEY':'fixture'})['route'],'nvidia_nim')
 def test_official_defaults_and_safe_hosts(self):
  p=registry.provider('qwen');c=registry.configuration(p,{'SIGNAL_QWEN_API_KEY':'fixture'})
  self.assertEqual(c['model'],'qwen3.8-flash')
  self.assertEqual(api.safe_endpoint(p,c['base_url']),'https://ws-ixip3dluugdr0m7r.cn-beijing.maas.aliyuncs.com/compatible-mode/v1')
  with self.assertRaises(ValueError):api.safe_endpoint(p,'https://untrusted.example/v1')
 def test_chat_token_budget_and_minimax_routes(self):
  p=registry.provider('minimax')
  for value,expected in [('8192',8192),('12',128),('invalid',3000)]:
   with patch.dict(os.environ,{'SIGNAL_MAX_TOKENS':value},clear=True):
    for route in ('official','tokenhub','openrouter','nvidia_nim'):
     c=registry.configuration(p,{next(r for r in p['routes'] if r['id']==route)['env_key_var']:'fixture'},route)
     body=api.request_for(p,c,'Question')[2]
     field='max_completion_tokens' if route=='official' else 'max_tokens'
     self.assertEqual(body[field],expected)
     self.assertNotIn('max_tokens' if route=='official' else 'max_completion_tokens',body)
 def test_reasoning_fallback_and_think_stripping(self):
  p=registry.provider('deepseek')
  for field in ('reasoning_content','reasoning'):
   for finish in ('stop','length',None):
    result=api.parse(p,{'choices':[{'message':{'content':None,field:'推理回答'},'finish_reason':finish}]})
    self.assertEqual(result['answer'],'推理回答');self.assertTrue(result['answer_from_reasoning'])
    self.assertEqual(result['complete'],finish=='stop')
  result=api.parse(p,{'choices':[{'message':{'content':'<think>hidden</think>答案','reasoning_content':'hidden'},'finish_reason':'stop'}]})
  self.assertEqual(result['answer'],'答案');self.assertFalse(result['answer_from_reasoning'])
  result=api.parse(p,{'choices':[{'message':{'content':'<think>unfinished'},'finish_reason':'length'}]})
  self.assertEqual(result['answer'],'');self.assertFalse(result['complete'])
 def test_repo_env_loader_without_real_credentials(self):
  from repo_env import load_repo_env
  with tempfile.TemporaryDirectory() as t,patch.dict(os.environ,{'EXISTING':'keep'},clear=True):
   path=pathlib.Path(t)/'fixture.env'
   path.write_text('# comment\nEXISTING=replace\nNEW="fixture value"\nINVALID-NAME=skip\nBROKEN\nEMPTY=\n')
   load_repo_env(path)
   self.assertEqual(os.environ['EXISTING'],'keep');self.assertEqual(os.environ['NEW'],'fixture value')
   self.assertEqual(os.environ['EMPTY'],'');self.assertNotIn('INVALID-NAME',os.environ)
   os.environ['SIGNAL_LOAD_DOTENV']='0'
   with patch.object(pathlib.Path,'read_text',side_effect=AssertionError('must not read')):load_repo_env(path)
 def test_smoke_uses_client_path_and_redacts_answers(self):
  import contextlib, io, smoke_cn_providers as smoke
  env={'SIGNAL_TOKENHUB_API_KEY':'secret-fixture','SIGNAL_QWEN_API_KEY':'secret-fixture','SIGNAL_DOUBAO_API_KEY':'secret-fixture'}
  raw={'choices':[{'message':{'content':'蓝色 secret-fixture'},'finish_reason':'stop'}]}
  output=io.StringIO()
  with patch.dict(os.environ,env,clear=True),patch.object(api,'http_json',return_value=raw) as http,contextlib.redirect_stdout(output):
   self.assertEqual(smoke.main(),0)
  self.assertEqual(http.call_count,7);self.assertEqual(output.getvalue().count('PASS'),7)
  self.assertNotIn('secret-fixture',output.getvalue())
 def tearDown(self):api.CONFIG.clear()
 def test_defaults_overrides_and_doubao(self):
  with patch.dict(os.environ,{},clear=True):
   self.assertTrue(all(not p['configured'] for p in api.config_public()))
   os.environ.update(SIGNAL_DOUBAO_API_KEY='secret')
   self.assertEqual(registry.configuration(registry.provider('doubao'))['model'],'doubao-seed-2-1-turbo-260628')
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
  expected={'openai':('responses','gpt-5.4-mini'),'anthropic':('anthropic','claude-sonnet-4-5'),'gemini':('gemini','gemini-3.5-flash'),'perplexity':('chat','sonar'),'deepseek':('chat','deepseek-chat'),'zhipu':('chat','glm-4.7-flash')}
  for pid,(style,model) in expected.items():
   p=registry.provider(pid);self.assertEqual(p['api_style'],style);self.assertEqual(p['default_model'],model)
   self.assertIn(p['region'],['us','cn'])
 def test_all_configured_and_subset_skip_no_network(self):
  raw={'choices':[{'message':{'content':'Brand secret'},'finish_reason':'stop'}]}
  with patch.dict(os.environ,{'SIGNAL_DEEPSEEK_API_KEY':'secret','SIGNAL_QWEN_API_KEY':'secret'},clear=True),tempfile.TemporaryDirectory() as t,patch.object(api,'results_dir',return_value=pathlib.Path(t)),patch.object(api,'http_json',return_value=raw) as http:
   d={'market':'US','prompts':['Question'],'brand_aliases':['Brand'],'skus':[]}
   with concurrent.futures.ThreadPoolExecutor() as pool:r=api.start_run(d,pool)
   self.assertEqual(http.call_count,4) # Shared Bailian key also configures Kimi and GLM pools.
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
