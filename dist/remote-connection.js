/* HTTPS team workspace. Only its origin is persisted; credentials stay in memory. */
let remoteConnection={url:'',expiresAt:0,message:'',busy:false,offline:false};
let remoteExpiryTimer=null,remoteEpoch=0;
try{remoteConnection.url=remoteOrigin(localStorage.getItem('signal-analysis-backend')||'')}catch{}
function remoteOrigin(value){
  const u=new URL(value);
  if(u.protocol!=='https:'||u.username||u.password||u.pathname!=='/'||u.search||u.hash)throw Error('请输入 HTTPS 后台地址，仅包含域名和可选端口，不含路径、账号或查询参数。');
  return u.origin;
}
function remoteClear(message='已退出，请重新登录。'){
  remoteEpoch++;clearTimeout(remoteExpiryTimer);clearTimeout(geoTimer);
  geoToken='';remoteConnection.expiresAt=0;remoteConnection.offline=false;remoteConnection.message=message;
  geoState={runner:{profiles:[]},runs:[]};geoActive=null;geoPlanView=null;
}
function remoteRender(){if(page==='research')render()}
function remoteReady(){return Boolean(geoToken&&!remoteConnection.offline&&geoState.remote?.ready===true)}
function remoteCanRun(calls=1){const b=geoState.remote?.budget;return remoteReady()&&!geoState.busy&&Number.isFinite(b?.remaining)&&b.remaining>=calls}
const remoteReasons={missing_bai_key:'后台尚未配置 B.AI 密钥，请联系工作台管理员配置服务器后刷新。',catalog_unavailable:'后台暂时无法读取模型目录，请管理员检查网络和密钥后刷新。',model_catalog_unavailable:'后台暂时无法读取模型目录，请管理员检查网络和密钥后刷新。',required_models_unavailable:'后台缺少可用的 GPT 或 Gemini 固定模型，请管理员检查目录与配置后刷新。',runtime_unavailable:'后台运行依赖未就绪，请管理员修复运行环境后刷新。'};
function remoteConnectionMarkup(){
  const c=remoteConnection,r=geoState.remote,b=r?.budget,limits=r?.limits;
  const profiles=geoState.runner.profiles||[];
  return `<section class="ru-remote" id="remote-connection" aria-label="连接分析后台"><h2>连接分析后台</h2><p>单团队共享工作台：授权成员可互相查看、下载和停止分析。B.AI 密钥由管理员在后台配置。</p>${geoToken?`<p><b>${c.offline?'后台连接失败':r?.ready?'后台已连接 · 运行依赖已就绪':'后台已连接 · 暂不能开始分析'}</b> · 登录有效至 ${esc(new Date(c.expiresAt).toLocaleTimeString())}</p><p class="mono">${esc(c.url)}</p><div class="actions"><button onclick="geoRefresh()" ${c.busy?'disabled':''}>刷新后台状态</button><button onclick="remoteLogout()" ${c.busy?'disabled':''}>退出 / 更换后台</button></div>`:`<form onsubmit="remoteLogin(event)"><label class="ru-field" for="remote-backend-url"><span>HTTPS 后台地址</span><input id="remote-backend-url" type="url" value="${esc(c.url)}" placeholder="https://你的分析后台域名" required autocomplete="off"></label><label class="ru-field" for="remote-password"><span>团队密码</span><input id="remote-password" type="password" required autocomplete="off"></label><button class="primary" ${c.busy?'disabled':''}>${c.busy?'正在登录…':'连接并登录'}</button></form>`}<p class="ru-help">只记住后台地址；密码和登录令牌仅存于当前页面内存，刷新后需重新登录。不会自动开始付费分析。</p>${c.message?`<p class="ru-warning" role="status">${esc(c.message)}</p>`:''}${geoToken&&r?.ready!==true?`<p class="ru-warning">${esc(remoteReasons[r?.reason]||'后台就绪状态未知，请刷新状态或联系管理员。')}</p>`:''}${geoToken?`<p>固定美国市场 · ${esc(limits?.count??'未知')} 题 · 最多 ${esc(limits?.max_models??'未知')} 个模型 · 每题 ${esc(limits?.repeats??'未知')} 次</p><p>UTC ${esc(b?.date??'未知日期')} 调用额度：已预约 ${esc(b?.reserved??'未知')} / ${esc(b?.limit??'未知')}，剩余 ${esc(b?.remaining??'未知')} 次。预约不是实际账单金额，失败和停止不自动退还。</p>${!Number.isFinite(b?.remaining)?'<p class="ru-warning">预算状态未知，已暂停新付费分析，请刷新后台状态。</p>':b.remaining===0?'<p class="ru-warning">今日额度已用完。可读取和导出已有报告，次日或管理员调整额度后再开始。</p>':''}<details><summary>固定模型与调用条件</summary>${profiles.length?profiles.map(p=>`<p><b>${esc(p.name)}</b><br><code>${esc(p.model)}</code> · ${esc(p.protocol)} · 联网请求：${p.search===false?'关闭':'未知'}<br>目录可见，尚未验证调用</p>`).join(''):'<p>模型目录暂不可用，不代表测评结果为零。</p>'}<p>目录读取时间：${esc(r?.catalog_fetched_at||geoState.runner.fetched_at||'后台未提供')}</p></details>`:''}</section>`;
}
const remoteErrorMessages={invalid_request:'请求参数不符合后台要求，请检查官网、30 道题目和已选固定模型。',unauthorized:'团队密码错误或登录已失效，请重新登录。',origin_forbidden:'后台未允许当前页面来源，请管理员核对 GitHub Pages 的跨域配置。',not_found:'后台接口或任务不存在，请刷新任务列表。',busy:'团队已有分析正在运行，请等待完成或明确停止后再开始。',request_too_large:'提交内容过大，请缩短品牌背景或题目。',rate_limited:'请求过于频繁，请稍后手动重试，不会自动重试。',daily_budget_exceeded:'今日调用额度不足，请在次日或管理员调整额度后再明确开始。',budget_unavailable:'后台预算记录暂不可用，已暂停新分析，请联系管理员。',backend_unavailable:'后台服务未就绪，请稍后刷新状态或联系管理员。',model_catalog_unavailable:'后台模型目录暂不可用，请管理员检查密钥与网络后刷新。',catalog_unavailable:'后台模型目录暂不可用，请管理员检查密钥与网络后刷新。',runtime_unavailable:'后台运行依赖未就绪，请管理员检查运行环境。',missing_bai_key:'后台尚未配置 B.AI 密钥，请联系管理员。',required_models_unavailable:'后台缺少固定 GPT 或 Gemini 模型，请联系管理员。',upstream_failed:'模型执行服务请求失败；已有证据保留，不会自动重试付费请求。'};
function remotePayload(endpoint,body){
  if(body===undefined)return undefined;
  const common=['website','market','brand_aliases','skus','competitors','focus','context','count','repeats','providers','generator'];
  const fields={inspect:['website','market'],plan:[...common,'generate_only','manual'],start:[...common,'generate_only'],sample:[...common,'prompts'],analyze:['id','brand_aliases','skus','competitors'],stop:['id']}[endpoint];
  if(!fields)throw Error('该操作不在远端工作台接口范围内。');
  return Object.fromEntries(fields.filter(k=>Object.hasOwn(body,k)).map(k=>[k,body[k]]));
}
async function remoteRequest(path,body,token=geoToken){
  let response;
  try{response=await fetch(remoteConnection.url+path,{method:body===undefined?'GET':'POST',credentials:'omit',redirect:'error',cache:'no-store',headers:{...(token?{Authorization:'Bearer '+token}:{}),...(body===undefined?{}:{'Content-Type':'application/json'})},...(body===undefined?{}:{body:JSON.stringify(body)})})}
  catch{const error=Error('后台连接失败，请检查后台地址、网络和服务状态后手动刷新。');error.connectionFailure=true;throw error}
  if(response.status===401){if(token===geoToken){remoteClear('登录已失效，请重新登录。');remoteRender()}throw Error(token?'登录已失效，请重新登录。':'团队密码错误或登录失败，请重新输入。')}
  let data;try{data=await response.json()}catch{const error=Error('后台响应格式错误，请联系管理员检查服务。');error.connectionFailure=true;throw error}
  if(!response.ok)throw Error(remoteErrorMessages[data.code]||'后台请求失败，请刷新状态或联系管理员。')
  return data;
}
async function remoteLogin(event){
  event?.preventDefault();if(remoteConnection.busy)return;
  const passwordInput=$('#remote-password');let password=passwordInput?.value||'';
  if(passwordInput)passwordInput.value='';
  try{
    const url=remoteOrigin($('#remote-backend-url')?.value.trim()||'');
    remoteClear('');remoteConnection.url=url;localStorage.setItem('signal-analysis-backend',url);
    remoteConnection.busy=true;remoteRender();
    const epoch=remoteEpoch;const result=await remoteRequest('/api/workspace/login',{password},'');password='';
    if(epoch!==remoteEpoch)return;
    const expiry=Date.parse(result.expires_at);
    if(typeof result.token!=='string'||!result.token||!Number.isFinite(expiry)||expiry<=Date.now())throw Error('后台登录响应无效，请联系管理员。');
    geoToken=result.token;remoteConnection.expiresAt=expiry;
    remoteExpiryTimer=setTimeout(()=>{remoteClear('登录已到期，请重新登录。');remoteRender()},Math.min(expiry-Date.now(),2147483647));
    geoMarket='US';await geoRefresh(false);
  }catch(e){remoteConnection.message=e.message}
  finally{password='';remoteConnection.busy=false;remoteRender()}
}
async function remoteLogout(){
  const token=geoToken;remoteConnection.busy=true;
  // Local access ends immediately, even if the server is temporarily unavailable.
  remoteClear('已退出，请重新登录。');remoteRender();
  try{await remoteRequest('/api/workspace/logout',{},token)}catch{remoteConnection.message='已清除本页登录。后台注销未确认，原会话最迟一小时失效。'}
  finally{remoteConnection.busy=false;remoteRender()}
}
const loopbackGeoFetch=geoFetch;
geoFetch=async function(path,body){
  if(!geoRemoteMode())return loopbackGeoFetch(path,body);
  if(path.split('?')[0]==='resume')throw Error('在线工作台不支持续跑，请核对已有证据后明确开始新任务。');
  if(!geoToken||Date.now()>=remoteConnection.expiresAt){remoteClear('请先连接分析后台并登录。');remoteRender();throw Error('请先连接分析后台并登录。')}
  const epoch=remoteEpoch;
  try{const result=await remoteRequest('/api/geo/'+path,remotePayload(path.split('?')[0],body));if(epoch!==remoteEpoch)throw Error('登录状态已改变，请重新操作。');if(path==='state')remoteConnection.offline=false;return result}
  catch(e){if(geoToken){if(e.connectionFailure)remoteConnection.offline=true;remoteConnection.message=e.message}throw e}
};
const loopbackGeoLoad=geoLoad;
geoLoad=async function(){if(!geoRemoteMode())return loopbackGeoLoad();remoteConnection.message='请连接分析后台并登录；刷新页面后需重新登录。';remoteRender()};
const localGeoRefresh=geoRefresh;
geoRefresh=async function(capture=true){
  if(!geoRemoteMode())return localGeoRefresh(capture);
  if(capture)researchSave();
  if(!geoToken){remoteConnection.message='请先连接分析后台并登录。';remoteRender();return}
  try{const state=await geoFetch('state');geoState={...state,runner:{...state.runner,profiles:state.runner?.profiles||[]},runs:state.runs||[]};remoteConnection.message='';remoteNormalizeSelection();}
  catch(e){remoteConnection.message=e.message}
  remoteRender();
};
function remoteNormalizeSelection(){
  if(!geoRemoteMode())return;
  geoMarket='US';const d=geoDraft.US;
  const ids=new Set((geoState.runner.profiles||[]).filter(p=>p.markets?.includes('US')).map(p=>p.id));
  d.providers=[...new Set(d.providers||[])].filter(id=>ids.has(id)).slice(0,2);
  if(!d.providers.includes(d.generator))d.generator=d.providers[0]||'';
  d.count='30';d.repeats='1';
}
const localGeoPayload=geoPayload;
geoPayload=function(){const body=localGeoPayload();if(geoRemoteMode()){remoteNormalizeSelection();const d=geoDraft.US;Object.assign(body,{market:'US',count:30,repeats:1,providers:d.providers.slice(),generator:d.generator})}return body};
const localGeoOptions=geoOptions;
geoOptions=function(){if(!geoRemoteMode())return localGeoOptions();const d=geoDraft.US;return geoState.runner.profiles.filter(p=>(d.providers||[]).includes(p.id)).map(p=>`<option value="${esc(p.id)}" ${p.id===d.generator?'selected':''}>${esc(p.name)} · ${esc(p.model)}</option>`).join('')||'<option value="">先选择回答模型</option>'};
const localResearchToggle=researchToggle;
researchToggle=function(vendor){localResearchToggle(vendor);if(geoRemoteMode()){remoteNormalizeSelection();render()}};
const localResearchModel=researchModel;
researchModel=function(vendor,pid){localResearchModel(vendor,pid);if(geoRemoteMode()){remoteNormalizeSelection();render()}};
const localGeoChange=geoChange;
geoChange=function(m){if(geoRemoteMode()&&m!=='US'){researchMessage='在线工作台固定测量美国市场。';render();return}return localGeoChange(m)};
const localGeoStart=geoStart;
geoStart=async function(manual,generateOnly=false){
  if(!geoRemoteMode())return localGeoStart(manual,generateOnly);
  researchSave();remoteNormalizeSelection();
  const d=geoDraft.US,providers=d.providers||[],prompts=(d.questions||'').split('\n').map(s=>s.trim()).filter(Boolean);
  let error='';
  if(!geoToken)error='请先连接分析后台并登录。';
  else if(!remoteReady())error='后台尚未就绪，请查看连接状态并手动刷新。';
  else if(!providers.length||providers.length>2)error='请选择 1–2 个固定 GPT / Gemini 模型。';
  else if(manual&&(prompts.length!==30||new Set(prompts).size!==30||prompts.some(p=>p.length>4000)))error='手工采样必须恰好 30 道不同问题，每题不超过 4000 字符。';
  else if(!remoteCanRun(manual?30*providers.length:generateOnly?3:3+30*providers.length))error='后台正在运行任务或今日剩余额度不足。请刷新状态，核对调用计划后再开始。';
  if(error){researchMessage=error;render();return}
  return localGeoStart(manual,generateOnly);
};
const localResearchSelect=researchSelect;
researchSelect=function(){let html=localResearchSelect();if(!geoRemoteMode())return html;html=html.replace(/<a class="button primary" href="http:\/\/127\.0\.0\.1:8771[^>]*>[^<]*<\/a>/g,'<a class="button primary" href="#remote-connection">查看后台连接</a>');return html};
const localResearchAdvanced=researchAdvanced;
researchAdvanced=function(){const html=localResearchAdvanced();return geoRemoteMode()?html.replace(/<p><a href="http:\/\/127\.0\.0\.1:8771[\s\S]*?<\/p>/g,'<p class="ru-help">固定模型由后台管理员配置。目录可见不代表真实调用已验证；不自动切换模型或协议。</p>'):html};
const localResearchDisplayModel=researchDisplayModel;
researchDisplayModel=function(pid){if(!geoRemoteMode())return localResearchDisplayModel(pid);return geoActive?.config?.configuration?.[pid]?.model||geoState.runner.profiles.find(p=>p.id===pid)?.model||geoModel(pid)};
const beforeRemoteRender=render;
render=function(){
  beforeRemoteRender();if(page!=='research'||!geoRemoteMode())return;
  const count=(geoDraft.US.providers||[]).length;
  for(const button of document.querySelectorAll('[onclick^="geoStart("],[onclick="geoGenerateOnly()"]')){
    const action=button.getAttribute('onclick'),calls=action==='geoGenerateOnly()'?3:action.includes('true')?30*count:3+30*count;
    button.disabled=!count||!remoteCanRun(calls);
  }
};
if(geoRemoteMode()){geoMarket='US';geoActive=null;geoToken='';remoteNormalizeSelection();}
if(page==='research')render();
