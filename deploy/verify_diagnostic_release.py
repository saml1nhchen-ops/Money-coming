"""Read-only production acceptance; never logs in or submits model requests."""
import hashlib
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.request
from connection_diagnostics import publish

ROOT = pathlib.Path(__file__).resolve().parents[1]
API = 'https://api.github.com/repos/saml1nhchen-ops/Money-coming'
BACKEND = 'https://43.154.242.184.sslip.io'
FRONT = 'https://saml1nhchen-ops.github.io/Money-coming/dist/'


def get(url, authenticated=False):
    headers = {'User-Agent': 'SignalGEO-release-verification/1.0', 'Cache-Control': 'no-cache'}
    if authenticated:
        if not url.startswith(API + '/'):
            raise ValueError('Invalid verification endpoint')
        headers.update(Authorization='Bearer ' + os.environ['GH_TOKEN'], Accept='application/vnd.github+json')
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as response:
        data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('Verification response exceeded limit')
        return data


def main():
    revision = os.environ.get('GITHUB_SHA', '')
    if not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise ValueError('Invalid expected revision')
    report = {'kind': 'diagnostic_production_verification', 'expected_revision': revision, 'model_calls': 0, 'read_only': True}
    for attempt in range(60):
        try:
            data = json.loads(get(API + '/actions/runs?head_sha=' + revision + '&per_page=30', True))
            releases = [r for r in data.get('workflow_runs', []) if r.get('path') == '.github/workflows/request-release.yml']
            report['releases'] = [{'id': r['id'], 'status': r['status'], 'conclusion': r.get('conclusion'), 'url': r['html_url']} for r in releases]
            report['health'] = json.loads(get(BACKEND + '/healthz'))
            assets = []
            for name in ('team.html', 'site-readiness.js', 'site-readiness.css', 'remote-connection.js', 'research-ui.js'):
                actual = hashlib.sha256(get(FRONT + name + '?v=' + revision)).hexdigest()
                expected = hashlib.sha256((ROOT / 'dist' / name).read_bytes()).hexdigest()
                assets.append({'name': name, 'matches': actual == expected, 'sha256': actual})
            report['frontend'] = assets
            deployed = bool(any(r.get('conclusion') == 'success' for r in releases) and report['health'].get('revision') == revision and report['health'].get('ok') is True and report['health'].get('capabilities', {}).get('diagnostics_v1') is True and all(a['matches'] for a in assets))
            report['claude_available'] = report['health'].get('capabilities', {}).get('claude_available') is True
            caps = report['health'].get('capabilities', {})
            report['all_models_available'] = caps.get('analysis_all_models') is True and isinstance(caps.get('analysis_max_models'), int) and caps['analysis_max_models'] >= 3
            report['ok'] = deployed and report['claude_available'] and report['all_models_available']
            report.pop('observation_error', None)
            if deployed:
                break
            print('Waiting for the exact Release, backend revision and Pages assets; attempt', attempt + 1, flush=True)
        except Exception as error:
            report.update(ok=False, observation_error=type(error).__name__)
            print('Production observations not ready; attempt', attempt + 1, flush=True)
        time.sleep(15)
    pathlib.Path('diagnostic-production-report.json').write_text(json.dumps(report, indent=2))
    print('Read-only production evidence: ' + publish(report))
    if not report.get('ok'):
        raise SystemExit('Production release acceptance did not pass')


if __name__ == '__main__':
    main()
