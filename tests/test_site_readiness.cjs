/* Real team entry, synthetic HTTPS backend only. Never contacts a website or a model. */
const {chromium}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const ID='12345678-1234-4234-8234-123456789012';
function fixture(outcome='readable'){
 const e={id:'e1',resource_id:'seed',url:'https://brand.example/',captured_at:'2026-10-22T12:00:00Z',http_status:outcome==='limited'?429:200,content_type:'text/html',source_field:'og:site_name',excerpt:'Brand source <img src=x onerror=alert(1)> and <script>alert(1)</script>',redirects:[]};
 const audit={schema_version:'geo-readiness-v1',id:ID,revision:1,request_id:ID,market:'US',status:'awaiting_confirmation',phase:'confirmation',stage:'confirmation',created_at:e.captured_at,website:{requested_url:'https://brand.example/',final_url:'https://brand.example/',origin:'https://brand.example'},access:{outcome,http_status:e.http_status,readable_characters:outcome==='readable'?2345:0,redirects:[],checks:[{id:'tls',status:'unknown',message:'证据不足'}],findings:[]},candidates:{brand:outcome==='readable'?{id:'b1',name:'Brand',aliases:[],basis:'website_metadata',kind:'brand',source_url:e.url,source_field:'og:site_name',evidence_ids:['e1']}:null,products:[],competitors:[]},evidence:[e],confirmed:null,report:null,warnings:[],reused:false,usage:{http_requests:1,model_calls:0}};
 return audit;
}
function reported(a,confirmed){
 const r=structuredClone(a);r.confirmed=confirmed;r.phase='done';r.status='partial';r.stage='done';
 r.report={schema_version:'geo-readiness-v1',rule_version:'v1-test',generated_at:a.created_at,target:{url:a.website.final_url,market:a.market,brand:confirmed.brand.name},scope:{kind:'finite_website_readiness',resources:[{url:a.website.final_url,status:'fetched'},{url:'https://brand.example/llms.txt',status:'unknown'}],limitations:['本次只检查有限页面'],model_calls:0},summary:{score:null,partial_score:100,coverage_percent:60,known_weight:60,total_weight:100,passed:4,failed:0,unknown:3,not_applicable:1,conclusions:['证据不足，部分资源不可达']},sections:[{id:'readability',title:'可读文件与内容',checks:[{id:'llms',title:'llms.txt 读取',status:'unknown',weight:0,reason:'请求超时，无法判断是否存在',evidence_ids:['e1'],action:'稍后明确复测',methodology:'只读同源资源'}]},{id:'trust',title:'可信度线索',checks:[{id:'identity',title:'官网身份线索',status:'unknown',weight:10,reason:'用户提供品牌不使网页身份检查通过',evidence_ids:['e1'],methodology:'官网可观察线索'}]}],robots:{resource_id:'robots',fetch_status:'unknown',agents:[{user_agent:'OAI-SearchBot',purpose:'search',path:'/',decision:'unknown',parser:'protego',evidence_ids:['e1'],notes:['获取失败，不是明确禁止']},{user_agent:'GPTBot',purpose:'training',path:'/',decision:'disallowed',parser:'protego',evidence_ids:['e1'],notes:['训练禁用不等于无法推荐']},{user_agent:'Googlebot',purpose:'search',path:'/',decision:'not_found',parser:'protego',evidence_ids:[],notes:['未发现声明，不是明确允许']}]},evidence:a.evidence,recommendations:[{id:'r1',priority:'P1',check_ids:['llms'],evidence_ids:['e1'],action:'补充可读取证据',retest:'重新检测并核对超时资源'}],model_analysis:{status:'not_tested',binding:{audit_id:a.id,url:a.website.final_url,market:a.market,brand_aliases:[confirmed.brand.name]},job_id:null,report:null}};return r;
}
(async()=>{const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});try{
 const p=await browser.newPage(),requests=[],errors=[];let latest=fixture(),pendingPreview=null,delay=false,enableModels=false,lastModel=null;
 p.on('pageerror',e=>errors.push(e.message));
 await p.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url());
  if(u.hostname==='fixture.example'){
   const name=path.basename(u.pathname),file=path.join('dist',name);
   if(/^[\w.-]+$/.test(name)&&fs.existsSync(file))return route.fulfill({body:fs.readFileSync(file),contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html'});
   return route.abort();
  }
  const body=req.postData()?req.postDataJSON():undefined;requests.push({url:u.href,method:req.method(),body});
  const json=data=>route.fulfill({json:data});
  if(u.pathname==='/api/geo/state')return json({runner:{profiles:enableModels?[{id:'mock-google',name:'Synthetic Google',model:'synthetic-text',manufacturer:'Google',markets:['US','CN'],protocol:'chat'}]:[]},runs:[],remote:{ready:enableModels,reason:'missing_bai_key',budget:{remaining:enableModels?100:0}}});
  if(u.pathname==='/api/geo/start'){lastModel={id:'22345678-1234-4234-8234-123456789012',status:'finished',stage:'report',created_at:'2026-10-22T12:00:00Z',config:body,prompts:[{text:'Synthetic question',family:'discovery'}],samples:[{id:'s1',question_index:0,provider:'mock-google',status:'complete',answer:'Synthetic answer'}],report:null,plan:{answer_calls:30}};return json(lastModel)}
  if(u.pathname==='/api/geo/run')return json(lastModel);
  if(u.pathname==='/api/geo/export')return json({...lastModel,raw_evidence:{synthetic:'No real model called'}});
  if(u.pathname==='/api/geo/audit'){
   if(req.method()==='POST'){
    if(delay){pendingPreview=route;return;}
    latest=fixture(body.website.includes('limited')?'limited':body.website.includes('challenge')?'challenge':'readable');latest.market=body.market;
    latest.website={requested_url:body.website,final_url:body.website,origin:new URL(body.website).origin};
    return json({id:ID,status:'queued',phase:'preview'});
   }
   return json(latest);
  }
  if(u.pathname==='/api/geo/audit-confirm'){assert(body.confirmed.brand.name===''&&body.confirmed.brand.aliases.length===0 || body.confirmed.brand.aliases.length>0,'backend contract requires nonempty aliases for named brands');latest=reported(latest,body.confirmed);return json({...latest,status:'running',phase:'report',stage:'content',report:null});}
  if(u.pathname==='/api/geo/audit-export')return json(latest);
  return route.abort();
 });
 await p.addInitScript(()=>{if(window.top!==window)return;localStorage.setItem('signal-research-market','US');localStorage.setItem('signal-analysis-backend','https://backend.example');localStorage.setItem('signal-team-auth:v1:'+encodeURIComponent('https://backend.example'),JSON.stringify({version:1,backend_url:'https://backend.example',token:'fixture-session-token-123',expires_at:new Date(Date.now()+3600000).toISOString(),remembered:true}));});
 await p.goto('https://fixture.example/team.html#/w/demo/research');await p.locator('#audit-url').waitFor();await p.waitForTimeout(100);
 assert.match(await p.locator('.sr-steps [aria-current="step"]').textContent(),/1输入官网/);
 assert.equal(await p.locator('#ru-brand,#ru-products,#ru-competitors,.ru-model').count(),0,'URL-only first step');
 assert.equal(requests.filter(r=>/audit/.test(r.url)).length,0,'restore/render never POST');
 await p.screenshot({path:'/tmp/site-readiness-step1.png',fullPage:true});
 const mobile=await browser.newPage({viewport:{width:390,height:844}});await mobile.route('**/*',route=>{const u=new URL(route.request().url()),file=path.join('dist',path.basename(u.pathname));return u.hostname==='fixture.example'&&fs.existsSync(file)?route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'}):route.abort()});await mobile.goto('https://fixture.example/team.html#/w/demo/research');await mobile.locator('#audit-url').waitFor();await mobile.screenshot({path:'/tmp/site-readiness-mobile.png',fullPage:true});await mobile.close();
 assert.doesNotMatch(await p.locator('#site-readiness').textContent(),/30 道|B\.AI|模型额度不足|暂不能开始分析/);
 await p.locator('#audit-url').fill('http://127.0.0.1');await p.locator('#audit-url-form button').click();assert.equal(requests.filter(r=>/audit/.test(r.url)).length,0,'unsafe URL does not fetch');
 await p.locator('#audit-url').fill('brand.example');await p.waitForTimeout(750);assert.equal(requests.filter(r=>/audit/.test(r.url)).length,0,'input alone never submits');
 await p.locator('#audit-url-form button').click();await p.locator('#audit-brand').waitFor();
 assert.match(await p.locator('.sr-steps [aria-current="step"]').textContent(),/2确认信息/);assert.equal(await p.locator('#audit-brand').inputValue(),'Brand');assert.equal(await p.locator('#audit-competitors').inputValue(),'');await p.screenshot({path:'/tmp/site-readiness-step2.png',fullPage:true});
 await p.getByText('查看自动识别来源与原文',{exact:true}).click();assert.match(await p.locator('#site-readiness').textContent(),/Brand source/);assert.equal(await p.locator('#site-readiness img,#site-readiness script').count(),0);
 await p.locator('#audit-brand').fill('User Brand');assert.equal(await p.locator('label').filter({has:p.locator('#audit-brand')}).locator('small').count(),0,'no provenance process badges in the form');
 await p.evaluate(()=>render());assert.equal(await p.locator('#audit-brand').inputValue(),'User Brand','render keeps editing');
 await p.locator('[data-sr="confirm"]').click();await p.locator('[data-sr="html"]').waitFor();
 await p.screenshot({path:'/tmp/site-readiness-step3.png',fullPage:true});
 assert.match(await p.locator('.sr-steps [aria-current="step"]').textContent(),/3网站报告/);assert.match(await p.locator('#site-readiness').textContent(),/robots.txt 状态：未知/);
 const confirmation=requests.find(r=>r.url.includes('audit-confirm')).body;
 assert.deepEqual(confirmation.confirmed.products,[]);assert.deepEqual(confirmation.confirmed.competitors,[]);
 assert.equal(confirmation.confirmed.brand.name,'User Brand');assert.deepEqual(confirmation.confirmed.brand.aliases,['User Brand']);assert.match(await p.locator('#site-readiness').textContent(),/证据不足，暂无完整分数/);assert.match(await p.locator('#site-readiness').textContent(),/仅覆盖 60%/);assert.match(await p.locator('#site-readiness').textContent(),/未发现声明不同于明确允许/);
 assert.equal(requests.filter(r=>/enrich|models|\/start|\/sample/.test(r.url)).length,0,'zero supplier and research calls');
 for(const format of ['html','json']){
   const download=p.waitForEvent('download');await p.locator('[data-sr="'+format+'"]').click();const d=await download,content=fs.readFileSync(await d.path(),'utf8');
   if(format==='html'){
    assert(content.includes('完整审计数据'));assert(content.includes('请求超时，无法判断是否存在'));assert(content.includes('&lt;script&gt;alert(1)&lt;/script&gt;'));assert(!content.includes('<script>'));assert(!content.includes('fixture-session-token'));assert(!/src=["']https?:/.test(content));assert(content.includes('浏览器打印为 PDF'));
   }else{const parsed=JSON.parse(content);assert.equal(parsed.report.sections.length,2);assert.equal(parsed.report.evidence.length,1);assert.equal(parsed.report.robots.agents.length,3);assert.equal(parsed.usage.model_calls,0)}
 }
 await p.locator('[data-sr="print"]').click();await p.waitForFunction(()=>document.querySelector('iframe')?.contentDocument?.body?.textContent.includes('完整审计数据'));const printBody=await p.locator('iframe').evaluate(f=>f.contentDocument.body.textContent);assert.match(printBody,/请求超时，无法判断是否存在/);assert.match(printBody,/完整审计数据/);
 await p.locator('[data-sr="edit"]').click();assert.equal(await p.locator('#audit-brand').inputValue(),'User Brand');
 await p.locator('[data-sr="url"]').click();await p.locator('#audit-url').fill('limited.example');await p.locator('#audit-url-form button').click();await p.locator('#audit-brand').waitFor();
 assert.match(await p.locator('#site-readiness').textContent(),/不能据此确定为反爬/);assert.equal(await p.locator('#audit-brand').inputValue(),'');await p.locator('[data-sr="confirm"]').click();await p.locator('[data-sr="html"]').waitFor();assert.equal(requests.filter(r=>r.url.includes('audit-confirm')).at(-1).body.confirmed.brand.name,'','blocked website permits empty brand');
 // Explicit retest is the only route that requests refresh.
 await p.locator('[data-sr="refresh"]').click();await p.locator('#audit-brand').waitFor();assert.equal(requests.filter(r=>r.method==='POST'&&r.url.endsWith('/audit')).at(-1).body.refresh,true);
 await p.locator('#audit-brand').fill('Manual');await p.locator('[data-sr="confirm"]').click();await p.locator('[data-sr="html"]').waitFor();
 await p.locator('[data-sr="models"]').click();assert.equal(await p.locator('#audit-url').count(),0);assert.match(await p.locator('#view').textContent(),/调用模型并按实际用量计费/);assert.match(await p.locator('#view').textContent(),/02 \/ 分析范围/);assert.equal(requests.filter(r=>/\/start|\/sample/.test(r.url)).length,0);
 // Explicit synthetic legacy model execution may bind only the job started from this audit.
 enableModels=true;await p.evaluate(()=>geoRefresh());
 await p.locator('.ru-model').first().click();await p.locator('button[onclick="geoStart(false)"]').click();
 await p.waitForTimeout(100);assert.equal(await p.locator('.rq-card').count(),1,'old question evidence remains accessible');
 await p.locator('[data-sr="return"]').click();assert.equal(await p.locator('[data-sr="html"]').count(),1);
 const modelDownload=p.waitForEvent('download');await p.locator('[data-sr="json"]').click();const modelExport=JSON.parse(fs.readFileSync(await (await modelDownload).path(),'utf8'));assert.equal(modelExport.report.model_analysis.status,'tested');assert.equal(modelExport.report.model_analysis.job_id,lastModel.id);assert.equal(modelExport.report.model_analysis.report.raw_evidence.synthetic,'No real model called');
 await p.locator('[data-sr="history"]').last().click();await p.locator('[data-sr="return"]').click();const historyDownload=p.waitForEvent('download');await p.locator('[data-sr="json"]').click();const historyExport=JSON.parse(fs.readFileSync(await (await historyDownload).path(),'utf8'));assert.equal(historyExport.report.model_analysis.job_id,lastModel.id,'history navigation preserves only the job explicitly bound to this audit');
 // A changed model brand on the same URL must not bind to the confirmed website audit.
 await p.locator('[data-sr="edit"]').click();await p.locator('#audit-brand').fill('New Confirmed Brand');await p.locator('[data-sr="confirm"]').click();await p.locator('[data-sr="html"]').waitFor();
 await p.locator('[data-sr="models"]').click();await p.evaluate(()=>researchNext(1));await p.locator('#ru-brand').fill('Other Model Brand');await p.evaluate(()=>researchNext(2));await p.locator('button[onclick="geoStart(false)"]').click();await p.waitForTimeout(100);await p.locator('[data-sr="return"]').click();
 const mismatchDownload=p.waitForEvent('download');await p.locator('[data-sr="json"]').click();const mismatchExport=JSON.parse(fs.readFileSync(await (await mismatchDownload).path(),'utf8'));assert.equal(mismatchExport.report.model_analysis.status,'not_tested','same URL with different brand must not bind model evidence');
 // Render the backend's real synthetic contract fixture, including every check and evidence.
 const actualContract=JSON.parse(fs.readFileSync('tests/fixtures/site-readiness-contract.json','utf8'));
 const contractResult=await p.evaluate(a=>{const html=siteReadinessHTML(a),d=new DOMParser().parseFromString(html,'text/html');return {body:d.body.textContent,active:d.querySelectorAll('script,link,img').length}},actualContract);
 for(const section of actualContract.report.sections)for(const check of section.checks)assert(contractResult.body.includes(check.id)&&contractResult.body.includes(check.title));
 for(const e of actualContract.report.evidence)assert(contractResult.body.includes(e.id));assert.equal(contractResult.active,0);
 const aiContract=structuredClone(actualContract);aiContract.competitor_suggestion={status:'complete',provider:'Pollinations Classic',model:'gpt-oss-20b',model_calls:1};aiContract.confirmed.competitors=[{name:'AI Rival <script>alert(1)</script>',basis:'model_inference',aliases:['AI Rival'],evidence_ids:[]}];
 const aiExport=await p.evaluate(a=>{const d=new DOMParser().parseFromString(siteReadinessHTML(a),'text/html');return {text:d.body.textContent,scripts:d.querySelectorAll('script').length}},aiContract);assert.doesNotMatch(aiExport.text,/免费 AI 竞品建议|AI 建议，经用户确认（未核验）/);assert.match(aiExport.text,/model_inference/);assert.match(aiExport.text,/gpt-oss-20b/);assert.equal(aiExport.scripts,0);
 const challengeText=await p.evaluate(a=>{a.access={outcome:'challenge',http_status:200};a.report.robots.fetch_status='not_found';return new DOMParser().parseFromString(siteReadinessReport(a),'text/html').body.textContent},actualContract);assert.match(challengeText,/即使 HTTP 200，也未读取到可确认的正常页面内容/);assert.match(challengeText,/robots.txt 状态：未发现声明/);
 // A delayed preview from another market must not enter the new confirmation page.
 await p.locator('[data-sr="edit"]').click();await p.locator('[data-sr="url"]').click();delay=true;
 await p.locator('#audit-url').fill('slow.example');await p.locator('#audit-url-form button').click();await p.waitForTimeout(50);
 await p.evaluate(()=>geoChange('CN'));assert.equal(await p.locator('#audit-url').inputValue(),'');
 await pendingPreview.fulfill({json:fixture()});pendingPreview=null;await p.waitForTimeout(50);assert.equal(await p.locator('#audit-brand').count(),0);
 // Route leave/return never starts a POST; auth/backend epochs isolate state.
 const posts=requests.filter(r=>r.method==='POST').length;
 await p.evaluate(()=>{location.hash='/w/demo/overview'});await p.waitForTimeout(30);await p.evaluate(()=>{location.hash='/w/demo/research'});await p.locator('#audit-url').waitFor();assert.equal(requests.filter(r=>r.method==='POST').length,posts);
 await p.evaluate(()=>remoteBackendChanged('https://other-backend.example'));assert.equal(await p.locator('#audit-url').inputValue(),'');assert.equal(await p.evaluate(()=>window.remoteEnrichmentContext().token),undefined);
 assert.deepEqual(errors,[]);
 console.log('Site readiness real-team Chromium: URL-only, safe validation, zero-model preview/confirmation/report, evidence and edits, blocked/unknown/partial, full safe HTML+JSON, explicit refresh/model opt-in, market/route/backend/auth isolation passed.');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
