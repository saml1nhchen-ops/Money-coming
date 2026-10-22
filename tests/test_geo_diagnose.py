import hashlib, json, pathlib, subprocess, sys, tempfile, time, unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import geo_diagnose

HOME = '''<!doctype html><html lang="zh-CN"><head><title>Aster 净水器 | Aster</title>
<meta name="description" content="Aster 家用净水器官网">
<link rel="canonical" href="https://aster.example/">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Aster","sameAs":["https://weibo.com/aster","https://www.zhihu.com/org/aster"]}</script>
</head><body><h1>Aster 家用净水器</h1><h2>为什么选择 Aster</h2><h2>产品系列</h2>
<p>''' + '我们专注家用净水二十年，提供反渗透与超滤两类产品。' * 12 + '''</p>
<a href="/about">关于我们</a><a href="/products/ro-500">RO-500 净水器</a><a href="/faq">常见问题</a>
<a href="/privacy">隐私政策</a><a href="tel:4000000000">客服电话</a><p>沪ICP备12345678号</p></body></html>'''
ABOUT = '<html lang="zh-CN"><head><title>关于 Aster</title><meta name="description" content="品牌介绍"></head><body><h1>关于 Aster</h1><p>' + 'Aster 成立于 2005 年，总部位于上海。' * 30 + '</p></body></html>'
PRODUCT = '''<html lang="zh-CN"><head><title>RO-500 | Aster</title><meta name="description" content="RO-500 规格">
<script type="application/ld+json">{"@type":"Product","name":"RO-500"}</script></head><body><h1>RO-500</h1>
<table><tr><th>通量</th><td>500G</td></tr><tr><th>滤芯</th><td>4 级</td></tr></table><p>''' + '经国家检测报告认证，出水达标。' * 20 + '''</p>
<a href="https://www.cnas.org.cn/report">检测报告</a></body></html>'''
FAQ = '<html lang="zh-CN"><head><title>常见问题 | Aster</title></head><body><h1>常见问题</h1><h2>滤芯多久更换？</h2><p>' + '一般 12 个月。' * 30 + '</p><h2>如何安装？</h2><h3>是否需要打孔？</h3></body></html>'
ROBOTS = 'User-agent: Bytespider\nDisallow: /\n\nUser-agent: *\nAllow: /\nSitemap: https://aster.example/sitemap.xml\n'
SITEMAP = '<urlset><url><loc>https://aster.example/</loc><lastmod>' + time.strftime('%Y-%m-%d') + '</lastmod></url><url><loc>https://aster.example/about</loc></url></urlset>'

def fake_site(pages):
    def fetch(url, limit=geo_diagnose.MAX_BYTES):
        body = pages.get(url)
        status = 200 if body is not None else 404
        kind = 'text/xml' if url.endswith('.xml') else 'text/plain' if url.endswith('.txt') else 'text/html'
        raw = (body or '').encode()
        return {'requested_url': url, 'url': url, 'status': status, 'content_type': kind, 'headers': {}, 'body': body or '', 'bytes': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest(), 'truncated': False, 'fetch_error': None, 'fetched_at': geo_diagnose.stamp()}
    return fetch

SITE = {'https://aster.example/': HOME, 'https://aster.example/about': ABOUT, 'https://aster.example/products/ro-500': PRODUCT,
        'https://aster.example/faq': FAQ, 'https://aster.example/robots.txt': ROBOTS, 'https://aster.example/sitemap.xml': SITEMAP}
CFG = geo_diagnose.validate({'website': 'aster.example', 'market': 'CN', 'brand': 'Aster', 'aliases': ['阿斯特']})

def node_validate(bundle):
    script = ("const vm=require('node:vm'),fs=require('node:fs');const ctx={console,localStorage:{getItem:()=>null},document:{querySelector:()=>null,addEventListener:()=>{}},URL,URLSearchParams,structuredClone};"
              "vm.createContext(ctx);vm.runInContext(fs.readFileSync('dist/app.js','utf8').replace(/init\\(\\);\\s*$/,''),ctx);vm.runInContext(fs.readFileSync('dist/diagnostic.js','utf8').replace(/init\\(\\);\\s*$/,''),ctx);"
              "ctx.input=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(vm.runInContext('validateBundle(input);scoreRules(input.rules)',ctx)))")
    p = subprocess.run(['node', '-e', script], input=json.dumps(bundle).encode(), capture_output=True, cwd=ROOT, timeout=60)
    if p.returncode: raise AssertionError(p.stderr.decode()[-2000:])
    return json.loads(p.stdout)

class CatalogTests(unittest.TestCase):
    def test_dimension_weights_match_frontend(self):
        totals = {}
        for r in geo_diagnose.CATALOG['rules']: totals[r['dimension']] = totals.get(r['dimension'], 0) + r['weight']
        self.assertEqual(totals, {'access': 25, 'entity': 20, 'questions': 20, 'trust': 15, 'structure': 10, 'maintenance': 10})
        self.assertEqual(len({r['rule_id'] for r in geo_diagnose.CATALOG['rules']}), len(geo_diagnose.CATALOG['rules']))

