const {chromium}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});try{
 const p=await browser.newPage(),requests=[],errors=[];p.on('pageerror',e=>errors.push(e.message));
 await p.route('**/*',async route=>{const u=new URL(route.request().url());if(u.hostname==='fixture.example'){
 const name=u.pathname==='/'?'team.html':path.basename(u.pathname);if(!/^[\w.-]+$/.test(name))return route.abort();const file=path.join('dist',name);if(fs.existsSync(file))return route.fulfill({body:fs.readFileSync(file),contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html'});
 } requests.push({url:u.href,method:route.request().method(),body:route.request().postDataJSON()});
 const json=data=>route.fulfill({json:data});
 if(u.pathname==='/api/geo/state')return json({runner:{profiles:[]},runs:[],remote:{ready:false,reason:'required_models_unavailable',budget:{remaining:0}}});
 if(u.pathname==='/api/geo/enrich')return json({id:'12345678-1234-4234-8234-123456789012',status:'finished',website:{status:'fetched'},brand:{name:'Cremo',kind:'brand',basis:'website_metadata',source_field:'og:site_name'},products:[{name:'Shave Cream',kind:'product',basis:'website_text'}],competitors:[],model_suggestion:{status:'free_model_unavailable'},billing:{model_calls:0}});
 return route.abort();});
 await p.addInitScript(()=>{localStorage.setItem('signal-analysis-backend','https://backend.example');localStorage.setItem('signal-team-auth:v1:'+encodeURIComponent('https://backend.example'),JSON.stringify({version:1,backend_url:'https://backend.example',token:'mock-session-token-123456',expires_at:new Date(Date.now()+3600000).toISOString(),remembered:true}));});
 await p.goto('https://fixture.example/team.html#/w/demo/research');await p.locator('#geo-website').waitFor();await p.waitForTimeout(800);
 assert.equal(requests.filter(r=>r.url.includes('/enrich')).length,0,'saved login has no model trigger');
 await p.locator('#geo-website').fill('https://cremocompany.com');await p.waitForTimeout(800);await p.locator('#ru-brand').focus();
 assert.equal(requests.filter(r=>r.url.includes('/enrich')).length,1);assert.deepEqual(Object.keys(requests.find(r=>r.url.includes('/enrich')).body).sort(),['market','request_id','website']);
 assert.equal(await p.locator('#ru-brand').inputValue(),'Cremo');assert.equal(await p.locator('#ru-products').inputValue(),'Shave Cream');
 assert.match(await p.locator('#brand-autofill').textContent(),/尚未提供可验证的免费/);
 assert.equal(await p.evaluate(()=>window.remoteEnrichmentContext().token),undefined);
 assert.equal(requests.filter(r=>/start|sample/.test(r.url)).length,0);
 await p.locator('button[onclick="researchNext(2)"]').last().click();assert.match(await p.locator('#view').textContent(),/02 \/ 分析范围/);
 assert.equal(requests.filter(r=>/start|sample/.test(r.url)).length,0);assert.deepEqual(errors,[]);
 console.log('Actual team.html Chromium: private saved-login restore, zero-budget/no-free-model website autofill, payload allowlist, no auto research, explicit next-step confirmation passed.');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
