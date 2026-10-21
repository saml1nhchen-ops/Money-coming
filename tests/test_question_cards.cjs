const vm = require('node:vm'), fs = require('node:fs'), assert = require('node:assert/strict');
const ctx = {console, URL, URLSearchParams, structuredClone, crypto: require('node:crypto').webcrypto,
  location: {hostname: 'preview.example', port: ''}, window: {scrollTo() {}},
  localStorage: {getItem: () => null, setItem() {}}, document: {querySelector: () => null, addEventListener() {}}};
vm.createContext(ctx);
for (const file of ['app.js', 'research.js', 'research-ui.js', 'report-summary.js', 'question-cards.js']) {
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

console.log('Question cards: full bank, family denominators, per-model gaps, raw evidence, repeats, truncation and escaping passed.');
