"""Single team HTTPS edge (TLS terminates at the hosting platform)."""
import base64, html, collections, datetime, hashlib, hmac, http.server, json, os, pathlib, re, secrets, socketserver, threading, time, urllib.error, urllib.parse, urllib.request
from brand_enrichment import EnrichmentError
from geo_audit import AuditError
from device_sessions import DeviceSessions,StoreUnavailable,SessionLimit,GenerationChanged,MAX_AGE
ORIGIN='https://saml1nhchen-ops.github.io'
UUID=re.compile(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\Z')
class Failure(Exception):
 def __init__(self,status,code): self.status=status;self.code=code
class LocalAPI:
 def __init__(self): self.tokens={};self.lock=threading.Lock()
 def call(self,service,path,body=None):
  port,prefix={'geo':(8772,'/api/geo/'),'bai':(8771,'/api/bai/'),'native':(8770,'/api/tools/')}[service]
  base=f'http://127.0.0.1:{port}{prefix}'
  with self.lock:
   if service not in self.tokens:
    req=urllib.request.Request(base+'session',headers={'Sec-Fetch-Site':'same-origin'})
    with urllib.request.urlopen(req,timeout=5) as r:self.tokens[service]=json.load(r)['token']
   token=self.tokens[service]
  req=urllib.request.Request(base+path,None if body is None else json.dumps(body).encode(),{'Authorization':'Bearer '+token,'Content-Type':'application/json'})
  try:
   with urllib.request.urlopen(req,timeout=130 if body is not None else 10) as r:return json.load(r)
  except urllib.error.HTTPError as e:
   if e.code==401:
    with self.lock:self.tokens.pop(service,None)
   # Preserve safe status semantics without reading or forwarding the error body.
   # Never replay POST: its outcome may already be billed.
   codes={400:'invalid_request',404:'not_found',409:'busy',429:'rate_limited'}
   raise Failure(e.code if e.code in codes else 502,codes.get(e.code,'upstream_failed')) from None
  except (OSError,ValueError):raise Failure(502,'upstream_failed') from None
class Budget:
 def __init__(self,path,limit):self.path=pathlib.Path(path);self.limit=limit;self.lock=threading.RLock()
 def records(self):
  try:
   if not self.path.exists():return {}
   d=json.loads(self.path.read_text())
   if not isinstance(d,dict) or any(not re.fullmatch(r'\d{4}-\d{2}-\d{2}',k) or type(v)!=int or v<0 for k,v in d.items()):raise ValueError()
   return d
  except (OSError,ValueError):raise Failure(503,'budget_unavailable') from None
 def state(self):
  with self.lock:
   day=datetime.datetime.now(datetime.timezone.utc).date().isoformat();n=self.records().get(day,0)
   return {'date':day,'limit':self.limit,'reserved':n,'remaining':max(0,self.limit-n)}
 def reserve(self,n):
  with self.lock:
   d=self.records();s=self.state()
   if n>s['remaining']:raise Failure(429,'daily_budget_exceeded')
   d[s['date']]=s['reserved']+n
   tmp=self.path.with_name(self.path.name+'.'+secrets.token_hex(8)+'.tmp')
   try:
    self.path.parent.mkdir(parents=True,exist_ok=True)
    with tmp.open('x') as f:json.dump(d,f);f.flush();os.fsync(f.fileno())
    os.replace(tmp,self.path)
    fd=os.open(self.path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
   except OSError:raise Failure(503,'budget_unavailable') from None
   finally:
    try:tmp.unlink(missing_ok=True)
    except OSError:pass
class Workspace:
 def __init__(self,password,host,budget,api=None,session_store=None):
  if len(password)<16:raise ValueError('Workspace password must contain at least 16 characters')
  parts=host.split(':')
  if len(parts)>2 or len(parts)==2 and (not parts[1].isdigit() or not 1<=int(parts[1])<=65535) or len(parts[0])>253 or any(not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?',label) for label in parts[0].split('.')):raise ValueError('Invalid public host')
  self.digest=hashlib.sha256(password.encode()).digest();self.host=host.lower();self.budget=budget;self.api=api or LocalAPI();self.lock=threading.RLock();self.sessions={};self.attempts=collections.defaultdict(collections.deque);self.global_attempts=collections.deque();self.ready=False;self.reason='missing_bai_key';self.profiles=[];self.closing=False;self.active=None;self.shutdown_requested=threading.Event();self.maintenance_requested=threading.Event();self.session_store=session_store;self.enrich_active=None;self.enricher=None;self.audit_active=None;self.auditor=None
 def begin_shutdown(self):
  self.shutdown_requested.set()
  # Serialize shutdown with the complete reserve/submit/active publication.
  with self.lock:self.closing=True
 def stopping(self):return self.closing or self.shutdown_requested.is_set()
 def require_admission(self):
  if self.maintenance_requested.is_set():raise Failure(503,'maintenance')
  if not self.ready or self.stopping():raise Failure(503,self.reason or 'backend_unavailable')
 def login(self,password,source,remember=False):
  with self.lock:
   now=time.time()
   for q in (self.attempts[source],self.global_attempts):
    while q and q[0]<=now-900:q.popleft()
   if len(self.attempts[source])>=5 or len(self.global_attempts)>=30:raise Failure(429,'rate_limited')
   self.attempts[source].append(now);self.global_attempts.append(now)
   if not isinstance(password,str) or not hmac.compare_digest(hashlib.sha256(password.encode()).digest(),self.digest):raise Failure(401,'unauthorized')
   self.sessions={t:e for t,e in self.sessions.items() if e>now}
   if remember:
    if self.session_store is None:raise Failure(503,'session_store_unavailable')
    try:token,expires=self.session_store.issue(len(self.sessions),now)
    except SessionLimit:raise Failure(429,'session_limit_reached') from None
    except (StoreUnavailable,GenerationChanged):raise Failure(503,'session_store_unavailable') from None
   else:
    if len(self.sessions)>=32:raise Failure(429,'rate_limited')
    if self.session_store is not None:
     try:self.session_store.check_capacity(len(self.sessions),now)
     except SessionLimit:raise Failure(429,'session_limit_reached') from None
     except (StoreUnavailable,GenerationChanged):pass # Explicit legacy login stays available.
    token=secrets.token_urlsafe(32);expires=now+3600;self.sessions[token]=expires
   return {'token':token,'expires_at':datetime.datetime.fromtimestamp(expires,datetime.timezone.utc).isoformat(),'remembered':remember,'workspace':{'mode':'shared_team','shared_reports':True}}
 def auth(self,value):
  token=value[7:] if value.startswith('Bearer ') else ''
  if not token or len(token)>256:raise Failure(401,'unauthorized')
  with self.lock:
   if token.startswith('td1_'):
    if self.session_store is None:raise Failure(503,'session_store_unavailable')
    try:valid=self.session_store.authenticate(token)
    except GenerationChanged:valid=False
    except StoreUnavailable:raise Failure(503,'session_store_unavailable') from None
    if not valid:raise Failure(401,'unauthorized')
   elif self.sessions.get(token,0)<=time.time():self.sessions.pop(token,None);raise Failure(401,'unauthorized')
  return token
 def logout(self,token):
  with self.lock:
   if token.startswith('td1_'):
    if self.session_store is None:raise Failure(503,'session_store_unavailable')
    try:self.session_store.revoke(token)
    except (StoreUnavailable,GenerationChanged):raise Failure(503,'session_store_unavailable') from None
   else:self.sessions.pop(token,None)
 def redact_text(self,value):
  # Treat public response fields AND dictionary keys as untrusted strings.
  # Do not decode whole responses: preserve evidence text except secret variants.
  for name in ('SIGNAL_BAI_API_KEY','SIGNAL_WORKSPACE_PASSWORD'):
   secret=os.environ.get(name)
   if not secret:continue
   variants={secret,urllib.parse.quote(secret,safe=''),urllib.parse.quote_plus(secret),json.dumps(secret,ensure_ascii=True)[1:-1],html.escape(secret),base64.b64encode(secret.encode()).decode(),base64.urlsafe_b64encode(secret.encode()).decode()}
   variants|={v.rstrip('=') for v in tuple(variants)}
   variants|={urllib.parse.quote(v,safe='') for v in tuple(variants)}
   for variant in sorted(variants,key=len,reverse=True):
    if variant:value=re.sub(re.escape(variant),'[REDACTED]',value,flags=re.I)
   # Also cover mixed raw/percent-encoded characters and percent hex casing.
   pattern=''.join('(?:'+re.escape(c)+'|'+re.escape(''.join('%'+format(b,'02X') for b in c.encode()))+')' for c in secret)
   value=re.sub(pattern,'[REDACTED]',value,flags=re.I)
  return value
 def sanitize(self,value):
  # Raw provider errors and authentication metadata never cross the edge.
  hidden={'key','token','authorization','apikey','headers','requestheaders','password','secret','secretkey','accesstoken','credential','credentials'}
  if isinstance(value,dict):return {self.redact_text(k):('模型调用失败；详情保留在服务器证据中' if k.lower()=='error' and v else self.sanitize(v)) for k,v in value.items() if re.sub(r'[^a-z0-9]','',k.lower()) not in hidden}
  if isinstance(value,list):return [self.sanitize(v) for v in value]
  if isinstance(value,str):return self.redact_text(value)
  return value
 def validate(self,path,d):
  common={'website','market','brand_aliases','skus','competitors','focus','context','count','repeats','providers','generator'}
  fields={'inspect':{'website','market'},'start':common|{'generate_only'},'sample':common|{'prompts'},'plan':common|{'generate_only','manual'},'analyze':{'id','brand_aliases','skus','competitors'},'stop':{'id'}}
  if set(d)-fields[path]:raise Failure(400,'invalid_request')
  if path in ('analyze','stop'):
   if not isinstance(d.get('id'),str) or not UUID.fullmatch(d['id']):raise Failure(400,'invalid_request')
   return
  if d.get('market') not in ('CN','US') or not isinstance(d.get('website'),str):raise Failure(400,'invalid_request')
  if path=='inspect':return
  if type(d.get('count',30))!=int or d.get('count',30)!=30 or type(d.get('repeats',1))!=int or d.get('repeats',1)!=1:raise Failure(400,'invalid_request')
  ids=d.get('providers');allowed={p['id'] for p in self.profiles}
  if not isinstance(ids,list) or not 1<=len(ids)<=2 or any(not isinstance(p,str) or p not in allowed for p in ids) or len(set(ids))!=len(ids) or d.get('generator') not in ids:raise Failure(400,'invalid_request')
  for k in ('generate_only','manual'):
   if k in d and type(d[k])!=bool:raise Failure(400,'invalid_request')
  if path=='sample':
   import geo_plan
   ps=d.get('prompts')
   if not isinstance(ps,list) or len(ps)!=30 or any(not isinstance(p,str) or not p.strip() or len(p)>4000 for p in ps) or len({geo_plan.question_key(p) for p in ps})!=30:raise Failure(400,'invalid_request')
  d['count']=30;d['repeats']=1
 def dispatch(self,path,d=None):
  if path=='state':
   # Same lock as reservation/submission/publication. Once maintenance+idle is
   # observable, no earlier admitted POST can still publish a queued task.
   with self.lock:
    s=self.api.call('geo','state')
    if self.enrich_active or self.audit_active:s['busy']=True
    if self.active and not s['busy']:
     previous=self.api.call('geo','run?id='+self.active)
     if previous.get('status') in ('queued','running'):s['busy']=True
     else:self.active=None
    maintenance=self.maintenance_requested.is_set()
    s['runner']['profiles']=self.profiles;s['runner']['configured']=self.ready;s['runner']['fetched_at']=getattr(self,'fetched_at',None)
    s['remote']={'mode':'shared_team','shared_reports':True,'ready':self.ready and not self.stopping() and not maintenance,'model_ready':self.ready,'maintenance':maintenance,'deployment_gate':'signals-v1','reason':'maintenance' if maintenance else self.reason,'limits':{'count':30,'max_models':2,'repeats':1},'budget':self.budget.state()};return s,200
  if path.startswith('audit'):
   if self.auditor is None:raise Failure(503,'audit_unavailable')
   try:
    if d is None:
     ident=urllib.parse.parse_qs(path.split('?',1)[1])['id'][0]
     return self.auditor.get(ident,export=path.startswith('audit-export?')),200
    with self.lock:
     if path=='audit':
      if not isinstance(d,dict) or set(d)-{'website','market','request_id','refresh'} or not {'website','market','request_id'}<=set(d) or d.get('market') not in ('CN','US') or type(d.get('refresh',False))!=bool or not isinstance(d.get('request_id'),str) or not UUID.fullmatch(d['request_id']):raise Failure(400,'invalid_request')
      import website_inspection
      url=website_inspection.normalize_url(d['website'])
      if self.redact_text(url)!=url:raise Failure(400,'invalid_request')
      cached=self.auditor.lookup(d['request_id'],url,d['market'],d.get('refresh',False))
      if cached:return cached,200
     elif path=='audit-confirm':
      if set(d)!={'id','confirmed'} or not isinstance(d['id'],str) or not UUID.fullmatch(d['id']) or self.redact_text(json.dumps(d,ensure_ascii=False))!=json.dumps(d,ensure_ascii=False):raise Failure(400,'invalid_request')
     else:raise Failure(404,'not_found')
     if self.stopping() or self.maintenance_requested.is_set():raise Failure(503,'maintenance')
     if self.audit_active or self.enrich_active or self.api.call('geo','state')['busy']:raise Failure(409,'busy')
     if self.active and self.api.call('geo','run?id='+self.active).get('status') in ('queued','running'):raise Failure(409,'busy')
     if path=='audit-confirm':return self.auditor.confirm(d['id'],d['confirmed'])
     return self.auditor.start(d['request_id'],url,d['market']),202
   except AuditError as error:raise Failure(error.status,error.code) from None
  if path.startswith('enrich'):
   if self.enricher is None:raise Failure(503,'enrichment_store_unavailable')
   try:
    if d is None:return self.enricher.get(urllib.parse.parse_qs(path.split('?',1)[1])['id'][0]),200
    if set(d)!={'website','market','request_id'} or d.get('market') not in ('CN','US') or not isinstance(d.get('request_id'),str) or not UUID.fullmatch(d['request_id']):raise Failure(400,'invalid_request')
    import website_inspection
    url=website_inspection.normalize_url(d['website'])
    if self.redact_text(url)!=url:raise Failure(400,'invalid_request')
    with self.lock:
     cached=self.enricher.lookup(d['request_id'],url,d['market'])
     if cached:return cached,200
     if self.stopping() or self.maintenance_requested.is_set():raise Failure(503,'maintenance')
     if self.enrich_active or self.audit_active or self.api.call('geo','state')['busy']:raise Failure(409,'busy')
     if self.active and self.api.call('geo','run?id='+self.active).get('status') in ('queued','running'):raise Failure(409,'busy')
     return self.enricher.start(d['request_id'],url,d['market']),202
   except EnrichmentError as error:raise Failure(error.status,error.code) from None
  if d is None:return self.api.call('geo',path),200
  name=path;self.validate(name,d)
  if name=='plan':
   with self.lock:
    self.require_admission();result=self.api.call('geo',name,d);self.require_admission();return result,200
  if name in ('start','sample'):
   with self.lock:
    self.require_admission()
    if self.enrich_active or self.audit_active:raise Failure(409,'busy')
    s=self.api.call('geo','state')
    if s['busy']:raise Failure(409,'busy')
    if self.active:
     previous=self.api.call('geo','run?id='+self.active)
     if previous.get('status') in ('queued','running'):raise Failure(409,'busy')
     self.active=None
    plan=self.api.call('geo','plan',{**d,'manual':name=='sample',**({'generate_only':False} if name=='sample' else {})})
    expected=(0 if name=='sample' else 3)+(0 if d.get('generate_only') else 30*len(d['providers']))
    if plan.get('maximum_calls')!=expected:raise Failure(503,'backend_unavailable')
    self.require_admission()
    self.budget.reserve(expected)
    self.require_admission()
    result=self.api.call('geo',name,d);self.active=result['id'];return result,202
  return self.api.call('geo',name,d),201 if name=='analyze' else 200
class Server(http.server.ThreadingHTTPServer):
 daemon_threads=True;allow_reuse_address=True
 def __init__(self,address,workspace):self.workspace=workspace;self.slots=threading.BoundedSemaphore(32);super().__init__(address,Handler)
 def process_request(self,request,address):
  if not self.slots.acquire(False):request.close();return
  try:super().process_request(request,address)
  except Exception:self.slots.release();raise
 def process_request_thread(self,request,address):
  try:request.settimeout(10);super().process_request_thread(request,address)
  finally:self.slots.release()
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def reply(self,value,status=200):
  safe=self.server.workspace.sanitize(value)
  if status>=400 and value.get('error')==value.get('code') and re.fullmatch(r'[a-z_]{1,64}',value.get('code','')):safe['error']=value['code']
  if self.path=='/api/workspace/login' and status==200 and 'token' in value:safe['token']=value['token']
  data=json.dumps(safe,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(0 if status==204 else len(data)));self.send_header('Cache-Control','no-store');self.send_header('Vary','Origin');self.send_header('X-Content-Type-Options','nosniff')
  if self.headers.get('Origin')==ORIGIN:self.send_header('Access-Control-Allow-Origin',ORIGIN)
  if status==429:self.send_header('Retry-After','900' if value.get('code')=='rate_limited' else '86400')
  if self.command=='OPTIONS':self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS');self.send_header('Access-Control-Allow-Headers','Content-Type, Authorization')
  self.end_headers()
  if status!=204:self.wfile.write(data)
 def handle_api(self):
  w=self.server.workspace
  try:
   hosts=self.headers.get_all('Host',[])
   health_local=self.path=='/healthz' and self.command=='GET' and len(hosts)==1 and hosts[0] in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')
   if len(hosts)!=1 or hosts[0].lower()!=w.host and not health_local:raise Failure(403,'host_forbidden')
   origins=self.headers.get_all('Origin',[])
   if len(origins)>1 or origins and origins[0]!=ORIGIN:raise Failure(403,'origin_forbidden')
   u=urllib.parse.urlsplit(self.path)
   if u.scheme or u.netloc or u.fragment:raise Failure(400,'invalid_request')
   get={'/api/geo/state','/api/geo/run','/api/geo/export','/api/geo/enrich','/api/geo/audit','/api/geo/audit-export'};post={'/api/workspace/login','/api/workspace/logout',*[f'/api/geo/{p}' for p in ('inspect','plan','start','sample','analyze','stop','enrich','audit','audit-confirm')]}
   if self.command=='OPTIONS':
    if u.path not in get|post or not origins or self.headers.get('Access-Control-Request-Method') not in ('GET','POST') or any(h.strip().lower() not in ('content-type','authorization') for h in self.headers.get('Access-Control-Request-Headers','').split(',') if h.strip()):raise Failure(403,'origin_forbidden')
    return self.reply({},204)
   if u.path=='/healthz' and self.command=='GET' and not u.query:
    revision=os.environ.get('SIGNAL_BUILD_REVISION','unknown');version=os.environ.get('SIGNAL_BUILD_VERSION','unknown')
    if not re.fullmatch(r'[0-9a-f]{40}',revision):revision='unknown'
    if not re.fullmatch(r'[A-Za-z0-9._+-]{1,128}',version):version='unknown'
    metadata={k:v for k,v in (('revision',revision),('version',version)) if v!='unknown'}
    if w.session_store is not None and w.session_store.usable():metadata['capabilities']={'remember_login':True,'remember_login_max_age_seconds':MAX_AGE}
    return self.reply({'ok':not w.stopping(),**metadata},200 if not w.stopping() else 503)
   if u.path not in (get if self.command=='GET' else post):raise Failure(404,'not_found')
   if u.path in ('/api/geo/run','/api/geo/export','/api/geo/enrich','/api/geo/audit','/api/geo/audit-export') and self.command=='GET':
    q=urllib.parse.parse_qs(u.query,keep_blank_values=True,strict_parsing=True)
    if set(q)!={'id'} or len(q['id'])!=1 or not UUID.fullmatch(q['id'][0]):raise Failure(400,'invalid_request')
   elif u.query:raise Failure(400,'invalid_request')
   token=None
   if u.path!='/api/workspace/login':token=w.auth(self.headers.get('Authorization',''))
   d=None
   if self.command=='POST':
    sizes=self.headers.get_all('Content-Length',[])
    if self.headers.get('Transfer-Encoding') or len(sizes)!=1 or not re.fullmatch(r'[0-9]+',sizes[0]):raise Failure(400,'invalid_request')
    n=int(sizes[0]);limit=4096 if u.path.endswith('/login') else 256*1024
    if n>limit:raise Failure(413,'request_too_large')
    if n<1 or self.headers.get_content_type()!='application/json':raise Failure(400,'invalid_request')
    raw=self.rfile.read(n)
    if len(raw)!=n:raise Failure(400,'invalid_request')
    d=json.loads(raw)
    if not isinstance(d,dict):raise Failure(400,'invalid_request')
   if u.path=='/api/workspace/login':
    if 'password' not in d or set(d)-{'password','remember'} or 'remember' in d and type(d['remember'])!=bool:raise Failure(400,'invalid_request')
    return self.reply(w.login(d['password'],self.client_address[0],d.get('remember',False)))
   if u.path=='/api/workspace/logout':
    if d:raise Failure(400,'invalid_request')
    w.logout(token)
    return self.reply({'ok':True})
   path=u.path.removeprefix('/api/geo/')+('?' +u.query if u.query else '')
   result,status=w.dispatch(path,d);self.reply(result,status)
  except Failure as e:self.reply({'error':e.code,'code':e.code},e.status)
  except (ValueError,TypeError,KeyError):self.reply({'error':'invalid_request','code':'invalid_request'},400)
  except Exception:self.reply({'error':'backend_unavailable','code':'backend_unavailable'},503)
 do_GET=handle_api;do_POST=handle_api;do_OPTIONS=handle_api
