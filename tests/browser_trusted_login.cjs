/* Trusted-login protocol and race tests. Every HTTP request is intercepted. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),SITE='https://saml1nhchen-ops.github.io';
const A='https://43.154.242.184.sslip.io',B='https://other-team.example.test';
const PASSWORD='synthetic-team-password',PREFIX='signal-team-auth:v1:';
const key=url=>PREFIX+encodeURIComponent(url);
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE||(fs.existsSync(chromium.executablePath())?undefined:'/usr/bin/chromium'),args:['--no-sandbox']});
 try{
  const sessions=new Map(),requests=[],errors=[];let serial=0,capability=true,status503=false,old401='',releaseState,holdLogin=false,releaseLogin,probeFailure=false,storeFailure=false;
  async function setup(context){
   context.on('page',p=>{p.setDefaultTimeout(7000);p.on('pageerror',e=>errors.push(e.message))});
   await context.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url());
    if(url.origin===SITE){if(url.pathname.includes('/api/'))return route.fulfill({status:404,contentType:'application/json',body:'{}'});const name=url.pathname.split('/dist/')[1]||'index.html';return route.fulfill({body:fs.readFileSync(path.join(ROOT,'dist',name)),contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html'})}
    assert([A,B].includes(url.origin),'unexpected external origin');
    const body=req.postDataJSON(),auth=req.headers().authorization?.slice(7)||'';
    requests.push({origin:url.origin,path:url.pathname,body,auth});let status=200,data;
    if(url.pathname==='/healthz'){status=probeFailure?503:200;data=probeFailure?{code:'backend_unavailable'}:{ok:true,...(capability?{capabilities:{remember_login:true,remember_login_max_age_seconds:2592000}}:{})};}
    else if(url.pathname==='/api/workspace/login'){
     assert.equal(body.password,PASSWORD);assert.deepEqual(Object.keys(body).sort(),capability&&!probeFailure?['password','remember']:['password']);
     if(storeFailure&&body.remember){status=503;data={code:'session_store_unavailable'};}else{
     const credential='td1_synthetic_'+(++serial)+'_'+('a'.repeat(32));
     const remembered=body.remember===true,expires=new Date(Date.now()+(remembered?30*86400000:3600000)).toISOString();
     sessions.set(credential,{origin:url.origin,valid:true,expires});data={token:credential,expires_at:expires,remembered,workspace:{mode:'shared_team',shared_reports:true}};
     if(holdLogin)await new Promise(resolve=>releaseLogin=resolve);}
    }else if(url.pathname==='/api/workspace/logout'){
     const session=sessions.get(auth);assert(!session||session.origin===url.origin,'credential crossed origins');if(session)session.valid=false;data={ok:true};
    }else if(url.pathname==='/api/geo/state'){
     const session=sessions.get(auth);assert(!session||session.origin===url.origin,'credential crossed origins');
     if(auth===old401){await new Promise(resolve=>releaseState=resolve);status=401;data={code:'unauthorized'}}
     else if(status503){status=503;data={code:'session_store_unavailable'}}
     else if(!session?.valid){status=401;data={code:'unauthorized'}}
     else data={runner:{configured:true,profiles:[]},busy:false,runs:[],remote:{ready:true,limits:{count:30,max_models:2,repeats:1},budget:{date:'2026-10-21',limit:126,reserved:0,remaining:126}}};
    }else throw Error('unexpected business call '+url.pathname);
    try{await route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)})}catch{}
   });
  }
  const context=await browser.newContext();await setup(context);
  const p=await context.newPage();
  const visit=async page=>{await page.goto(SITE+'/Money-coming/dist/team.html#/w/demo/research');await page.locator('#remote-connection').waitFor()};
  const logged=async page=>page.getByText('团队后台已连接 · 运行依赖已就绪',{exact:true}).waitFor();
  const record=async(page,url=A)=>page.evaluate(k=>JSON.parse(localStorage.getItem(k)),key(url));
  async function login(page,{url=A,remember=true}={}){
   if(await page.locator('#remote-password').count()===0)await page.evaluate(()=>remotePasswordLogin());
   await page.locator('#remote-backend-url').fill(url);await page.locator('#remote-password').fill(PASSWORD);
   if(remember)await page.locator('#remote-remember').check();else await page.locator('#remote-remember').uncheck();
   await page.getByRole('button',{name:'连接并登录',exact:true}).click();await logged(page);
  }
  await visit(p);assert(await p.locator('#remote-remember').isChecked());await login(p);
  let saved=await record(p);assert.equal(saved.remembered,true);assert(Date.parse(saved.expires_at)>Date.now()+29*86400000);
  assert(!JSON.stringify(await p.evaluate(()=>({...localStorage}))).includes(PASSWORD));
  const first=saved.token,beforeReload=requests.length;await p.reload();await logged(p);
  assert.deepEqual(requests.slice(beforeReload).map(r=>r.path),['/api/geo/state']);assert.equal((await record(p)).token,first);
  status503=true;await p.evaluate(()=>geoRefresh());assert.equal((await record(p)).token,first);assert.equal(await p.evaluate(()=>remoteCanRun()),false);
  await p.reload();await p.getByText('后台连接失败',{exact:true}).waitFor();assert.equal((await record(p)).token,first);
  status503=false;await p.evaluate(()=>geoRefresh());await logged(p);
  const other=await context.newPage();await visit(other);await logged(other);
  // A late 401 from the old credential must not delete a newer stored session.
  old401=first;await other.evaluate(()=>{window.oldState=geoRefresh()});await p.waitForTimeout(30);
  await login(p);saved=await record(p);assert.notEqual(saved.token,first);const replacement=saved.token;
  releaseState?.();old401='';await logged(other);assert.equal((await record(other)).token,replacement);
  await other.evaluate(()=>remoteLogout());await p.locator('#remote-password').waitFor();assert.equal(await record(p),null);assert.equal(sessions.get(replacement).valid,false);
  // Explicitly transient login on a capable backend never stores the token.
  await login(p,{remember:false});assert.equal(await record(p),null);assert.equal(requests.filter(r=>r.path==='/api/workspace/login').at(-1).body.remember,false);
  await p.reload();await p.locator('#remote-password').waitFor();
  // Legacy backend receives password only: never optimistic remember+400 retry.
  capability=false;await login(p);saved=await record(p);assert.equal(saved.remembered,false);assert(Date.parse(saved.expires_at)<Date.now()+3700000);
  assert((await p.locator('#remote-connection').innerText()).includes('1 小时'));const legacyCount=requests.filter(r=>r.path==='/api/workspace/login').length;
  await p.reload();await logged(p);assert.equal(requests.filter(r=>r.path==='/api/workspace/login').length,legacyCount);
  // Origin B uses its own record and never receives origin A's credential.
  capability=true;const third=await context.newPage();await visit(third);await logged(third);
  await third.evaluate(url=>remoteBackendChanged(url),B);await third.locator('#remote-password').waitFor();await login(third,{url:B});
  const bToken=(await record(third,B)).token;assert(await record(p,A));assert.equal((await record(third,B)).backend_url,B);
  sessions.get((await record(p,A)).token).valid=false;await p.evaluate(()=>geoRefresh());await p.locator('#remote-password').waitFor();assert.equal(await record(p,A),null);assert.equal((await record(third,B)).token,bToken);
  await third.evaluate(()=>remoteLogout());assert.equal(await record(third,B),null);
  // Cancel an in-flight login: its response cannot recreate saved authentication.
  await p.evaluate(url=>remoteBackendChanged(url),A);holdLogin=true;
  await p.locator('#remote-password').fill(PASSWORD);await p.getByRole('button',{name:'连接并登录',exact:true}).click();await p.waitForTimeout(40);
  await p.evaluate(()=>remoteLogout());releaseLogin?.();holdLogin=false;await p.waitForTimeout(60);assert.equal(await record(p,A),null);assert.equal(await p.evaluate(()=>geoToken),'');
  probeFailure=true;await login(p);assert.equal(requests.filter(r=>r.path==='/api/workspace/login').at(-1).body.remember,undefined);await p.evaluate(()=>remoteLogout());probeFailure=false;
  storeFailure=true;const beforeStoreFailure=requests.filter(r=>r.path==='/api/workspace/login').length;await p.locator('#remote-password').fill(PASSWORD);await p.getByRole('button',{name:'连接并登录',exact:true}).click();await p.getByText(/后台保持登录服务暂不可用/).waitFor();assert.equal(requests.filter(r=>r.path==='/api/workspace/login').length,beforeStoreFailure+1);assert.equal(await record(p),null);await login(p,{remember:false});assert.equal(await record(p),null);await p.evaluate(()=>remoteLogout());storeFailure=false;
  // A 30-day expiry must survive JS's 24.8-day timer limit, then expire absolutely.
  await login(p);const timerRecord=await record(p);
  const clockPage=await context.newPage();await clockPage.clock.install({time:new Date()});await visit(clockPage);await logged(clockPage);
  await clockPage.clock.fastForward(2147483647);assert.equal(await clockPage.evaluate(()=>geoToken),'team-session');assert.equal((await record(clockPage)).token,timerRecord.token);
  await clockPage.clock.fastForward(6*86400000);await clockPage.locator('#remote-password').waitFor();assert.equal(await record(clockPage),null);
  await context.close();
  // Unavailable storage is a clear memory-only fallback, not a login failure.
  const blocked=await browser.newContext();await setup(blocked);
  await blocked.addInitScript(()=>{const read=Storage.prototype.getItem,write=Storage.prototype.setItem;Storage.prototype.getItem=function(k){if(k.startsWith('signal-team-auth:'))throw new DOMException('blocked','SecurityError');return read.call(this,k)};Storage.prototype.setItem=function(k,v){if(k.startsWith('signal-team-auth:'))throw new DOMException('blocked','SecurityError');return write.call(this,k,v)}});
  const memory=await blocked.newPage();await visit(memory);await login(memory);assert((await memory.locator('#remote-connection').innerText()).includes('无法保存登录'));
  const logins=requests.filter(r=>r.path==='/api/workspace/login').length;await memory.reload();await memory.locator('#remote-password').waitFor();assert.equal(requests.filter(r=>r.path==='/api/workspace/login').length,logins);
  assert.deepEqual(errors,[]);assert(requests.every(r=>['/healthz','/api/workspace/login','/api/workspace/logout','/api/geo/state'].includes(r.path)));
  console.log('Trusted login synthetic: capability/legacy protocols, default opt-in/transient, restore-only state, 503 retention/401 removal, origin isolation, cross-tab replacement/logout, late responses, storage fallback, 24.8-day timer and absolute expiry passed.');
  await blocked.close();
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
