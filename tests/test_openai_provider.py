"""Offline OpenAI registry, request and returned-usage contracts."""
import os
import pathlib
import sys
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'tools'))
import ai_api
from bench_geo_collect import usage_totals


def test_registry_and_route_resolution():
    p = ai_api.provider('openai')
    assert p['default_model'] == 'gpt-5.4-mini'
    assert 'gpt-5.4-mini' in p['model_hint']
    assert p['env_key_var'] == 'SIGNAL_OPENAI_API_KEY'
    assert ai_api.registry.route_pool(p, {}) == []
    with patch.dict(os.environ, {'SIGNAL_LOAD_DOTENV': '0', 'SIGNAL_OPENAI_API_KEY': 'fixture'}, clear=True):
        route, = ai_api.registry.route_pool(p)
        assert route['route'] == route['route_platform'] == 'official'
        assert route['base_url'] == 'https://api.openai.com/v1'
        assert route['model'] == 'gpt-5.4-mini'
        assert route['concurrency'] == 4
        assert ai_api.resolved(p)['route'] == 'pool'
        assert ai_api.registry.configuration(p, route='official')['model'] == 'gpt-5.4-mini'
    assert ai_api.provider('bai')['default_model'] == 'gpt-5'


def test_model_request_bodies():
    cases = {
        'gpt-5.1': 'none', 'gpt-5.2-mini': 'none', 'gpt-5.4-mini': 'none',
        'gpt-5.4-nano': 'none', 'gpt-5.5': 'none', 'gpt-6-mini': 'none',
        'gpt-5': 'minimal', 'gpt-5-mini': 'minimal', 'gpt-5-nano': 'minimal',
        'gpt-5-mini-2025-08-07': 'minimal', 'o1': 'low', 'o3-mini': 'low',
        'o4-mini': 'low', 'gpt-5.4-chat-latest': None, 'gpt-4.1-mini': None,
        'gpt-4o': None, 'gpt-4o-mini': None,
    }
    p = ai_api.provider('openai')
    with patch.dict(os.environ, {'SIGNAL_LOAD_DOTENV': '0', 'SIGNAL_MAX_TOKENS': '1234'}, clear=True), patch.object(ai_api, 'http_json', side_effect=AssertionError('HTTP forbidden')):
        for protocol in ('responses', 'chat'):
            for model, effort in cases.items():
                c = {'model': model, 'base_url': p['base_url'], 'key': 'fixture',
                     'search': False, 'protocol': protocol, 'thinking_off': {}}
                url, _, body = ai_api.request_for(p, c, 'question')
                if protocol == 'responses':
                    assert url.endswith('/responses')
                    assert body['max_output_tokens'] == 1234
                    assert body.get('reasoning') == ({'effort': effort} if effort else None)
                else:
                    assert url.endswith('/chat/completions')
                    assert body['max_completion_tokens'] == 1234
                    assert body.get('reasoning_effort') == effort
                assert 'max_tokens' not in body
                with patch.dict(os.environ, {'SIGNAL_GEO_THINKING': '1'}):
                    body = ai_api.request_for(p, c, 'question')[2]
                    assert 'reasoning' not in body and 'reasoning_effort' not in body


def test_returned_usage_parsing_and_totals():
    samples = []
    fixtures = [
        ('responses', {'input_tokens': 11, 'output_tokens': 7, 'output_tokens_details': {'reasoning_tokens': 0}}),
        ('chat', {'prompt_tokens': 13, 'completion_tokens': 9, 'completion_tokens_details': {'reasoning_tokens': 3}}),
    ]
    for protocol, usage in fixtures:
        raw = {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'fixture'}]}]} if protocol == 'responses' else {'choices': [{'message': {'content': 'fixture'}, 'finish_reason': 'stop'}]}
        raw['usage'] = usage
        p = {**ai_api.provider('openai'), 'protocol': protocol}
        with patch.object(ai_api, 'http_json', return_value=raw):
            parsed = ai_api.parse(p, ai_api.http_json('unused', {}, {}))
        assert parsed['usage'] == usage
        assert parsed['complete']
        samples.append(parsed)
    assert usage_totals(samples + [{'usage': None}, {}]) == {'input': 24, 'output': 16, 'reasoning': 3}


def test_benchmark_reports_usage_without_answers():
    import contextlib
    import io
    import bench_geo_collect as bench

    def collect(job):
        job['samples'] = [{'provider': 'direct:openai', 'status': 'complete',
            'latency_ms': 100, 'answer': 'DO_NOT_PRINT_ANSWER',
            'usage': {'input_tokens': 10, 'output_tokens': 5,
                      'output_tokens_details': {'reasoning_tokens': 0}}}]
    output = io.StringIO()
    with patch.dict(os.environ, {'SIGNAL_LOAD_DOTENV': '0', 'SIGNAL_OPENAI_API_KEY': 'DO_NOT_PRINT_KEY'}, clear=True), patch.object(sys, 'argv', ['bench', '--providers', 'openai', '--questions', '1']), patch.object(bench.geo_flow, 'collect', side_effect=collect), patch.object(ai_api, 'http_json', side_effect=AssertionError('HTTP forbidden')), contextlib.redirect_stdout(output):
        assert bench.main() == 0
    text = output.getvalue()
    assert 'direct:openai: success=1 input_tokens=10 output_tokens=5 reasoning_tokens=0' in text
    assert 'total: input_tokens=10 output_tokens=5 reasoning_tokens=0' in text
    assert 'DO_NOT_PRINT' not in text


# Keep these offline contracts runnable with both pytest and the standard library.
def load_tests(loader, tests, pattern):
    import unittest
    return unittest.TestSuite(unittest.FunctionTestCase(test) for test in (
        test_registry_and_route_resolution, test_model_request_bodies,
        test_returned_usage_parsing_and_totals, test_benchmark_reports_usage_without_answers,
    ))
