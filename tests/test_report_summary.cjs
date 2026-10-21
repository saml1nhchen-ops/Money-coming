const vm = require('node:vm'), fs = require('node:fs'), assert = require('node:assert/strict');
const job = JSON.parse(fs.readFileSync('tests/fixtures/report-job.json', 'utf8'));
const ctx = {
  console, URL, URLSearchParams, structuredClone, crypto: require('node:crypto').webcrypto,
  localStorage: {getItem: () => null}, document: {querySelector: () => null, addEventListener: () => {}},
  location: {hostname: 'preview.example', port: ''}, job,
};
vm.createContext(ctx);
for (const file of ['app.js', 'research.js', 'research-ui.js', 'report-summary.js']) {
  vm.runInContext(fs.readFileSync('dist/' + file, 'utf8').replace(/init\(\);\s*$/, ''), ctx);
}
const run = code => vm.runInContext(code, ctx);
run('geoActive=job');
assert.equal(run('researchMetrics(job.report).score'), 50);
assert.equal(run('researchMetrics(job.report).total'), 4); // Failure and branded question excluded.
assert.equal(run('reportGapGroups(job.report).length'), 1); // Same question from two models, counted once.
assert.equal(run('reportGapGroups(job.report)[0].ids.length'), 2);
assert.equal(run('reportCitedSources(job.report).length'), 2);
assert.equal(run('reportCitedSources(job.report).some(s=>s.domain==="hidden.example")'), false);
const html = run('researchReport(job.report,job)');
const sections = ['report-overview', 'report-gaps', 'report-sources', 'report-actions', 'report-details'];
for (let i = 1; i < sections.length; i++) assert(html.indexOf(`id="${sections[i - 1]}"`) < html.indexOf(`id="${sections[i]}"`));
assert(html.includes('阶段结果'));
assert(html.includes('尚未修改或发布'));
assert(html.includes('reportOpenEvidence'));
assert(!html.includes('hidden.example'));
// Missing/unsupported citation metadata does not become a fabricated zero citation rate.
run('let missing=structuredClone(job);missing.report.samples.forEach(s=>s.analysis.citations=[]);missing.report.sources=[];');
assert(run('researchReport(missing.report,missing)').includes('不将缺失信息记成'));
// An empty run has no score or competitor conclusion, while a measured zero remains zero.
run('let emptyRun=structuredClone(job);emptyRun.report.samples=[];emptyRun.report.gaps=[];emptyRun.report.sources=[];for(const m of emptyRun.report.groups.discovery.models){m.eligible=0;for(const b of m.brands){b.denominator=0;b.mentions=0;b.score=null;b.citation_answers=0;b.average_rank=null;b.ranked_samples=0}}');
assert.equal(run('researchMetrics(emptyRun.report).score'), null);
assert(run('researchReport(emptyRun.report,emptyRun)').includes('有效回答不足，暂时无法评分'));
run('let zero=structuredClone(job);for(const m of zero.report.groups.discovery.models){const b=m.brands.find(b=>b.own);b.mentions=0;b.score=0}');
assert.equal(run('researchMetrics(zero.report).score'), 0);
assert(run('researchReport(zero.report,zero)').includes('rr-score-number">0<span>'));
run('let hostile=structuredClone(job);hostile.report.gaps[0].prompt="<img src=x onerror=alert(1)>";hostile.report.samples[1].answer="<script>alert(1)</script>";');
assert(!run('researchReport(hostile.report,hostile)').includes('<img src=x'));
run('let drawerHTML=reportEvidenceContent(hostile.report.samples.find(s=>s.id==="s2"))');
assert(run('drawerHTML').includes('&lt;script&gt;'));
assert(!run('drawerHTML').includes('<script>'));
console.log('Report: denominator, grouped competitor gaps, citation scope, missing/zero scores, section order and evidence escaping passed.');
