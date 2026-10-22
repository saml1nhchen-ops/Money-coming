"""Finite audit fetches. Child-process deadlines bound DNS, read loops and parsing.

Only stdlib pinned HTTP is used. Tools receive captured HTML, never network URLs
for downloading. No proxy bypass, cookies, retry, JS, or cross-origin crawling.
"""
import hashlib,ipaddress,multiprocessing,os,re,socket,time,urllib.error,urllib.parse,urllib.request
import website_inspection,website_check,pinned_http
MAX_BYTES=4*1024*1024
class AuditFetchError(Exception):
 def __init__(self,code):self.code=code
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):return None

def _worker(pipe,operation,args):
 try:
  if operation=='dns':result=socket.getaddrinfo(args[0],args[1],type=socket.SOCK_STREAM)
  elif operation=='http':
   url,addresses,limit,accept,timeout=args
   request=urllib.request.Request(url,headers={'User-Agent':'SignalGEO/1.0','Accept':accept,'Accept-Encoding':'identity'})
   opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),pinned_http.PinnedHTTPHandler(addresses),pinned_http.PinnedHTTPSHandler(addresses),NoRedirect)
   try:response=opener.open(request,timeout=timeout)
   except urllib.error.HTTPError as error:response=error
   with response:
    headers={k:response.headers.get(k)[:1000] for k in ('Content-Type','Location','Retry-After','Link','X-Robots-Tag') if response.headers.get(k) is not None}
    raw=response.read(limit) if 200<=response.status<300 else b'';length=response.headers.get('Content-Length','');declared=int(length) if length.isdigit() else None
    truncated=len(raw)==limit and (declared is None or declared>limit)
    result={'status':response.status,'headers':headers,'raw':raw,'truncated':truncated}
  elif operation=='parse':
   import trafilatura
   from html.parser import HTMLParser
   html,url=args
   class Parser(website_inspection.WebsiteExtractor):
    def __init__(self):super().__init__();self.alternates=[]
    def handle_starttag(self,tag,attrs):
     super().handle_starttag(tag,attrs);a=dict(attrs)
     if tag=='link' and 'alternate' in a.get('rel','').lower() and a.get('type','').lower() in ('text/markdown','text/x-markdown'):self.alternates.append(a.get('href',''))
   p=Parser();p.feed(html);meta=p.metadata();meta['markdown_alternates']=p.alternates[:5];meta['robots_meta']={k:p.meta[k][:500] for k in ('robots','googlebot') if k in p.meta};meta['author']=p.meta.get('author','')[:200];meta['date']=p.meta.get('article:published_time','')[:100]
   semantic=[]
   def visit(obj,depth=0):
    if depth>12:return
    if isinstance(obj,list):
     for item in obj:visit(item,depth+1)
    elif isinstance(obj,dict):
     types=obj.get('@type',[]);types=[types] if isinstance(types,str) else types
     if isinstance(types,list):semantic.extend(t for t in types if t in ('Organization','Corporation','Brand','Product','Article','WebPage','WebSite','BreadcrumbList','FAQPage','LocalBusiness'))
     for value in obj.values():
      if isinstance(value,(dict,list)):visit(value,depth+1)
   visit(p.ld);meta['semantic_types']=sorted(set(semantic))
   extracted=trafilatura.extract(html,url=url,output_format='txt',fast=True,include_comments=False) or ''
   result={'metadata':meta,'text':'\n'.join(p.parts)[:100000],'extracted_text':extracted[:200000]}
  elif operation=='robots':
   from protego import Protego
   text,paths,agents=args;rules=Protego.parse(text);result={agent:{path:bool(rules.can_fetch(path,agent)) for path in paths} for agent in agents}
  else:raise AuditFetchError('invalid_operation')
  pipe.send({'ok':True,'value':result})
 except BaseException as error:
  code='audit_unavailable' if isinstance(error,ImportError) else website_check.classify(error)
  pipe.send({'ok':False,'error':code})
 finally:pipe.close()

def _isolated_worker(pipe,operation,args):
 # A fresh spawned process owns this environment. Parent variables are untouched.
 for name in list(os.environ) if multiprocessing.parent_process() is not None else []:
  if re.search(r'TOKEN|SECRET|PASSWORD|CREDENTIAL|API_KEY|PRIVATE_KEY',name,re.I):os.environ.pop(name,None)
 if multiprocessing.parent_process() is not None and operation in ('parse','robots'):
  def denied(*args,**kwargs):raise OSError('Offline parser network is disabled')
  socket.socket.connect=denied;socket.create_connection=denied;socket.getaddrinfo=denied
 _worker(pipe,operation,args)

