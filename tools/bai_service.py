"""B.AI connector on its own loopback port, preserving existing runner sessions.

No subscriptions, purchases, automatic routing, automatic retries or key persistence.
"""
import concurrent.futures,datetime,hashlib,http.server,ipaddress,json,pathlib,re,secrets,socket,threading,time,urllib.error,urllib.parse,urllib.request,uuid
import ai_api as shared
ROOT=pathlib.Path(__file__).resolve().parents[1];PORT=8771;TOKEN=secrets.token_urlsafe(32)
SITE='https://signal-geo-workbench-lh.saml1nhchen.chatgpt.site'
BASE='https://api.b.ai/v1';KEY='';MODELS=[];PROFILES={};FETCHED=None
LOCK=threading.RLock();POOL=concurrent.futures.ThreadPoolExecutor(max_workers=2)
def remote(path,key,body=None):
 if path not in ('/models','/chat/completions','/responses','/messages'):raise ValueError('Unsupported endpoint')
 if any(not ipaddress.ip_address(x[4][0]).is_global for x in socket.getaddrinfo('api.b.ai',443)):raise ValueError('Invalid provider address')
 headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'}
 if path=='/messages':headers['anthropic-version']='2023-06-01'
 req=urllib.request.Request(BASE+path,None if body is None else json.dumps(body).encode(),headers,method='GET' if body is None else 'POST')
 try:
  with urllib.request.build_opener(shared.NoRedirect).open(req,timeout=120) as r:
   data=r.read(8*1024*1024+1)
   if len(data)>8*1024*1024:raise ValueError('Response exceeds 8 MB')
   value=json.loads(data)
   if value.get('error') or value.get('success') is False:raise ValueError('B.AI returned an API error')
   return value
 except urllib.error.HTTPError as e:raise ValueError('B.AI HTTP '+str(e.code)+'; check key, balance, permissions and protocol') from None
 except urllib.error.URLError:raise ValueError('B.AI connection failed or timed out') from None
def state():
 with LOCK:return {'configured':bool(KEY),'models':MODELS,'profiles':list(PROFILES.values()),'fetched_at':FETCHED,'base_url':BASE,'billing':'按 API 用量消耗 Credits；不购买订阅，不自动充值'}
def connect(payload):
 global KEY,MODELS,FETCHED
 key=payload.get('key','').strip()
 if not key or len(key)>4096 or any(c in key for c in '\r\n'):raise ValueError('Enter a B.AI API key')
 result=remote('/models',key)
 models=[]
 for x in result.get('data',[]):
  mid=x.get('id') if isinstance(x,dict) else None
  if isinstance(mid,str) and 0<len(mid)<=200 and key not in mid:
   models.append({'id':mid,'name':str(x.get('name') or mid)[:200].replace(key,'[REDACTED]')})
 if not models:raise ValueError('No accessible models returned; existing connection kept')
 with LOCK:KEY=key;MODELS=models;FETCHED=shared.stamp();PROFILES.clear()
 return state()
def profile(payload):
 model=payload.get('model');protocol=payload.get('protocol','chat');markets=payload.get('markets',[]);search=bool(payload.get('search'))
 with LOCK:
  if not KEY:raise ValueError('Connect your B.AI key first')
  if model not in {m['id'] for m in MODELS}:raise ValueError('Choose a model returned for this API key')
  if protocol not in ('chat','responses','anthropic'):raise ValueError('Unsupported protocol')
  if not markets or any(m not in ('CN','US') for m in markets):raise ValueError('Choose CN and/or US market')
  if model.casefold()=='auto':raise ValueError('Choose a fixed model, not Auto')
  if search and (protocol=='chat' or 'deepseek' in model.casefold()):raise ValueError('Use a supported Responses/Messages model for search; DeepSeek search is unsupported')
  pid='bai-'+hashlib.sha256((model+'|'+protocol+'|'+str(search)).encode()).hexdigest()[:16]
  name=str(payload.get('name') or model).strip()[:120]
  if not name or KEY in name:raise ValueError('Enter a model display name')
  PROFILES[pid]={'id':pid,'name':name,'model':model,'protocol':protocol,'markets':sorted(set(markets)),'search':search,'provider':'bai','base_url':BASE}
 return state()
