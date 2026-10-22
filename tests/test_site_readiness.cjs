/* Offline rendering compatibility and escaping, independent of API fixtures. */
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const ctx={console,URL,URLSearchParams,structuredClone,Map,Set,crypto:require('node:crypto').webcrypto,window:{SIGNAL_GEO_MODE:'team',addEventListener(){}},document:{addEventListener(){}},page:'overview',names:{},geoPage(){},render(){},geoChange(){},diagnosticPage(){},geoState:{runner:{profiles:[]}},location:{hash:''},esc:s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('dist/diagnostic.js','utf8'),ctx);vm.runInContext(fs.readFileSync('dist/site-readiness.js','utf8'),ctx);
const d=JSON.parse(fs.readFileSync('tests/fixtures/diagnostic-full-contract.json','utf8'));
assert.equal(vm.runInContext('typeof scoreRules',ctx),'function');ctx.payload=d;
const frontendScore=vm.runInContext('scoreRules(payload.bundle.rules)',ctx);
for(const key of ['total','lower','upper','coverage'])assert.equal(frontendScore[key],d.bundle.scores[key],'same v0.1 scoring: '+key);
const dangerous='<img src=x onerror=alert(1)><script>alert(1)</script>';
d.bundle.run_manifest.brand=dangerous;d.bundle.answers[0].raw_answer=dangerous;d.bundle.answers[0].citations=[{url:'javascript:alert(1)'},{url:'https://safe.example/path',title:dangerous}];d.bundle.evidence[0].excerpt=dangerous;
d.bundle.competitor_gaps=[];d.bundle.performance.gaps=[{prompt:dangerous,competitors:['Rival Tea']}];
d.trend={comparable:true,baseline:{total:null,lower:20,upper:60,coverage:.6},current:{total:null,lower:30,upper:60,coverage:.7},delta:{lower:10,upper:0},differences:[]};
const html=ctx.window.unifiedDiagnosticHTML(d);
assert(html.includes('&lt;img'));assert(!html.includes('<img'));assert(!html.includes('<script'));assert(!html.includes('href="javascript:'));assert(html.includes('href="https://safe.example/path"'));assert(html.includes('同一组自然发现问题'));assert(html.includes('Rival Tea'));assert(html.includes('20–60'));assert(html.includes('30–60'));assert(html.includes('60%'));assert(html.includes('70%'));
for(const q of d.bundle.questions)assert(html.includes(ctx.esc(q.question)));for(const e of d.bundle.evidence)assert(html.includes(ctx.esc(e.evidence_id)));
assert(html.includes('完整保存快照与原始证据'));assert(html.includes('default-src'));
const legacy=JSON.parse(fs.readFileSync('tests/fixtures/site-readiness-contract.json','utf8'));
for(const outcome of ['limited','challenge','readable']){legacy.access.outcome=outcome;legacy.access.http_status=outcome==='limited'?429:200;legacy.access.checks=[{id:'tls',status:'unknown',message:dangerous}];const text=ctx.window.siteReadinessReport(legacy,true);assert(text.includes('官网'));assert(!text.includes('<img'));if(outcome==='limited')assert(text.includes('不能据此确定为反爬'));if(outcome==='challenge')assert(text.includes('即使 HTTP 200'))}
// Browser direct entry is unaffected: the unified module exits before referring to team globals.
const direct={window:{SIGNAL_GEO_MODE:'browser'}};vm.createContext(direct);vm.runInContext(fs.readFileSync('dist/site-readiness.js','utf8'),direct);assert.equal(direct.window.unifiedDiagnosticHTML,undefined);
console.log('Unified rendering: real saved v0.1 fixture score parity, native-vs-unsafe citations, full escaped raw evidence/export, real competitor performance/gaps, two-point range/coverage trend, legacy access diagnostics, direct-browser isolation passed.');
// Reduced, de-identified structure from the user-provided terminal full/no-answer snapshot.
const incomplete=JSON.parse(fs.readFileSync('tests/fixtures/diagnostic-full-no-answers.json','utf8'));
const incompleteHTML=ctx.window.unifiedDiagnosticHTML(incomplete);
assert(incompleteHTML.includes('模型分析未完成'));assert(incompleteHTML.includes('本次未取得模型回答'));assert(!incompleteHTML.includes('本次选择仅检查官网'));assert(incompleteHTML.includes('已确认45分，另有45分待核实'));assert(incompleteHTML.includes('已核验55%的评分项'));assert(incompleteHTML.includes('本次带广告参数的网址受访问规则限制'));assert(incompleteHTML.includes('本次读取未识别出完整的页面标题'));
const running=structuredClone(incomplete);running.status='running';assert.throws(()=>ctx.window.unifiedDiagnosticHTML(running));
const wrongRun=structuredClone(incomplete);wrongRun.bundle.run_manifest.run_id='other';assert.throws(()=>ctx.window.unifiedDiagnosticHTML(wrongRun));
const generic=structuredClone(incomplete);generic.website='https://brand.example/';assert(!ctx.window.unifiedDiagnosticReport(generic).includes('本次带广告参数的网址受访问规则限制'));
console.log('Real terminal full/no-answer shape: 45–90/55% preserved, incomplete model wording, narrow advertising-path evidence, pending/mismatched snapshot export rejected.');

const uncertain=structuredClone(incomplete);uncertain.progress={runner_status:'unknown'};assert.throws(()=>ctx.window.unifiedDiagnosticHTML(uncertain));
const manyGaps=structuredClone(d);manyGaps.bundle.competitor_gaps=Array.from({length:5},(_,i)=>({question:'Gap '+i,competitors:['Rival']}));const compact=ctx.window.unifiedDiagnosticReport(manyGaps);assert(compact.includes('查看其余2道问题'));for(let i=0;i<5;i++)assert(compact.includes('Gap '+i));assert(!ctx.window.unifiedDiagnosticHTML(manyGaps).includes('查看其余2道问题'));

assert(incompleteHTML.includes('<details><summary>完整保存快照与原始证据</summary>'));assert(!incompleteHTML.includes('details>*{display:block!important}'));
