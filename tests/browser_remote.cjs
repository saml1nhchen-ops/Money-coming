/* Synthetic HTTPS team-page integration. No real login, provider key or model request. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname,'..');
const ORIGIN = 'https://saml1nhchen-ops.github.io';
const BACKEND = 'https://team-backend.example.test';
const PASSWORD = 'synthetic-team-password';
const TOKEN = 'synthetic-team-session';
const runId = '00000000-0000-4000-8000-000000000001';
(async () => {
  const executablePath = process.env.BROWSER_EXECUTABLE || (fs.existsSync(chromium.executablePath()) ? undefined : '/usr/bin/chromium');
  const browser = await chromium.launch({headless:true,executablePath,args:['--no-sandbox']});
  try {
    const context = await browser.newContext({acceptDownloads:true});
    const page = await context.newPage(); page.setDefaultTimeout(8000);
    const errors = [], requests = [], vendorRequests = [];
    page.on('pageerror',e => errors.push(e.message));
    let ready = false, unknownBudget = false, remaining = 126, unauthorized = false, offline = false;
    let started = false, runMarket = 'CN';
    const profiles = [{id:'p',name:'GPT fixed',model:'gpt-fixed-test',manufacturer:'OpenAI',markets:['CN','US'],protocol:'chat',search:false},
      {id:'q',name:'Gemini fixed',model:'gemini-fixed-test',manufacturer:'Google',markets:['CN','US'],protocol:'chat',search:false}];
    const fixture = JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/report-job.json'),'utf8'));
    function job() { const j = structuredClone(fixture); j.id = runId; j.config.market = runMarket; j.browser_direct = false; return j; }
    await page.route('**/*',async route => {
      const u = new URL(route.request().url());
      if (u.origin !== ORIGIN) { vendorRequests.push(u.origin); return route.abort(); }
      if (u.pathname.startsWith('/api/')) return route.fulfill({status:404,contentType:'application/json',body:'{}'});
      const name = u.pathname.split('/dist/')[1] || 'index.html';
      const file = path.join(root,'dist',name);
      return route.fulfill({body:fs.readFileSync(file),contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html'});
    });
    await page.route(BACKEND+'/**',async route => {
      const r = route.request(), u = new URL(r.url()), body = r.postDataJSON();
      requests.push({url:r.url(),method:r.method(),headers:r.headers(),body});
      if (offline) return route.abort();
      let status = 200, data;
      if (u.pathname === '/api/workspace/login') {
        assert.deepEqual(body,{password:PASSWORD});
        data = {token:TOKEN,expires_at:new Date(Date.now()+3600000).toISOString(),workspace:{mode:'shared_team',shared_reports:true}};
      } else {
        assert.equal(r.headers().authorization,'Bearer '+TOKEN);
        if (unauthorized) { status = 401; data = {error:'unauthorized',code:'unauthorized'}; }
        else if (u.pathname === '/api/workspace/logout') data = {ok:true};
        else if (u.pathname === '/api/geo/state') data = {runner:{configured:ready,profiles,fetched_at:'2026-10-21T00:00:00Z'},busy:false,
          runs:started?[{id:runId,created_at:fixture.created_at,status:'partial',market:runMarket,brand:'Northstar'}]:[],
          remote:{mode:'shared_team',shared_reports:true,ready,reason:ready?null:'missing_bai_key',limits:{count:30,max_models:2,repeats:1},
            ...(unknownBudget?{}:{budget:{date:'2026-10-21',limit:126,reserved:126-remaining,remaining}})}};
        else if (u.pathname === '/api/geo/start') { assert(!('prompts' in body)); assert.equal(body.count,30); assert.equal(body.repeats,1); assert.equal(body.providers.length,2); assert(body.providers.includes(body.generator)); runMarket = body.market; started = true; status = 202; data = job(); }
        else if (u.pathname === '/api/geo/plan') { assert(!('prompts' in body)); data={questions:30,manufacturers:2,answer_calls:60,generation_calls:3,maximum_calls:63,families:{discovery:21,brand:5,comparison:4}}; }
        else if (u.pathname === '/api/geo/run') data = job();
        else if (u.pathname === '/api/geo/export') data = {...job(),raw_evidence:{'sample-raw.json':{synthetic:true}}};
        else if (u.pathname === '/api/geo/stop') data = {status:'stop_requested'};
        else { status = 404; data = {error:'not_found',code:'not_found'}; }
      }
      return route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
    });
    await page.goto(ORIGIN+'/Money-coming/dist/team.html?draft_brand=Northstar&draft_market=CN&draft_website=https%3A%2F%2Fnorthstar.example%2F&draft_context=Public+skin+care+background');
    await page.locator('#remote-connection').waitFor();
    assert.equal(await page.evaluate(()=>window.SIGNAL_GEO_MODE),'team');
    assert.equal(await page.evaluate(()=>typeof window.browserBaiResearchBroker),'undefined');
    assert.equal(await page.evaluate(()=>typeof window.BrowserResearchEngine),'undefined');
    assert.equal(await page.locator('#ru-brand').inputValue(),'Northstar');
    assert.equal(await page.evaluate(()=>geoMarket),'CN'); assert(!page.url().includes('draft_'));
    assert.equal(await page.locator('a[href*="127.0.0.1"]').count(),0);
    assert.equal(await page.locator('#bai-key').count(),0);
    await page.locator('#remote-backend-url').fill('http://insecure.example');
    await page.locator('#remote-password').fill(PASSWORD);
    await page.locator('#remote-connection form').evaluate(f=>f.dispatchEvent(new Event('submit',{cancelable:true})));
    assert.equal(requests.length,0);
    await page.locator('#remote-backend-url').fill(BACKEND); await page.locator('#remote-password').fill(PASSWORD);
    await page.getByRole('button',{name:'连接并登录',exact:true}).click();
    await page.getByText('团队已登录 · 暂不能开始分析',{exact:true}).waitFor();
    assert.deepEqual(requests.map(r=>new URL(r.url).pathname),['/api/workspace/login','/api/geo/state']);
    assert.equal(await page.locator('#remote-password').count(),0);
    await page.getByRole('button',{name:'下一步：选择 AI',exact:false}).click();
    await page.locator('.ru-model').nth(0).click(); await page.locator('.ru-model').nth(1).click();
    assert(await page.getByRole('button',{name:'开始分析',exact:false}).isDisabled());
    ready = true; unknownBudget = true; await page.getByRole('button',{name:'刷新后台状态',exact:true}).click();
    assert(await page.getByRole('button',{name:'开始分析',exact:false}).isDisabled());
    unknownBudget = false; remaining = 0; await page.getByRole('button',{name:'刷新后台状态',exact:true}).click();
    assert(await page.getByRole('button',{name:'开始分析',exact:false}).isDisabled());
    remaining = 126; await page.getByRole('button',{name:'刷新后台状态',exact:true}).click();
    assert.equal(await page.locator('#geo-generator option').count(),2);
    await page.getByRole('button',{name:'开始分析',exact:false}).click();
    await page.locator('.rq-card').first().waitFor();
    assert.equal(requests.find(r=>new URL(r.url).pathname==='/api/geo/start').body.market,'CN');
    assert.equal(await page.locator('.rq-card').count(),fixture.prompts.length);
    await page.locator('.rq-card').first().click(); await page.locator('#overlay [role=dialog]').waitFor();
    assert.equal(await page.locator('#overlay .rq-model').count(),2); await page.evaluate(()=>closeOverlay());
    assert.equal(await page.locator('[onclick="geoResume()"]').count(),0);
    const downloadPromise = page.waitForEvent('download'); await page.getByRole('button',{name:'↓ 下载分析证据',exact:true}).click();
    const exported = JSON.parse(fs.readFileSync(await (await downloadPromise).path(),'utf8')); assert(exported.raw_evidence);
    assert(!JSON.stringify(exported).includes(TOKEN)); assert(!JSON.stringify(exported).includes(PASSWORD));
    const exportRequest = requests.find(r=>new URL(r.url).pathname==='/api/geo/export'); assert.equal(exportRequest.headers.authorization,'Bearer '+TOKEN); assert(!exportRequest.url.includes(TOKEN));
    await page.getByRole('button',{name:'美国',exact:true}).click(); assert.equal(await page.evaluate(()=>geoMarket),'US');
    assert.equal(await page.locator('#ru-brand').inputValue(),'');
    await page.locator('#ru-brand').fill('Another brand'); await page.locator('#geo-website').fill('https://another.example/');
    await page.getByRole('button',{name:'下一步：选择 AI',exact:false}).click();
    await page.locator('.ru-model').nth(0).click(); await page.locator('.ru-model').nth(1).click();
    assert.equal(await page.evaluate(()=>geoPayload().market),'US');
    offline = true; await page.getByRole('button',{name:'刷新后台状态',exact:true}).click();
    await page.getByText('后台连接失败',{exact:true}).waitFor(); assert(await page.getByRole('button',{name:'开始分析',exact:false}).isDisabled());
    offline = false; unauthorized = true; await page.getByRole('button',{name:'刷新后台状态',exact:true}).click();
    await page.getByRole('button',{name:'连接并登录',exact:true}).waitFor(); assert.equal(await page.evaluate(()=>geoToken),''); assert.equal(await page.evaluate(()=>geoActive),null);
    const storage = await page.evaluate(()=>JSON.stringify({...localStorage})); assert(storage.includes(BACKEND)); assert(!storage.includes(TOKEN)); assert(!storage.includes(PASSWORD)); assert(!storage.includes('signal-research-drafts'));
    await page.reload(); await page.locator('#remote-password').waitFor(); assert.equal(await page.locator('#remote-backend-url').inputValue(),BACKEND); assert.equal(await page.locator('#remote-password').inputValue(),'');
    await page.goto(ORIGIN+'/Money-coming/dist/'); await page.waitForFunction(()=>page==='overview');
    assert.equal(await page.evaluate(()=>window.SIGNAL_GEO_MODE),undefined);
    assert.equal(await page.evaluate(()=>typeof window.browserBaiResearchBroker),'object');
    assert.equal(await page.locator('#remote-connection').count(),0);
    assert.deepEqual(vendorRequests,[]); assert.deepEqual(errors,[]);
    console.log('Synthetic team browser: isolated entry, public draft, login/state only, CN/US, readiness/budget/offline/401 gates, 30-question request shape, cards/dialog/export and memory-only authentication passed.');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1)});
