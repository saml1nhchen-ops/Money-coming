"""Single team HTTPS edge (TLS terminates at the hosting platform)."""
import collections, datetime, hashlib, hmac, http.server, json, os, pathlib, re, secrets, socketserver, threading, time, urllib.error, urllib.parse, urllib.request
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
 def __init__(self,password,host,budget,api=None):
  if len(password)<16:raise ValueError('Workspace password must contain at least 16 characters')
  parts=host.split(':')
  if len(parts)>2 or len(parts)==2 and (not parts[1].isdigit() or not 1<=int(parts[1])<=65535) or len(parts[0])>253 or any(not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?',label) for label in parts[0].split('.')):raise ValueError('Invalid public host')
  self.digest=hashlib.sha256(password.encode()).digest();self.host=host.lower();self.budget=budget;self.api=api or LocalAPI();self.lock=threading.RLock();self.sessions={};self.attempts=collections.defaultdict(collections.deque);self.global_attempts=collections.deque();self.ready=False;self.reason='missing_bai_key';self.profiles=[];self.closing=False;self.active=None;self.shutdown_requested=threading.Event()
 def begin_shutdown(self):
  self.shutdown_requested.set()
  # Serialize shutdown with the complete reserve/submit/active publication.
  with self.lock:self.closing=True
 def stopping(self):return self.closing or self.shutdown_requested.is_set()
 def login(self,password,source):
  with self.lock:
   now=time.time()
   for q in (self.attempts[source],self.global_attempts):
    while q and q[0]<=now-900:q.popleft()
   if len(self.attempts[source])>=5 or len(self.global_attempts)>=30:raise Failure(429,'rate_limited')
   self.attempts[source].append(now);self.global_attempts.append(now)
   if not isinstance(password,str) or not hmac.compare_digest(hashlib.sha256(password.encode()).digest(),self.digest):raise Failure(401,'unauthorized')
   self.sessions={t:e for t,e in self.sessions.items() if e>now}
   if len(self.sessions)>=32:raise Failure(429,'rate_limited')
   token=secrets.token_urlsafe(32);expires=now+3600;self.sessions[token]=expires
   return {'token':token,'expires_at':datetime.datetime.fromtimestamp(expires,datetime.timezone.utc).isoformat(),'workspace':{'mode':'shared_team','shared_reports':True}}
 def auth(self,value):
  token=value[7:] if value.startswith('Bearer ') else ''
  with self.lock:
   if self.sessions.get(token,0)<=time.time():self.sessions.pop(token,None);raise Failure(401,'unauthorized')
  return token
 def sanitize(self,value):
  # Raw provider errors are not part of the public contract.
  if isinstance(value,dict):return {k:('模型调用失败；详情保留在服务器证据中' if k=='error' and v else self.sanitize(v)) for k,v in value.items() if k.lower() not in ('key','token','authorization','api_key','headers','request_headers')}
  if isinstance(value,list):return [self.sanitize(v) for v in value]
  if isinstance(value,str):
   for name in ('SIGNAL_BAI_API_KEY','SIGNAL_WORKSPACE_PASSWORD'):
    secret=os.environ.get(name)
    if secret:value=value.replace(secret,'[REDACTED]')
  return value
 def validate(self,path,d):
  common={'website','market','brand_aliases','skus','competitors','focus','context','count','repeats','providers','generator'}
  fields={'inspect':{'website','market'},'start':common|{'generate_only'},'sample':common|{'prompts'},'plan':common|{'generate_only','manual'},'analyze':{'id','brand_aliases','skus','competitors'},'stop':{'id'}}
  if set(d)-fields[path]:raise Failure(400,'invalid_request')
  if path in ('analyze','stop'):
   if not isinstance(d.get('id'),str) or not UUID.fullmatch(d['id']):raise Failure(400,'invalid_request')
   return
  if d.get('market')!='US' or not isinstance(d.get('website'),str):raise Failure(400,'invalid_request')
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
   s=self.api.call('geo','state');s['runner']['profiles']=self.profiles;s['runner']['configured']=self.ready;s['runner']['fetched_at']=getattr(self,'fetched_at',None)
   s['remote']={'mode':'shared_team','shared_reports':True,'ready':self.ready and not self.stopping(),'reason':self.reason,'limits':{'count':30,'max_models':2,'repeats':1},'budget':self.budget.state()};return s,200
  if d is None:return self.api.call('geo',path),200
  name=path;self.validate(name,d)
  if name in ('start','sample','plan') and (not self.ready or self.stopping()):raise Failure(503,self.reason or 'backend_unavailable')
  if name in ('start','sample'):
   with self.lock:
    if self.stopping():raise Failure(503,'backend_unavailable')
    s=self.api.call('geo','state')
    if s['busy']:raise Failure(409,'busy')
    if self.active:
     previous=self.api.call('geo','run?id='+self.active)
     if previous.get('status') in ('queued','running'):raise Failure(409,'busy')
     self.active=None
    plan=self.api.call('geo','plan',{**d,'manual':name=='sample',**({'generate_only':False} if name=='sample' else {})})
    expected=(0 if name=='sample' else 3)+(0 if d.get('generate_only') else 30*len(d['providers']))
    if plan.get('maximum_calls')!=expected:raise Failure(503,'backend_unavailable')
    if self.stopping():raise Failure(503,'backend_unavailable')
    self.budget.reserve(expected)
    if self.stopping():raise Failure(503,'backend_unavailable')
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
   get={'/api/geo/state','/api/geo/run','/api/geo/export'};post={'/api/workspace/login','/api/workspace/logout',*[f'/api/geo/{p}' for p in ('inspect','plan','start','sample','analyze','stop')]}
   if self.command=='OPTIONS':
    if u.path not in get|post or not origins or self.headers.get('Access-Control-Request-Method') not in ('GET','POST') or any(h.strip().lower() not in ('content-type','authorization') for h in self.headers.get('Access-Control-Request-Headers','').split(',') if h.strip()):raise Failure(403,'origin_forbidden')
    return self.reply({},204)
   if u.path=='/healthz' and self.command=='GET' and not u.query:return self.reply({'ok':True},200 if not w.closing else 503)
   if u.path not in (get if self.command=='GET' else post):raise Failure(404,'not_found')
   if u.path in ('/api/geo/run','/api/geo/export'):
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
    if set(d)!={'password'}:raise Failure(400,'invalid_request')
    return self.reply(w.login(d['password'],self.client_address[0]))
   if u.path=='/api/workspace/logout':
    if d:raise Failure(400,'invalid_request')
    with w.lock:w.sessions.pop(token,None)
    return self.reply({'ok':True})
   path=u.path.removeprefix('/api/geo/')+('?' +u.query if u.query else '')
   result,status=w.dispatch(path,d);self.reply(result,status)
  except Failure as e:self.reply({'error':e.code,'code':e.code},e.status)
  except (ValueError,TypeError,KeyError):self.reply({'error':'invalid_request','code':'invalid_request'},400)
  except Exception:self.reply({'error':'backend_unavailable','code':'backend_unavailable'},503)
 do_GET=handle_api;do_POST=handle_api;do_OPTIONS=handle_api
