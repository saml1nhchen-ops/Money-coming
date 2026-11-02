"""Explicit provider API adapters. Credentials live in process memory, evidence on disk.

API observations never imply consumer application visibility. No automatic retries,
fallbacks, fabricated responses, or client-provided headers/unchecked URL targets.
"""
import copy, datetime, hashlib, ipaddress, json, os, pathlib, re, socket, threading, time, unicodedata, urllib.error, urllib.parse, urllib.request, uuid

ROOT=pathlib.Path(__file__).resolve().parents[1]
CONFIG={}; LOCK=threading.RLock()

import model_providers as registry
def catalog():return registry.catalog()
def provider(pid):return registry.provider(pid)
def resolved(p,route=None):
 c=CONFIG.get(p['id'])
 if c and route in (None,'auto','official'):return {**c,'route':'official','free':registry.model_is_free(p['routes'][0],c['model']),'protocol':p['protocol']}
 return registry.configuration(p,route=route)
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
  result=[]
  for p in catalog():
   c=resolved(p)
   routes=registry.route_status(p)
   if CONFIG.get(p['id']):routes[0].update({k:v for k,v in resolved(p,'official').items() if k!='key'},configured=True)
   result.append({**p,'routes':routes,'configured':bool(c),'status':'configured' if c else 'not configured','configuration':{k:v for k,v in (c or {'model':p['default_model'],'base_url':p['base_url'],'search':False}).items() if k!='key'}})
  return result
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
def env_int(name,default,minimum,maximum):
 try:return max(minimum,min(maximum,int(os.environ.get(name,str(default)))))
 except ValueError:return default
def max_output_tokens():return env_int('SIGNAL_MAX_TOKENS',3000,128,32768)
def call_timeout():return env_int('SIGNAL_CALL_TIMEOUT',90,1,600)
def http_json(url,headers,body):
 host=urllib.parse.urlsplit(url).hostname
 # Some egress proxies use RFC 2544 fake-IP DNS; permit only this range on opt-in.
 fake_ip_dns=os.environ.get('SIGNAL_ALLOW_FAKE_IP_DNS')=='1'
 fake_ip_range=ipaddress.ip_network('198.18.0.0/15')
 for entry in socket.getaddrinfo(host,443):
  address=ipaddress.ip_address(entry[4][0])
  if not address.is_global and not (fake_ip_dns and address in fake_ip_range):raise ValueError('API host must resolve to public addresses')
 req=urllib.request.Request(url,json.dumps(body).encode(),{'Content-Type':'application/json',**headers},method='POST')
 try:
  with urllib.request.build_opener(NoRedirect).open(req,timeout=call_timeout()) as r:
   raw=r.read(8*1024*1024+1)
   if len(raw)>8*1024*1024:raise ValueError('Provider response exceeds 8 MB')
   return json.loads(raw)
 except urllib.error.HTTPError as e:
  # Do not echo provider error bodies, headers or URLs: they can contain secrets.
  raise ValueError('Provider HTTP '+str(e.code)+'; verify key, balance, model permissions and endpoint') from None
 except urllib.error.URLError:raise ValueError('Provider connection failed or timed out') from None
