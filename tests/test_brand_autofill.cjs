const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try {
 const page=await browser.newPage();
 await page.route('**/*',route=>route.abort());
 await page.setContent('<main id="view"></main>');
 await page.addScriptTag({content:`
 window.SIGNAL_GEO_MODE='team'; let geoMarket='US',researchStep=1;
 let geoDraft={US:{brand:'',website:'',skus:'',competitors:''},CN:{brand:'',website:'',skus:'',competitors:''}};
 let context={backend:'https://mock.example',epoch:1,authenticated:true}, calls=[],waiting=[];
 let esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let geoRows=s=>(s||'').split('\\n').filter(Boolean).map(name=>({name}));
 function researchSave(){for(const [id,k] of [['geo-website','website'],['ru-brand','brand'],['ru-products','skus'],['ru-competitors','competitors']]){const e=document.getElementById(id);if(e)geoDraft[geoMarket][k]=e.value}}
 function geoChange(m){researchSave();geoMarket=m;mount()}
 window.remoteEnrichmentContext=()=>({...context});
 window.remoteEnrich=body=>{calls.push(body);return new Promise((resolve,reject)=>waiting.push({resolve,reject}))};
 Object.defineProperty(crypto,'randomUUID',{value:()=> '12345678-1234-4234-8234-123456789012'});
 function mount(){document.getElementById('view').innerHTML=researchBrand()}
 function result(name='Cremo',status='finished'){return {id:'12345678-1234-4234-8234-123456789012',status,website:{status:'fetched',captured_at:'2026-10-22T12:00:00Z'},brand:{name,kind:'brand',basis:'website_metadata',source_url:'https://example.com',source_field:'og:site_name'},products:[{name:'Shave Cream',kind:'product',basis:'website_text'}],competitors:[{name:'<img src=x onerror=alert(1)>',kind:'competitor',basis:'model_inference'}],model_suggestion:{status:'free_model_unavailable'},billing:{model_calls:0}}}
 `});
 // Load real production markup, keeping test-only draft/save plumbing.
 await page.addScriptTag({content:fs.readFileSync('dist/research-ui.js','utf8').split('\n').filter(l=>l.startsWith('function researchField(')||l.startsWith('function researchBrand(')).join('\n')});
 await page.addScriptTag({content:fs.readFileSync('dist/brand-autofill.js','utf8')});
 await page.evaluate(()=>mount());
 await page.waitForTimeout(750); assert.equal(await page.evaluate(()=>calls.length),0,'render does not request');
 await page.locator('#geo-website').fill('cremocompany.com');
 await page.waitForTimeout(750); await page.locator('#ru-brand').focus();
 assert.equal(await page.evaluate(()=>calls.length),1,'debounce plus blur singleflight');
 await page.locator('#ru-brand').fill('My brand');
 await page.evaluate(()=>waiting.shift().resolve(result()));
 await page.waitForTimeout(50);
 assert.equal(await page.locator('#ru-brand').inputValue(),'My brand');
 assert.equal(await page.locator('#ru-products').inputValue(),'Shave Cream');
 assert.equal(await page.locator('#ru-competitors').inputValue(),'');
 assert.equal(await page.locator('#brand-autofill img').count(),0);
 assert.match(await page.locator('#brand-autofill').textContent(),/尚未提供可验证的免费/);
 await page.locator('[data-brand-candidate="2"]').click();
 assert.match(await page.locator('#ru-competitors').inputValue(),/<img/);
 assert.equal(await page.evaluate(()=>researchStep),1,'candidate adoption never starts research');
 // A later URL result cannot overwrite the current URL, market, backend or auth.
 for(const change of ['url','market','backend','auth']){
   await page.locator('#geo-website').fill(change+'.example.com');
   await page.locator('#ru-brand').focus();
   const count=await page.evaluate(()=>calls.length);
   if(change==='url') await page.evaluate(()=>{const e=document.getElementById('geo-website');e.value='next.example.com';e.dispatchEvent(new Event('input',{bubbles:true}));});
   else if(change==='market') await page.evaluate(()=>geoChange(geoMarket==='US'?'CN':'US'));
   else await page.evaluate(change=>{context.epoch++;if(change==='backend')context.backend='https://other.example';else context.authenticated=false;window.dispatchEvent(new Event('remote-enrichment-invalidated'))},change);
   await page.evaluate(()=>waiting.shift().resolve(result('STALE')));
   await page.waitForTimeout(50);
   assert.notEqual(await page.locator('#ru-brand').inputValue(),'STALE',change+' isolation');
   await page.evaluate(()=>{context.authenticated=true;context.epoch++;window.dispatchEvent(new Event('remote-enrichment-invalidated'));mount()});
   assert.equal(await page.evaluate(()=>calls.length),count,'identity restore does not submit');
 }
 // Generic brand with blank fields, queued website then GET suggestion completion.
 await page.evaluate(()=>{geoDraft[geoMarket].brand='';geoDraft[geoMarket].skus='';mount()});
 await page.locator('#geo-website').fill('generic.example.com'); await page.locator('#ru-brand').focus();
 await page.evaluate(()=>waiting.shift().resolve(result('Generic','running')));
 await page.waitForTimeout(1300);
 assert.equal(typeof await page.evaluate(()=>calls.at(-1)),'string','poll uses independent GET identity');
 await page.evaluate(()=>waiting.shift().resolve({...result('Generic'),reused:true})); await page.waitForTimeout(40);
 assert.match(await page.locator('#brand-autofill').textContent(),/复用 24 小时内缓存/);
 // A failed GET can resume read-only from its known id, without another POST.
 await page.locator('#geo-website').fill('https://poll.example.com:443');await page.locator('#ru-brand').focus();
 assert.equal(await page.evaluate(()=>calls.at(-1).website),'https://poll.example.com/');
 await page.evaluate(()=>waiting.shift().resolve(result('Poll','running')));await page.waitForTimeout(1300);
 await page.evaluate(()=>waiting.shift().reject(new Error('mock poll offline')));await page.waitForTimeout(50);
 const postsBefore=await page.evaluate(()=>calls.filter(x=>typeof x==='object').length);
 await page.locator('#brand-autofill-read').click();
 assert.equal(typeof await page.evaluate(()=>calls.at(-1)),'string','manual recovery uses GET');
 await page.evaluate(()=>waiting.shift().resolve(result('Poll','running')));await page.waitForTimeout(1300);
 assert.equal(typeof await page.evaluate(()=>calls.at(-1)),'string','recovery resumes GET polling');
 await page.evaluate(()=>waiting.shift().resolve({...result('Poll'),reused:true}));await page.waitForTimeout(50);
 assert.equal(await page.evaluate(()=>calls.filter(x=>typeof x==='object').length),postsBefore,'no model POST resubmission');
 assert.match(await page.locator('#brand-autofill').textContent(),/复用 24 小时内缓存/);
 await page.locator('#geo-website').fill('http://port.example.com:80');await page.locator('#ru-brand').focus();
 assert.equal(await page.evaluate(()=>calls.at(-1).website),'http://port.example.com/');
 await page.evaluate(()=>waiting.shift().resolve(result()));await page.waitForTimeout(30);
 // Late website candidates never mutate draft fields after first-step confirmation.
 await page.locator('#geo-website').fill('late.example.com');await page.locator('#ru-brand').focus();
 const beforeLate=await page.evaluate(()=>JSON.stringify(geoDraft));
 await page.evaluate(()=>{researchStep=2;document.getElementById('ru-products').remove();waiting.shift().resolve(result('LATE'))});
 await page.waitForTimeout(50);
 assert.equal(await page.evaluate(()=>JSON.stringify(geoDraft)),beforeLate,'late response cannot change confirmed draft');
 await page.evaluate(()=>{researchStep=1;mount()});
 // Only a completed, zero-model-call website failure may explicitly fetch anew.
 await page.locator('#geo-website').fill('failed-site.example.com');await page.locator('#ru-brand').focus();
 await page.evaluate(()=>waiting.shift().resolve({...result(),stage:'done',status:'failed',website:{status:'failed'},billing:{model_calls:0}}));await page.waitForTimeout(30);
 const failedPosts=await page.evaluate(()=>calls.filter(x=>typeof x==='object').length);
 await page.locator('#brand-autofill-read').click();
 assert.equal(typeof await page.evaluate(()=>calls.at(-1)),'object','explicit zero-call website failure allows POST');
 assert.equal(await page.evaluate(()=>calls.filter(x=>typeof x==='object').length),failedPosts+1);
 await page.evaluate(()=>waiting.shift().resolve({...result(),stage:'done',status:'failed',website:{status:'failed'},billing:{model_calls:1}}));await page.waitForTimeout(30);
 await page.locator('#brand-autofill-read').click();
 assert.equal(typeof await page.evaluate(()=>calls.at(-1)),'string','attempted website failure remains read-only GET');
 await page.evaluate(()=>waiting.shift().resolve(result()));await page.waitForTimeout(30);
 // Busy/failure never schedules automatic POST retry.
 await page.locator('#geo-website').fill('busy.example.com');await page.locator('#ru-brand').focus();
 await page.evaluate(()=>waiting.shift().reject(new Error('团队已有任务')));await page.waitForTimeout(1500);
 const count=await page.evaluate(()=>calls.length);await page.locator('#geo-website').focus();await page.locator('#ru-brand').focus();
 assert.equal(await page.evaluate(()=>calls.length),count);
 await page.evaluate(()=>{context.authenticated=false;context.epoch++;window.dispatchEvent(new Event('remote-enrichment-invalidated'))});
 await page.locator('#geo-website').fill('loggedout.example.com');await page.locator('#ru-brand').focus();
 assert.equal(await page.evaluate(()=>calls.length),count);
 const direct=await browser.newPage();await direct.setContent('<p>Direct browser mode</p>');
 await direct.addScriptTag({content:"window.SIGNAL_GEO_MODE='browser'"});
 await direct.addScriptTag({content:fs.readFileSync('dist/brand-autofill.js','utf8')});
 assert.equal(await direct.evaluate(()=>typeof brandAutofillMarkup),'undefined');
 console.log('Chromium: debounce/blur singleflight, edit protection, candidate escaping/adoption, free-model unavailable, URL/market/backend/auth isolation, GET polling/cache, no busy retry, no render/restore/direct-browser calls passed.');
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
