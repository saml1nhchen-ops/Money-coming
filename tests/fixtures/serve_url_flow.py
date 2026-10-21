"""Controlled HTTP integration server, NEVER a real Cremo/model measurement.

Run: python tests/fixtures/serve_url_flow.py [--partial] [--no-models]
Only outbound website/model transports are replaced. The application HTTP routes,
HTML parser, pinned question generator/parser, persistence and analysis stay real.
All data is temporary and discarded on exit. Binds loopback only.
"""
import argparse
import email.message
import io
import json
import pathlib
import re
import sys
import tempfile
import uuid
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'tools'))
import geo_flow as flow

HTML = b'''<!doctype html><html><head><title>Cremo | Synthetic test page</title>
<meta property="og:site_name" content="Cremo">
<meta name="description" content="Synthetic fixture for workflow testing, not the real Cremo website."></head>
<body><h1>Cremo fixture</h1><p>SYNTHETIC TEST EVIDENCE. This local HTML tests page extraction,
brand detection and diagnostic presentation. It is not a snapshot of the Cremo website,
nor evidence of its product quality, discoverability, or performance in any AI model.</p></body></html>'''


class Response(io.BytesIO):
    headers = email.message.Message()
    headers['Content-Type'] = 'text/html; charset=utf-8'


class WebsiteTransport:
    def open(self, request, timeout=30):
        if flow.urllib.parse.urlsplit(request.full_url).hostname not in ('cremocompany.com', 'www.cremocompany.com'):
            raise ValueError('Fixture only supports the Cremo test URL')
        return Response(HTML)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--partial', action='store_true')
    parser.add_argument('--no-models', action='store_true')
    args = parser.parse_args()
    runs = {}
    generation_batch = 0
    sampling = {'openai': 0, 'gemini': 0}

    def direct(path, body=None):
        nonlocal generation_batch
        if path == 'providers':
            return {'providers': [] if args.no_models else [
                {'id': pid, 'name': 'FIXTURE ' + name, 'markets': ['US'], 'protocol': 'chat',
                 'configured': True, 'configuration': {'model': model}}
                for pid, name, model in [('openai', 'OpenAI', 'gpt-fixture'), ('gemini', 'Google', 'gemini-fixture')]]}
        if path == 'run':
            prompt = body['prompts'][0]
            pid = body['providers'][0]
            if 'Return questions in this exact order:' in prompt:
                if 'Avoid these previous questions: []' in prompt:
                    generation_batch = 0
                    sampling.update(openai=0, gemini=0)
                specs = re.findall(r'(\d+):(discovery|brand|comparison)/([a-z]+)', prompt)
                questions = []
                for i, family, dimension in specs:
                    number = generation_batch * 10 + int(i)
                    text = (f'What grooming options suit scenario {number}?' if family == 'discovery' else
                            f'What does Cremo offer for scenario {number}?' if family == 'brand' else
                            f'How does Cremo compare with alternatives for scenario {number}?')
                    questions.append({'type': 'recommendation', 'topic': dimension, 'prompt': text,
                                      'targetIncluded': family != 'discovery', 'auditCategory': 'organic_discovery' if family == 'discovery' else 'brand_awareness'})
                generation_batch += 1
                answer = json.dumps(questions)
                citations = []
                status, error = 'complete', ''
            else:
                n = sampling[pid]
                sampling[pid] += 1
                status = 'failed' if args.partial and pid == 'gemini' and n == 2 else 'complete'
                error = 'HTTP 429: synthetic fixture rate limit' if status == 'failed' else ''
                answer = '' if error else ('SYNTHETIC TEST ANSWER.\n' + (
                    '1. Cremo: fixture mention only.\n2. Rival: fixture alternative.' if n % 3 == 0 else
                    '1. Rival: fixture alternative. No tracked brand mentioned.' if n % 3 == 1 else
                    'Cremo is discussed without an explicit rank. <script>window.fixtureXSS=1</script>') +
                    '\nOrdinary answer link: https://cremocompany.com/example')
                citations = [{'url': 'https://cremocompany.com/fixture', 'title': 'Synthetic citation'}] if n % 3 == 0 else []
            rid = str(uuid.uuid4())
            runs[rid] = {'id': rid, 'status': 'finished', 'planned': 1,
                         'samples': [{'id': rid, 'provider': pid, 'prompt': prompt, 'answer': answer,
                                      'status': status, 'error': error, 'citations': citations,
                                      'retrieved_sources': [], 'model': pid + '-fixture', 'synthetic': True}]}
            return runs[rid]
        return runs[path.split('id=')[1]]

    class Handler(flow.Handler):
        def end_headers(self):
            self.send_header('X-Signal-GEO-Test-Fixture', 'synthetic-not-live')
            super().end_headers()

    with tempfile.TemporaryDirectory(prefix='geo-http-fixture-') as directory, \
         patch.object(flow, 'DATA', pathlib.Path(directory)), \
         patch.object(flow, 'bridge', return_value={'configured': False, 'profiles': [], 'models': []}), \
         patch.object(flow, 'direct_bridge', side_effect=direct), \
         patch.object(flow.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]), \
         patch.object(flow.urllib.request, 'build_opener', return_value=WebsiteTransport()):
        print('SYNTHETIC FIXTURE ONLY: http://127.0.0.1:8772/#/w/demo/research', flush=True)
        flow.http.server.ThreadingHTTPServer(('127.0.0.1', 8772), Handler).serve_forever()


if __name__ == '__main__':
    main()
