// Synthetic credentials and intercepted responses only; no paid API calls.
const {chromium}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 const context=await browser.newContext(),page=await context.newPage();
 const origin='https://saml1nhchen-ops.github.io',device='signal-bai-device-connection-v1',fake='SYNTHETIC-DEVICE-TEST';let models=0,chat=0,reject=false,hold=false,release;
 await context.route(origin+'/**',async route=>{const u=new URL(route.request().url()),name=u.pathname.split('/dist/')[1]||'index.html';if(u.pathname.includes('/api/'))return route.fulfill({status:404,body:'{}'});return route.fulfill({body:fs.readFileSync(path.join(__dirname,'../dist',name)),contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html'});});
 await context.route('https://api.b.ai/**',async route=>{if(!route.request().url().endsWith('/models')){chat++;return route.fulfill({status:500,body:'{}'});}models++;if(hold)await new Promise(resolve=>release=resolve);try{await route.fulfill({status:reject?401:200,contentType:'application/json',body:JSON.stringify(reject?{error:{code:'api_error'}}:{data:[{id:'gpt-fixed-test'}]})});}catch{}});
 const open=async p=>{await p.goto(origin+'/Money-coming/dist/#/w/demo/research');await p.waitForFunction(()=>typeof browserResearchConnect==='function');};
 const connect=async remember=>{await page.evaluate(()=>browserResearchConnect());await page.locator('#bai-key').fill(fake);await page.locator('#bai-remember').setChecked(remember);await page.locator('#bai-connect').click();await page.waitForFunction(()=>geoState.runner.configured);};
 await open(page);assert.equal(models,0);await page.evaluate(()=>browserResearchConnect());assert.equal(await page.locator('#bai-remember').isChecked(),false);await page.evaluate(()=>closeOverlay());
 await connect(false);assert.equal(await page.evaluate(k=>localStorage.getItem(k),device),null);await page.reload();await page.waitForFunction(()=>typeof browserResearchConnect==='function');assert.equal(await page.evaluate(()=>geoState.runner.configured),false);assert.equal(models,1);
 await connect(true);assert.equal(await page.evaluate(k=>JSON.parse(localStorage.getItem(k)).key,device),fake);const before=models;await page.reload();await page.waitForFunction(()=>geoState.runner.configured);assert.equal(models,before+1);assert.equal(chat,0);assert(!page.url().includes(fake));assert(!(await page.locator('body').innerText()).includes(fake));
 // A second tab restores without disconnecting the already connected first tab.
 const second=await context.newPage();await open(second);await second.waitForFunction(()=>geoState.runner.configured);await page.waitForTimeout(50);assert.equal(await page.evaluate(()=>geoState.runner.configured),true);
 // Explicit logout forgets this device and disconnects all open tabs.
 await second.evaluate(()=>browserResearchClear());await page.waitForFunction(()=>!geoState.runner.configured);assert.equal(await second.evaluate(k=>localStorage.getItem(k),device),null);await second.close();
 // A failed auto-connect is attempted once and forgotten, never starting chat.
 await connect(true);reject=true;const count=models;await page.reload();await page.waitForFunction(()=>geoState.runner.configured===false&&document.body.innerText.includes('自动连接未成功'));assert.equal(models,count+1);assert.equal(await page.evaluate(k=>localStorage.getItem(k),device),null);reject=false;
 // Logout while restore is in flight cannot resurrect the key or connection.
 await connect(true);hold=true;await page.reload();await page.waitForFunction(()=>geoState.busy);await page.evaluate(()=>browserResearchClear());release?.();hold=false;await page.waitForTimeout(80);assert.equal(await page.evaluate(()=>geoState.runner.configured),false);assert.equal(await page.evaluate(k=>localStorage.getItem(k),device),null);
 // Browsers that block local storage can still use a memory-only connection.
 const blocked=await context.newPage();await blocked.addInitScript(()=>{Storage.prototype.setItem=function(){throw new DOMException('blocked','SecurityError')};});await open(blocked);await blocked.evaluate(()=>browserResearchConnect());await blocked.locator('#bai-key').fill(fake);await blocked.locator('#bai-remember').check();await blocked.locator('#bai-connect').click();await blocked.waitForFunction(()=>geoState.runner.configured);assert.equal(await blocked.evaluate(k=>localStorage.getItem(k),device),null);assert.equal(chat,0);
 await browser.close();console.log('Device connection passed: opt-in only, reload restore, no paid calls, multi-tab continuity/logout, failed restore, stale response, blocked storage.');
})().catch(e=>{console.error(e);process.exit(1)});
