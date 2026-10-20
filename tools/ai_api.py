"""Explicit provider API adapters. Credentials live in process memory, evidence on disk.

API observations never imply consumer application visibility. No automatic retries,
fallbacks, fabricated responses, or client-provided headers/unchecked URL targets.
"""
import copy, datetime, hashlib, ipaddress, json, os, pathlib, re, socket, threading, time, unicodedata, urllib.error, urllib.parse, urllib.request, uuid

ROOT=pathlib.Path(__file__).resolve().parents[1]
CATALOG_PATH=ROOT/'dist/ai-providers.json'
CONFIG={}; LOCK=threading.RLock()

def catalog():return json.loads(CATALOG_PATH.read_text('utf-8'))
def provider(pid):
 p=next((p for p in catalog() if p['id']==pid),None)
 if not p:raise ValueError('Unknown API provider')
 return p
def stamp():return datetime.datetime.now(datetime.UTC).isoformat()
def save(path,obj):
 data=json.dumps(obj,ensure_ascii=False,indent=2).encode('utf-8')
 tmp=path.with_suffix('.tmp');tmp.write_bytes(data);tmp.replace(path)
 return hashlib.sha256(data).hexdigest()
def safe_endpoint(p,url):
 u=urllib.parse.urlsplit(url)
 if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.port not in (None,443):raise ValueError('API base URL must be HTTPS without credentials, query or fragment')
 hosts=p.get('hosts',[])
 if p['id']!='custom' and u.hostname not in hosts and not (p['id']=='qwen' and re.fullmatch(r'[a-zA-Z0-9-]+\.(cn-beijing|cn-hongkong|ap-southeast-1|us-east-1|eu-central-1|ap-northeast-1)\.maas\.aliyuncs\.com',u.hostname)):
  raise ValueError('Use an official host listed for this provider')
 return url.rstrip('/')
def config_public():
 with LOCK:
  return [{**p,'configured':bool(CONFIG.get(p['id'],{}).get('key')),'configuration':{k:v for k,v in CONFIG.get(p['id'],{}).items() if k!='key'}} for p in catalog()]
def configure(data):
 p=provider(data.get('provider'));pid=p['id']
 if data.get('clear'):
  with LOCK:CONFIG.pop(pid,None)
  return {'configured':False}
 key=data.get('key','').strip(); model=data.get('model','').strip()
 if not key or len(key)>4096 or any(c in key for c in '\r\n'):raise ValueError('Enter a valid provider API key')
 if not model or len(model)>200 or not re.fullmatch(r'[\w./:@+-]+',model):raise ValueError('Enter the exact model ID (Perplexity: preset name)')
 base=safe_endpoint(p,data.get('base_url') or p['base_url'])
 search=bool(data.get('search'))
 if search and not p.get('search'):raise ValueError('This adapter does not implement native web search')
 with LOCK:CONFIG[pid]={'key':key,'model':model,'base_url':base,'search':search}
 return {'configured':True}
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):return None
def http_json(url,headers,body):
 host=urllib.parse.urlsplit(url).hostname
 if any(not ipaddress.ip_address(x[4][0]).is_global for x in socket.getaddrinfo(host,443)):raise ValueError('API host must resolve to public addresses')
 req=urllib.request.Request(url,json.dumps(body).encode(),{'Content-Type':'application/json',**headers},method='POST')
 try:
  with urllib.request.build_opener(NoRedirect).open(req,timeout=120) as r:
   raw=r.read(8*1024*1024+1)
   if len(raw)>8*1024*1024:raise ValueError('Provider response exceeds 8 MB')
   return json.loads(raw)
 except urllib.error.HTTPError as e:
  # Do not echo provider error bodies, headers or URLs: they can contain secrets.
  raise ValueError('Provider HTTP '+str(e.code)+'; verify key, balance, model permissions and endpoint') from None
 except urllib.error.URLError:raise ValueError('Provider connection failed or timed out') from None
def request_for(p,c,prompt):
 base=c['base_url'];model=c['model'];search=c['search'];kind=p['protocol']
 headers={'Authorization':'Bearer '+c['key']}
 if kind=='responses':
  body={'model':model,'input':prompt,'max_output_tokens':4096,'store':False}
  if search:body['tools']=[{'type':'web_search'}]
  return base+'/responses',headers,body
 if kind=='perplexity':return base+'/agent',headers,{'preset':model,'input':prompt}
 if kind=='gemini':
  body={'contents':[{'role':'user','parts':[{'text':prompt}]}],'generationConfig':{'maxOutputTokens':4096}}
  if search:body['tools']=[{'google_search':{}}]
  return base+'/models/'+urllib.parse.quote(model,safe='')+':generateContent',{'x-goog-api-key':c['key']},body
 if kind=='anthropic':
  body={'model':model,'max_tokens':4096,'messages':[{'role':'user','content':prompt}]}
  if search:body['tools']=[{'type':'web_search_20250305','name':'web_search','max_uses':3}]
  return base+'/messages',{'x-api-key':c['key'],'anthropic-version':'2023-06-01'},body
 body={'model':model,'messages':[{'role':'user','content':prompt}],'stream':False}
 body['max_completion_tokens' if p['id']=='minimax' else 'max_tokens']=4096
 if search and p['id']=='qwen':body['enable_search']=True
 return base+'/chat/completions',headers,body
