/* Native CDP browser-origin probes. No login, storage access, or model calls. */
import {spawn, spawnSync} from 'node:child_process';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
export const PAGE='https://saml1nhchen-ops.github.io/Money-coming/dist/team.html?v=c7177be#/w/demo/research';
export const TARGET='https://43.154.242.184.sslip.io/healthz';
const ORIGIN='https://saml1nhchen-ops.github.io';
const pause=ms=>new Promise(r=>setTimeout(r,ms));
export function healthBody(body){
 let d;try{d=JSON.parse(body);}catch{return {json:false};}if(!d||typeof d!=='object'||Array.isArray(d))return {json:false};
 const out={};if(typeof d.ok==='boolean')out.ok=d.ok;
 if(typeof d.revision==='string'&&/^(?:[a-f0-9]{40}|unknown)$/.test(d.revision))out.revision=d.revision;
 if(typeof d.version==='string'&&/^[A-Za-z0-9._+-]{1,128}$/.test(d.version))out.version=d.version;
 if(d.capabilities&&typeof d.capabilities==='object'){out.capabilities={};if(typeof d.capabilities.remember_login==='boolean')out.capabilities.remember_login=d.capabilities.remember_login;const n=d.capabilities.remember_login_max_age_seconds;if(Number.isInteger(n)&&n>=0&&n<=31536000)out.capabilities.remember_login_max_age_seconds=n;}
 return out;
}
export function csp(value){
 if(typeof value!=='string')return {present:false};
 const keywords=new Set(["'self'","'none'","'unsafe-inline'","'unsafe-eval'","'strict-dynamic'","'report-sample'",'https:','http:','data:','blob:','*']);
 const names=new Set(['default-src','connect-src','script-src','script-src-elem','style-src','style-src-elem','img-src','font-src','frame-src','frame-ancestors','object-src','base-uri','form-action','upgrade-insecure-requests','block-all-mixed-content','report-uri','report-to','worker-src','manifest-src','media-src']);
 return {present:true,truncated:value.length>8192,directives:value.slice(0,8192).split(';').map(part=>part.trim().split(/\s+/)).filter(([name])=>names.has(name)).map(([name,...sources])=>({name,sources:sources.slice(0,32).map(s=>{if(keywords.has(s))return s;if(s.startsWith("'nonce-"))return 'nonce-source';if(/^'sha(?:256|384|512)-/.test(s))return 'hash-source';try{const u=new URL(s);return [ORIGIN,'https://43.154.242.184.sslip.io','https://api.b.ai'].includes(u.origin)?u.origin:'other-source';}catch{return 'other-source';}})}))};
}
export function loadingFailure(p){return {error:/^net::ERR_[A-Z0-9_]+$/.test(p.errorText||'')?p.errorText:'browser_network_failed',cancelled:p.canceled===true,...(p.blockedReason?{blocked_reason:/^[A-Za-z]{1,64}$/.test(p.blockedReason)?p.blockedReason:'other'}:{}),...(p.corsErrorStatus?{cors_error:/^[A-Za-z]{1,100}$/.test(p.corsErrorStatus.corsError||'')?p.corsErrorStatus.corsError:'other'}:{})};}
class CDP {
 constructor(ws){this.ws=ws;this.next=0;this.pending=new Map();this.handlers=[];ws.addEventListener('close',()=>{for(const {reject} of this.pending.values())reject(new Error('cdp_closed'));this.pending.clear();});ws.addEventListener('message',event=>{let msg;try{msg=JSON.parse(String(event.data));}catch{return;}if(msg.id){const item=this.pending.get(msg.id);if(item){this.pending.delete(msg.id);msg.error?item.reject(new Error('cdp_command_failed')):item.resolve(msg.result);}}else this.handlers.forEach(h=>h(msg));});}
 send(method,params={},sessionId){return new Promise((resolve,reject)=>{const id=++this.next;this.pending.set(id,{resolve,reject});this.ws.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));});}
 close(){this.ws.close();for(const {reject} of this.pending.values())reject(new Error('cdp_closed'));this.pending.clear();}
}
async function run(){
 const report={page:PAGE,target:TARGET,credentials_sent:false};let chrome,profile,cdp;
 const deadline=setTimeout(()=>{if(chrome)chrome.kill('SIGKILL');},42000);
 try{
  if(typeof WebSocket!=='function')throw new Error('node_websocket_unavailable');
  const executable=['google-chrome','google-chrome-stable','chromium','chromium-browser'].find(name=>spawnSync('which',[name],{stdio:'ignore'}).status===0);
  if(!executable)throw new Error('chrome_unavailable');
  profile=await mkdtemp(join(tmpdir(),'signal-connection-chrome-'));
  chrome=spawn(executable,['--headless=new','--remote-debugging-port=0','--remote-debugging-address=127.0.0.1','--user-data-dir='+profile,'--no-first-run','--no-default-browser-check','about:blank'],{stdio:'ignore',env:Object.fromEntries(Object.entries(process.env).filter(([name])=>!/(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|API_KEY|PRIVATE_KEY)/i.test(name)))});
  let port,path;
  for(let i=0;i<100;i++){try{const lines=(await readFile(join(profile,'DevToolsActivePort'),'utf8')).trim().split('\n');port=Number(lines[0]);path=lines[1];if(port&&path?.startsWith('/devtools/browser/'))break;}catch{}if(chrome.exitCode!==null)throw new Error('chrome_start_failed');await pause(100);}
  if(!port||!path)throw new Error('chrome_start_timeout');
  const ws=new WebSocket('ws://127.0.0.1:'+port+path);await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',()=>reject(new Error('cdp_connect_failed')),{once:true});});cdp=new CDP(ws);
  const version=await cdp.send('Browser.getVersion');report.chrome={product:/^[A-Za-z]+\/[0-9.]+$/.test(version.product)?version.product:'unknown',protocol_version:/^[0-9.]+$/.test(version.protocolVersion)?version.protocolVersion:'unknown'};
  const {targetId}=await cdp.send('Target.createTarget',{url:'about:blank'});const {sessionId}=await cdp.send('Target.attachToTarget',{targetId,flatten:true});
  const requestIds=new Set();report.network_failures=[];report.page_csp={observed:false};report.page_csp_report_only={observed:false};let loaded=false,probing=false;
  cdp.handlers.push(msg=>{if(msg.sessionId!==sessionId)return;const p=msg.params||{};
   if(msg.method==='Page.loadEventFired')loaded=true;
   if(msg.method==='Network.requestWillBeSent'&&probing&&p.request?.url===TARGET)requestIds.add(p.requestId);
   if(msg.method==='Network.loadingFailed'&&requestIds.has(p.requestId)&&report.network_failures.length<16)report.network_failures.push(loadingFailure(p));
   if(msg.method==='Network.responseReceived'){
    const r=p.response||{};
    if(p.type==='Document'&&r.url?.startsWith('https://saml1nhchen-ops.github.io/Money-coming/')){const headers=r.headers||{};const key=Object.keys(headers).find(k=>k.toLowerCase()==='content-security-policy');report.page_csp={observed:true,...csp(key?headers[key]:null)};const reportOnly=Object.keys(headers).find(k=>k.toLowerCase()==='content-security-policy-report-only');report.page_csp_report_only={observed:true,...csp(reportOnly?headers[reportOnly]:null)};}
    if(r.url===TARGET&&requestIds.has(p.requestId)){report.health_transport={status:r.status,security_state:['secure','insecure','neutral','unknown'].includes(r.securityState)?r.securityState:'unknown'};const s=r.securityDetails;if(s)report.health_transport.tls={protocol:/^TLS [0-9.]+$/.test(s.protocol)?s.protocol:'unknown',valid_from:Number.isInteger(s.validFrom)?s.validFrom:null,valid_to:Number.isInteger(s.validTo)?s.validTo:null};}
   }
  });
  await cdp.send('Page.enable',{},sessionId);await cdp.send('Runtime.enable',{},sessionId);await cdp.send('Network.enable',{},sessionId);
  await cdp.send('Page.navigate',{url:PAGE},sessionId);for(let i=0;i<100&&!loaded;i++)await pause(100);
  const origin=await cdp.send('Runtime.evaluate',{expression:'location.origin',returnByValue:true},sessionId);report.actual_origin=origin.result?.value===ORIGIN?ORIGIN:'unexpected_origin';
  if(report.actual_origin!==ORIGIN)throw new Error('page_origin_mismatch');
  const expression=`(async()=>{const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),15000);try{const r=await fetch(${JSON.stringify(TARGET)},{method:'GET',credentials:'omit',cache:'no-store',redirect:'error',signal:controller.signal});const body=await r.text();return {status:r.status,body:body.length<=65536?body:null};}catch(e){return {error:e&&e.name==='AbortError'?'timeout':'fetch_network_failed'};}finally{clearTimeout(timer);}})()`;
  probing=true;
  const result=await cdp.send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true},sessionId);const value=result.result?.value;
  report.health=value&&typeof value.status==='number'?{status:value.status,body:healthBody(value.body)}:{error:value?.error==='timeout'?'timeout':'fetch_network_failed'};
  await pause(250);return report;
 }catch(error){report.error=['node_websocket_unavailable','chrome_unavailable','chrome_start_failed','chrome_start_timeout','cdp_connect_failed','page_origin_mismatch'].includes(error.message)?error.message:'browser_probe_failed';return report;}
 finally{clearTimeout(deadline);if(cdp)cdp.close();if(chrome&&chrome.exitCode===null){chrome.kill('SIGTERM');await Promise.race([new Promise(r=>chrome.once('exit',r)),pause(1500)]);if(chrome.exitCode===null)chrome.kill('SIGKILL');}if(profile)await rm(profile,{recursive:true,force:true,maxRetries:2}).catch(()=>{});}
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){const timer=setTimeout(()=>{process.stdout.write(JSON.stringify({page:PAGE,target:TARGET,error:'browser_probe_timeout',credentials_sent:false})+'\n');process.exit(1);},45000);run().then(report=>{clearTimeout(timer);process.stdout.write(JSON.stringify(report)+'\n');});}