def isolated(operation,args,timeout):
 if timeout<=0:raise AuditFetchError('deadline_exceeded')
 deadline=time.monotonic()+timeout
 ctx=multiprocessing.get_context('spawn');parent,child=ctx.Pipe(duplex=False);process=ctx.Process(target=_isolated_worker,args=(child,operation,args),daemon=True);process.start();child.close()
 try:
  if not parent.poll(max(0,deadline-time.monotonic())):raise AuditFetchError('operation_timeout')
  result=parent.recv()
  if not result.get('ok'):raise AuditFetchError(result.get('error','connection_failed'))
  return result['value']
 except (EOFError,OSError):raise AuditFetchError('connection_failed') from None
 finally:
  parent.close()
  if process.is_alive():process.terminate()
  process.join(timeout=.2)
  if process.is_alive():process.kill();process.join(timeout=.2)

def origin(url):
 u=urllib.parse.urlsplit(url);return urllib.parse.urlunsplit((u.scheme,u.netloc,'','',''))
def same_seed_redirect(old,new,initial):
 a=urllib.parse.urlsplit(initial);b=urllib.parse.urlsplit(new);previous=urllib.parse.urlsplit(old)
 return not (previous.scheme=='https' and b.scheme=='http') and not (previous.scheme==b.scheme and previous.port!=b.port) and a.hostname.removeprefix('www.')==b.hostname.removeprefix('www.') and (a.scheme==b.scheme or a.scheme=='http' and b.scheme=='https') and a.port in (None,80,443) and b.port in (None,80,443)
