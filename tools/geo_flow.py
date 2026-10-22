"""Website -> pinned NiubiGEO prompt generation -> existing model runner -> evidence.

Separate process preserves existing provider-key sessions. Credentials never leave
their original runner. Only authenticated loopback APIs are used between processes.
"""
import concurrent.futures,copy,hashlib,http.server,ipaddress,json,pathlib,re,secrets,shutil,socket,subprocess,threading,time,urllib.error,urllib.parse,urllib.request,uuid
from html.parser import HTMLParser
import ai_api as shared
import geo_analysis,geo_plan
import website_inspection
import pinned_http
import website_check
import geo_diagnose
ROOT=pathlib.Path(__file__).resolve().parents[1];DATA=ROOT/'runtime/geo-flows';PORT=8772
TOKEN=secrets.token_urlsafe(32);POOL=concurrent.futures.ThreadPoolExecutor(max_workers=1);GUARD=threading.Lock();BUSY=False;CANCEL=set()
SITE='https://signal-geo-workbench-lh.saml1nhchen.chatgpt.site';SESSIONS={};DIAGNOSES=None

def bridge(path,body=None):
 prefix='/api/bai/';base='http://127.0.0.1:8771'
 if not re.fullmatch(r'(state|run|export|runs)(\?id=[a-f0-9-]{36})?',path):raise ValueError('Unsupported runner operation')
 if not SESSIONS.get('bai'):
  req=urllib.request.Request(base+prefix+'session',headers={'Sec-Fetch-Site':'same-origin'})
  with urllib.request.urlopen(req,timeout=5) as r:SESSIONS['bai']=json.load(r)['token']
 req=urllib.request.Request(base+prefix+path,None if body is None else json.dumps(body).encode(),{'Authorization':'Bearer '+SESSIONS['bai'],'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(req,timeout=15) as r:return json.load(r)
 except urllib.error.HTTPError as e:
  if e.code==401:SESSIONS.clear()
  raise ValueError('模型执行器拒绝请求；请检查本机连接和配置') from None
 except urllib.error.URLError:raise ValueError('请先启动并连接 B.AI 执行器（8771）') from None

def direct_bridge(path,body=None):
 if not re.fullmatch(r'(providers|run|export)(\?id=[a-f0-9-]{36})?',path):raise ValueError('Unsupported direct API operation')
 base='http://127.0.0.1:8770/api/tools/'
 if not SESSIONS.get('direct'):
  with urllib.request.urlopen(urllib.request.Request(base+'session',headers={'Sec-Fetch-Site':'same-origin'}),timeout=5) as r:SESSIONS['direct']=json.load(r)['token']
 req=urllib.request.Request(base+'ai/'+path,None if body is None else json.dumps(body).encode(),{'Authorization':'Bearer '+SESSIONS['direct'],'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(req,timeout=15) as r:return json.load(r)
 except urllib.error.HTTPError as e:
  if e.code==401:SESSIONS.pop('direct',None)
  raise ValueError('独立 API 执行器拒绝请求，请检查 8770 的配置') from None
 except urllib.error.URLError:raise ValueError('独立 API 执行器未运行（8770）') from None

class Extractor(HTMLParser):
 def __init__(self):super().__init__();self.skip=0;self.parts=[]
 def handle_starttag(self,t,a):
  if t in ('script','style','noscript','svg'):self.skip+=1
 def handle_endtag(self,t):
  if t in ('script','style','noscript','svg') and self.skip:self.skip-=1
 def handle_data(self,s):
  if not self.skip and s.strip():self.parts.append(s.strip())

def fetch_website(url,allow_short=False):
 check=website_check.Check()
 try:url=website_inspection.normalize_url(url)
 except ValueError:check.fail('invalid_address','unsafe','address')
 check.value['final_url']=url;check.check('address','passed','address_ok')
 try:pinned_http.require_direct_policy()
 except ValueError:check.fail('proxy_unsupported','unsafe','address')
 for _ in range(5):
  try:u=urllib.parse.urlsplit(url);port=u.port
  except ValueError:check.fail('invalid_address','unsafe','address')
  check.value.update(final_url=url,http_status=None,content_type=None,bytes=None,readable_characters=None)
  for key in ('dns','http','content'):next(r for r in check.value['checks'] if r['id']==key).update(status='unknown',message='尚无足够证据判断。')
  if u.scheme not in ('https','http') or not u.hostname or u.username or u.password or port not in (None,80,443):check.fail('invalid_address','unsafe','address')
  if u.scheme=='http':check.check('tls','skipped','tls_skipped')
  else:next(r for r in check.value['checks'] if r['id']=='tls').update(status='unknown',message='尚无足够证据判断。')
  try:addresses=socket.getaddrinfo(u.hostname,port or (443 if u.scheme=='https' else 80),type=socket.SOCK_STREAM)
  except OSError:check.fail('dns_failed','unreachable','dns')
  if not addresses:check.fail('dns_failed','unreachable','dns')
  check.check('dns','passed','dns_ok')
  if any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):check.fail('unsafe_address','unsafe','address')
  req=urllib.request.Request(url,headers={'User-Agent':'SignalGEO/1.0 website-research','Accept':'text/html,text/plain','Accept-Encoding':'identity'})
  try:
   with urllib.request.build_opener(urllib.request.ProxyHandler({}),pinned_http.PinnedHTTPHandler(addresses),pinned_http.PinnedHTTPSHandler(addresses),shared.NoRedirect).open(req,timeout=30) as r:
    status=getattr(r,'status',200);status=status if type(status)==int else 200
    check.value['http_status']=status;check.check('http','passed','http_ok')
    if u.scheme=='https':check.check('tls','passed','tls_ok')
    kind=website_check.content_type(r.headers.get('Content-Type',''));check.value['content_type']=kind
    if kind not in ('text/html','text/plain','application/xhtml+xml'):check.fail('unsupported_content','unsupported','content')
    raw=r.read(2*1024*1024+1);check.value['bytes']=len(raw)
    if len(raw)>2*1024*1024:check.fail('content_too_large','unsupported','content')
    try:html=raw.decode(r.headers.get_content_charset() or 'utf-8',errors='replace')
    except LookupError:html=raw.decode('utf-8',errors='replace')
    is_html=kind!='text/plain'
    if is_html:
     parser=website_inspection.WebsiteExtractor();parser.feed(html);text='\n'.join(parser.parts)[:18000];metadata=parser.metadata()
    else:text=html[:18000];metadata={'readable_characters':len(html.strip())}
    check.value['readable_characters']=metadata.get('readable_characters',len(text))
    if is_html and website_check.challenge(html,metadata):check.fail('website_challenge','challenge','content')
    if check.value['readable_characters']<100:
     if not allow_short:check.fail('content_too_short','unsupported','content')
     check.check('content','failed','content_too_short');check.finding('content_too_short');outcome='unsupported'
    else:check.check('content','passed','content_ok');outcome='readable'
    return {'url':url,'captured_at':shared.stamp(),'content_sha256':hashlib.sha256(raw).hexdigest(),'text':text,'bytes':len(raw),'metadata':metadata,'is_html':is_html,'diagnostics':check.finish(outcome)}
  except urllib.error.HTTPError as error:
   try:
    status=error.code;check.value['http_status']=status
    if u.scheme=='https':check.check('tls','passed','tls_ok')
    check.value['content_type']=website_check.content_type(error.headers.get('Content-Type')) if error.headers else None
    if status in (301,302,303,307,308) and error.headers.get('Location'):
     try:location=website_inspection.normalize_url(urllib.parse.urljoin(url,error.headers['Location']))
     except ValueError:check.fail('invalid_address','unsafe','address')
     check.value['redirects'].append({'url':url,'status':status,'location':location});check.check('http','passed','http_ok');url=location;continue
    check.value['retry_after']=website_check.safe_retry_after(error.headers.get('Retry-After')) if error.headers else None
    check.fail('http_limited' if status==429 else 'http_blocked' if status==403 else 'http_error','limited' if status==429 else 'blocked' if status==403 else 'unreachable','http')
   finally:error.close()
  except website_check.WebsiteCheckError:raise
  except (urllib.error.URLError,OSError) as error:
   code=website_check.classify(error);check.fail(code,'unreachable','tls' if code.startswith('tls_') else 'dns' if code=='dns_failed' else 'http')
 check.fail('redirect_limit','unsupported','http')

def inspect_website(d):
 if not isinstance(d,dict) or d.get('market') not in ('CN','US'):raise ValueError('请选择中国或美国市场')
 url=website_inspection.normalize_url(d.get('website'))
 try:snapshot=fetch_website(url,allow_short=True)
 except (urllib.error.URLError,TimeoutError,OSError):raise ValueError('官网连接失败或超时，请检查网址与网络后重试；未生成分数') from None
 return website_inspection.inspect_snapshot(snapshot,d['market'])

def niubi(operation,config,**extra):
 up=ROOT/'runtime/upstreams/niubigeo';node=shutil.which('node')
 cli=up/'node_modules/tsx/dist/cli.mjs'
 if not node or not cli.exists():raise ValueError('NiubiGEO Node/tsx 环境缺失，请运行原始运行环境安装脚本')
 args=[node,str(cli),str(ROOT/'tools/niubi_bridge.mts')]
 p=subprocess.run(args,input=json.dumps({**config,**extra,'operation':operation},ensure_ascii=False).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=40,cwd=ROOT)
 if p.returncode:raise ValueError('NiubiGEO 生成器解析失败：模型应返回完整的结构化题目，原始输出已保留')
 return json.loads(p.stdout)

def folder(rid):
 if not re.fullmatch(r'[a-f0-9-]{36}',rid):raise ValueError('任务 ID 无效')
 return DATA/rid

def get(rid):return json.loads((folder(rid)/'flow.json').read_text('utf-8'))
def persist(job):shared.save(folder(job['id'])/'flow.json',job)
def catalog():
 try:state=bridge('state')
 except Exception:state={'configured':False,'profiles':[],'models':[]}
 try:
  for p in direct_bridge('providers')['providers']:
   if p['configured']:state['profiles'].append({'id':'direct:'+p['id'],'name':p['name'],'markets':p['markets'],'protocol':p['protocol'],'provider':p['id'],'channel':'direct',**p['configuration']})
 except Exception:pass
 for p in state['profiles']:p['manufacturer']=geo_plan.vendor(p)
 state['configured']=bool(state['profiles']);return state

def validate(d,check_models=True):
 d=copy.deepcopy(d)
 if d.get('market') not in ('CN','US'):raise ValueError('请选择中国或美国市场')
 if not isinstance(d.get('website'),str) or not geo_analysis.host(d['website']):raise ValueError('请输入品牌官网')
 aliases=d.get('brand_aliases')
 if not isinstance(aliases,list) or not 1<=len(aliases)<=20 or any(not isinstance(a,str) or not a.strip() or len(a)>200 for a in aliases):raise ValueError('请填写品牌名称与精确别名')
 d['brand_aliases']=[a.strip() for a in aliases]
 for field in ('skus','competitors'):
  rows=d.get(field,[])
  if not isinstance(rows,list) or len(rows)>30:raise ValueError('SKU / 竞品最多各 30 行')
  for r in rows:
   if not isinstance(r,dict) or not isinstance(r.get('name'),str) or not 0<len(r['name'])<=200 or not isinstance(r.get('aliases'),list) or not r['aliases'] or any(not isinstance(a,str) or not 0<len(a.strip())<=200 for a in r['aliases']):raise ValueError('每个 SKU / 竞品需要名称与精确别名')
   domains=r.get('domains',[])
   if not isinstance(domains,list) or any(not isinstance(a,str) or not re.fullmatch(r'[a-z0-9.-]+',a) or '.' not in a for a in domains):raise ValueError('竞品域名只填写 example.com 格式')
   r['domains']=[a.removeprefix('www.') for a in domains]
  if len({r['name'].casefold() for r in rows})!=len(rows):raise ValueError('SKU / 竞品名称不能重复')
  d[field]=rows
 if any(shared.mention(a,d['brand_aliases']) or shared.mention(b,[a]) for c in d['competitors'] for a in c['aliases'] for b in d['brand_aliases']):raise ValueError('品牌与竞品别名不能重叠')
 if len({d['brand_aliases'][0],*[c['name'] for c in d['competitors']]})!=len(d['competitors'])+1:raise ValueError('品牌和竞品名称必须不同')
 for f in ('count','repeats'):
  v=d.get(f,30 if f=='count' else 1)
  limit=300 if f=='count' else (5 if not check_models else 1)
  if type(v)!=int or not 1<=v<=limit:raise ValueError('题数 1–300；新任务每题只调用一次，默认每市场 30 道不同题目')
  d[f]=v
 ids=d.get('providers',[])
 if not isinstance(ids,list) or not 1<=len(ids)<=16 or len(set(ids))!=len(ids) or len(ids)*d['count']*d['repeats']>15000:raise ValueError('请选择 1–16 个厂商；单任务最多 15000 次回答')
 for f in ('focus','context'):
  if not isinstance(d.get(f,''),str) or len(d.get(f,''))>18000:raise ValueError('业务背景过长')
 if not check_models:return d
 state=catalog();profiles={p['id']:p for p in state['profiles']}
 if not state['configured']:raise ValueError('请先在 B.AI 页面连接密钥并配置模型')
 for pid in [*ids,d.get('generator')]:
  if pid not in profiles or d['market'] not in profiles[pid]['markets']:raise ValueError('生成模型和测试模型必须属于当前市场')
 manufacturers=[geo_plan.vendor(profiles[pid]) for pid in ids]
 if len(set(manufacturers))!=len(manufacturers):raise ValueError('每个厂商只保留一个固定模型；同一厂商的直连与聚合渠道也不能同时计入')
 if any(v.startswith('未识别:') for v in manufacturers):raise ValueError('无法识别所选模型的厂商，请先使用明确的厂商模型 ID')
 d['configuration']={pid:profiles[pid] for pid in set([*ids,d['generator']])}
 return d

def start(d):
 global BUSY
 config=validate(d)
 with GUARD:
  if BUSY:raise ValueError('已有流程正在执行，请等待或停止当前流程')
  BUSY=True
 try:
  rid=str(uuid.uuid4());folder(rid).mkdir(parents=True)
  lock=json.loads((ROOT/'tools/upstreams.lock.json').read_text('utf-8'));source=next(x for x in lock if x['id']=='niubigeo')
  task_plan=geo_plan.plan(config)
  job={'id':rid,'created_at':shared.stamp(),'status':'queued','stage':'queued','config':config,'generation':None,'generations':[],'prompts':[],'calls':[],'samples':[],'report':None,'plan':task_plan,'planned_max_calls':task_plan['maximum_calls'],'upstream':{'repository':source.get('repository'),'commit':source['commit'],'module':'src/prompts/prompt-generator.ts'},'entry_type':'model_api'}
  persist(job);POOL.submit(execute,job);return job
 except Exception:
  with GUARD:BUSY=False
  raise

def call(job,pid,prompts,kind):
 if job['id'] in CANCEL:raise ValueError('已停止；已提交的单次调用会完成并保留证据')
 cfg=job['config'];is_direct=pid.startswith('direct:');remote=direct_bridge if is_direct else bridge
 r=remote('run',{'market':cfg['market'],'providers':[pid.removeprefix('direct:')],'prompts':prompts,'brand_aliases':cfg['brand_aliases'],'skus':cfg['skus'],'website':cfg['website']})
 job['calls'].append({'kind':kind,'runner_id':r['id'],'provider':pid,'planned':r['planned'],**job.get('inflight_spec',{})});persist(job)
 deadline=time.monotonic()+145*len(prompts)+30
 while time.monotonic()<deadline:
  r=remote('run?id='+r['id'])
  if r['status'] in ('finished','failed'):
   raw=remote('export?id='+r['id']);shared.save(folder(job['id'])/(r['id']+'.json'),raw)
   for s in raw['samples']:s.update(provider=pid,channel='direct' if is_direct else 'bai',protocol=cfg['configuration'][pid]['protocol'],model_requested=cfg['configuration'][pid]['model'])
   return raw
  time.sleep(1)
 raise ValueError('执行器等待超时；请查看原始调用记录，流程未自动重试')

def execute(job):
 global BUSY
 try:
  job['status']='running';job['stage']='website';persist(job);cfg=job['config']
  try:job['website']=fetch_website(cfg['website'])
  except Exception as e:
   job['website']={'url':cfg['website'],'error':str(e) if isinstance(e,ValueError) else '官网读取失败','text':''}
   if not cfg.get('context'):raise ValueError('官网抓取失败，请补充业务背景再运行；尚未调用模型') from None
  job['stage']='generating';persist(job)
  generate_bank(job)
  if len(job['prompts'])<cfg['count']:raise ValueError('题库去重后不足目标题数，已保留现有题目。请审核后使用可编辑题集；没有自动补题或开始采样')
  job['prompt_hash']=geo_plan.fingerprint(job['prompts']);job['stage']='sampling';persist(job)
  if cfg.get('generate_only'):job['status']='finished';job['stage']='report'
  else:collect(job)
 except Exception as e:job['status']='stopped' if job['id'] in CANCEL else 'failed';job['error']=str(e) if isinstance(e,ValueError) else '本地流程处理失败；已完成证据保留'
 finally:
  job['finished_at']=shared.stamp();persist(job)
  with GUARD:BUSY=False;CANCEL.discard(job['id'])

def generate_bank(job):
 cfg=job['config'];job.setdefault('prompts',[]);job.setdefault('generations',[]);seen=set()
 for batch_index,specs in enumerate(geo_plan.blueprint(cfg['count'])):
  if job['id'] in CANCEL:raise ValueError('自动出题已停止，已生成的问题保留')
  batch_cfg={**cfg,'count':len(specs),'question_blueprint':specs,'batch_index':batch_index,'previous_questions':[p['text'] for p in job['prompts'][-6:]]}
  prompt=niubi('build',batch_cfg,website_text='User supplied scope: '+cfg.get('context','')+'\nWebsite excerpt: '+job['website']['text'])['prompt']
  generated=call(job,cfg['generator'],[prompt],'generation');g={'batch':batch_index+1,'runner_id':generated['id'],'sample':generated['samples'][0] if generated['samples'] else None};job['generation']=g;job['generations'].append(g);persist(job)
  s=g['sample']
  if not s or s['status']!='complete':raise ValueError('自动出题失败：'+(s.get('error','回答不完整') if s else '没有返回样本'))
  parsed=niubi('parse',batch_cfg,text=s['answer'])
  for n,p in enumerate(parsed):
   key=geo_plan.question_key(p['text'])
   if key in seen:continue
   seen.add(key);spec=specs[n];p.update(id='q-'+str(len(job['prompts'])+1),planned_family=spec['family'],dimension=spec['dimension'],family=geo_plan.question_family(p['text'],cfg),generation_batch=batch_index+1);job['prompts'].append(p)
  job['generation_progress']={'complete':batch_index+1,'planned':len(geo_plan.blueprint(cfg['count']))};persist(job)

def collect(job):
 if job['id'] in CANCEL:raise ValueError('流程已停止，已有回答已保存')
 cfg=job['config'];prompts=[p['text'] for p in job['prompts']]
 attempted={(s['provider'],s.get('repeat',1),s['question_index']) for s in job['samples']};blocked=job.setdefault('blocked_models',{})
 for repeat in range(cfg['repeats']):
  for pid in cfg['providers']:
   if pid in blocked:continue
   for n,prompt in enumerate(prompts):
    if (pid,repeat+1,n) in attempted:continue
    if job['id'] in CANCEL:raise ValueError('流程已停止，已有回答已保存')
    job['inflight_spec']={'question_index':n,'repeat':repeat+1,'batch':len(job['samples'])//64+1}
    result=call(job,pid,[prompt],'sampling')
    for s in result['samples']:job['samples'].append({**s,'id':result['id']+'-'+str(n),'question_index':n,'runner_id':result['id'],'repeat':repeat+1})
    job.pop('inflight_spec',None)
    if len(job['samples'])%10==0:job['report']=geo_analysis.analyze(job['samples'],cfg,job['prompts'])
    persist(job)
    errors=[s.get('error','') for s in result['samples'] if s['status']=='failed']
    if any(re.search(r'HTTP (400|401|403|404|429)|余额|额度|权限',e) for e in errors):blocked[pid]=errors[0];persist(job);break
 job['report']=geo_analysis.analyze(job['samples'],cfg,job['prompts']);job['status']='finished' if not blocked and len(job['samples'])==len(prompts)*len(cfg['providers'])*cfg['repeats'] and all(s['status']=='complete' for s in job['samples']) else 'partial';job['stage']='report'

def start_manual(d):
 global BUSY
 prompts=d.get('prompts',[])
 if not isinstance(prompts,list) or not 1<=len(prompts)<=300 or any(not isinstance(p,str) or not p.strip() or len(p)>4000 for p in prompts):raise ValueError('请填写 1–300 道完整问题')
 if len({geo_plan.question_key(p) for p in prompts})!=len(prompts):raise ValueError('题库存在重复问题，请去重后再提交')
 config=validate({**d,'count':len(prompts)})
 with GUARD:
  if BUSY:raise ValueError('已有流程正在执行')
  BUSY=True
 rid=str(uuid.uuid4());folder(rid).mkdir(parents=True)
 bank=[{'id':'q-'+str(i+1),'text':p.strip(),'type':'manual','family':geo_plan.question_family(p,config),'dimension':'manual'} for i,p in enumerate(prompts)];task_plan=geo_plan.plan(config,True)
 job={'id':rid,'created_at':shared.stamp(),'status':'queued','stage':'sampling','config':config,'generation':None,'prompts':bank,'prompt_hash':geo_plan.fingerprint(bank),'samples':[],'calls':[],'report':None,'plan':task_plan,'planned_max_calls':task_plan['maximum_calls'],'upstream':{'module':'manual questions; Signal GEO deterministic analysis'},'entry_type':'model_api'};persist(job)
 def run():
  global BUSY
  try:job['status']='running';persist(job);collect(job)
  except Exception as e:job['status']='stopped' if rid in CANCEL else 'failed';job['error']=str(e) if isinstance(e,ValueError) else '本地处理失败'
  finally:
   job['finished_at']=shared.stamp();persist(job)
   with GUARD:BUSY=False;CANCEL.discard(rid)
 POOL.submit(run);return job

def reanalyze(d):
 parent=get(d['id'])
 if parent['status'] in ('queued','running'):raise ValueError('请等待原任务完成')
 if not parent['samples']:raise ValueError('原任务没有回答，无法重新分析')
 cfg=validate({**parent['config'],**{k:d[k] for k in ('brand_aliases','skus','competitors') if k in d}},check_models=False)
 job=copy.deepcopy(parent);job.update(id=str(uuid.uuid4()),created_at=shared.stamp(),finished_at=shared.stamp(),config=cfg,parent_run_id=parent['id'],analysis_only=True,planned_max_calls=0,calls=[],status='finished',stage='report')
 job.pop('error',None);job['report']=geo_analysis.analyze(job['samples'],cfg,job.get('prompts',[]));folder(job['id']).mkdir(parents=True)
 for p in folder(parent['id']).glob('*.json'):
  if p.name!='flow.json':shutil.copyfile(p,folder(job['id'])/p.name)
 persist(job);return job

def resume(d):
 global BUSY
 job=get(d['id'])
 if job['status'] not in ('stopped','interrupted','failed','partial') or not job.get('prompt_hash'):raise ValueError('仅支持已有冻结题库的中断 / 部分完成任务继续采样')
 if geo_plan.fingerprint(job['prompts'])!=job['prompt_hash']:raise ValueError('冻结题库已变化，不能继续原任务')
 current=validate(job['config'])
 for pid in job['config']['providers']:
  for k in ('model','protocol','base_url','search'):
   if current['configuration'][pid].get(k)!=job['config']['configuration'][pid].get(k):raise ValueError('模型配置与原任务不一致，请恢复原配置或新建任务')
 # Reconcile already-submitted calls; never blindly repeat a possibly billed request.
 accounted={s.get('runner_id') for s in job['samples']}
 for c in job['calls']:
  if c['kind']!='sampling' or c['runner_id'] in accounted:continue
  remote=direct_bridge if c['provider'].startswith('direct:') else bridge
  r=remote('run?id='+c['runner_id'])
  if r['status'] not in ('finished','failed'):raise ValueError('上次提交的回答仍在执行，请稍后继续；未重复提交')
  if 'question_index' not in c:raise ValueError('旧版记录缺少恢复检查点，请从可编辑题集新建任务')
  raw=remote('export?id='+c['runner_id']);shared.save(folder(job['id'])/(c['runner_id']+'.json'),raw)
  for s in raw['samples']:job['samples'].append({**s,'provider':c['provider'],'id':c['runner_id']+'-'+str(c['question_index']),'question_index':c['question_index'],'runner_id':c['runner_id'],'repeat':c['repeat']})
 with GUARD:
  if BUSY:raise ValueError('已有流程正在执行')
  BUSY=True
 job['blocked_models']={};job.pop('error',None);job['resumed_at']=shared.stamp();job['status']='queued';job['stage']='sampling';persist(job)
 def run():
  global BUSY
  try:job['status']='running';persist(job);collect(job)
  except Exception as e:job['status']='stopped' if job['id'] in CANCEL else 'failed';job['error']=str(e) if isinstance(e,ValueError) else '采样处理失败'
  finally:
   job['finished_at']=shared.stamp();persist(job)
   with GUARD:BUSY=False;CANCEL.discard(job['id'])
 POOL.submit(run);return job

class Handler(http.server.SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw):super().__init__(*a,directory=str(ROOT/'dist'),**kw)
 def log_message(self,*a):pass
 def reply(self,obj,status=200):
  data=json.dumps(obj,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
 def auth(self):
  if self.headers.get('Host') not in ('127.0.0.1:8772','localhost:8772') or self.headers.get('Origin') not in (None,'http://127.0.0.1:8772','http://localhost:8772') or not secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+TOKEN):self.reply({'error':'请打开本机自动诊断工作台'},401);return False
  return True
 def do_GET(self):
  try:
   u=urllib.parse.urlsplit(self.path);q=urllib.parse.parse_qs(u.query)
   if u.path=='/api/geo/session':
    if self.headers.get('Host') not in ('127.0.0.1:8772','localhost:8772') or self.headers.get('Sec-Fetch-Site')!='same-origin':return self.reply({'error':'需要本机同源配对'},403)
    return self.reply({'token':TOKEN})
   if u.path.startswith('/api/geo/'):
    if not self.auth():return
    if u.path=='/api/geo/state':return self.reply({'runner':catalog(),'busy':BUSY,'runs':[{'id':j['id'],'created_at':j['created_at'],'status':j['status'],'market':j['config']['market'],'brand':j['config']['brand_aliases'][0]} for j in [json.loads(p.read_text('utf-8')) for p in sorted(DATA.glob('*/flow.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:40]]]})
    if u.path=='/api/geo/diagnoses':return self.reply(DIAGNOSES.list())
    if u.path=='/api/geo/diagnosis':return self.reply(DIAGNOSES.get(q['id'][0]))
    if u.path in ('/api/geo/run','/api/geo/export'):
     job=get(q['id'][0])
     if u.path.endswith('export'):job['raw_evidence']={p.name:json.loads(p.read_text('utf-8')) for p in folder(job['id']).glob('*.json') if p.name!='flow.json'}
     return self.reply(job)
    return self.reply({'error':'接口不存在'},404)
   if u.path.startswith('/api/'):return self.reply({'error':'此执行器仅提供自动诊断；模型密钥在原 B.AI 服务中配置'},404)
   return super().do_GET()
  except Exception as e:self.reply({'error':str(e) if isinstance(e,(ValueError,KeyError)) else '无法读取本地任务'},400)
 def do_POST(self):
  if not self.auth():return
  try:
   n=int(self.headers.get('Content-Length','0'))
   if not 0<n<=256*1024:raise ValueError('请求不能超过 256 KB')
   d=json.loads(self.rfile.read(n))
   if self.path=='/api/geo/inspect':return self.reply(inspect_website(d))
   if self.path=='/api/geo/start':return self.reply(start(d),202)
   if self.path=='/api/geo/sample':return self.reply(start_manual(d),202)
   if self.path=='/api/geo/analyze':return self.reply(reanalyze(d),201)
   if self.path=='/api/geo/plan':return self.reply(geo_plan.plan(validate(d),bool(d.get('manual'))))
   if self.path=='/api/geo/diagnose':return self.reply(DIAGNOSES.start(d),202)
   if self.path=='/api/geo/resume':return self.reply(resume(d),202)
   if self.path=='/api/geo/stop':
    job=get(d['id']);CANCEL.add(job['id']);return self.reply({'status':'stop_requested'})
   return self.reply({'error':'接口不存在'},404)
  except Exception as e:self.reply({'error':str(e) if isinstance(e,ValueError) else '无法提交任务'},400)

if __name__=='__main__':
 DATA.mkdir(parents=True,exist_ok=True);DIAGNOSES=geo_diagnose.Store(flows=get)
 for p in DATA.glob('*/flow.json'):
  try:
   j=json.loads(p.read_text('utf-8'))
   if j['status'] in ('running','queued'):j.update(status='interrupted',error='执行器曾重启；未自动重新调用模型');persist(j)
  except (ValueError,KeyError,OSError):pass
 print('Signal GEO: http://127.0.0.1:8772/#/w/demo/research',flush=True)
 http.server.ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
