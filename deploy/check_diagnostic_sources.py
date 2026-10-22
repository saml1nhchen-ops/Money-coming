"""Real public-source integration, no vendor key, login, or model calls.

Runs on an ordinary trusted validation runner. Respect the same finite collector
and robots policy as production; restrictions are evidence, not test bypasses.
"""
import json
import pathlib
import secrets
import sys
import tempfile
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from geo_audit import AuditManager
from geo_diagnose import DiagnosticManager
from remote_gateway import Budget, Workspace


class NoModelAPI:
    def call(self, service, path, data=None):
        if service == 'geo' and path == 'state':
            return {'busy': False, 'runs': []}
        raise AssertionError('Public-source validation must not call a model')


def wait(read, ident, running):
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        value = read(ident)
        if value['status'] not in running:
            return value
        time.sleep(.25)
    raise AssertionError('Bounded source diagnostic did not complete')


def main():
    reports = []
    with tempfile.TemporaryDirectory(prefix='diagnostic-sources-') as directory:
        root = pathlib.Path(directory)
        workspace = Workspace(secrets.token_urlsafe(24), 'validation.example', Budget(root / 'budget.json', 126))
        workspace.api = NoModelAPI()
        workspace.auditor = AuditManager(workspace, root / 'runtime/audits/index.sqlite3')
        manager = DiagnosticManager(workspace, root / 'runtime/diagnostics/index.sqlite3', root=root)
        try:
            clients = manager.entities('clients', {'name': 'Public-source validation'})['clients']
            client_id = next(c['id'] for c in clients if not c['internal'])
            projects = manager.entities('projects', {'client_id': client_id, 'name': 'Public-source validation'})['projects']
            project_id = next(p['id'] for p in projects if not p['internal'])
            for website in ('https://cremocompany.com/', 'https://www.nike.com/', 'https://www.lorealparisusa.com/'):
                aid = str(uuid.uuid4())
                with workspace.lock:
                    workspace.auditor.start(aid, website, 'US')
                preview = wait(workspace.auditor.get, aid, {'queued', 'running'})
                candidates = preview['candidates']
                brand = candidates.get('brand') or {}
                confirmed = {
                    'brand': {'name': brand.get('name', ''), 'aliases': brand.get('aliases', [])},
                    'products': [{'name': p['name'], 'aliases': p.get('aliases', [p['name']]), 'source_candidate_id': p['id']} for p in candidates.get('products', [])],
                    'competitors': [], 'context': '',
                }
                created, status = manager.create({'audit_id': aid, 'confirmed': confirmed, 'profile_ids': [], 'project_id': project_id, 'request_id': str(uuid.uuid4()), 'mode': 'website'})
                assert status == 202
                final = wait(manager.detail, created['id'], {'queued', 'running'})
                bundle = final.get('bundle')
                assert bundle and bundle['schema_version'] == 'v0.1' and bundle['demo'] is False
                assert not bundle['answers'] and final['plan']['maximum_calls'] == 0
                assert sum(rule['weight'] for rule in bundle['rules']) == 100
                assert all(rule['evidence_ids'] for rule in bundle['rules'] if rule['status'] in ('pass', 'partial', 'fail'))
                assert final['summary']['total'] is None  # No invented factual/page-coverage judgments.
                reports.append({'website': website, 'status': final['status'], 'brand': final['brand'], 'products': [p['name'] for p in confirmed['products']], 'pages': final.get('pages', []), 'summary': final['summary'], 'model_calls': 0, 'bundle': bundle})
        finally:
            manager.pool.shutdown(wait=True)
            workspace.auditor.pool.shutdown(wait=True)
    report = {'kind': 'real_diagnostic_sources', 'model_calls': 0, 'sources': reports}
    pathlib.Path('diagnostic-source-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    for row in reports:
        print(row['website'], row['status'], row['brand'], 'products=' + str(len(row['products'])), 'model_calls=0')


if __name__ == '__main__':
    main()