def run_path(rid):
 if not re.fullmatch(r'[a-f0-9-]{36}',rid):raise ValueError('Invalid run ID')
 return ROOT/'runtime/bai-runs'/rid
def get_run(rid,export=False):
 base=run_path(rid);data=json.loads((base/'run.json').read_text('utf-8'))
 if export:data['raw_evidence']={p.name:json.loads(p.read_text('utf-8')) for p in base.glob('*-raw.json')}
 return data
def list_runs():
 root=ROOT/'runtime/bai-runs'
 return [json.loads(p.read_text('utf-8')) for p in sorted(root.glob('*/run.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:30]]
def prepare(payload):
 market=payload.get('market');ids=payload.get('providers',[]);prompts=payload.get('prompts',[]);aliases=payload.get('brand_aliases',[]);skus=payload.get('skus',[])
 if market not in ('CN','US'):raise ValueError('Select CN or US')
 if not isinstance(ids,list) or not 1<=len(ids)<=16 or len(ids)!=len(set(ids)):raise ValueError('Select 1–16 unique models')
 if not isinstance(prompts,list) or not 1<=len(prompts)<=10 or len(ids)*len(prompts)>64 or any(not isinstance(x,str) or not x.strip() or len(x)>4000 for x in prompts):raise ValueError('Use 1–10 questions and at most 64 calls')
 if not isinstance(aliases,list) or not aliases or any(not isinstance(a,str) or not a.strip() or len(a)>200 for a in aliases):raise ValueError('Enter brand aliases')
 if not isinstance(skus,list) or len(skus)>50:raise ValueError('At most 50 SKUs')
 for s in skus:
  if not isinstance(s,dict) or not isinstance(s.get('name'),str) or not s['name'].strip() or not isinstance(s.get('aliases'),list) or not s['aliases'] or any(not isinstance(a,str) or not a.strip() or len(a)>200 for a in s['aliases']):raise ValueError('Each SKU needs a name and exact aliases')
 if len({s['name'] for s in skus})!=len(skus):raise ValueError('SKU names must be unique')
 with LOCK:
  if not KEY:raise ValueError('B.AI key not connected')
  profiles={}
  for pid in ids:
   p=PROFILES.get(pid)
   if not p or market not in p['markets']:raise ValueError('Selected model is unavailable for this market')
   profiles[pid]=dict(p)
  key=KEY
 return profiles,key
def start(payload,pool=POOL):
 profiles,key=prepare(payload);rid=str(uuid.uuid4());base=run_path(rid);base.mkdir(parents=True)
 run={k:payload.get(k) for k in ('market','providers','prompts','brand_aliases','skus','website')}
 run.update({'id':rid,'entry_type':'model_api','channel':'bai','created_at':shared.stamp(),'status':'queued','planned':len(run['providers'])*len(run['prompts']),'configuration':profiles,'samples':[],'summary':[],'methodology':'api-mention-v1; complete unprompted exact-alias mention rate; coverage reported; not recommendation rank or consumer-app measurement'})
 shared.save(base/'run.json',run);pool.submit(execute,run,key,base);return {'id':rid,'status':'queued','planned':run['planned']}
def execute(run,key,base):
 def redact(obj):
  if isinstance(obj,str):return obj.replace(key,'[REDACTED]')
  if isinstance(obj,list):return [redact(x) for x in obj]
  if isinstance(obj,dict):return {k:redact(v) for k,v in obj.items()}
  return obj
 run['status']='running';shared.save(base/'run.json',run)
 try:
  for pid in run['providers']:
   p=run['configuration'][pid]
   for n,prompt in enumerate(run['prompts']):
    s={'provider':pid,'channel':'bai','protocol':p['protocol'],'model_requested':p['model'],'question_index':n,'prompt':prompt,'captured_at':shared.stamp(),'status':'failed','entry_type':'model_api','brand_prompted':bool(shared.mention(prompt,run['brand_aliases'])),'search_requested':p['search']};t=time.monotonic()
    try:
     url,h,body=shared.request_for(p,{'base_url':BASE,'key':key,'model':p['model'],'search':p['search']},prompt)
     if p['protocol']=='responses':body.pop('store',None)
     raw=remote(url.removeprefix(BASE),key,body);s.update(shared.parse(p,raw));s['status']='complete' if s['complete'] else 'incomplete'
     s['brand_match']=shared.mention(s['answer'],run['brand_aliases']);s['sku_matches']={k['name']:shared.mention(s['answer'],k['aliases']) for k in run.get('skus') or []};s['sku_prompted']={k['name']:bool(shared.mention(prompt,k['aliases'])) for k in run.get('skus') or []}
     file=base/(pid+'-'+str(n)+'-raw.json');s['raw_sha256']=shared.save(file,redact(raw));s['raw_file']=file.name
    except Exception as e:s['error']=str(e) if isinstance(e,ValueError) else 'API request/response processing failed'
    s['latency_ms']=round(1000*(time.monotonic()-t));run['samples'].append(redact(s));run['summary']=shared.aggregate(run['samples'],run['providers'],run.get('skus') or []);shared.save(base/'run.json',redact(run))
  run['status']='finished';run['finished_at']=shared.stamp();shared.save(base/'run.json',redact(run))
 except Exception:run['status']='failed';run['error']='Local processing interrupted; existing evidence retained';shared.save(base/'run.json',redact(run))
def clear():
 global KEY,MODELS,FETCHED
 with LOCK:KEY='';MODELS=[];FETCHED=None;PROFILES.clear()
 return state()
class Handler(http.server.SimpleHTTPRequestHandler):
 def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT/'dist'),**kwargs)
 def log_message(self,*args):pass
 def valid_origin(self):return self.headers.get('Origin') in (None,SITE,'http://127.0.0.1:8771','http://localhost:8771')
 def end_headers(self):
  origin=self.headers.get('Origin')
  if self.valid_origin() and origin:self.send_header('Access-Control-Allow-Origin',origin)
  self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');super().end_headers()
 def reply(self,value,status=200):
  data=json.dumps(value,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def auth(self):
  if not self.valid_origin() or not secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+TOKEN):self.reply({'error':'Open the B.AI local workbench to connect'},401);return False
  return True
 def do_GET(self):
  try:
   url=urllib.parse.urlsplit(self.path);q=urllib.parse.parse_qs(url.query)
   if url.path=='/api/bai/session':
    if self.headers.get('Sec-Fetch-Site')!='same-origin' or self.headers.get('Host') not in ('127.0.0.1:8771','localhost:8771'):return self.reply({'error':'Use same-origin local pairing'},403)
    return self.reply({'token':TOKEN})
   if url.path.startswith('/api/bai/'):
    if not self.auth():return
    if url.path=='/api/bai/state':return self.reply(state())
    if url.path=='/api/bai/runs':return self.reply({'runs':list_runs()})
    if url.path in ('/api/bai/run','/api/bai/export'):return self.reply(get_run(q['id'][0],url.path.endswith('/export')))
    return self.reply({'error':'Unknown B.AI endpoint'},404)
   if url.path.startswith('/api/'):return self.reply({'error':'This service runs B.AI only; other connections remain on port 8770'},404)
   return super().do_GET()
  except Exception as e:self.reply({'error':str(e) if isinstance(e,(ValueError,KeyError)) else 'Unable to read local state'},400)
 def do_POST(self):
  if not self.auth():return
  try:
   n=int(self.headers.get('Content-Length','0'))
   if not 0<n<=512*1024:raise ValueError('Body limit 512 KB')
   d=json.loads(self.rfile.read(n))
   if self.path=='/api/bai/connect':return self.reply(connect(d))
   if self.path=='/api/bai/profile':return self.reply(profile(d))
   if self.path=='/api/bai/run':return self.reply(start(d),202)
   if self.path=='/api/bai/clear':return self.reply(clear())
   return self.reply({'error':'Unknown B.AI endpoint'},404)
  except Exception as e:self.reply({'error':str(e) if isinstance(e,ValueError) else 'B.AI connection or configuration failed'},400)
if __name__=='__main__':
 print('Signal GEO B.AI: http://127.0.0.1:8771/#/w/demo/bai',flush=True)
 http.server.ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
