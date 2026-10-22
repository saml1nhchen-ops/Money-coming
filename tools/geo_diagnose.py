"""Durable same-team diagnostics. Paid work only enters the existing gateway ledger.

No background retry/resume of interrupted work. Shares are immutable, scoped copies;
only a token hash is persisted. Original audit/flow schemas are retained for history.
"""
import concurrent.futures,contextlib,copy,datetime,hashlib,json,pathlib,re,secrets,sqlite3,threading,time,urllib.parse,uuid
from geo_audit import AuditError,validate_confirmation
RULES=json.loads(pathlib.Path(__file__).with_name('diagnostic_rules.json').read_text())
TERMINAL={'finished','partial','failed','interrupted'}
UUID=re.compile(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\Z')
SHARE_AGE=30*86400
class DiagnosticError(Exception):
 def __init__(self,status,code):self.status=status;self.code=code

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def ident(value):
 if not isinstance(value,str) or not UUID.fullmatch(value):raise DiagnosticError(400,'invalid_request')
 return value
def text(value,limit=200,empty=False):
 if not isinstance(value,str) or len(value)>limit or (not empty and not value.strip()):raise DiagnosticError(400,'invalid_request')
 return value.strip()
def confirmation_input(c):
 return {'brand':{k:c['brand'][k] for k in ('name','aliases')},'products':[{k:r[k] for k in ('name','aliases','source_candidate_id') if k in r} for r in c['products']],'competitors':[{k:r[k] for k in ('name','aliases','source_candidate_id','domains') if k in r} for r in c['competitors']],'context':c.get('context','')}

def score(rules):
 applicable=[r for r in rules if r['status']!='not_applicable'];a=sum(r['weight'] for r in applicable);u=sum(r['weight'] for r in applicable if r['status']=='unknown');p=sum(r['weight']*(1 if r['status']=='pass' else r['partial_credit'] if r['status']=='partial' else 0) for r in applicable)
 return {'applicable_weight':a,'unknown_weight':u,'earned':p,'lower':round(100*p/a,2) if a else None,'upper':round(100*(p+u)/a,2) if a else None,'coverage':(a-u)/a if a else None,'total':round(100*p/a,2) if a and u==0 else None}

def bundle_for(record,audit,flow=None,extra=None):
 """Adapt observable rules; Q&A outcomes never manufacture website coverage/facts."""
 config=record['config'];report=audit.get('report') or {};evidence=[];mapping={}
 for e in audit.get('evidence',[]):
  eid='WEB-'+e['id'];mapping[e['id']]=eid
  excerpt=e.get('excerpt') or '未取得内容；此次读取状态见附录。'
  evidence.append({'evidence_id':eid,'source_type':'website_capture','provided_at':e.get('captured_at') or now(),'url':e.get('url') or config['website'],'hash':'sha256:'+digest(e),'locator':e.get('source_field') or 'captured response','excerpt':excerpt,'integrity':'Captured excerpt and metadata; hash covers this evidence record, not the entire remote website.','entry':'Signal finite safe HTTP collector','capture':e})
 for resource in extra or []:
  eid='PAGE-'+resource['id'];value=resource.get('parsed') or {};evidence.append({'evidence_id':eid,'source_type':'website_capture','provided_at':resource['captured_at'],'url':resource['url'],'hash':'sha256:'+resource.get('sha256',digest(resource)),'locator':'bounded captured HTML','excerpt':value.get('extracted_text','')[:8000] or '读取失败或未取得正文。','integrity':'Bounded response SHA256 where available; no browser or external validation.','entry':'Signal finite safe HTTP collector','http_status':resource.get('status'),'error_code':resource.get('error')})
 checks={c['id']:c for section in report.get('sections',[]) for c in section['checks']};rules=[]
 for spec in RULES['rules']:
  c=checks.get(spec.get('check'));status=c['status'] if c else 'unknown';ids=[mapping[i] for i in (c or {}).get('evidence_ids',[]) if i in mapping]
  reason=c['reason'] if c else {'products':'产品名称线索不认证产品事实完整性；未进行逐项事实核验。','question_coverage':'尚未对冻结问题所需事实与网页逐条配对核验；模型提及不等于官网覆盖。','fact_verification':'官网身份和联系线索不是独立事实认证。','cross_page_facts':'已保留有限页面证据；尚未进行跨页事实一致性人工核验。'}.get(spec.get('observation'),'未取得足够证据。')
  if status in ('pass','partial','fail') and not ids:status='unknown'
  rules.append({'rule_id':'R-'+spec['id'],'dimension':spec['dimension'],'weight':spec['weight'],'status':status,'partial_credit':.5,'reason':reason,'evidence_ids':ids,'target_page':config['website'],'rubric':'pass=1; partial=0.5; fail=0; unknown retains score interval. '+spec['rubric'],'verification':spec['verification'],'action':spec['action'],'version':RULES['version'],'na_reason':'not applicable in captured scope' if status=='not_applicable' else ''})
 questions=[];answers=[]
 if flow:
  for n,p in enumerate(flow.get('prompts',[])):
   question=p.get('text','') if isinstance(p,dict) else p
   family=p.get('family') if isinstance(p,dict) else None
   import geo_plan
   family=family or geo_plan.question_family(question,flow['config']);family='brand' if family in ('brand','brand_knowledge','awareness') else 'comparison' if family=='comparison' else 'discovery'
   questions.append({'question_id':'Q-'+str(n+1),'question':question,'question_version':1,'question_type':family})
  for n,s in enumerate(flow.get('samples',[])):
   qi=s.get('question_index',0);q=questions[qi] if 0<=qi<len(questions) else {'question_id':'Q-unknown','question':s.get('prompt','Unknown question'),'question_type':'discovery'};analysis=s.get('analysis') or __import__('geo_analysis').sample_analysis(s,flow['config'])
   mentions=analysis.get('entities',[]);own=next((e for e in mentions if e.get('own')),None)
   # Citation support comes only from an explicit provider capability/evidence flag.
   supported=s.get('citation_supported') is True;complete=supported and s.get('citation_complete') is True
   answers.append({'evidence_id':'ANSWER-'+str(n+1),'question_id':q['question_id'],'question':q['question'],'question_version':1,'question_type':q['question_type'],'platform':s.get('model_returned') or s.get('model_requested') or s.get('provider','unknown'),'entry':'model_api','market':config['market'],'language':'zh' if config['market']=='CN' else 'en','status':'success' if s.get('status')=='complete' and s.get('answer','').strip() else 'failed','raw_answer':s.get('answer',''),'mention':bool(own.get('alias')) if own and s.get('status')=='complete' else None,'recommendation':None,'citation_supported':supported,'citation_complete':complete,'citation_type':'api_native' if supported else 'unsupported','citations':[{'url':c['url']} for c in s.get('citations',[]) if isinstance(c,dict) and isinstance(c.get('url'),str) and urllib.parse.urlsplit(c['url']).scheme in ('http','https')],'answer_links':[c for c in analysis.get('citations',[]) if c.get('kind')=='answer_link'],'truncated':s.get('truncated',False),'cached':s.get('cached',False),'collected_at':s.get('created_at') or flow.get('created_at') or now(),'ranking':copy.deepcopy(analysis.get('entities',[])),'raw_sha256':digest(s)})
 findings=[]
 for r in rules:
  if r['status'] not in ('fail','unknown'):continue
  findings.append({'finding_id':'F-'+r['rule_id'],'scope':'本次有限官网页面','status':r['status'],'finding_type':'supported_gap' if r['status']=='fail' else 'unknown','priority':'P1' if r['status']=='fail' else '待验证','question_ids':[],'evidence_ids':r['evidence_ids'],'rule_ids':[r['rule_id']],'target_pages':[r['target_page']],'observed_gap':r['reason'],'alternative_explanations':'抓取、地区、页面范围或缺少事实核验均可能影响观察；不能推断模型推荐因果。','recommended_action':r['action'],'owner':'项目负责人','effort_band':'待评估','verification':r['verification'],'priority_reason':'基于本次限定范围的证据或证据缺口。','publication_status':'unpublished'})
 manifest={'run_id':record['id'],'brand':config['confirmed']['brand']['name'] or '未识别品牌','domains':[urllib.parse.urlsplit(config['website']).hostname],'market':config['market'],'language':'zh' if config['market']=='CN' else 'en','mode':'full' if config['mode']=='full' else 'page','rule_version':RULES['version'],'parser_version':RULES['parser_version'],'judge_version':'deterministic-observations-v1','question_set_version':digest([q['question'] for q in questions]),'page_set_version':digest(sorted({e['url'] for e in evidence})),'configuration':digest(record['comparison_config']),'sampled_at':record['created_at'],'planned':record['plan']['answer_calls'],'attempted':len(answers),'page_weighting':'有限代表页；规则按维度权重，不将页面数量当质量。'}
 b={'schema_version':'v0.1','demo':False,'run_manifest':manifest,'rules':rules,'questions':questions,'answers':answers,'findings':findings,'evidence':evidence,'scores':score(rules),'dimension_scores':[{'dimension':d,**score([r for r in rules if r['dimension']==d])} for d in ('access','entity','questions','trust','structure','maintenance')],'performance':{k:copy.deepcopy(v) for k,v in ((flow or {}).get('report') or {}).items() if k!='samples'} if flow else None,'competitor_gaps':copy.deepcopy(((flow or {}).get('report') or {}).get('gaps',[])),'source_snapshot':copy.deepcopy(report),'limitations':['官网规则准备度与模型问答表现分开；不是平台排名或事实认证。','未逐条核验的问题覆盖、事实完整性和跨页一致性保持unknown。','最多8资源/10HTTP/4MiB/累计60秒，遵守同源、robots及安全连接约束。']}
 return b

class DiagnosticManager:
 def __init__(self,workspace,path,root=None,poll_interval=.25):
  self.w=workspace;self.path=pathlib.Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.root=pathlib.Path(root) if root else self.path.parents[2];self.poll_interval=poll_interval;self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
  with self.db() as c:
   c.executescript('CREATE TABLE IF NOT EXISTS clients(id TEXT PRIMARY KEY,name TEXT NOT NULL,internal INTEGER NOT NULL,created_at TEXT NOT NULL); CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,client_id TEXT NOT NULL,name TEXT NOT NULL,internal INTEGER NOT NULL,created_at TEXT NOT NULL,config TEXT NOT NULL); CREATE TABLE IF NOT EXISTS diagnostics(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,request_hash TEXT NOT NULL,payload TEXT NOT NULL); CREATE TABLE IF NOT EXISTS shares(id TEXT PRIMARY KEY,diagnostic_id TEXT NOT NULL,token_hash TEXT UNIQUE NOT NULL,created_at TEXT NOT NULL,expires REAL NOT NULL,revoked INTEGER NOT NULL,snapshot TEXT NOT NULL);')
   c.execute('INSERT OR IGNORE INTO clients VALUES(?,?,?,?)',('internal-history','历史记录',1,now()))
   c.execute('INSERT OR IGNORE INTO projects VALUES(?,?,?,?,?,?)',('internal-history','internal-history','内部历史记录',1,now(),'{}'))
   for did,payload in c.execute('SELECT id,payload FROM diagnostics').fetchall():
    d=json.loads(payload)
    if d['status'] not in TERMINAL:d.update(status='interrupted',stage='interrupted',error_code='interrupted');c.execute('UPDATE diagnostics SET payload=? WHERE id=?',(json.dumps(d,ensure_ascii=False),did))
  self.import_history()
 @contextlib.contextmanager
 def db(self):
  c=None
  try:
   c=sqlite3.connect(self.path,timeout=5);c.execute('PRAGMA foreign_keys=ON')
   with c:yield c
  except (sqlite3.Error,OSError,ValueError):raise DiagnosticError(503,'diagnostic_store_unavailable') from None
  finally:
   if c:c.close()
 def save(self,d):
  safe=self.w.sanitize(d)
  with self.db() as c:c.execute('UPDATE diagnostics SET payload=? WHERE id=?',(json.dumps(safe,ensure_ascii=False),d['id']))
 def raw(self,did):
  ident(did)
  with self.db() as c:row=c.execute('SELECT payload FROM diagnostics WHERE id=?',(did,)).fetchone()
  if not row:raise DiagnosticError(404,'not_found')
  try:return json.loads(row[0])
  except ValueError:raise DiagnosticError(503,'diagnostic_store_unavailable') from None
 def detail(self,did):
  d=self.raw(did)
  with self.db() as c:d['shares']=[{'share_id':r[0],'created_at':r[1],'expires_at':datetime.datetime.fromtimestamp(r[2],datetime.timezone.utc).isoformat(),'revoked':bool(r[3])} for r in c.execute('SELECT id,created_at,expires,revoked FROM shares WHERE diagnostic_id=? ORDER BY created_at DESC',(did,))]
  return d
 def listing(self):
  with self.db() as c:rows=c.execute('SELECT payload FROM diagnostics').fetchall()
  return {'diagnostics':sorted([{k:v for k,v in json.loads(r[0]).items() if k in ('id','project_id','client_id','status','stage','created_at','summary','error_code','baseline_id','brand','website','market','legacy_type','plan')} for r in rows],key=lambda d:d['created_at'],reverse=True)}
 def entities(self,kind,data=None):
  with self.db() as c:
   if data is not None:
    if self.w.redact_text(json.dumps(data,ensure_ascii=False))!=json.dumps(data,ensure_ascii=False):raise DiagnosticError(400,'invalid_request')
    allowed={'name'} if kind=='clients' else {'client_id','name','brand','market','question_set'}
    if set(data)-allowed or 'name' not in data:raise DiagnosticError(400,'invalid_request')
    name=text(data['name']);did=str(uuid.uuid4());created=now()
    if kind=='clients':c.execute('INSERT INTO clients VALUES(?,?,0,?)',(did,name,created))
    else:
     cid=data.get('client_id');row=c.execute('SELECT internal FROM clients WHERE id=?',(cid,)).fetchone()
     if not row or row[0]:raise DiagnosticError(400,'invalid_client')
     cfg={k:data[k] for k in ('brand','market','question_set') if k in data}
     if 'brand' in cfg:text(cfg['brand'])
     if 'market' in cfg and cfg['market'] not in ('CN','US'):raise DiagnosticError(400,'invalid_request')
     if 'question_set' in cfg and (not isinstance(cfg['question_set'],list) or len(cfg['question_set'])>30 or any(not isinstance(v,str) or len(v)>4000 for v in cfg['question_set'])):raise DiagnosticError(400,'invalid_request')
     c.execute('INSERT INTO projects VALUES(?,?,?,0,?,?)',(did,cid,name,created,json.dumps(cfg,ensure_ascii=False)))
   rows=c.execute('SELECT * FROM '+kind+' ORDER BY created_at').fetchall()
  if kind=='clients':return {'clients':[{'id':r[0],'name':r[1],'internal':bool(r[2]),'created_at':r[3]} for r in rows]}
  return {'projects':[{'id':r[0],'client_id':r[1],'name':r[2],'internal':bool(r[3]),'created_at':r[4],'config':json.loads(r[5])} for r in rows]}
 def admission(self):
  from remote_gateway import Failure
  if self.w.stopping() or self.w.maintenance_requested.is_set():raise DiagnosticError(503,'maintenance')
  if self.w.diagnostic_active or self.w.audit_active or self.w.enrich_active or self.w.api.call('geo','state').get('busy'):raise DiagnosticError(409,'busy')
  if self.w.active and self.w.api.call('geo','run?id='+self.w.active).get('status') in ('queued','running'):raise DiagnosticError(409,'busy')
 def create(self,data,baseline=None):
  if self.w.redact_text(json.dumps(data,ensure_ascii=False))!=json.dumps(data,ensure_ascii=False):raise DiagnosticError(400,'invalid_request')
  allowed={'audit_id','confirmed','profile_ids','project_id','request_id','mode'}
  if set(data)-allowed or not {'audit_id','confirmed','profile_ids','project_id','request_id'}<=set(data):raise DiagnosticError(400,'invalid_request')
  did=ident(data['request_id']);aid=ident(data['audit_id']);mode=data.get('mode','full')
  key=digest({'data':data,'baseline':baseline['id'] if baseline else None})
  with self.w.lock:
   with self.db() as c:
    previous=c.execute('SELECT request_hash,payload FROM diagnostics WHERE id=?',(did,)).fetchone()
    if previous:
     if previous[0]!=key:raise DiagnosticError(409,'request_conflict')
     return self.detail(did),200
    project=c.execute('SELECT client_id,internal,config FROM projects WHERE id=?',(data['project_id'],)).fetchone()
   if not project or project[1]:raise DiagnosticError(400,'invalid_project')
   if mode not in ('full','website'):raise DiagnosticError(400,'invalid_request')
   if not self.w.auditor:raise DiagnosticError(503,'audit_unavailable')
   audit=self.w.auditor.get_internal(aid)
   if audit['status'] in ('queued','running'):raise DiagnosticError(409,'busy')
   confirmed=validate_confirmation(data['confirmed'],audit);profiles=data['profile_ids']
   if not isinstance(profiles,list) or len(profiles)>16 or any(not isinstance(p,str) for p in profiles) or len(set(profiles))!=len(profiles):raise DiagnosticError(400,'invalid_request')
   if mode=='full' and (not profiles or not confirmed['brand']['name']):raise DiagnosticError(400,'invalid_request')
   if mode=='website' and profiles:raise DiagnosticError(400,'invalid_request')
   selected={p['id']:p for p in self.w.profiles}
   if any(p not in selected or audit['market'] not in selected[p].get('markets',[]) for p in profiles):raise DiagnosticError(400,'invalid_request')
   cfg={'audit_id':aid,'website':audit['website']['requested_url'],'market':audit['market'],'confirmed':confirmed,'profile_ids':profiles,'mode':mode}
   comparison={'website':cfg['website'],'market':cfg['market'],'confirmed':confirmation_input(confirmed),'profiles':[selected[p] for p in profiles],'rule_version':RULES['version'],'parser_version':RULES['parser_version']}
   project_config=json.loads(project[2])
   question_context={'website':cfg['website'],'market':cfg['market'],'brand_aliases':sorted({a.casefold() for a in confirmed['brand']['aliases']})}
   project_questions=project_config.get('question_set',[]) if project_config.get('question_context')==question_context else []
   if project_questions and (len(project_questions)!=30 or len({q.strip().casefold() for q in project_questions})!=30):raise DiagnosticError(400,'invalid_question_set')
   plan={'generation_calls':3 if mode=='full' and not baseline and not project_questions else 0,'answer_calls':30*len(profiles) if mode=='full' else 0,'count':30,'repeats':1};plan['maximum_calls']=plan['generation_calls']+plan['answer_calls']
   if mode=='full':
    self.w.require_admission()
    if plan['maximum_calls']>self.w.budget.state()['remaining']:raise DiagnosticError(429,'daily_budget_exceeded')
   self.admission()
   d={'id':did,'project_id':data['project_id'],'client_id':project[0],'status':'queued','stage':'queued','created_at':now(),'brand':confirmed['brand']['name'],'website':cfg['website'],'market':cfg['market'],'config':cfg,'comparison_config':comparison,'plan':plan,'audit_id':aid,'job_id':None,'bundle':None,'summary':None,'error_code':None,'baseline_id':baseline['id'] if baseline else None,'trend':None,'legacy':None}
   if baseline:d['frozen_prompts']=copy.deepcopy(baseline['frozen_prompts']);d['question_set_version']=baseline['question_set_version']
   elif project_questions and mode=='full':d['frozen_prompts']=copy.deepcopy(project_questions);d['question_set_version']=digest(project_questions)
   with self.db() as c:
    c.execute('INSERT INTO diagnostics VALUES(?,?,?,?)',(did,d['project_id'],key,json.dumps(self.w.sanitize(d),ensure_ascii=False)))
    c.execute('UPDATE projects SET config=? WHERE id=?',(json.dumps({'brand':d['brand'],'website':d['website'],'market':d['market'],'question_context':question_context,'question_set':d.get('frozen_prompts',[])}),d['project_id']))
   self.w.diagnostic_active=did
   try:self.pool.submit(self.execute,d,baseline)
   except RuntimeError:self.w.diagnostic_active=None;d.update(status='interrupted',stage='interrupted',error_code='interrupted');self.save(d);raise DiagnosticError(503,'diagnostic_unavailable') from None
   return copy.deepcopy(d),202
 def wait_audit(self,aid):
  while True:
   a=self.w.auditor.get_internal(aid)
   with self.w.lock:active=self.w.audit_active==a['id']
   if a['status'] not in ('queued','running') and not active:return a
   if self.w.stopping():raise DiagnosticError(503,'interrupted')
   time.sleep(self.poll_interval)
 def extra_pages(self,a):
  from audit_fetch import origin,FetchBudget
  resources=a['_internal']['resources'];seed=resources[0];robots=next((r for r in resources if r['kind']=='robots'),None);usage=a['usage'];budget=self.w.auditor.budget_factory(usage);budget.max_resources=8;budget.admission=lambda:not self.w.stopping() and not self.w.maintenance_requested.is_set()
  base=origin(seed['url']);existing={r['url'] for r in resources};links=(seed.get('parsed') or {}).get('metadata',{}).get('product_links',[]);extra=[]
  def permitted(url):
   if not robots:return False
   if robots.get('status') in (404,410):return True
   if robots.get('error') or not robots.get('text'):return False
   try:return budget.run('robots',(robots['text'],[url],['SignalGEO/1.0']))['SignalGEO/1.0'][url]
   except Exception:return False
  def priority(link):
   href=link.get('href','').lower();return 0 if re.search(r'/products?/',href) else 1 if re.search(r'about|contact|privacy|terms|policy',href) else 2
  def role(url):
   path=urllib.parse.urlsplit(url).path.lower();return 'product' if re.search(r'/products?/',path) else 'about' if 'about' in path else 'contact' if 'contact' in path else 'policy' if re.search(r'privacy|terms|policy',path) else 'other'
  roles={role(r['url']) for r in resources if r.get('parsed')}
  for link in sorted(links,key=priority):
   if len(extra)>=2 or budget.usage['resources_requested']>=8 or budget.remaining()<=0:break
   try:
    from website_inspection import normalize_url
    url=normalize_url(urllib.parse.urljoin(seed['url'],link.get('href','')))
   except (ValueError,TypeError):continue
   if url in existing or origin(url)!=base or role(url) in roles:continue
   existing.add(url)
   if not permitted(url):continue
   roles.add(role(url));extra.append(budget.fetch(url,'about',base,permitted=permitted))
  return extra,budget.finish()
 def source_material(self,d,audit,extra,usage):
  resources=(audit['_internal']['resources']+extra)[:8];parts=[];remaining=24000
  for resource in resources:
   if resource.get('error') or not resource.get('parsed'):continue
   content=resource['parsed'].get('extracted_text') or resource['parsed'].get('text','')
   if not content:continue
   block=('Source URL: '+resource['url']+'\n'+content)[:remaining];parts.append(block);remaining-=len(block)+2
   if remaining<=0:break
  snapshot={'version':'audited-material-v1','website':d['website'],'captured_at':now(),'text':'\n\n'.join(parts)[:24000],'resources':[{'url':r['url'],'http_status':r.get('status'),'error_code':r.get('error'),'sha256':r.get('sha256')} for r in resources],'usage':usage,'limits':{'resources':8,'http_requests':10,'bytes':4*1024*1024,'active_seconds':60}}
  snapshot['evidence_signature']=digest(snapshot)
  return snapshot
 def execute(self,d,baseline=None):
  try:
   d.update(status='running',stage='website');self.save(d)
   if baseline:
    aid=str(uuid.uuid4())
    with self.w.lock:
     if self.w.stopping() or self.w.maintenance_requested.is_set():raise DiagnosticError(503,'maintenance')
     self.w.auditor.start(aid,d['website'],d['market'])
    d['audit_id']=aid;d['config']['audit_id']=aid;self.save(d);self.wait_audit(aid)
   with self.w.lock:
    if self.w.stopping() or self.w.maintenance_requested.is_set():raise DiagnosticError(503,'maintenance')
    self.w.auditor.confirm(d['audit_id'],confirmation_input(d['config']['confirmed']))
   audit=self.wait_audit(d['audit_id']);extra,usage=self.extra_pages(audit);d['website_usage']=usage;d['pages']=[{'url':r['url'],'status':r.get('status'),'error_code':r.get('error')} for r in audit['_internal']['resources']+extra];d['bundle']=bundle_for(d,self.w.auditor.public(audit),extra=extra);d['summary']=d['bundle']['scores'];self.save(d)
   flow=None
   if d['config']['mode']=='full':
    confirmed=d['config']['confirmed'];profiles=d['config']['profile_ids']
    cfg={'website':d['website'],'market':d['market'],'brand_aliases':confirmed['brand']['aliases'],'skus':[{k:p[k] for k in ('name','aliases')} for p in confirmed['products']],'competitors':[{k:p.get(k,[]) for k in ('name','aliases','domains')} for p in confirmed['competitors']],'context':confirmed.get('context',''),'providers':profiles,'generator':profiles[0],'count':30,'repeats':1}
    path='sample' if d.get('frozen_prompts') else 'start'
    if d.get('frozen_prompts'):cfg['prompts']=d['frozen_prompts']
    d['stage']='model_submitting';self.save(d)
    result,_=self.w.dispatch(path,cfg,_diagnostic=d['id'],_source_snapshot=self.source_material(d,audit,extra,usage) if path=='start' else None);d['job_id']=result['id'];d['stage']='sampling';self.save(d)
    while True:
     flow=self.w.api.call('geo','run?id='+d['job_id'])
     if flow['status'] not in ('queued','running'):break
     if self.w.stopping():raise DiagnosticError(503,'interrupted')
     time.sleep(self.poll_interval)
    d['frozen_prompts']=[p['text'] if isinstance(p,dict) else p for p in flow.get('prompts',[])];d['question_set_version']=digest(d['frozen_prompts'])
    d['bundle']=bundle_for(d,self.w.auditor.public(audit),flow,extra);d['summary']=d['bundle']['scores']
    if flow['status'] not in ('finished','partial'):d['error_code']='sampling_incomplete'
   else:d['frozen_prompts']=[];d['question_set_version']=digest([])
   d['status']='finished' if d['summary']['total'] is not None and (not flow or flow['status']=='finished') else 'partial';d['stage']='done';d['completed_at']=now()
   if baseline:d['trend']=self.compare(baseline,d)
   with self.db() as c:
    row=c.execute('SELECT config FROM projects WHERE id=?',(d['project_id'],)).fetchone();pc=json.loads(row[0]);pc['question_set']=d['frozen_prompts'];pc['question_set_version']=d['question_set_version'];c.execute('UPDATE projects SET config=? WHERE id=?',(json.dumps(pc,ensure_ascii=False),d['project_id']))
   self.save(d)
  except Exception as e:
   code=getattr(e,'code','diagnostic_failed');d.update(status='partial' if d.get('bundle') else 'interrupted' if code=='interrupted' else 'failed',stage='done',error_code=code if re.fullmatch(r'[a-z_]{1,64}',str(code)) else 'diagnostic_failed',completed_at=now());self.save(d)
  finally:
   with self.w.lock:
    if self.w.diagnostic_active==d['id']:self.w.diagnostic_active=None
 def compare(self,baseline,current):
  differences=[]
  if baseline.get('comparison_config')!=current.get('comparison_config'):differences.append('configuration')
  for key in ('rule_version','parser_version','question_set_version','page_set_version','judge_version'):
   if baseline.get('bundle',{}).get('run_manifest',{}).get(key)!=current.get('bundle',{}).get('run_manifest',{}).get(key):differences.append(key)
  def sampling_signature(record):
   rows=(record.get('bundle') or {}).get('answers',[])
   fields=('question_id','question','question_version','question_type','platform','entry','market','language','region','citation_supported','citation_type')
   return sorted((digest([row.get(k) for k in fields]) for row in rows))
  if sampling_signature(baseline)!=sampling_signature(current):differences.append('actual_sampling_conditions')
  if any(a.get('cached') or a.get('truncated') for d in (baseline,current) for a in (d.get('bundle') or {}).get('answers',[])):differences.append('cached_or_truncated_samples')
  comparable=not differences
  return {'baseline_id':baseline['id'],'comparable':comparable,'differences':differences,'baseline':baseline.get('summary'),'current':current.get('summary'),'delta':{k:round(current['summary'][k]-baseline['summary'][k],2) for k in ('lower','upper') if comparable and current['summary'].get(k) is not None and baseline['summary'].get(k) is not None} if comparable else None,'note':'配置一致不证明因果效果；网站准备度与模型表现分别解读。'}
 def retest(self,data):
  if set(data)!={'id','request_id'}:raise DiagnosticError(400,'invalid_request')
  original=self.raw(data['id'])
  if original.get('legacy') or original['status'] not in ('finished','partial') or not original.get('bundle'):raise DiagnosticError(409,'diagnostic_not_retestable')
  if original['config']['mode']=='full' and len(original.get('frozen_prompts',[]))!=30:raise DiagnosticError(409,'question_set_unavailable')
  cfg=original['config'];return self.create({'audit_id':original['audit_id'],'confirmed':confirmation_input(cfg['confirmed']),'profile_ids':cfg['profile_ids'],'project_id':original['project_id'],'request_id':data['request_id'],'mode':cfg['mode']},original)
 def share(self,data):
  if set(data)!={'id'}:raise DiagnosticError(400,'invalid_request')
  d=self.raw(data['id'])
  with self.db() as c:
   project=c.execute('SELECT internal FROM projects WHERE id=?',(d['project_id'],)).fetchone()
   if not project or project[0] or d.get('legacy'):raise DiagnosticError(403,'internal_project_not_shareable')
   if d['status'] not in ('finished','partial') or not d.get('bundle'):raise DiagnosticError(409,'diagnostic_not_shareable')
   snapshot={k:copy.deepcopy(d[k]) for k in ('brand','website','market','created_at','status','summary','bundle')};snapshot['bundle']['run_manifest']['run_id']='shared-report'
   snapshot['bundle'].get('source_snapshot',{}).pop('model_analysis',None)
   share_token=secrets.token_urlsafe(32);sid=str(uuid.uuid4());created=now();expires=time.time()+SHARE_AGE
   c.execute('INSERT INTO shares VALUES(?,?,?,?,?,0,?)',(sid,d['id'],hashlib.sha256(share_token.encode()).hexdigest(),created,expires,json.dumps(snapshot,ensure_ascii=False)))
  return {'share_id':sid,'share_token':share_token,'expires_at':datetime.datetime.fromtimestamp(expires,datetime.timezone.utc).isoformat()}
 def revoke(self,data):
  if set(data)!={'share_id'}:raise DiagnosticError(400,'invalid_request')
  sid=ident(data['share_id'])
  with self.db() as c:
   if not c.execute('UPDATE shares SET revoked=1 WHERE id=?',(sid,)).rowcount:raise DiagnosticError(404,'not_found')
  return {'ok':True}
 def shared(self,token):
  if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise DiagnosticError(404,'not_found')
  with self.db() as c:row=c.execute('SELECT snapshot,expires,revoked FROM shares WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
  if not row or row[2] or row[1]<=time.time():raise DiagnosticError(404,'not_found')
  return {'diagnostic':json.loads(row[0]),'expires_at':datetime.datetime.fromtimestamp(row[1],datetime.timezone.utc).isoformat()}
 def import_history(self):
  # Source payloads remain untouched, never relabelled as v0.1 or shareable.
  entries=[]
  if self.w.auditor:
   with self.w.auditor.db() as c:entries += [('audit',r[0],json.loads(r[1])) for r in c.execute('SELECT id,payload FROM audits')]
  for p in (self.root/'runtime/geo-flows').glob('*/flow.json'):
   try:entries.append(('flow',p.parent.name,json.loads(p.read_text())))
   except (OSError,ValueError):continue
  with self.db() as c:
   for kind,source,payload in entries:
    did=str(uuid.uuid5(uuid.NAMESPACE_URL,'signal-history:'+kind+':'+source));cfg=payload.get('config',{});public=self.w.auditor.public(payload) if kind=='audit' else payload
    d={'id':did,'project_id':'internal-history','client_id':'internal-history','status':payload.get('status','unknown'),'stage':'legacy','created_at':payload.get('created_at') or now(),'brand':cfg.get('brand_aliases',[''])[0] if cfg.get('brand_aliases') else (payload.get('confirmed') or {}).get('brand',{}).get('name',''),'website':cfg.get('website') or payload.get('website',{}).get('requested_url',''),'market':cfg.get('market') or payload.get('market'),'legacy_type':kind,'legacy':{'source_id':source,'schema':payload.get('schema_version','geo-flow-original'),'payload':public},'bundle':None,'summary':None,'error_code':None,'baseline_id':None,'trend':None}
    c.execute('INSERT OR IGNORE INTO diagnostics VALUES(?,?,?,?)',(did,'internal-history','legacy:'+kind+':'+source,json.dumps(self.w.sanitize(d),ensure_ascii=False)))
