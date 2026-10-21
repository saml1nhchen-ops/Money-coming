const vm = require('node:vm'), fs = require('node:fs'), assert = require('node:assert/strict');
const ctx = {console, URL, URLSearchParams, structuredClone, crypto: require('node:crypto').webcrypto,
  location: {hostname: 'preview.example', port: ''}, window: {scrollTo() {}},
  localStorage: {getItem: () => null, setItem() {}}, document: {querySelector: () => null, addEventListener() {}}};
vm.createContext(ctx);
for (const file of ['app.js', 'research.js', 'website-inspect.js', 'research-ui.js', 'report-summary.js', 'question-cards.js']) {
  vm.runInContext(fs.readFileSync('dist/' + file, 'utf8').replace(/init\(\);\s*$/, ''), ctx);
}
const run = code => vm.runInContext(code, ctx);
ctx.job = {
  status: 'partial', config: {providers: ['direct:p', 'q', 'missing'], configuration: {'direct:p': {model: 'Frozen Model'}}, brand_aliases: ['Cremo']},
  prompts: [{text: 'Same prompt', family: 'discovery'}, {text: 'Same prompt', family: 'brand'}, {text: '<img src=x onerror=alert(1)>', family: 'comparison'}],
  samples: [{id: 'one', question_index: 0, provider: 'direct:p', repeat: 1, status: 'complete', answer: 'raw answer'},
    {id: 'two', question_index: 0, provider: 'direct:p', repeat: 2, status: 'failed', error: 'Actual failure <script>'},
    {id: 'unanalysed', question_index: 1, provider: 'q', status: 'complete', answer: '<script>unanalysed</script>'}],
  report: {samples: [{id: 'one', question_index: 0, provider: 'direct:p', repeat: 1, status: 'complete', answer: 'raw answer',
    analysis: {family: 'discovery', eligible: true, entities: [{own: true, name: 'Cremo', alias: 'Cremo', rank: {position: 2, evidence: '2. Cremo'}}, {own: false, name: 'Competitor', alias: null}],
      citations: [{kind: 'citation', own: true, url: 'https://cremocompany.com', owner: 'Cremo'}, {kind: 'answer_link', url: 'javascript:alert(1)'}]}},
    {id: 'zero', question_index: 0, provider: 'q', status: 'complete', answer: 'Other', analysis: {family: 'discovery', eligible: true, entities: [{own: true, name: 'Cremo', alias: null}], citations: []}}]}
};
const cards = run('questionCards(job)');
assert.equal((cards.match(/class="rq-card"/g) || []).length, 3);
assert(cards.includes('question-card-2'));
assert(cards.includes('品牌认知题 · 不计自然发现分母'));
assert(cards.includes('品牌比较题 · 不计自然发现分母'));
assert(!cards.includes('<img src=x'));
assert.equal(run('questionSamples(job,0,"direct:p").length'), 2);
assert.equal(run('questionSamples(job,1,"direct:p").length'), 0);
const dialog = run('questionDialogContent(job,0)');
assert.equal((dialog.match(/class="rq-model"/g) || []).length, 3);
assert(dialog.includes('Frozen Model'));
assert(dialog.includes('第 2 次采样'));
assert(dialog.includes('Actual failure &lt;script&gt;'));
assert(dialog.includes('第 2 位'));
assert(dialog.includes('2. Cremo'));
assert(dialog.includes('未提及'));
assert(dialog.includes('未运行'));
assert(dialog.includes('AI 返回的引用'));
assert(dialog.includes('回答中的普通链接'));
assert(!dialog.includes('href="javascript:'));
const unknown = run('questionDialogContent(job,1)');
assert(unknown.includes('未知'));
assert(unknown.includes('&lt;script&gt;unanalysed'));
assert(!unknown.includes('<script>'));
run('job.status="running"');
assert(run('questionDialogContent(job,2)').includes('等待中'));
run('job.report=null');
assert.equal((run('questionCards(job)').match(/class="rq-card"/g) || []).length, 3);
assert(run('questionSampleContent({status:"complete",truncated:true,answer:"partial",analysis:{entities:[{own:true,alias:"Cremo"}]}},job)').includes('回答截断'));
assert(run('questionSampleContent({status:"complete",truncated:true,answer:"partial",analysis:{entities:[{own:true,alias:"Cremo"}]}},job)').includes('未知'));

(async () => {
  run('render=()=>{}; location.hostname="127.0.0.1"; location.port="8772"; geoToken="test-token"; geoMarket="US"; geoDraft.US={website:"cremocompany.com",brand:"",context:"My edited context"};');
  const inspection = {website: {url: 'https://cremocompany.com/', captured_at: '2026-10-21', content_sha256: 'hash', bytes: 250},
    brand: {name: 'Cremo', aliases: ['Cremo'], source: 'title', needs_confirmation: true},
    diagnosis: {scope: 'website_readiness', score: null, checks: [{id: 'title', label: 'Title', status: 'unknown', evidence: '<script>', action: 'Review'}], methodology: 'Unknown stays null'},
    context: 'Fetched context', warnings: ['Confirm brand']};
  let calls = 0;
  ctx.geoFetch = async (path, body) => { assert.equal(path, 'inspect'); assert.equal(body.market, 'US'); calls++; return inspection; };
  await run('researchInspectWebsite()');
  assert.equal(calls, 1);
  assert.equal(run('geoDraft.US.brand'), ''); // A fallback candidate is not silently used.
  assert.equal(run('geoDraft.US.context'), 'My edited context');
  assert.equal(run('researchBrandPending()'), true);
  const inspected = run('researchInspectionMarkup()');
  assert(inspected.includes('id="confirm-inspected-brand"'));
  assert(inspected.includes('id="website-readiness-score">—'));
  assert(inspected.includes('&lt;script&gt;'));
  assert(inspected.includes('尚未连接模型'));
  run('researchNext(2)');
  assert.equal(run('researchStep'), 1);
  run('researchConfirmInspectedBrand()');
  assert.equal(run('geoDraft.US.brand'), 'Cremo');
  assert.equal(run('researchBrandPending()'), false);
  run('geoDraft.US.brand="Cremo | Cremo Company | CREMO US"; geoDraft.US.inspectedBrandConfirmed=false; researchConfirmInspectedBrand()');
  assert.equal(run('geoDraft.US.brand'), 'Cremo | Cremo Company | CREMO US');
  run('researchNext(2)');
  assert.equal(run('researchStep'), 2);
  run('geoDraft.US.website="https://changed.example"');
  assert.equal(run('researchCurrentInspection()'), null);
  ctx.geoFetch = async () => { throw Error('HTTP 400 blocked'); };
  await run('researchInspectWebsite()');
  assert.equal(run('geoDraft.US.inspection'), null);
  assert(run('researchMessage').includes('未生成页面分数'));
  console.log('URL inspection and question cards: confirmation, context preservation, null scores, complete bank, model gaps, repeats, raw evidence and escaping passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
