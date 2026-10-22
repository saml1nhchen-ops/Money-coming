"""Bounded public transport/parser diagnostics. No credentials, models or cookies."""
import hashlib,http.client,json,multiprocessing,pathlib,re,socket,sys,urllib.error,urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'));sys.path.insert(0,str(ROOT/'deploy'))
import audit_fetch as f,pinned_http,website_inspection
from geo_audit import preview_candidates
from connection_diagnostics import publish
OBSERVED=[]
HEADERS=('Content-Type','Content-Length','Location','Retry-After','Server','CF-Mitigated','X-Shopify-Stage','X-DC','X-Cache','Via','Content-Encoding','X-Robots-Tag')
def child_http(pipe,args):
 try:
  url,addresses,limit,accept,timeout=args
  request=urllib.request.Request(url,headers={'User-Agent':'SignalGEO/1.0','Accept':accept,'Accept-Encoding':'identity'})
  op=urllib.request.build_opener(urllib.request.ProxyHandler({}),pinned_http.PinnedHTTPHandler(addresses),pinned_http.PinnedHTTPSHandler(addresses),f.NoRedirect)
  try:response=op.open(request,timeout=timeout)
  except urllib.error.HTTPError as e:response=e
  with response:
   headers={k:response.headers.get(k)[:500] for k in HEADERS if response.headers.get(k) is not None}
   raw=response.read(limit if 200<=response.status<300 else min(16384,limit));declared=headers.get('Content-Length','');declared=int(declared) if declared.isdigit() else None
   text=raw[:16384].decode('utf-8','replace');p=website_inspection.WebsiteExtractor();p.feed(text)
   diagnostic={'url':url,'status':response.status,'headers':headers,'captured_bytes':len(raw),'body_sha256':hashlib.sha256(raw).hexdigest(),'body_title':p.metadata()['title'],'body_excerpt':' '.join(p.body_parts)[:1500],'markers':{k:bool(re.search(v,text,re.I)) for k,v in {'cloudflare':'cloudflare|cf-chl-|challenge-platform','shopify':'shopify','akamai':'akamai|edgesuite|edgekey','access_denied':'access denied|request rejected','rate_limit':'too many requests|rate limit','human_verification':'verify.{0,30}human|captcha|checking your browser'}.items()}}
   pipe.send({'ok':True,'response':{'status':response.status,'headers':headers,'raw':raw,'truncated':len(raw)==limit and (declared is None or declared>limit)},'diagnostic':diagnostic})
 except BaseException as e:pipe.send({'ok':False,'error':type(e).__name__})
 finally:pipe.close()
def observed_worker(op,args,timeout):
 if op!='http':return f.isolated(op,args,timeout)
 ctx=multiprocessing.get_context('spawn');parent,child=ctx.Pipe(duplex=False);p=ctx.Process(target=child_http,args=(child,args),daemon=True);p.start();child.close()
 try:
  if not parent.poll(timeout):raise f.AuditFetchError('operation_timeout')
  value=parent.recv()
  if not value['ok']:raise f.AuditFetchError('connection_failed')
  OBSERVED.append(value['diagnostic']);return value['response']
 finally:
  parent.close()
  if p.is_alive():p.terminate()
  p.join(timeout=.2)
  if p.is_alive():p.kill();p.join(timeout=.2)
def main():
 report={'kind':'brand_fetch_root_cause','models_called':0,'client':'production SignalGEO pinned urllib + actual offline parsers','sites':[]}
 for url in ('https://cremocompany.com/','https://www.nike.com/','https://www.lorealparisusa.com/','https://www.lorealparis.com.cn/','https://example.com/'):
  OBSERVED.clear();budget=f.FetchBudget(worker=observed_worker);r=budget.fetch(url);parsed=r.get('parsed') or {};meta=parsed.get('metadata') or {};a={'evidence':[],'candidates':{'brand':None,'products':[],'competitors':[]}};preview_candidates(a,r)
  report['sites'].append({'url':url,'requests':list(OBSERVED),'error':r.get('error'),'access':r.get('diagnostics'),'usage':budget.finish(),'metadata':meta,'extracted_characters':len(parsed.get('extracted_text','')),'visible_text_excerpt':parsed.get('extracted_text','')[:1500],'candidates':a['candidates']})
 pathlib.Path('connection-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print('Read-only diagnosis report: '+publish(report))
if __name__=='__main__':main()