class FetchBudget:
 def __init__(self,usage=None,worker=isolated):
  self.usage=dict(usage or {'http_requests':0,'resources_requested':0,'bytes_received':0,'active_duration_ms':0,'model_calls':0});self.usage.setdefault('bytes_budget_used',self.usage['bytes_received']);self.worker=worker;self.started=time.monotonic();self.deadline=self.started+max(0,60-self.usage['active_duration_ms']/1000);self.admission=lambda:True
 def remaining(self):return self.deadline-time.monotonic()
 def run(self,op,args):
  if not self.admission():raise AuditFetchError('maintenance')
  timeout=min(10,self.remaining())
  if timeout<=0:raise AuditFetchError('deadline_exceeded')
  result=self.worker(op,args,timeout)
  if self.remaining()<=0:raise AuditFetchError('deadline_exceeded')
  return result
 def finish(self):
  self.usage['active_duration_ms']+=max(0,int((time.monotonic()-self.started)*1000));self.started=time.monotonic();return dict(self.usage)
 def fetch(self,url,kind='seed',seed_origin=None,permitted=None):
  requested=website_inspection.normalize_url(url);check=website_check.Check();check.value['final_url']=requested;check.check('address','passed','address_ok')
  r={'id':'resource-'+str(self.usage['resources_requested']+1),'requested_url':requested,'url':requested,'kind':kind,'status':None,'headers':{},'text':'','raw_html':'','parsed':None,'error':None,'captured_at':website_check.datetime.datetime.now(website_check.datetime.timezone.utc).isoformat()}
  def fail(code,outcome='unreachable'):
   r['error']=code
   messages={'deadline_exceeded':'达到审计累计60秒时限，未继续请求。','operation_timeout':'本次安全抓取或解析超时，未自动重试。','resource_budget_exceeded':'达到最多6个资源范围，未继续请求。','http_budget_exceeded':'达到最多10次HTTP请求范围，未继续请求。','bytes_budget_exceeded':'达到累计4MiB读取范围，未继续请求。','cross_origin_redirect':'拒绝跨出本次允许来源或降低HTTPS的跳转。','robots_disallowed':'辅助资源跳转被robots策略阻止，未请求该地址。','maintenance':'后台维护期间未提交新的抓取或解析。','audit_unavailable':'已锁定的审计解析依赖不可用。'}
   if code in website_check.MESSAGES:check.finding(code)
   else:check.value['findings'].append({'code':code if code in messages else 'connection_failed','message':messages.get(code,website_check.MESSAGES['connection_failed'])})
   field='tls' if code.startswith('tls_') else 'dns' if code=='dns_failed' else 'address' if code in ('unsafe_address','invalid_address','cross_origin_redirect','proxy_unsupported') else 'content' if code in ('unsupported_content','content_too_large','website_challenge') else 'http' if code in ('http_error','http_limited','http_blocked') else None
   if field:
    row=next(c for c in check.value['checks'] if c['id']==field);row.update(status='failed',message=website_check.MESSAGES.get(code,messages.get(code,website_check.MESSAGES['connection_failed'])))
   check.value['possible_access_restriction']=code in ('http_limited','http_blocked','website_challenge');r['diagnostics']=check.finish(outcome);return r
  if self.usage['resources_requested']>=6:return fail('resource_budget_exceeded')
  self.usage['resources_requested']+=1
  try:pinned_http.require_direct_policy()
  except ValueError:return fail('proxy_unsupported','unsafe')
  limit=2*1024*1024 if kind=='seed' else 512*1024;current=requested
  try:
   for _ in range(5):
    if self.usage['http_requests']>=10:raise AuditFetchError('http_budget_exceeded')
    current=website_inspection.normalize_url(current);r['url']=current;check.value.update(final_url=current,http_status=None)
    for row in check.value['checks']:
     if row['id'] in ('dns','tls','http','content'):row.update(status='unknown',message='尚无足够证据判断。')
    if seed_origin and origin(current)!=seed_origin:raise AuditFetchError('cross_origin_redirect')
    if permitted is not None and not permitted(current):raise AuditFetchError('robots_disallowed')
    u=urllib.parse.urlsplit(current);addresses=self.run('dns',(u.hostname,u.port or (443 if u.scheme=='https' else 80)))
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise AuditFetchError('unsafe_address')
    check.check('dns','passed','dns_ok')
    if u.scheme=='http':check.check('tls','skipped','tls_skipped')
    capacity=min(limit,max(0,MAX_BYTES-self.usage['bytes_budget_used']))
    if capacity<=0:raise AuditFetchError('bytes_budget_exceeded')
    self.usage['http_requests']+=1
    self.usage['bytes_budget_used']+=capacity
    response=self.run('http',(current,addresses,capacity,'text/markdown' if kind=='markdown' else 'text/html,text/plain,application/xhtml+xml',min(10,self.remaining())))
    raw=response['raw'];self.usage['bytes_budget_used']-=capacity-min(capacity,len(raw));self.usage['bytes_received']+=len(raw);r.update(status=response['status'],headers=response['headers']);check.value.update(http_status=r['status'],bytes=len(raw),content_type=website_check.content_type(r['headers'].get('Content-Type')))
    if u.scheme=='https':check.check('tls','passed','tls_ok')
    check.check('http','passed','http_ok')
    if len(raw)>capacity or response.get('truncated'):raise AuditFetchError('content_too_large' if capacity==limit else 'bytes_budget_exceeded')
    if r['status'] in (301,302,303,307,308) and r['headers'].get('Location'):
     next_url=website_inspection.normalize_url(urllib.parse.urljoin(current,r['headers']['Location']))
     check.value['redirects'].append({'url':current,'status':r['status'],'location':next_url})
     if kind=='seed' and not same_seed_redirect(current,next_url,requested) or kind!='seed' and origin(next_url)!=seed_origin:raise AuditFetchError('cross_origin_redirect')
     current=next_url;continue
    r['sha256']=hashlib.sha256(raw).hexdigest();r['text']=raw.decode('utf-8',errors='replace');check.value['retry_after']=website_check.safe_retry_after(r['headers'].get('Retry-After'))
    if not 200<=r['status']<300:return fail('http_limited' if r['status']==429 else 'http_blocked' if r['status']==403 else 'http_error','limited' if r['status']==429 else 'blocked' if r['status']==403 else 'unreachable')
    ctype=check.value['content_type']
    if kind in ('seed','about'):
     if ctype not in ('text/html','application/xhtml+xml'):return fail('unsupported_content','unsupported')
     r['raw_html']=r['text'];r['parsed']=self.run('parse',(r['raw_html'],current));parsed=r['parsed'];check.value['readable_characters']=parsed['metadata'].get('readable_characters',0)
     if website_check.challenge(r['raw_html'],parsed['metadata']):r['parsed']=None;return fail('website_challenge','challenge')
     if check.value['readable_characters']<100 and len(parsed.get('extracted_text') or '')<100:
      check.check('content','unknown','content_too_short');check.finding('content_too_short');r['diagnostics']=check.finish('metadata_only');return r
     check.check('content','passed','content_ok')
    elif ctype not in ('text/plain','text/markdown','text/x-markdown'):return fail('unsupported_content','unsupported')
    r['diagnostics']=check.finish('readable');return r
   raise AuditFetchError('redirect_limit')
  except AuditFetchError as error:return fail(error.code,'unsafe' if error.code in ('unsafe_address','cross_origin_redirect') else 'unsupported' if error.code in ('content_too_large','redirect_limit') else 'unreachable')
  except (ValueError,OSError):return fail('invalid_address','unsafe')
