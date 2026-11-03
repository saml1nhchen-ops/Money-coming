"""Hermetic request policy and local quota contracts; no live transports."""
import concurrent.futures
import datetime
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import ai_api as api
import model_providers as registry
import route_ledger as ledger
import route_pool as scheduler


class Quotas(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=pathlib.Path(self.tmp.name)/'ledger.json'
        env=patch.dict(os.environ,{'SIGNAL_LOAD_DOTENV':'0','SIGNAL_ROUTE_LEDGER':str(self.path)},clear=True)
        env.start();self.addCleanup(env.stop)
        scheduler.STATE.clear();scheduler.CURSOR.clear()

    def route(self, **kw):
        return {'route_platform':'fixture','route':'fixture','base_url':'https://fixture.example',
                'model':'model','concurrency':2,'quota':{'free_tokens':100},**kw}

    def test_math_expiry_unlimited_override(self):
        r=self.route();self.assertEqual(ledger.fraction(r),1)
        ledger.update(ledger.key(r),70);self.assertEqual(ledger.fraction(r),.3)
        r['quota']['expires']='2020-01-01';self.assertEqual(ledger.fraction(r),0)
        r['quota']['unlimited']=True;self.assertEqual(ledger.fraction(r),1)
        with patch.dict(os.environ,{'SIGNAL_ROUTE_QUOTAS':json.dumps({'fixture/model':{'free_tokens':200}})}):
            self.assertEqual(ledger.fraction(r),.65)
        self.assertEqual(ledger.fraction(self.route(quota={'kind':'usd_credit'})),.25)
        self.assertEqual(ledger.fraction(self.route(quota={'free_tokens':100,'expires':'2027-01-01'}),datetime.date(2027,1,1)),.3)

    def test_atomic_concurrent_persistence_seed_and_off(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _:ledger.update('fixture/model',1),range(80)))
        self.assertEqual(json.loads(self.path.read_text())['fixture/model']['tokens'],80)
        ledger.update('fixture/model',40,seed=True)
        self.assertEqual(ledger.read()['fixture/model']['tokens'],80)
        self.assertTrue(ledger.read()['fixture/model']['partial'])
        for identity,tokens in ledger.KNOWN.items():ledger.update(identity,tokens,seed=True)
        self.assertEqual(ledger.read()['tokenhub/glm-5.3-flash']['tokens'],70403)
        self.assertEqual(list(self.path.parent.iterdir()),[self.path])
        with patch.dict(os.environ,{'SIGNAL_ROUTE_LEDGER':'off'}):
            ledger.update('fixture/model',100);self.assertEqual(ledger.read(),{})
        self.assertEqual(ledger.read()['fixture/model']['tokens'],80)

    def test_usage_without_double_counting(self):
        self.assertEqual(ledger.usage_tokens({'input_tokens':10,'output_tokens':20,'output_tokens_details':{'reasoning_tokens':5}})['total'],30)
        self.assertEqual(ledger.usage_tokens({'promptTokenCount':10,'candidatesTokenCount':20,'thoughtsTokenCount':5})['total'],35)
        r=self.route()
        scheduler.invoke('fixture',[r],lambda _: {'usage':{'prompt_tokens':5,'completion_tokens':2}}, {})
        self.assertEqual(ledger.read()['fixture/model']['tokens'],7)

    def test_skip_exhausted_fallback_demotion_and_off(self):
        low=self.route(model='low');good=self.route(model='good');fallback=self.route(model='last',fallback_only=True)
        ledger.update(ledger.key(low),96)
        self.assertEqual(scheduler.invoke('fixture',[low,good,fallback],lambda _: {},{})[0],good)
        ledger.update(ledger.key(good),100)
        self.assertEqual(scheduler.invoke('fixture',[low,good,fallback],lambda _: {},{})[0],fallback)
        self.assertIn(scheduler.invoke('fixture',[low,good],lambda _: {},{})[0],[low,good])
        # Healthy cooldown and admission filtering still precede quota choice.
        scheduler.STATE[scheduler.identity('fixture',good)]['until']=float('inf')
        self.assertEqual(scheduler.invoke('fixture',[low,good],lambda _: {},{})[0],low)
        scheduler.CURSOR.clear()
        with patch.dict(os.environ,{'SIGNAL_ROUTE_QUOTA_MODE':'off'}):
            self.assertEqual(scheduler.invoke('fixture',[low,good],lambda _: {},{})[0],low)

    def test_preferred_tokenhub_flash_pool_and_default(self):
        p=registry.provider('zhipu')
        keys={'SIGNAL_TOKENHUB_API_KEY':'fixture'}
        default=registry.configuration(p,keys,'tokenhub')
        self.assertEqual(default['model'],'glm-5.3-flash')
        self.assertFalse(default['fallback_only'])
        route=next(r for r in registry.route_pool(p,keys) if r['model']=='glm-5.3-flash')
        self.assertFalse(route['fallback_only'])
        self.assertEqual(route['concurrency'],4)
        self.assertEqual(route['quota'],{'free_tokens':1000000,'expires':'2027-11-03','scope':'per_model'})
        self.assertEqual(api.request_for(p,route,'OK')[2]['reasoning_effort'],'low')

    def test_fallback_waits_for_preferred_slot_or_grace(self):
        for mode in ('release','release_late','elapsed','deadline','zero','invalid','off'):
            with self.subTest(mode=mode):
                scheduler.STATE.clear()
                preferred=self.route(model='preferred',concurrency=1)
                ledger.update(ledger.key(preferred),60,seed=True)
                fallback=self.route(model='fallback',fallback_only=True)
                state={'busy':1,'failures':0,'until':0}
                scheduler.STATE[scheduler.identity('fixture',preferred)]=state
                clock=[100.0];waits=[]
                def wait(seconds):
                    waits.append(seconds);clock[0]+=seconds
                    if mode=='release' or mode=='release_late' and clock[0]>=102:state['busy']=0
                grace={'zero':'0','invalid':'bad'}.get(mode,'2')
                with patch.dict(os.environ,{'SIGNAL_ROUTE_FALLBACK_GRACE':grace,'SIGNAL_ROUTE_QUOTA_MODE':'off' if mode=='off' else 'weighted'}), \
                     patch.object(scheduler.time,'monotonic',side_effect=lambda:clock[0]), \
                     patch.object(scheduler.CONDITION,'wait',side_effect=wait):
                    if mode=='deadline':
                        with self.assertRaises(TimeoutError):
                            scheduler.invoke('fixture',[preferred,fallback],lambda _: {},{},deadline=101)
                    else:
                        selected,_=scheduler.invoke('fixture',[preferred,fallback],lambda _: {},{})
                        self.assertEqual(selected,preferred if mode in ('release','release_late') else fallback)
                if mode in ('elapsed','invalid'):self.assertGreaterEqual(sum(waits),2)
                if mode=='zero':self.assertEqual(waits,[])
                if mode=='release':self.assertLess(sum(waits),2)

    def test_fallback_immediate_when_preferred_unusable(self):
        for reason in ('failed','cooled','exhausted','absent'):
            with self.subTest(reason=reason):
                scheduler.STATE.clear()
                preferred=self.route(model=reason)
                fallback=self.route(model='fallback',fallback_only=True)
                if reason=='cooled':
                    scheduler.STATE[scheduler.identity('fixture',preferred)]={'busy':0,'failures':3,'until':float('inf')}
                if reason=='exhausted':ledger.update(ledger.key(preferred),100)
                def request(r):
                    if r==preferred:raise TimeoutError()
                    return {}
                with patch.object(scheduler.CONDITION,'wait',side_effect=AssertionError('unexpected wait')):
                    selected,_=scheduler.invoke('fixture',[fallback] if reason=='absent' else [preferred,fallback],request,{})
                self.assertEqual(selected,fallback)

    def test_weighting_and_late_success_accounting(self):
        low=self.route(model='low');high=self.route(model='high')
        ledger.update(ledger.key(low),80)
        with patch.object(scheduler.random,'choices',side_effect=lambda population,**kw:[population[1]]) as choose:
            self.assertEqual(scheduler.invoke('weighted',[low,high],lambda _: {},{})[0],high)
            weights=choose.call_args.kwargs['weights']
            self.assertEqual(weights,[.2,1.0])
        import threading
        gate=threading.Event();finished=threading.Event()
        def request(route):
            gate.wait(1)
            return {'usage':{'input_tokens':2,'output_tokens':3}}
        def release():finished.set()
        with self.assertRaises(TimeoutError):scheduler.bounded_request(request,high,.001,release)
        gate.set();self.assertTrue(finished.wait(1))
        self.assertEqual(ledger.read()[ledger.key(high)]['tokens'],5)

    def test_all_default_requests_and_exceptions(self):
        keys={r['env_key_var']:'fixture' for p in registry.catalog() for r in p['routes']}
        for p in registry.catalog():
            for spec in p['routes']:
                if not spec['default_model']:continue
                c=registry.configuration(p,keys,spec['id'])
                body=api.request_for(p,c,'Reply with OK.')[2]
                if 'thinking_off' in spec and p['id']!='openai':
                    for name,value in spec['thinking_off'].items():self.assertEqual(body[name],value)
                if spec.get('fallback_only') and spec.get('platform')!='nvidia':self.assertEqual(body['reasoning_effort'],'low')
        p=registry.provider('gemini')
        for model,expected in [('gemini-2.5-flash',{'thinkingBudget':0}),('gemini-2.5-pro',{'thinkingBudget':128}),('gemini-3.5-flash',{'thinkingLevel':'minimal'}),('gemini-3-pro',{'thinkingLevel':'low'})]:
            c={'model':model,'base_url':p['base_url'],'key':'fixture','search':False}
            self.assertEqual(api.request_for(p,c,'OK')[2]['generationConfig']['thinkingConfig'],expected)
        p=registry.provider('zhipu')
        for r in registry.route_pool(p,keys):
            if r['model'] in ('glm-5.2','glm-5.3'):self.assertTrue(r['fallback_only'])

    def test_benchmark_china_plus_openai_and_averages(self):
        import contextlib,io,bench_geo_collect as bench
        output=io.StringIO()
        def collect(job):
            self.assertEqual(len(job['config']['providers']),8)
            self.assertIn('direct:openai',job['config']['providers'])
            job['samples']=[{'provider':pid,'status':'complete','latency_ms':1,
                'usage':{'input_tokens':10,'output_tokens':2},'route_platform':'fixture','route_model':'fixture'}
                for pid in job['config']['providers']]
        keys={r['env_key_var']:'fixture' for p in registry.catalog() for r in p['routes']}
        with patch.dict(os.environ,keys),patch.object(sys,'argv',['bench','--china-families','--with','openai','--questions','1']),patch.object(bench.geo_flow,'collect',side_effect=collect),patch.object(api,'http_json',side_effect=AssertionError('network forbidden')),contextlib.redirect_stdout(output):
            self.assertEqual(bench.main(),0)
        self.assertIn('direct:openai: average_tokens_per_call input=10.0 output=2.0 reasoning=0.0',output.getvalue())

    def test_verifier_dry_run_no_transport_or_credentials(self):
        import contextlib,io,verify_routes
        out=io.StringIO()
        with patch.object(sys,'argv',['verify','--dry-run']),patch.object(api,'http_json',side_effect=AssertionError('network forbidden')),patch.object(registry,'credential',side_effect=lambda name,env: env.get(name,'')),contextlib.redirect_stdout(out):
            self.assertEqual(verify_routes.main(),0)
        rows=[json.loads(line) for line in out.getvalue().splitlines()]
        self.assertTrue(rows);self.assertNotIn('Authorization',out.getvalue());self.assertNotIn('dry-run',out.getvalue())

    def test_probe_reasoning_routes_are_fallback_only(self):
        keys={r['env_key_var']:'fixture' for p in registry.catalog() for r in p['routes']}
        for family,platform,model in [('zhipu','tokenhub','glm-5.2'),
                                      ('minimax','nvidia','minimaxai/minimax-m3.1-flash')]:
            route=next(r for r in registry.route_pool(registry.provider(family),keys)
                       if (r['route_platform'],r['model'])==(platform,model))
            self.assertTrue(route['fallback_only'])

    def test_verifier_failure_diagnostics_never_echo_exception(self):
        import contextlib,io,urllib.error,verify_routes
        cases=[(ValueError('Provider HTTP 401; sk-secret'),('authentication',401)),
               (urllib.error.HTTPError('https://sk-secret',429,'sk-secret',{},None),('rate_limited',429)),
               (ValueError('Provider HTTP 503; sk-secret'),('provider_error',503)),
               (TimeoutError('sk-secret'),('timeout',None)),
               (urllib.error.URLError('sk-secret'),('connection_error',None)),
               (ValueError('sk-secret'),('request_failed',None)),
               (json.JSONDecodeError('sk-secret','sk-secret',0),('invalid_json',None))]
        for error,expected in cases:
            self.assertEqual(verify_routes.error_diagnostics(error),expected)
        out=io.StringIO()
        keys={r['env_key_var']:'fixture' for p in registry.catalog() for r in p['routes']}
        with patch.dict(os.environ,keys),patch.object(sys,'argv',['verify','--families','openai']),patch.object(api,'http_json',side_effect=cases[0][0]),contextlib.redirect_stdout(out):
            self.assertEqual(verify_routes.main(),1)
        self.assertIn('error_category=authentication http_status=401',out.getvalue())
        self.assertNotIn('sk-secret',out.getvalue())

if __name__=='__main__':unittest.main()
