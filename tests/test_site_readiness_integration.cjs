/* Migrated website-only path: real browser/gateway/stores/Protego/Trafilatura, no model execution. */
const {chromium}=require('playwright'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'readiness-integration-'));
 const child=spawn(process.env.SIGNAL_TEST_PYTHON||'/tmp/geo-audit-venv/bin/python',['tests/diagnostic_fixture_server.py',root],{env:{...process.env,PYTHONPATH:path.resolve('tools')},stdio:['ignore','pipe','pipe']});
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
    requests.push({path:u.pathname,method:req.method(),body:req.postData()?req.postDataJSON():null});
    const response=await route.fetch({url:`http://127.0.0.1:${connection.port}${u.pathname}${u.search}`,headers:{...req.headers(),host:'public.example',origin:'https://saml1nhchen-ops.github.io'}});
    return route.fulfill({response});
   }
   return route.abort();
  });
  await page.addInitScript(token=>{if(window.top!==window)return;localStorage.setItem('signal-research-market','US');localStorage.setItem('signal-analysis-backend','https://backend.example');localStorage.setItem('signal-team-auth:v1:'+encodeURIComponent('https://backend.example'),JSON.stringify({version:1,backend_url:'https://backend.example',token,expires_at:new Date(Date.now()+3600000).toISOString(),remembered:true}));},connection.token);
  await page.goto('https://saml1nhchen-ops.github.io/Money-coming/dist/team.html#/w/demo/research');
  await page.locator('#audit-url').waitFor();await page.waitForFunction(()=>remoteDiagnosticsContext().authenticated && remoteDiagnosticsContext().supported);assert.equal(requests.filter(v=>v.path.includes('/audit')).length,0);
  assert.equal(await page.locator('#ru-brand,#ru-products,#ru-competitors,.ru-model').count(),0);
  await page.locator('aside a').filter({hasText:'客户与项目'}).click();await page.locator('#workflow-client-name').fill('Website-only customer');await page.locator('#workflow-client-form button').click();await page.locator('#workflow-project-client option').filter({hasText:'Website-only customer'}).waitFor({state:'attached'});await page.locator('#workflow-project-client').selectOption({label:'Website-only customer'});await page.locator('#workflow-project-name').fill('Website-only project');await page.locator('#workflow-project-form button').click();await page.getByText('Website-only customer / Website-only project',{exact:true}).waitFor();
  async function download(kind){const wait=page.waitForEvent('download');await page.locator(`[data-wf="${kind}"]`).click();return fs.readFileSync(await(await wait).path(),'utf8')}
  async function preview(url){await page.locator('aside a').filter({hasText:'从官网生成诊断'}).click();await page.locator('#audit-url').fill(url);await page.locator('#audit-url-form button').click();await page.locator('#audit-brand').waitFor({timeout:60000});}
  async function websiteStart(){await page.locator('[data-sr="confirm"]').click();await page.locator('input[name="workflow-mode"][value="website"]').check();await page.locator('[data-wf="start"]').click();await page.locator('[data-wf="json"]').waitFor({timeout:60000});}
  await preview('https://acme.example/');assert.equal(await page.locator('#audit-brand').inputValue(),'Acme Tea');assert.match(await page.locator('#audit-products').inputValue(),/Green Tea/);assert.match(await page.locator('#audit-competitors').inputValue(),/Rival Tea/);
  await page.locator('#audit-brand').fill('Manual Acme');await page.locator('#audit-products').fill('Manual Product');await websiteStart();
  const full=JSON.parse(await download('json'));assert.equal(full.config.confirmed.brand.name,'Manual Acme');assert.deepEqual(full.config.confirmed.brand.evidence_ids,[]);assert.equal(full.bundle.run_manifest.brand,'Manual Acme');assert.equal(full.plan.maximum_calls,0);assert.equal(full.job_id,null);assert.ok(full.bundle.evidence.length);assert.equal(full.bundle.answers.length,0);assert.equal(full.website_usage.model_calls,0);
  const agents=full.bundle.source_snapshot.robots.agents;assert.ok(agents.some(a=>a.user_agent==='GPTBot'&&a.decision==='disallowed'));assert.ok(agents.some(a=>a.user_agent==='OAI-SearchBot'&&a.decision==='allowed'));
  const html=await download('html');assert.match(html,/Manual Acme/);assert.match(html,/完整保存快照与原始证据/);assert.match(html,/geo-readiness-v1/);assert.match(html,/v0.1/);
  await preview('https://failed.example/');assert.equal(await page.locator('#audit-brand').inputValue(),'');await websiteStart();
  const failed=JSON.parse(await download('json'));assert.equal(failed.config.confirmed.brand.name,'');assert.equal(failed.summary.total,null);assert.equal(failed.plan.maximum_calls,0);assert.equal(failed.job_id,null);assert.equal(failed.website_usage.model_calls,0);assert.ok(failed.bundle.rules.some(r=>r.status==='unknown'));assert.match(await download('html'),/完整保存快照与原始证据/);
  assert.equal(fs.existsSync(path.join(root,'runtime/budget.json')),false,'website-only never reserves paid calls');assert.equal(requests.filter(v=>/enrich|models|\/start|\/sample|\/plan/.test(v.path)).length,0);assert.equal(requests.filter(v=>v.path==='/api/geo/audit-confirm').length,0,'no isolated website-final endpoint');assert(requests.filter(v=>v.path==='/api/diagnostics'&&v.method==='POST').every(v=>v.body.mode==='website'&&v.body.profile_ids.length===0));assert.deepEqual(errors,[]);console.log('PASS migrated website-only real Chromium/gateway/Protego/Trafilatura: manual edit evidence protection, robots allow/disallow, success and whole-site failure v0.1 exports; zero model jobs/reservations.');
 }finally{if(browser)await browser.close();child.kill('SIGTERM');await new Promise(resolve=>{if(child.exitCode!==null){resolve();return;}child.once('exit',resolve);setTimeout(()=>{child.kill('SIGKILL');resolve()},5000).unref()});fs.rmSync(root,{recursive:true,force:true});}
})().catch(e=>{console.error(e.message);process.exitCode=1});
