/* Real browser -> real gateway -> real offline Protego/Trafilatura. No external HTTP. */
const {chromium}=require('playwright'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'readiness-integration-'));
 const child=spawn(process.env.SIGNAL_TEST_PYTHON||'python3',['tests/site_readiness_fixture_server.py',root],{stdio:['ignore','pipe','pipe']});
 let browser;let stderr='';child.stderr.on('data',d=>stderr+=d);
 try{
  const connection=await new Promise((resolve,reject)=>{let data='';const timer=setTimeout(()=>reject(Error('fixture startup timeout')),15000);child.stdout.on('data',d=>{data+=d;if(data.includes('\n')){clearTimeout(timer);try{resolve(JSON.parse(data.split('\n')[0]))}catch{reject(Error('invalid fixture startup'))}}});child.on('exit',()=>reject(Error('fixture exited')))});
  browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
  const page=await browser.newPage(),requests=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
   const req=route.request(),u=new URL(req.url());
   if(u.hostname==='saml1nhchen-ops.github.io'){
    const name=path.basename(u.pathname),file=path.join('dist',name);
    if(/^[\w.-]+$/.test(name)&&fs.existsSync(file))return route.fulfill({body:fs.readFileSync(file),contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html'});
   }
   if(u.hostname==='backend.example'){
    requests.push(u.pathname);
    const response=await route.fetch({url:`http://127.0.0.1:${connection.port}${u.pathname}${u.search}`,headers:{...req.headers(),host:'public.example',origin:'https://saml1nhchen-ops.github.io'}});
    return route.fulfill({response});
   }
   return route.abort();
  });
  await page.addInitScript(token=>{localStorage.setItem('signal-research-market','US');localStorage.setItem('signal-analysis-backend','https://backend.example');localStorage.setItem('signal-team-auth:v1:'+encodeURIComponent('https://backend.example'),JSON.stringify({version:1,backend_url:'https://backend.example',token,expires_at:new Date(Date.now()+3600000).toISOString(),remembered:true}));},connection.token);
  await page.goto('https://saml1nhchen-ops.github.io/Money-coming/dist/team.html#/w/demo/research');
  await page.locator('#audit-url').waitFor();assert.equal(requests.filter(v=>v.includes('/audit')).length,0);
  assert.equal(await page.locator('#ru-brand,#ru-products,#ru-competitors,.ru-model').count(),0);
  async function download(kind){const wait=page.waitForEvent('download');await page.locator(`[data-sr="${kind}"]`).click();return fs.readFileSync(await(await wait).path(),'utf8')}
  await page.locator('#audit-url').fill('https://acme.example/');await page.locator('#audit-url-form button').click();await page.locator('#audit-brand').waitFor({timeout:30000});
  assert.equal(await page.locator('#audit-brand').inputValue(),'Acme Tea');assert.match(await page.locator('#audit-products').inputValue(),/Green Tea/);assert.match(await page.locator('#audit-competitors').inputValue(),/Rival Tea/);
  await page.locator('#audit-brand').fill('Manual Acme');await page.locator('#audit-products').fill('Manual Product');await page.locator('[data-sr="confirm"]').click();await page.locator('[data-sr="json"]').waitFor({timeout:30000});
  const full=JSON.parse(await download('json'));assert.equal(full.confirmed.brand.name,'Manual Acme');assert.deepEqual(full.confirmed.brand.evidence_ids,[]);assert.equal(full.report.target.brand,'Manual Acme');assert.equal(full.usage.model_calls,0);assert.equal(full.report.model_analysis.status,'not_tested');assert.ok(full.report.evidence.length);
  const agents=full.report.robots.agents;assert.ok(agents.some(a=>a.user_agent==='GPTBot'&&a.decision==='disallowed'));assert.ok(agents.some(a=>a.user_agent==='OAI-SearchBot'&&a.decision==='allowed'));
  const html=await download('html');assert.match(html,/Manual Acme/);assert.match(html,/完整审计数据/);assert.match(html,/geo-readiness-v1/);
  await page.locator('[data-sr="edit"]').click();await page.locator('[data-sr="url"]').click();await page.locator('#audit-url').fill('https://failed.example/');await page.locator('#audit-url-form button').click();await page.locator('#audit-brand').waitFor({timeout:30000});assert.equal(await page.locator('#audit-brand').inputValue(),'');await page.locator('[data-sr="confirm"]').click();await page.locator('[data-sr="json"]').waitFor({timeout:30000});
  const failed=JSON.parse(await download('json'));assert.equal(failed.report.target.brand,'');assert.equal(failed.report.summary.score,null);assert.equal(failed.report.summary.partial_score,null);assert.equal(failed.usage.model_calls,0);assert.match(await download('html'),/geo-readiness-v1/);
  assert.equal(fs.existsSync(path.join(root,'unused-budget')),false);assert.equal(requests.filter(v=>/enrich|models|\/start|\/sample|\/plan/.test(v)).length,0);assert.deepEqual(errors,[]);console.log('PASS real Chromium/gateway/Protego/Trafilatura success and failure exports; zero model calls');
 }finally{if(browser)await browser.close();child.kill('SIGTERM');await new Promise(resolve=>{child.once('exit',resolve);setTimeout(()=>{child.kill('SIGKILL');resolve()},5000).unref()});fs.rmSync(root,{recursive:true,force:true});}
})().catch(e=>{console.error(e.message);process.exitCode=1});