class BundleTests(unittest.TestCase):
    def setUp(self):
        self.collected = geo_diagnose.collect(CFG['website'], fake_site(SITE))
        self.bundle = geo_diagnose.build_bundle(self.collected, CFG)
        self.rules = {r['rule_id']: r for r in self.bundle['rules']}

    def test_discovers_representative_pages(self):
        cats = {p['category']: p['url'] for p in self.collected['pages']}
        self.assertEqual(cats['about'], 'https://aster.example/about')
        self.assertEqual(cats['product'], 'https://aster.example/products/ro-500')
        self.assertEqual(cats['faq'], 'https://aster.example/faq')

    def test_rule_outcomes(self):
        expect = {'R-A1': 'pass', 'R-A2': 'partial', 'R-A3': 'pass', 'R-E1': 'pass', 'R-E2': 'pass', 'R-E3': 'pass', 'R-E4': 'pass', 'R-E5': 'pass',
                  'R-Q1': 'pass', 'R-Q2': 'pass', 'R-T1': 'partial', 'R-T2': 'not_applicable', 'R-T4': 'partial', 'R-T5': 'partial',
                  'R-S1': 'pass', 'R-M1': 'pass', 'R-M2': 'pass', 'R-Q3': 'unknown', 'R-Q4': 'unknown'}
        self.assertEqual({k: self.rules[k]['status'] for k in expect}, expect)
        self.assertIn('Bytespider', self.rules['R-A2']['reason'])

    def test_bundle_passes_frontend_validator_and_scores(self):
        score = node_validate(self.bundle)
        self.assertIsNone(score['total'])  # answer rules stay unknown in page mode
        self.assertEqual(score['unknown_weight'], 10)
        self.assertGreater(score['lower'], 50)

    def test_findings_reference_failed_and_unknown_rules(self):
        by_rule = {f['rule_ids'][0]: f for f in self.bundle['findings']}
        self.assertEqual(by_rule['R-A2']['finding_type'], 'supported_gap')
        self.assertEqual(by_rule['R-Q3']['priority'], '待验证')
        self.assertNotIn('R-A1', by_rule)

    def test_unreachable_homepage_keeps_rules_unknown(self):
        bundle = geo_diagnose.build_bundle(geo_diagnose.collect('https://down.example/', fake_site({})), CFG)
        rules = {r['rule_id']: r for r in bundle['rules']}
        self.assertEqual(rules['R-A1']['status'], 'fail')
        self.assertEqual(rules['R-E1']['status'], 'unknown')
        self.assertEqual(rules['R-A2']['status'], 'pass')  # robots.txt 404 = allow all
        node_validate(bundle)

    def test_answers_from_research_run(self):
        prompts = ['家用净水器推荐？', 'Aster 怎么样？']
        samples = [{'provider': 'p1', 'question_index': 0, 'prompt': prompts[0], 'status': 'complete', 'answer': '1. Aster RO-500\n2. 其他品牌', 'captured_at': geo_diagnose.stamp(),
                    'citations': [{'url': 'https://aster.example/products/ro-500'}], 'search_observed': True},
                   {'provider': 'p1', 'question_index': 1, 'prompt': prompts[1], 'status': 'complete', 'answer': 'Aster 是净水品牌。', 'captured_at': geo_diagnose.stamp()},
                   {'provider': 'p1', 'question_index': 0, 'prompt': prompts[0], 'status': 'failed', 'captured_at': geo_diagnose.stamp()}]
        flow = {'id': '00000000-0000-0000-0000-000000000001', 'status': 'finished', 'prompt_hash': 'abc',
                'config': {'market': 'CN', 'website': 'https://aster.example/', 'brand_aliases': ['Aster'], 'competitors': [], 'skus': [], 'providers': ['p1'], 'configuration': {'p1': {'model': 'gpt-x'}}},
                'samples': samples}
        bundle = geo_diagnose.build_bundle(self.collected, CFG, flow)
        rules = {r['rule_id']: r for r in bundle['rules']}
        self.assertEqual(bundle['run_manifest']['mode'], 'full')
        self.assertEqual(rules['R-Q3']['status'], 'pass')
        self.assertEqual(rules['R-Q4']['status'], 'pass')
        self.assertEqual([a['question_type'] for a in bundle['answers']], ['discovery', 'brand', 'discovery'])
        self.assertEqual(bundle['answers'][2]['status'], 'failed')
        node_validate(bundle)

class StoreTests(unittest.TestCase):
    def test_runs_and_persists(self):
        with tempfile.TemporaryDirectory() as d:
            store = geo_diagnose.Store(d, fake_site(SITE))
            job = store.start({'website': 'https://aster.example/', 'market': 'CN', 'brand': 'Aster'})
            for _ in range(100):
                if store.get(job['id'])['status'] not in ('queued', 'running'): break
                time.sleep(.05)
            done = store.get(job['id'])
            self.assertEqual(done['status'], 'finished')
            self.assertEqual(store.list()['diagnoses'][0]['unknown'], 2)

    def test_rejects_invalid_input(self):
        with tempfile.TemporaryDirectory() as d:
            store = geo_diagnose.Store(d, fake_site(SITE))
            for bad in [{'website': 'x.example', 'market': 'JP', 'brand': 'A'}, {'website': 'x.example', 'market': 'CN', 'brand': ''},
                        {'website': 'http://127.0.0.1:8080/', 'market': 'CN', 'brand': 'A'}, {'website': 'x.example', 'market': 'CN', 'brand': 'A', 'extra': 1},
                        {'website': 'x.example', 'market': 'CN', 'brand': 'A', 'flow_id': 'nope'}]:
                with self.assertRaises(ValueError): store.start(bad)

    def test_fetch_refuses_private_addresses(self):
        result = geo_diagnose.fetch('http://127.0.0.1/')
        self.assertIn(result['fetch_error'], ('unsafe_address', 'proxy_unsupported'))

if __name__ == '__main__':
    unittest.main()
