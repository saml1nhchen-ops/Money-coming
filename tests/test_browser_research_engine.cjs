/* Offline synthetic transport only; no real model calls. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const crypto=require('node:crypto');
const Engine=require('../dist/browser-research-engine.js');
const golden=JSON.parse(fs.readFileSync(__dirname+'/fixtures/browser-research-golden.json','utf8'));
const profiles=[{id:'gpt',name:'gpt-test',model:'gpt-test',manufacturer:'OpenAI',provider:'bai',channel:'bai',protocol:'chat',markets:['CN','US'],search:false},{id:'gemini',name:'gemini-test',model:'gemini-test',manufacturer:'Google',provider:'bai',channel:'bai',protocol:'chat',markets:['CN','US'],search:false}];
const cfg=()=>({market:'US',website:'https://cremocompany.com/',brand_aliases:['Cremo'],skus:[],competitors:[{name:'Rival',aliases:['Rival'],domains:['rival.example']}],context:'User supplied shaving cream products',focus:'Sensitive skin',count:30,repeats:1,providers:['gpt','gemini'],generator:'gpt'});
const raw=(text,finish='stop')=>({model:'actually-returned-model',choices:[{message:{content:text},finish_reason:finish}],usage:{prompt_tokens:3,completion_tokens:4}});
const defer=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
function broker(handler){
 let busy=false,epoch=0;const calls=[],leases=[];
 const transport={calls,leases,snapshot:()=>({configured:true,profiles:structuredClone(profiles),busy,browser_direct:true,fetched_at:'synthetic-time'}),
 acquire(spec){if(busy)throw Object.assign(new Error('busy'),{code:'busy'});busy=true;const own=epoch,lease={profiles:structuredClone(profiles.filter(p=>spec.profileIds.includes(p.id))),spec,releaseCount:0,cancelled:false,
 isCurrent(){return own===epoch&&!lease.cancelled&&busy;},cancel(){lease.cancelled=true;},release(){lease.releaseCount++;if(own===epoch)busy=false;},
 async chat(request){assert(lease.isCurrent());assert(calls.length<spec.maxCalls);assert(request.prompt.length<=20000);calls.push(request);return handler(request,calls.length);}};leases.push(lease);return lease;},
 reconnect(){epoch++;busy=false;}};return transport;
}
function generation(request){
 const specs=JSON.parse(request.prompt.split('Exact ordered blueprint: ')[1].split('\nAvoid duplicates')[0]);
 return raw(JSON.stringify({questions:specs.map(s=>({text:(s.family==='brand'?'What is Cremo benefit ':s.family==='comparison'?'Cremo versus Rival option ':'What shaving option addresses need ')+s.index+'?'}))}));
}
async function done(engine,id){for(let i=0;i<300;i++){const j=engine.get(id);if(!['queued','running'].includes(j.status))return j;await new Promise(r=>setTimeout(r,2));}throw new Error('Synthetic test did not finish');}
(async()=>{
 assert.deepEqual(Engine.analyze(golden.samples,golden.config,golden.prompts),golden.expected,'complete Python golden geo_analysis parity');
 const specs=Engine.blueprint().flat();assert.equal(specs.length,30);assert.equal(specs.filter(s=>s.family==='discovery').length,21);assert.equal(specs.filter(s=>s.family==='brand').length,5);assert.equal(specs.filter(s=>s.family==='comparison').length,4);
 {
  const b=broker(r=>r.maxOutputTokens===4096?generation(r):raw('1. Cremo: smooth\n2. Rival: alternative'));const updates=[];const e=Engine.create({transport:b,onUpdate:x=>updates.push(x)});
  const p=e.plan(cfg());assert.equal(p.maximum_calls,63);assert.equal(b.calls.length,0);
  for(const c of [{...cfg(),count:31},{...cfg(),repeats:2},{...cfg(),providers:['gpt','gpt']},{...cfg(),generator:'unknown'},{...cfg(),brand_aliases:['Rival']},{...cfg(),providers:['gpt','gemini','third']}])assert.throws(()=>e.start(c));
  const queued=e.start(cfg());assert.equal(queued.status,'queued');assert.equal(b.calls.length,0);assert.throws(()=>e.start(cfg()),{code:'busy'});
  const job=await done(e,queued.id);assert.equal(job.status,'finished');assert.equal(job.samples.length,60);assert.equal(b.calls.length,63);assert.equal(job.prompts.length,30);assert.equal(new Set(job.prompts.map(p=>p.text)).size,30);assert.equal(job.report.groups.discovery.question_count,21);assert.equal(job.website.status,'not_fetched');assert.equal(job.website.reason,'browser_mode_not_fetched');assert.equal(job.report.models[0].brands[0].score,100);assert(!('raw_evidence' in job));
  const evidence=e.export(job.id);assert.equal(Object.keys(evidence.raw_evidence).length,63);const s=evidence.samples[0],serialized=JSON.stringify(evidence.raw_evidence[s.raw_file],null,2);assert.equal(s.raw_sha256,crypto.createHash('sha256').update(serialized).digest('hex'));assert.equal(s.model_returned,'actually-returned-model');
  for(let i=0;i<30;i++){assert.equal(b.calls[3+i].prompt,job.prompts[i].text);assert.equal(b.calls[33+i].prompt,job.prompts[i].text);}
  const copy=e.get(job.id);copy.config.brand_aliases[0]='modified';assert.equal(e.get(job.id).config.brand_aliases[0],'Cremo');
  const before=b.calls.length,re=e.reanalyze({id:job.id,brand_aliases:['Other Brand']});assert.equal(re.analysis_only,true);assert.equal(re.parent_run_id,job.id);assert.equal(re.planned_max_calls,0);assert.equal(re.plan.maximum_calls,0);assert.equal(b.calls.length,before);assert.deepEqual(re.samples,job.samples);assert.equal(e.export(re.id).samples[0].raw_sha256,s.raw_sha256);
 }
 {
  const b=broker(generation),e=Engine.create({transport:b});const job=await done(e,e.start({...cfg(),generate_only:true,context:'Long background '.repeat(1100),focus:'A'.repeat(18000)}).id);assert.equal(job.status,'finished');assert.equal(b.calls.length,3);assert.equal(job.report,null);assert.equal(job.plan.maximum_calls,3);assert(b.calls.every(r=>r.prompt.length<=20000));assert(b.calls[2].prompt.includes(job.prompts[0].text));assert.equal(job.samples.length,0);
 }
 {
  const b=broker(()=>raw('Cremo')),e=Engine.create({transport:b});const prompts=Array.from({length:30},(_,i)=>'neutral question '+i);assert.equal(e.plan({...cfg(),prompts},{manual:true}).maximum_calls,60);assert.throws(()=>e.sample({...cfg(),prompts:[...prompts.slice(0,29),' NEUTRAL question 0! ']}));const j=await done(e,e.sample({...cfg(),prompts}).id);assert.equal(j.status,'finished');assert.equal(b.calls.length,60);assert.equal(j.generations.length,0);
 }
 for(const mode of ['duplicate','bad_json','truncated','bad_shape','http_429']){
  const b=broker((r,n)=>{if(mode==='http_429')throw Object.assign(new Error('Synthetic rate limit'),{code:'http_429'});if(mode==='bad_shape')return {synthetic:true};if(mode==='bad_json')return raw('Prose instead of JSON');if(mode==='truncated')return raw('{"questions":[','length');if(n===2)return raw(JSON.stringify({questions:Array.from({length:10},()=>({text:'same question!'}))}));return generation(r);});const e=Engine.create({transport:b});const j=await done(e,e.start(cfg()).id);assert.equal(j.status,'failed');assert.equal(j.samples.length,0);assert(b.calls.length<=2);assert.equal(j.report,null);if(mode!=='http_429')assert(Object.keys(e.export(j.id).raw_evidence).length>0);if(mode==='duplicate')assert.equal(j.prompts.length,11);
 }
 {
  let n=0;const b=broker(r=>{if(r.maxOutputTokens===4096)return generation(r);n++;if(n===1)return raw('Cremo cut off','length');if(n===2)throw Object.assign(new Error('Synthetic HTTP401'),{code:'http_401'});return raw('unexpected');}),e=Engine.create({transport:b});const j=await done(e,e.start(cfg()).id);assert.equal(j.status,'partial');assert.equal(b.calls.length,5);assert.equal(j.samples.length,2);assert.equal(j.samples[0].status,'incomplete');assert.equal(j.samples[0].truncated,true);assert.equal(j.samples[1].status,'failed');assert.equal(j.report.models[0].brands[0].score,null);assert.equal(j.report.models[0].brands[0].denominator,0);assert.equal(j.report.coverage.complete,0);
 }
 {
  const pending=defer();let entered=false;const b=broker(r=>{if(r.maxOutputTokens===4096)return generation(r);entered=true;return pending.promise;}),e=Engine.create({transport:b});const q=e.start(cfg());for(let i=0;i<100&&!entered;i++)await new Promise(r=>setTimeout(r,2));assert(entered);assert.deepEqual(e.stop(q.id),{status:'stop_requested'});assert.equal(b.leases[0].cancelled,false);pending.resolve(raw('Cremo in flight'));const j=await done(e,q.id);assert.equal(j.status,'stopped');assert.equal(b.calls.length,4);assert.equal(j.samples.length,1);assert.equal(j.samples[0].answer,'Cremo in flight');assert.equal(Object.keys(e.export(q.id).raw_evidence).length,4);assert.equal(b.leases[0].releaseCount,1);
 }
 {
  const pending=defer();const b=broker(()=>pending.promise),e=Engine.create({transport:b});const old=e.start(cfg());await new Promise(r=>setImmediate(r));e.reset();b.reconnect();assert.equal(e.state().runs.length,0);assert.throws(()=>e.get(old.id),{code:'not_found'});pending.resolve(raw('late response'));await new Promise(r=>setTimeout(r,10));assert.equal(e.state().runs.length,0);assert.equal(b.leases[0].cancelled,true);assert.equal(b.leases[0].releaseCount,1);
 }
 {
  const b=broker(()=>{throw new Error('must not be called');}),e=Engine.create({transport:b});const q=e.start(cfg());e.stop(q.id);const j=await done(e,q.id);assert.equal(j.status,'stopped');assert.equal(b.calls.length,0);
 }
 console.log('Browser research engine: offline Python golden and synthetic execution checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