def parse(p,raw):
 kind=p['protocol'];text='';complete=False;citations=[];sources=[];search_observed=False
 def source(obj,target):
  if not isinstance(obj,dict):return
  u=obj.get('url') or obj.get('uri')
  if isinstance(u,str) and urllib.parse.urlsplit(u).scheme in ('http','https'):target.append({'url':u,'title':obj.get('title','')})
 if raw.get('error'):raise ValueError('Provider returned an API error')
 if kind in ('responses','perplexity'):
  complete=raw.get('status')=='completed'
  for item in raw.get('output',[]):
   if item.get('type')=='web_search_call' and item.get('status')=='completed':search_observed=True
   if item.get('type')=='search_results':
    search_observed=True
    for s in item.get('results',[]):source(s,sources)
   if item.get('type')=='message':
    for part in item.get('content',[]):
     if part.get('type')=='output_text':text+=part.get('text','')+'\n'
     for a in part.get('annotations',[]):source(a.get('url_citation',a),citations)
 elif kind=='gemini':
  c=(raw.get('candidates') or [{}])[0];complete=c.get('finishReason')=='STOP'
  text='\n'.join(x.get('text','') for x in c.get('content',{}).get('parts',[]) if not x.get('thought'))
  g=c.get('groundingMetadata',{});search_observed=bool(g.get('webSearchQueries') or g.get('groundingChunks'))
  for s in g.get('groundingChunks',[]):source(s.get('web',{}),sources)
  for support in g.get('groundingSupports',[]):
   for i in support.get('groundingChunkIndices',[]):
    chunks=g.get('groundingChunks',[])
    if isinstance(i,int) and 0<=i<len(chunks):source(chunks[i].get('web',{}),citations)
 elif kind=='anthropic':
  complete=raw.get('stop_reason')=='end_turn'
  for part in raw.get('content',[]):
   if part.get('type')=='text':
    text+=part.get('text','')+'\n'
    for a in part.get('citations',[]):source(a,citations)
   if part.get('type')=='web_search_tool_result' and isinstance(part.get('content'),list):
    search_observed=True
    for s in part['content']:source(s,sources)
 else:
  c=(raw.get('choices') or [{}])[0];m=c.get('message',{});content=m.get('content','')
  text=content if isinstance(content,str) else '\n'.join(x.get('text','') for x in content or [] if isinstance(x,dict))
  # Some providers include thinking inside content. Retain it in raw evidence only.
  text=re.sub(r'<think>.*?</think>','',text,flags=re.S)
  complete=c.get('finish_reason')=='stop'
  for a in m.get('annotations',[]):source(a.get('url_citation',a),citations)
  for u in raw.get('citations',[]):source({'url':u} if isinstance(u,str) else u,citations)
  for s in raw.get('search_results',[]):source(s,sources)
  search_observed=bool(sources)
  for s in raw.get('search_info',{}).get('search_results',[]):source(s,sources);search_observed=True
 return {'answer':text.strip(),'complete':complete and bool(text.strip()),'model_returned':raw.get('model') or raw.get('modelVersion'), 'usage':raw.get('usage') or raw.get('usageMetadata'),'citations':citations,'retrieved_sources':sources,'search_observed':search_observed,'citation_coverage':'returned_metadata_only'}
def normalize(s):return ' '.join(unicodedata.normalize('NFKC',s).casefold().replace('’',"'").split())
def mention(text,aliases):
 text=normalize(text)
 for alias in aliases:
  a=normalize(alias)
  if a and re.search((r'(?<!\w)' if a[0].isascii() and a[0].isalnum() else '')+re.escape(a)+(r'(?!\w)' if a[-1].isascii() and a[-1].isalnum() else ''),text):return alias
 return None
def validate_run(d):
 market=d.get('market');ids=d.get('providers');prompts=d.get('prompts');aliases=d.get('brand_aliases');skus=d.get('skus',[])
 if market not in ('CN','US'):raise ValueError('Select CN or US market')
 if not isinstance(ids,list) or not 1<=len(ids)<=16 or len(set(ids))!=len(ids):raise ValueError('Select 1–16 unique providers')
 if not isinstance(prompts,list) or not 1<=len(prompts)<=10 or any(not isinstance(x,str) or not x.strip() or len(x)>4000 for x in prompts):raise ValueError('Enter 1–10 questions, each under 4000 characters')
 if len(ids)*len(prompts)>64:raise ValueError('Maximum 64 calls per batch')
 if not isinstance(aliases,list) or not aliases or any(not isinstance(a,str) or not a.strip() or len(a)>200 for a in aliases):raise ValueError('Enter exact brand aliases')
 if not isinstance(skus,list) or len(skus)>50:raise ValueError('Maximum 50 SKU rows')
 for s in skus:
  if not isinstance(s,dict) or not isinstance(s.get('name'),str) or not s['name'].strip() or not isinstance(s.get('aliases'),list) or not s['aliases'] or any(not isinstance(a,str) or not a.strip() or len(a)>200 for a in s['aliases']):raise ValueError('Each SKU needs a name and exact aliases')
 if len({s['name'] for s in skus})!=len(skus):raise ValueError('SKU names must be unique within a batch')
 configs={}
 with LOCK:
  for pid in ids:
   p=provider(pid)
   if market not in p['markets']:raise ValueError(pid+': not listed for this market')
   if not CONFIG.get(pid,{}).get('key'):raise ValueError(pid+': API key/model not configured; no calls submitted')
   configs[pid]=copy.deepcopy(CONFIG[pid])
 return configs