def request_for(p,c,prompt):
 base=c['base_url'];model=c['model'];search=c['search'];kind=c.get('protocol',p['protocol']);tokens=max_output_tokens();fast=os.environ.get('SIGNAL_GEO_THINKING')!='1'
 headers={'Authorization':'Bearer '+c['key']}
 if kind=='responses':
  body={'model':model,'input':prompt,'max_output_tokens':tokens,'store':False}
  if fast and (model.startswith('gpt-5') and 'chat' not in model or re.match(r'^(o3|o4-mini|o1)(?:-20|$)',model)):body['reasoning']={'effort':'low'}
  if search:body['tools']=[{'type':'web_search'}]
  return base+'/responses',headers,body
 if kind=='perplexity':return base+'/agent',headers,{'preset':model,'input':prompt}
 if kind=='gemini':
  body={'contents':[{'role':'user','parts':[{'text':prompt}]}],'generationConfig':{'maxOutputTokens':tokens}}
  if fast and model.startswith('gemini-3'):body['generationConfig']['thinkingConfig']={'thinkingLevel':'low'}
  elif fast and model.startswith('gemini-2.5'):body['generationConfig']['thinkingConfig']={'thinkingBudget':128 if 'pro' in model else 0}
  if search:body['tools']=[{'google_search':{}}]
  return base+'/models/'+urllib.parse.quote(model,safe='')+':generateContent',{'x-goog-api-key':c['key']},body
 if kind=='anthropic':
  body={'model':model,'max_tokens':tokens,'messages':[{'role':'user','content':prompt}]}
  if search:body['tools']=[{'type':'web_search_20250305','name':'web_search','max_uses':3}]
  return base+'/messages',{'x-api-key':c['key'],'anthropic-version':'2023-06-01'},body
 body={'model':model,'messages':[{'role':'user','content':prompt}],'stream':False}
 body['max_completion_tokens' if p['id']=='minimax' and c.get('route','official')=='official' else 'max_tokens']=tokens
 if fast:
  pid=p['id'];route=c.get('route','official');lower=model.lower()
  if pid=='qwen' and route in ('official','siliconflow'):body['enable_thinking']=False
  if pid=='qwen' and route=='nvidia_nim' and 'instruct' not in lower:body['chat_template_kwargs']={'enable_thinking':False}
  # MiniMax M3.1 Flash requires thinking; use its supported low effort setting.
  if pid=='minimax' and 'm3.1' in lower:
   if route=='nvidia_nim':body['chat_template_kwargs']={'reasoning_effort':'low'}
   else:body['reasoning_effort']='low'
  elif pid=='minimax' and route=='tokenhub' and any(x in lower for x in ('m2.5','m2.7','m3')):body['thinking']={'type':'disabled'}
  if pid=='hunyuan' and route=='tokenhub' and lower.startswith(('hy3','hy4')):body['thinking']={'type':'disabled'}
  if (pid=='doubao' and route in ('official','tokenhub')) or (pid=='zhipu' and route=='official'):body['thinking']={'type':'disabled'}
  # TokenHub GLM rejects thinking disabled and reasoning_effort none.
  if pid=='zhipu' and route=='tokenhub':body['reasoning_effort']='low'
  if pid=='deepseek' and route in ('official','tokenhub'):
   if model=='deepseek-reasoner':body['model']='deepseek-chat'
   elif 'v4' in lower or 'v3.2' in lower:body['thinking']={'type':'disabled'}
  # TokenHub Kimi K3.x also supports disabling thinking.
  if pid=='kimi' and ((route in ('official','tokenhub') and any(x in lower for x in ('k2.5','k2.6'))) or (route=='tokenhub' and 'k3.' in lower)):body['thinking']={'type':'disabled'}
 if search and p['id']=='qwen':body['enable_search']=True
 return base+'/chat/completions',headers,body
def parse(p,raw):
 kind=p['protocol'];text='';complete=False;citations=[];sources=[];search_observed=False;answer_from_reasoning=False
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
  text=re.sub(r'<think\b[^>]*>.*?(?:</think\s*>|$)','',text,flags=re.S|re.I)
  if not text.strip():
   reasoning=m.get('reasoning_content') or m.get('reasoning')
   if isinstance(reasoning,str):
    text=re.sub(r'<think\b[^>]*>.*?(?:</think\s*>|$)','',reasoning,flags=re.S|re.I)
    answer_from_reasoning=bool(text.strip())
  complete=c.get('finish_reason')=='stop'
  for a in m.get('annotations',[]):source(a.get('url_citation',a),citations)
  for u in raw.get('citations',[]):source({'url':u} if isinstance(u,str) else u,citations)
  for s in raw.get('search_results',[]):source(s,sources)
  search_observed=bool(sources)
  for s in raw.get('search_info',{}).get('search_results',[]):source(s,sources);search_observed=True
 return {'answer':text.strip(),'answer_from_reasoning':answer_from_reasoning,'complete':complete and bool(text.strip()),'model_returned':raw.get('model') or raw.get('modelVersion'), 'usage':raw.get('usage') or raw.get('usageMetadata'),'citations':citations,'retrieved_sources':sources,'search_observed':search_observed,'citation_coverage':'returned_metadata_only'}
def normalize(s):return ' '.join(unicodedata.normalize('NFKC',s).casefold().replace('’',"'").split())
def mention(text,aliases):
 text=normalize(text)
 for alias in aliases:
  a=normalize(alias)
  if a and re.search((r'(?<!\w)' if a[0].isascii() and a[0].isalnum() else '')+re.escape(a)+(r'(?!\w)' if a[-1].isascii() and a[-1].isalnum() else ''),text):return alias
 return None
