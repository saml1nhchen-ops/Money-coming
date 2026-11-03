import concurrent.futures
import json
import os
import pathlib
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'tools'))
# Disable import-time .env loading before importing the provider registry.
with patch.dict(os.environ, {'SIGNAL_LOAD_DOTENV': '0'}):
    import ai_api as api
    import model_providers as registry
    import route_pool as scheduler

ENV = {'SIGNAL_LOAD_DOTENV': '0', 'SIGNAL_QWEN_API_KEY': 'bailian-secret',
       'SIGNAL_TOKENHUB_API_KEY': 'tokenhub-secret'}
RAW = {'choices': [{'message': {'content': 'Brand'}, 'finish_reason': 'stop'}]}


class MultiRoute(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {**ENV, 'SIGNAL_ROUTE_QUOTA_MODE': 'off',
                                     'SIGNAL_ROUTE_LEDGER': 'off'}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        secrets = patch.object(registry, 'LOAD_SECRETS', False)
        secrets.start()
        self.addCleanup(secrets.stop)
        # These tests exercise admission/failover, not date-dependent quota policy.
        # Nested environment fixtures must not re-enable host ledger access.
        ledger = patch.object(scheduler.route_ledger, 'path', return_value=None)
        ledger.start()
        self.addCleanup(ledger.stop)
        fractions = patch.object(scheduler.route_ledger, 'fraction', return_value=1.0)
        fractions.start()
        self.addCleanup(fractions.stop)
        scheduler.STATE.clear()
        scheduler.CURSOR.clear()
        api.CONFIG.clear()

    def routes(self):
        return registry.route_pool(registry.provider('deepseek'), ENV)

    def test_missing_keys_overrides_and_cap(self):
        self.assertEqual(registry.route_pool(registry.provider('deepseek'), {}), [])
        env = {**ENV, 'SIGNAL_DEEPSEEK_ROUTES': 'tokenhub:deepseek-v4.1-flash,bailian:deepseek-v4.1-flash',
               'SIGNAL_ROUTE_CONCURRENCY': '2'}
        routes = registry.route_pool(registry.provider('deepseek'), env)
        self.assertEqual([r['route_platform'] for r in routes], ['tokenhub', 'bailian'])
        self.assertEqual([r['concurrency'] for r in routes], [2, 2])
        env['SIGNAL_DEEPSEEK_ROUTES'] = json.dumps([{'platform': 'tokenhub', 'model': 'custom', 'thinking_off': {}}])
        with self.assertRaisesRegex(ValueError, 'expected.*deepseek-v4.1-flash'):
            registry.route_pool(registry.provider('deepseek'), env)
        env = {'SIGNAL_TOKENHUB_API_KEY': 'fixture', 'SIGNAL_ROUTE_CONCURRENCY': '8'}
        self.assertEqual(registry.route_pool(registry.provider('zhipu'), env)[0]['concurrency'], 8)
        env['SIGNAL_ZHIPU_TOKENHUB_GLM_5_3_FLASH_CONCURRENCY'] = '2'
        self.assertEqual(registry.route_pool(registry.provider('zhipu'), env)[0]['concurrency'], 2)

    def test_one_version_matrix_and_override_enforcement(self):
        expected = {
            'hunyuan': ('hy3', {'tokenhub'}),
            'deepseek': ('deepseek-v4.1-flash', {'bailian', 'tokenhub'}),
            'kimi': ('kimi-k3.1-pro', {'tokenhub'}),
            'zhipu': ('glm-5.3-flash', {'tokenhub'}),
            'minimax': ('minimax-m3', {'tokenhub'}),
            'qwen': ('qwen3.7-plus', {'bailian'}),
            'doubao': ('doubao-seed-2-1-lite-260915', {'ark'}),
            'openai': ('gpt-5.4-mini', {'official'}),
            'gemini': ('gemini-3.5-flash', set()),
        }
        for family, (version, platforms) in expected.items():
            p = registry.provider(family)
            self.assertEqual(p['pool_model'], version)
            self.assertEqual(p['default_model'], version)
            routes = [r for r in p['routes'] if r.get('pool')]
            self.assertEqual({r['platform'] for r in routes}, platforms)
            if not routes: continue
            self.assertEqual({r['default_model'] for r in routes}, {version})
            name = 'SIGNAL_' + family.upper() + '_ROUTES'
            platform = routes[0]['platform']
            for override in (platform + ':wrong-version', json.dumps([{'platform': platform, 'model': 'wrong-version'}])):
                with self.assertRaisesRegex(ValueError, 'expected.*' + version):
                    registry.route_pool(p, {name: override})
            invalid = {**p, 'routes': [{**routes[0], 'default_model': 'wrong-version'}]}
            with self.assertRaisesRegex(ValueError, 'model mismatch'):
                registry.route_pool(invalid, {})
        routes = self.routes()
        routes[0]['model'] = 'wrong-version'
        with self.assertRaisesRegex(ValueError, 'model mismatch'):
            scheduler.invoke('deepseek', routes, lambda _: self.fail('must reject before request'), {})
        p = registry.provider('deepseek')
        single = registry.configuration(p, {**ENV, 'SIGNAL_DEEPSEEK_TOKENHUB_MODEL': 'custom'}, 'tokenhub')
        self.assertEqual(single['model'], 'custom')

    def test_failed_samples_retain_version_before_admission(self):
        sample = {}
        with self.assertRaises(TimeoutError):
            scheduler.invoke('deepseek', self.routes(), lambda _: self.fail('deadline'), sample, deadline=0)
        self.assertEqual(sample['model_version'], 'deepseek-v4.1-flash')
        self.assertEqual(sample['route_model'], 'deepseek-v4.1-flash')
        with patch.dict(os.environ, ENV, clear=True), tempfile.TemporaryDirectory() as tmp, patch.object(api, 'results_dir', return_value=pathlib.Path(tmp)), patch.object(api, 'http_json', side_effect=ValueError('Provider HTTP 401')):
            with concurrent.futures.ThreadPoolExecutor() as executor:
                started = api.start_run({'market': 'CN', 'providers': ['deepseek'], 'prompts': ['Question'], 'brand_aliases': ['Brand']}, executor)
            sample = api.get_run(started['id'])['samples'][0]
            self.assertEqual(sample['status'], 'failed')
            self.assertEqual(sample['model_version'], 'deepseek-v4.1-flash')
            self.assertEqual(sample['route_model'], 'deepseek-v4.1-flash')

    def test_distribution_and_caps_across_simultaneous_calls(self):
        routes = self.routes()
        for r in routes: r['concurrency'] = 1
        barrier = threading.Barrier(2)
        active = {}; peak = {}; lock = threading.Lock()
        def request(route):
            name = route['route']
            with lock:
                active[name] = active.get(name, 0)+1
                peak[name] = max(peak.get(name, 0), active[name])
            barrier.wait(2)
            with lock: active[name] -= 1
            return RAW
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: scheduler.invoke('deepseek', routes, request, {})[0]['route'], range(2)))
        self.assertEqual(len(set(results)), 2)
        self.assertEqual(set(peak.values()), {1})
        scheduler.CURSOR.clear()
        self.assertEqual([scheduler.invoke('deepseek', routes, lambda r: RAW, {})[0]['route'] for _ in range(2)], [r['route'] for r in routes])

    def test_failover_and_nonretryable(self):
        for error in (ValueError('Provider HTTP 429'), ValueError('Provider HTTP 503'),
                      TimeoutError(), ConnectionError(), urllib.error.URLError('fixture')):
            with self.subTest(error=type(error).__name__):
                scheduler.STATE.clear(); scheduler.CURSOR.clear()
                sample = {}; calls = []
                def request(route):
                    calls.append(route)
                    if len(calls) == 1: raise error
                    return RAW
                route, _ = scheduler.invoke('deepseek', self.routes(), request, sample)
                self.assertEqual(sample['failovers'], 1)
                self.assertEqual(len(sample['attempts']), 2)
                self.assertEqual(sample['route_model'], route['model'])
                self.assertEqual(sample['model_version'], 'deepseek-v4.1-flash')
                self.assertEqual(sample['route_platform'], route['route_platform'])
        sample = {}
        with self.assertRaises(ValueError):
            scheduler.invoke('deepseek', self.routes(), lambda r: (_ for _ in ()).throw(ValueError('Provider HTTP 401')), sample)
        self.assertEqual(len(sample['attempts']), 1)

    def test_attempt_timeout_fails_over_and_retains_admission(self):
        routes = self.routes()[:2]
        blocked = threading.Event()
        exited = threading.Event()
        sample = {}
        first_state = None
        def request(route):
            if route == routes[0]:
                try:
                    blocked.wait(2)
                    return {'late': True}
                finally:
                    exited.set()
            return RAW
        try:
            route, raw = scheduler.invoke('deepseek', routes, request, sample,
                                          timeout=.02, deadline=time.monotonic()+1)
            self.assertEqual(route, routes[1])
            self.assertEqual(raw, RAW)
            self.assertEqual(sample['failovers'], 1)
            self.assertEqual(sample['attempts'][0]['error'], 'transient')
            first_state = scheduler.STATE[scheduler.identity('deepseek', routes[0])]
            self.assertEqual(first_state['busy'], 1)
            self.assertEqual(sample['attempts'][0]['status'], 'failed')
        finally:
            blocked.set()
            self.assertTrue(exited.wait(1))
            with scheduler.CONDITION:
                scheduler.CONDITION.wait_for(lambda: first_state is None or first_state['busy'] == 0, timeout=1)
        self.assertEqual(first_state['busy'], 0)

    def test_total_deadline_bounds_attempts_and_admission_wait(self):
        routes = self.routes()[:2]
        release = threading.Event()
        exited = threading.Event()
        def request(route):
            try:
                release.wait(2)
                return RAW
            finally:
                exited.set()
        sample = {}
        try:
            with self.assertRaises(TimeoutError):
                scheduler.invoke('deepseek', routes, request, sample,
                                 timeout=1, deadline=time.monotonic()+.02)
            self.assertEqual(len(sample['attempts']), 1)
            for route in routes:
                scheduler.STATE.setdefault(scheduler.identity('deepseek', route), {})['busy'] = route['concurrency']
            with self.assertRaises(TimeoutError):
                scheduler.invoke('deepseek', routes, lambda r: self.fail('must not call'), {},
                                 timeout=1, deadline=time.monotonic()+.02)
        finally:
            release.set()
            self.assertTrue(exited.wait(1))
            state = scheduler.STATE[scheduler.identity('deepseek', routes[0])]
            with scheduler.CONDITION:
                self.assertTrue(scheduler.CONDITION.wait_for(lambda: state['busy'] < routes[0]['concurrency'], timeout=1))

    def test_cooldown_expiry_and_all_cooling(self):
        routes = self.routes()[:2]
        def request(route):
            if route == routes[0]: raise ValueError('Provider HTTP 429')
            return RAW
        with patch.dict(os.environ, {'SIGNAL_ROUTE_FAILURE_THRESHOLD': '3', 'SIGNAL_ROUTE_COOLDOWN': '60'}), patch.object(scheduler.time, 'monotonic', return_value=100):
            for _ in range(3):
                scheduler.CURSOR.clear()
                scheduler.invoke('deepseek', routes, request, {})
            state = scheduler.STATE[scheduler.identity('deepseek', routes[0])]
            self.assertEqual(state['until'], 160)
            scheduler.CURSOR.clear()
            self.assertEqual(scheduler.invoke('deepseek', routes, lambda r: RAW, {})[0], routes[1])
            scheduler.STATE[scheduler.identity('deepseek', routes[1])]['until'] = 160
            scheduler.CURSOR.clear()
            self.assertEqual(scheduler.invoke('deepseek', routes, lambda r: RAW, {})[0], routes[0])
        with patch.object(scheduler.time, 'monotonic', return_value=161):
            scheduler.CURSOR.clear()
            self.assertEqual(scheduler.invoke('deepseek', routes, lambda r: RAW, {})[0], routes[0])

    def test_budget_sample_metadata_redaction_and_http_mock(self):
        def http(url, headers, body):
            if 'maas.aliyuncs' in url: raise ValueError('Provider HTTP 429')
            return {**RAW, 'model': body['model'], 'echo': 'tokenhub-secret bailian-secret'}
        with patch.dict(os.environ, {**ENV, 'SIGNAL_ROUTE_QUOTA_MODE': 'off'}, clear=True), tempfile.TemporaryDirectory() as tmp, patch.object(api, 'results_dir', return_value=pathlib.Path(tmp)), patch.object(api, 'http_json', side_effect=http) as mock, patch.object(scheduler, 'invoke', wraps=scheduler.invoke) as invoke:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                started = api.start_run({'market': 'CN', 'providers': ['deepseek'], 'prompts': ['Question'], 'brand_aliases': ['Brand']}, executor)
            run = api.get_run(started['id'])
            self.assertEqual(run['planned'], 1)
            self.assertEqual(len(run['samples']), 1)
            sample = run['samples'][0]
            self.assertEqual(sample['status'], 'complete')
            self.assertEqual(sample['route_platform'], 'tokenhub')
            self.assertEqual(sample['route_model'], sample['model_returned'])
            self.assertEqual(sample['failovers'], 1)
            self.assertEqual(mock.call_count, 2)
            self.assertEqual(invoke.call_args.kwargs['timeout'], 30)
            self.assertIn('deadline', invoke.call_args.kwargs)
            for file in pathlib.Path(tmp).rglob('*.json'):
                self.assertNotIn('tokenhub-secret', file.read_text())
                self.assertNotIn('bailian-secret', file.read_text())

    def test_thinking_params_all_matrix_routes(self):
        keys = {r['env_key_var']: 'fixture' for p in registry.catalog() for r in p['routes']}
        with patch.dict(os.environ, {}, clear=True):
            for provider in registry.catalog():
                for route in registry.route_pool(provider, keys):
                    with self.subTest(model=route['model'], platform=route['route_platform']):
                        body = api.request_for(provider, route, 'Question')[2]
                        fields = {k: body[k] for k in ('thinking', 'enable_thinking', 'chat_template_kwargs', 'reasoning_effort') if k in body}
                        self.assertEqual(fields, route['thinking_off'])
                        if route['route_platform'] == 'nvidia':
                            self.assertEqual(fields['chat_template_kwargs'], {'thinking': False, 'enable_thinking': False})

    def test_secret_file_first_line(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(registry.pathlib.Path, 'home', return_value=pathlib.Path(tmp)), patch.object(registry, 'LOAD_SECRETS', True), patch.dict(os.environ, {}, clear=True):
            root = pathlib.Path(tmp)/'.secrets'; root.mkdir()
            (root/'SIGNAL_TOKENHUB_API_KEY').write_text('first\nnever-read\n')
            self.assertEqual(registry.route_pool(registry.provider('hunyuan'))[0]['key'], 'first')


    def test_benchmark_all_families_with_mock_http(self):
        import contextlib
        import io
        import bench_geo_collect as bench
        env = {**ENV, 'SIGNAL_NVIDIA_API_KEY': 'nvidia-secret', 'SIGNAL_DOUBAO_API_KEY': 'ark-secret',
               'SIGNAL_ZHIPU_API_KEY': 'zhipu-secret'}
        output = io.StringIO()
        with patch.dict(os.environ, env, clear=True), patch.object(sys, 'argv', ['bench', '--china-families', '--questions', '2']), patch.object(api, 'http_json', return_value=RAW), contextlib.redirect_stdout(output):
            self.assertEqual(bench.main(), 0)
        text = output.getvalue()
        self.assertIn('completion=14/14', text)
        self.assertIn('HTTP429=0 failovers=0', text)
        self.assertIn('bailian/', text)
        self.assertIn('tokenhub/', text)
        self.assertNotIn('secret', text)