def results_dir():
 p=ROOT/'runtime/ai-api-runs';p.mkdir(parents=True,exist_ok=True);return p
def get_run(rid):
 if not re.fullmatch(r'[a-f0-9-]{36}',rid):raise ValueError('Invalid run ID')
 return json.loads((results_dir()/rid/'run.json').read_text('utf-8'))
def list_runs():return [json.loads(p.read_text('utf-8')) for p in sorted(results_dir().glob('*/run.json'),key=lambda x:x.stat().st_mtime,reverse=True)[:30]]
def aggregate(samples,providers,skus):
 result=[]
 for pid in providers:
  allp=[s for s in samples if s['provider']==pid];ok=[s for s in allp if s['status']=='complete'];discovery=[s for s in ok if not s['brand_prompted']]
  sku_results=[]
  for k in skus:
   eligible=[s for s in discovery if not s.get('sku_prompted',{}).get(k['name'])];hits=sum(bool(s['sku_matches'].get(k['name'])) for s in eligible)
   sku_results.append({'name':k['name'],'mentions':hits,'denominator':len(eligible),'score':round(100*hits/len(eligible),1) if eligible else None})
  result.append({'provider':pid,'attempted':len(allp),'complete':len(ok),'discovery_complete':len(discovery),'brand_mention_score':round(100*sum(bool(s['brand_match']) for s in discovery)/len(discovery),1) if discovery else None,'skus':sku_results})
 return result
def start_run(d,pool):
 configs=validate_run(d);rid=str(uuid.uuid4());out=results_dir()/rid;out.mkdir();manifest={k:copy.deepcopy(d.get(k)) for k in ('market','providers','prompts','brand_aliases','skus','website')}
 manifest.update({'id':rid,'entry_type':'model_api','created_at':stamp(),'status':'queued','planned':len(d['providers'])*len(d['prompts']),'samples':[],'summary':[],'configuration':{pid:{k:v for k,v in c.items() if k!='key'} for pid,c in configs.items()},'methodology':'api-mention-v1: 100 × exact alias hits / complete unbranded answers; errors and truncated answers excluded, coverage reported; no consumer-app or market-population claim'})
 save(out/'run.json',manifest);pool.submit(execute_run,manifest,configs,out);return {'id':rid,'status':'queued','planned':manifest['planned']}
def execute_run(run,configs,out):
 run['status']='running';save(out/'run.json',run)
 secrets=[c['key'] for c in configs.values()]
 def redact(obj):
  if isinstance(obj,str):
   for secret in secrets:obj=obj.replace(secret,'[REDACTED]')
   return obj
  if isinstance(obj,list):return [redact(x) for x in obj]
  if isinstance(obj,dict):return {k:redact(v) for k,v in obj.items()}
  return obj
 try:
  for pid in run['providers']:
   p=provider(pid);c=configs[pid]
   for n,prompt in enumerate(run['prompts']):
    sample={'provider':pid,'question_index':n,'prompt':prompt,'captured_at':stamp(),'entry_type':'model_api','search_requested':c['search'],'brand_prompted':bool(mention(prompt,run['brand_aliases'])),'status':'failed'};started=time.monotonic()
    try:
     url,headers,body=request_for(p,c,prompt);raw=http_json(url,headers,body)
     sample.update(parse(p,raw));sample['status']='complete' if sample['complete'] else 'incomplete';sample['brand_match']=mention(sample['answer'],run['brand_aliases']);sample['sku_matches']={k['name']:mention(sample['answer'],k['aliases']) for k in run.get('skus') or []}
     rawfile=out/(pid+'-'+str(n)+'-raw.json');sample['raw_sha256']=save(rawfile,redact(raw));sample['raw_file']=rawfile.name
     # Exclude explicitly prompted SKU samples from that SKU's discovery scoring.
     sample['sku_prompted']={k['name']:bool(mention(prompt,k['aliases'])) for k in run.get('skus') or []}
    except Exception as e:sample['error']=redact(str(e) if isinstance(e,ValueError) else type(e).__name__+': request/response processing failed')
    sample['latency_ms']=round((time.monotonic()-started)*1000);run['samples'].append(redact(sample));run['summary']=aggregate(run['samples'],run['providers'],run.get('skus') or []);save(out/'run.json',redact(run))
  run['status']='finished';run['finished_at']=stamp();save(out/'run.json',redact(run))
 except Exception:
  run['status']='failed';run['error']='Batch interrupted by local processing error; completed evidence retained';save(out/'run.json',redact(run))
 finally:configs.clear()