def validate_run(d):
 market=d.get('market');ids=d.get('providers') if d.get('providers') is not None else [p['id'] for p in catalog() if resolved(p)];prompts=d.get('prompts');aliases=d.get('brand_aliases');skus=d.get('skus',[])
 if market not in ('CN','US'):raise ValueError('Select CN or US market')
 if not isinstance(ids,list) or not 0<=len(ids)<=24 or len(set(ids))!=len(ids):raise ValueError('Select up to 24 unique providers')
 if not isinstance(prompts,list) or not 1<=len(prompts)<=10 or any(not isinstance(x,str) or not x.strip() or len(x)>4000 for x in prompts):raise ValueError('Enter 1–10 questions, each under 4000 characters')
 if not isinstance(aliases,list) or not aliases or any(not isinstance(a,str) or not a.strip() or len(a)>200 for a in aliases):raise ValueError('Enter exact brand aliases')
 if not isinstance(skus,list) or len(skus)>50:raise ValueError('Maximum 50 SKU rows')
 for s in skus:
  if not isinstance(s,dict) or not isinstance(s.get('name'),str) or not s['name'].strip() or not isinstance(s.get('aliases'),list) or not s['aliases'] or any(not isinstance(a,str) or not a.strip() or len(a)>200 for a in s['aliases']):raise ValueError('Each SKU needs a name and exact aliases')
 if len({s['name'] for s in skus})!=len(skus):raise ValueError('SKU names must be unique within a batch')
 for field in ('routes','models'):
  if field in d and (not isinstance(d[field],dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in d[field].items())):raise ValueError('Invalid '+field)
 configs={}
 with LOCK:
  for pid in ids:
   p=provider(pid)
   c=resolved(p,(d.get('routes') or {}).get(pid))
   if not c:continue
   c=copy.deepcopy(c)
   model=(d.get('models') or {}).get(pid)
   if model:
    if not isinstance(model,str) or not re.fullmatch(r'[\w./:@+-]{1,200}',model):raise ValueError('Invalid model ID')
    c['model']=model
   route=next(r for r in p['routes'] if r['id']==c.get('route','official'))
   c['free']=registry.model_is_free(route,c['model'])
   configs[pid]=c
 if len(configs)*len(prompts)>64:raise ValueError('Maximum 64 calls per batch')
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
 configs=validate_run(d)
 if not configs and d.get('providers') is not None:
  ids=d['providers']
  raise ValueError('Selected providers not configured: '+(', '.join(ids) or '(none selected)'))
 d={**d,'providers':d.get('providers') if d.get('providers') is not None else (list(configs) if configs else [p['id'] for p in catalog()])}
 skipped=[pid for pid in d['providers'] if pid not in configs]
 rid=str(uuid.uuid4());out=results_dir()/rid;out.mkdir();manifest={k:copy.deepcopy(d.get(k)) for k in ('market','providers','prompts','brand_aliases','skus','website')}
 manifest.update({'id':rid,'entry_type':'model_api','created_at':stamp(),'status':'queued','planned':len(configs)*len(d['prompts']),'provider_status':{pid:'configured' if pid in configs else 'not configured' for pid in d['providers']},'samples':[],'summary':[],'configuration':{pid:{k:v for k,v in c.items() if k!='key'} for pid,c in configs.items()},'methodology':'api-mention-v1: 100 × exact alias hits / complete unbranded answers; errors and truncated answers excluded, coverage reported; no consumer-app or market-population claim'})
 manifest['skipped_providers']=skipped
 save(out/'run.json',manifest);pool.submit(execute_run,manifest,configs,out);return {'id':rid,'status':'queued','planned':manifest['planned'],'skipped_providers':skipped}
def execute_run(run,configs,out):
 run['status']='running';save(out/'run.json',run)
 secrets=[c['key'] for c in configs.values()]
 def redact(obj):
  if isinstance(obj,str):
   for secret in secrets:obj=obj.replace(secret,'[REDACTED]')
   return obj
  if isinstance(obj,list):return [redact(x) for x in obj]
  if isinstance(obj,dict):return {redact(k):redact(v) for k,v in obj.items()}
  return obj
 try:
  for pid in run['providers']:
   if pid not in configs:continue
   p=provider(pid);c=configs[pid]
   for n,prompt in enumerate(run['prompts']):
    sample={'provider':pid,'question_index':n,'prompt':prompt,'captured_at':stamp(),'entry_type':'model_api','search_requested':c['search'],'brand_prompted':bool(mention(prompt,run['brand_aliases'])),'status':'failed'};started=time.monotonic()
    try:
     url,headers,body=request_for(p,c,prompt);raw=http_json(url,headers,body)
     sample.update(route=c.get('route','official'),free=c.get('free',False));sample.update(parse({**p,'protocol':c.get('protocol',p['protocol'])},raw));sample['status']='complete' if sample['complete'] else 'incomplete';sample['brand_match']=mention(sample['answer'],run['brand_aliases']);sample['sku_matches']={k['name']:mention(sample['answer'],k['aliases']) for k in run.get('skus') or []}
     rawfile=out/(pid+'-'+str(n)+'-raw.json');sample['raw_sha256']=save(rawfile,redact(raw));sample['raw_file']=rawfile.name
     # Exclude explicitly prompted SKU samples from that SKU's discovery scoring.
     sample['sku_prompted']={k['name']:bool(mention(prompt,k['aliases'])) for k in run.get('skus') or []}
    except Exception as e:sample['error']=redact(str(e) if isinstance(e,ValueError) else type(e).__name__+': request/response processing failed')
    sample['latency_ms']=round((time.monotonic()-started)*1000);run['samples'].append(redact(sample));run['summary']=aggregate(run['samples'],run['providers'],run.get('skus') or []);save(out/'run.json',redact(run))
  run['status']='finished';run['finished_at']=stamp();save(out/'run.json',redact(run))
 except Exception:
  run['status']='failed';run['error']='Batch interrupted by local processing error; completed evidence retained';save(out/'run.json',redact(run))
 finally:configs.clear()
