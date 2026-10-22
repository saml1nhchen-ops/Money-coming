"""Independent zero-model finite website readiness workflow and rule report."""
import concurrent.futures,contextlib,copy,hashlib,importlib.metadata,json,pathlib,re,sqlite3,time,urllib.parse,uuid
from audit_fetch import FetchBudget,AuditFetchError,origin
import website_inspection
VERSION='geo-readiness-v1';RULE='geo-readiness-rules-v1.1'
SEARCH=['OAI-SearchBot','Claude-SearchBot','PerplexityBot','Googlebot']
AGENTS=[('*','usage_control'),('SignalGEO/1.0','usage_control'),*[(a,'search') for a in SEARCH],('GPTBot','training'),('GPTBot/1.2','training'),('ClaudeBot','training'),('ChatGPT-User','user_triggered'),('Claude-User','user_triggered')]
class AuditError(Exception):
 def __init__(self,status,code):self.status=status;self.code=code

def tools_available():
 try:return importlib.metadata.version('Protego')=='0.7.0' and importlib.metadata.version('trafilatura')=='2.3.1'
 except importlib.metadata.PackageNotFoundError:return False

def now():return __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def normalize(value):return website_inspection.normalize_url(value)
def evidence(resource,field=None,excerpt=None):
 ident='e-'+digest([resource['id'],field,excerpt])[:20]
 return {'id':ident,'resource_id':resource['id'],'url':resource['url'],'captured_at':resource['captured_at'],'http_status':resource.get('status'),'content_type':resource.get('diagnostics',{}).get('content_type'),'redirects':resource.get('diagnostics',{}).get('redirects',[]),**({'sha256':resource['sha256']} if resource.get('sha256') else {}),**({'source_field':field} if field else {}),**({'excerpt':excerpt} if excerpt is not None else {}),**({'error_code':resource['error']} if resource.get('error') else {})}
def add_evidence(audit,resource,field=None,excerpt=None):
 item=evidence(resource,field,excerpt)
 if not any(e['id']==item['id'] for e in audit['evidence']):audit['evidence'].append(item)
 return item['id']
def candidate(audit,resource,name,kind,field,basis='website_metadata'):
 name=' '.join(name.split())[:200];eid=add_evidence(audit,resource,field,name)
 return {'id':'candidate-'+digest([kind,name,resource['url'],field])[:20],'name':name,'aliases':[name],'kind':kind,'basis':basis,'source_url':resource['url'],'source_field':field,'evidence_ids':[eid],'needs_confirmation':True}
def preview_candidates(audit,seed):
 if seed.get('error') or not seed.get('parsed'):return
 meta=seed['parsed']['metadata'];brand=None
 if meta.get('site_name'):brand=candidate(audit,seed,meta['site_name'],'brand','meta[property="og:site_name"]')
 elif meta.get('structured_names'):
  row=meta['structured_names'][0];brand=candidate(audit,seed,row['name'],'brand',row['source'])
 elif meta.get('title'):
  name=re.split(r'\s+[|–—-]\s+|[|｜]',meta['title'],maxsplit=1)[0].strip()
  if name:brand=candidate(audit,seed,name,'brand','Markdown H1' if meta.get('source_format')=='markdown' else 'title',basis='website_text' if meta.get('source_format')=='markdown' else 'website_metadata')
 products=[];seen=set()
 for row in meta.get('product_names',[]):
  if row['name'].casefold() in seen:continue
  seen.add(row['name'].casefold());products.append(candidate(audit,seed,row['name'],'product',row['source']))
 linked=[]
 for link in meta.get('product_links',[]):
  name=re.sub(r'\s*[:|–—-]\s*(?:get notified|shop now|learn more|discover more)\s*$','',link['text'].strip(),flags=re.I);link={**link,'text':name};url=urllib.parse.urljoin(seed['url'],link['href'])
  try:same=origin(normalize(url))==origin(seed['url'])
  except ValueError:same=False
  path=urllib.parse.urlsplit(url).path
  if re.fullmatch(r'[A-Za-z]{2}',name) or re.match(r'^(?:all|shop|view|explore|discover|browse|see|buy|learn|read|sign)\b',name,re.I):continue
  if not same or not path.strip('/') or not name or len(name)>120 or name.casefold() in ('shop','shop all','shop now','all products','new','new & featured','new arrivals','best sellers','latest drops','men','women','kids','sale','contact','contact us','购物','联系我们'):continue
  if re.search(r'/(?:help|contact|privacy|terms|login|register|membership|cart|orders|blog|magazine|articles?)(?:/|$)',path,re.I):continue
  product=bool(link.get('product_marker') or re.search(r'/(?:products?|t)/[^/]+',path,re.I))
  category=bool(re.search(r'/(?:collections?|categor(?:y|ies)|w)/[^/]+',path,re.I) or re.search(r'^/(?:makeup|skin-care|hair-care|hair-color|shaving|body-care)(?:/|$)',path,re.I))
  if product or category:linked.append((0 if product else 1,link,url))
 for priority,link,url in sorted(linked,key=lambda row:row[0]):
  name=link['text'].strip()
  if name.casefold() in seen:continue
  seen.add(name.casefold());field='Markdown link' if meta.get('source_format')=='markdown' else 'a[href]';row=candidate(audit,seed,name,'product' if priority==0 else 'category',field,basis='website_text');row['evidence_ids']=[add_evidence(audit,seed,field,name+' — '+url)];products.append(row)
 competitors=[];body=seed['parsed'].get('text','')
 for link in meta.get('product_links',[]):
  name=link['text'].strip()
  if not name or len(name)>100 or brand and name.casefold()==brand['name'].casefold():continue
  match=re.search(r'(?:versus|\bvs\.?|compared (?:to|with)|alternative to)\s+'+re.escape(name)+r'\b',body,re.I)
  if match:
   row=candidate(audit,seed,name,'competitor','body.comparison','website_text');eid=add_evidence(audit,seed,'body.comparison',body[max(0,match.start()-100):match.end()+100]);row['evidence_ids']=[eid];competitors.append(row)
 if any(row['kind']=='product' for row in products):products=[row for row in products if row['kind']=='product']
 audit['candidates']={'brand':brand,'products':products[:6],'competitors':competitors[:5]}

def preview_fallback(audit,budget):
 """Only published same-origin Markdown supplements missing page metadata."""
 data=audit['_internal'];seed=data['resources'][0];base=origin(seed['url'])
 if seed['url'] in (base+'/robots.txt',base+'/llms.txt'):return
 robots=budget.fetch(base+'/robots.txt','robots',base);data['resources'].append(robots);add_evidence(audit,robots)
 policy=robots_policy(robots,budget,seed['url']);data['robots']=policy
 def permitted(url):
  if policy['fetch_status']=='not_found':return True
  if policy['fetch_status']!='available':return False
  try:return budget.run('robots',(robots['text'],[url],['SignalGEO/1.0']))['SignalGEO/1.0'][url]
  except AuditFetchError:return False
 url=base+'/llms.txt'
 if not permitted(url):return
 resource=budget.fetch(url,'llms',base,permitted=permitted);data['resources'].append(resource);add_evidence(audit,resource)
 if resource.get('error'):return
 text=resource.get('text','');heading=re.search(r'^#\s+([^\n]{1,200})\s*$',text,re.M)
 links=[{'text':name.strip(),'href':href.strip()} for name,href in re.findall(r'\[([^\]\n]{1,120})\]\(([^\s)]+)\)',text)[:100]]
 temporary={'evidence':audit['evidence'],'candidates':{}}
 snapshot={**resource,'parsed':{'metadata':{'source_format':'markdown','title':heading[1].strip() if heading else '','product_links':links},'text':text}}
 preview_candidates(temporary,snapshot)
 supplied=False
 for field in ('brand','products'):
  if not audit['candidates'][field] and temporary['candidates'][field]:audit['candidates'][field]=temporary['candidates'][field];supplied=True
 if supplied:audit['warnings'].append('部分识别候选来自官网公开 llms.txt，未将其当作首页正文；请核对来源。')

def validate_confirmation(payload,audit):
 if not isinstance(payload,dict) or set(payload)-{'brand','products','competitors','context'}:raise AuditError(400,'invalid_request')
 def aliases(value):return isinstance(value,list) and 0<=len(value)<=20 and all(isinstance(x,str) and 0<len(x.strip())<=200 for x in value)
 brand=payload.get('brand')
 if not isinstance(brand,dict) or set(brand)-{'name','aliases'} or not isinstance(brand.get('name'),str) or len(brand['name'].strip())>200 or not aliases(brand.get('aliases')) or not brand['name'].strip() and brand.get('aliases')!=[]:raise AuditError(400,'invalid_request')
 def normalized_aliases(name,values):
  result=[];seen=set()
  for value in ([name] if name else [])+values:
   value=value.strip();key=value.casefold()
   if value and key not in seen:seen.add(key);result.append(value)
  return result
 result={'brand':{'name':brand['name'].strip(),'aliases':normalized_aliases(brand['name'].strip(),brand['aliases'])}}
 original=audit['candidates'].get('brand')
 result['brand'].update(basis=original['basis'] if original and original['name']==result['brand']['name'] and original['aliases']==result['brand']['aliases'] else 'user_modified' if original else 'user_provided',evidence_ids=original['evidence_ids'] if original and original['name']==result['brand']['name'] and original['aliases']==result['brand']['aliases'] else [])
 for field in ('products','competitors'):
  rows=payload.get(field,[])
  if not isinstance(rows,list) or len(rows)>(6 if field=='products' else 5):raise AuditError(400,'invalid_request')
  candidates={c['id']:c for c in audit['candidates'][field]};clean=[]
  for row in rows:
   if not isinstance(row,dict) or set(row)-{'name','aliases','source_candidate_id','domains'} or not isinstance(row.get('name'),str) or not 0<len(row['name'].strip())<=200 or not aliases(row.get('aliases')):raise AuditError(400,'invalid_request')
   domains=row.get('domains',[])
   if not isinstance(domains,list) or any(not isinstance(d,str) or not re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+',d) for d in domains):raise AuditError(400,'invalid_request')
   source=candidates.get(row.get('source_candidate_id'));name=row['name'].strip();als=normalized_aliases(name,row['aliases']);same=source and source['name']==name and source['aliases']==als and (field!='competitors' or domains==source.get('domains',[]))
   clean.append({'name':name,'aliases':als,'basis':source['basis'] if same else 'user_modified' if source else 'user_provided','evidence_ids':source['evidence_ids'] if same else [],**({'domains':domains} if field=='competitors' else {}),**({'source_candidate_id':source['id']} if source else {})})
  if len({r['name'].casefold() for r in clean})!=len(clean):raise AuditError(400,'invalid_request')
  result[field]=clean
 context=payload.get('context','')
 if not isinstance(context,str) or len(context)>18000:raise AuditError(400,'invalid_request')
 result.update(context=context,confirmed_at=now());return result

def request_path(url):
 u=urllib.parse.urlsplit(url);return (u.path or '/')+('?' +u.query if u.query else '')

def robots_policy(resource,budget,url):
 status='not_found' if resource.get('status') in (404,410) else 'unknown';decisions={};paths=list(dict.fromkeys(['/',request_path(url)]))
 if not resource.get('error') and 200<=resource.get('status',0)<300:
  text=resource.get('text','');meaningful='\n'.join(line.split('#',1)[0].strip() for line in text.splitlines()).strip()
  if not meaningful or re.search(r'^\s*(?:user-agent|allow|disallow|sitemap)\s*:',text,re.I|re.M):
   try:decisions=budget.run('robots',(text,[origin(url)+p for p in paths],[a for a,_ in AGENTS]));status='available'
   except AuditFetchError:status='unknown'
 agents=[]
 for agent,purpose in AGENTS:
  for path in paths:
   decision='not_found' if status=='not_found' else ('allowed' if decisions[agent][origin(url)+path] else 'disallowed') if status=='available' else 'unknown'
   agents.append({'user_agent':agent,'purpose':purpose,'path':path,'decision':decision,'parser':'protego','evidence_ids':[],'notes':['Protego解析结果；未提供精确命中行。','训练策略与搜索/用户触发分别展示，不代表推荐概率。']+(['Googlebot仅说明搜索爬虫，不代表全部AI产品。'] if agent=='Googlebot' else ['用户触发UA的解析结果不保证客户端实际遵守。'] if purpose=='user_triggered' else [])})
 return {'resource_id':resource['id'],'fetch_status':status,'agents':agents}

def collect_report_resources(audit,budget):
 data=audit['_internal'];resources=data['resources'];seed=resources[0];base=origin(seed['url']);robots=next((r for r in resources if r['kind']=='robots'),None)
 if robots is None:robots=budget.fetch(base+'/robots.txt','robots',base);resources.append(robots)
 policy=robots_policy(robots,budget,seed['url']);data['robots']=policy
 def permitted(url):
  if policy['fetch_status']=='not_found':return True
  if policy['fetch_status']!='available':return False
  try:return budget.run('robots',(robots['text'],[url],['SignalGEO/1.0']))['SignalGEO/1.0'][url]
  except AuditFetchError:return False
 def auxiliary(url,kind):
  if any(r['kind']==kind and r.get('requested_url',r['url'])==url for r in resources):return
  if audit.get('_stopping') or not permitted(url):audit['warnings'].append('辅助资源未请求：robots策略不允许或获取状态未知。');return
  if budget.remaining()<=0 or budget.usage['resources_requested']>=6 or budget.usage['http_requests']>=10:return
  resources.append(budget.fetch(url,kind,base,permitted=permitted))
 auxiliary(base+'/llms.txt','llms')
 parsed_seed=seed.get('parsed') if not seed.get('error') else None;metadata={}
 if parsed_seed:
  metadata=parsed_seed.get('metadata',{})
  markdown=next((urllib.parse.urljoin(seed['url'],href) for href in metadata.get('markdown_alternates',[]) if _same_origin(urllib.parse.urljoin(seed['url'],href),base)),seed['url'])
  auxiliary(markdown,'markdown')
 if any('llms-full.txt' in r.get('text','') for r in resources if r.get('kind')=='llms'):auxiliary(base+'/llms-full.txt','llms-full')
 about=next((urllib.parse.urljoin(seed['url'],row['href']) for row in metadata.get('product_links',[]) if re.search(r'/(?:about|compare|comparison)(?:[/-]|$)',urllib.parse.urlsplit(row['href']).path,re.I) and _same_origin(urllib.parse.urljoin(seed['url'],row['href']),base)),None)
 if about:auxiliary(about,'about')
 data['usage']=budget.finish();audit['usage']=data['usage']

def _same_origin(url,base):
 try:return origin(normalize(url))==base
 except ValueError:return False

def build_report(audit):
 resources=audit['_internal']['resources'];seed=resources[0];parsed=seed.get('parsed') if not seed.get('error') else None;meta=parsed['metadata'] if parsed else {};policy=copy.deepcopy(audit['_internal'].get('robots',{'resource_id':None,'fetch_status':'unknown','agents':[]}));eids={}
 for r in resources:eids[r['id']]=add_evidence(audit,r,'robots.txt' if r['kind']=='robots' else 'response',r.get('text','')[:16000] if r['kind']=='robots' else None)
 for agent in policy['agents']:agent['evidence_ids']=[eids[policy['resource_id']]] if policy['resource_id'] in eids else []
 sections=[]
 def section(ident,title):s={'id':ident,'title':title,'checks':[]};sections.append(s);return s
 def check(section,ident,title,weight,status,reason,ids=None,action='补充页面证据后重新检测。'):
  section['checks'].append({'id':ident,'title':title,'weight':weight,'status':status,'reason':reason,'evidence_ids':ids or [eids[seed['id']]],'action':action,'methodology':RULE+'；仅本次有限公开网页证据，不是推荐概率或真实性认证。'})
 access=section('access','官网访问')
 check(access,'response','正常页面响应',15,'pass' if parsed else 'unknown','已获得可解析HTML页面。' if parsed else '访问失败、挑战或未取得可解析页面，无法判断正常内容。')
 tls=next((c['status'] for c in seed.get('diagnostics',{}).get('checks',[]) if c['id']=='tls'),'unknown')
 check(access,'tls','TLS证书与域名',5,'pass' if tls=='passed' else 'fail' if tls=='skipped' or tls=='failed' else 'unknown','本次最终页面TLS检查：'+tls)
 robots_section=section('robots','搜索与机器人策略')
 target_path=request_path(seed['url'])
 for agent in SEARCH:
  row=next((a for a in policy['agents'] if a['user_agent']==agent and a['path']==target_path),None);decision=row['decision'] if row else 'unknown'
  check(robots_section,'search-'+agent,agent+'搜索策略',5,'pass' if decision in ('allowed','not_found') else 'fail' if decision=='disallowed' else 'unknown','未发现robots声明，按RFC无已知限制；不是显式Allow。' if decision=='not_found' else '针对本页路径的Protego结论：'+decision,row['evidence_ids'] if row else [],'核对搜索UA与目标路径策略；训练限制单独解释。')
 content=section('content','可提取性与辅助文件')
 extracted=parsed.get('extracted_text') if parsed else None
 check(content,'extraction','Trafilatura正文提取',20,'unknown' if extracted is None else 'pass' if len(extracted)>=500 else 'fail','正文提取未完成，页面元信息与正文分别检查。' if parsed and extracted is None else '离线Trafilatura提取正文 '+str(len(extracted))+' 字符。' if extracted is not None else '未取得可解析HTML，不能判断正文可提取性。')
 check(content,'headings','标题与H1',10,'pass' if parsed and meta.get('title') and meta.get('h1') else 'fail' if parsed else 'unknown','title及H1均可观察。' if meta.get('title') and meta.get('h1') else '本次未同时观察到title与H1；失败读取不视作缺失。')
 check(content,'structured-data','语义结构化数据',10,'pass' if meta.get('semantic_types') else 'fail' if parsed else 'unknown','观察到可解析语义类型：'+', '.join(meta.get('semantic_types',[])) if meta.get('semantic_types') else '未观察到有效语义结构化数据，或页面不可读取。')
 for kind,label in [('llms','llms.txt'),('markdown','Markdown替代'),('llms-full','llms-full.txt')]:
  resource=next((r for r in resources if r['kind']==kind),None);status='pass' if resource and not resource.get('error') and (kind!='markdown' or resource.get('diagnostics',{}).get('content_type') in ('text/markdown','text/x-markdown')) else 'not_applicable' if resource and resource.get('status') in (404,410) else 'unknown'
  check(content,kind,label,0,status,'辅助信号，缺失不扣分，不保证模型推荐。'+(' 明确未发现。' if status=='not_applicable' else ' 未请求或失败保持未知。' if status=='unknown' else ' 已取得符合类型的资源。'),[eids[resource['id']]] if resource else [],'可选提供清晰的公开文本文件并复测；非强制要求。')
 declarations={**meta.get('robots_meta',{}),**({'x-robots-tag':seed['headers']['X-Robots-Tag']} if seed.get('headers',{}).get('X-Robots-Tag') else {})}
 noindex=any(re.search(r'(?<![A-Za-z])noindex(?![A-Za-z])',v,re.I) for v in declarations.values())
 index_ids=[add_evidence(audit,seed,key,value) for key,value in declarations.items()]
 check(content,'indexing-declarations','页面收录声明',0,'fail' if noindex else 'pass' if parsed else 'unknown','观察到含noindex的页面收录声明；不是训练限制，也不保证AI行为。UA前缀不推断作用范围。' if noindex else '已读取页面与白名单响应头，未观察到noindex；不保证实际收录。' if parsed else '页面未读取，无法检查收录声明。',index_ids or None,'核对meta robots/googlebot及X-Robots-Tag的预期收录声明，再重新检测。')
 trust=section('trust','官网身份与联系线索')
 observed=[r for r in resources if r.get('parsed') and not r.get('error') and r['kind'] in ('seed','about')];observed_meta=[r['parsed']['metadata'] for r in observed]
 links=[link for m in observed_meta for link in m.get('product_links',[])];text='\n'.join(r['parsed'].get('text','') for r in observed)
 identity=any(m.get('site_name') or any(re.search(r'Organization|Corporation|Brand|LocalBusiness',r.get('source','')) for r in m.get('structured_names',[])) for m in observed_meta)
 contact=bool(re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',text) or any(str(r.get('href','')).startswith(('mailto:','tel:')) or re.search(r'contact|联系',r.get('text',''),re.I) for r in links))
 policies=any(re.search(r'privacy|terms|policy|隐私|条款',r.get('text','')+' '+r.get('href',''),re.I) for r in links)
 for ident,label,weight,hit in [('identity','组织或品牌身份线索',10,identity),('contact','联系线索',5,contact),('policy','政策链接线索',5,policies)]:
  ids=[]
  for resource in observed:
   m=resource['parsed']['metadata'];excerpt=json.dumps(m.get('structured_names',[]),ensure_ascii=False) if ident=='identity' else '\n'.join(x.get('text','')+' '+x.get('href','') for x in m.get('product_links',[]) if re.search(r'contact|mail|tel:|联系' if ident=='contact' else r'privacy|terms|policy|隐私|条款',x.get('text','')+' '+x.get('href',''),re.I))
   if ident=='identity' and m.get('site_name'):excerpt=m['site_name']+' '+excerpt
   if excerpt and excerpt!='[]':ids.append(add_evidence(audit,resource,ident+'.observable_clues',excerpt[:2000]))
  check(trust,ident,label,weight,'pass' if hit else 'fail' if parsed else 'unknown','仅观察官网线索，未核验事实真实性或链接目标。' if hit else '可读页面未观察到该线索。' if parsed else '页面不可读，保持未知。',ids or None)
 check(trust,'author-date','作者和日期观察',0,'pass' if meta.get('author') or meta.get('date') else 'unknown','作者/日期仅作观察，不认证来源权威。')
 checks=[c for s in sections for c in s['checks']];known=sum(c['weight'] for c in checks if c['status'] in ('pass','fail'));passed=sum(c['weight'] for c in checks if c['status']=='pass');score=round(passed,1) if known==100 else None
 recommendations=[{'id':'recommend-'+c['id'],'priority':'high' if c['weight']>=10 else 'medium' if c['weight'] else 'low','check_ids':[c['id']],'evidence_ids':c['evidence_ids'],'action':c['action'],'retest':'用户明确选择重新检测后核对同规则与同页面。'} for c in checks if c['status'] in ('fail','unknown')]
 return {'schema_version':VERSION,'rule_version':RULE,'generated_at':now(),'target':{'url':seed['url'],'market':audit['market'],'brand':audit['confirmed']['brand']['name']},'scope':{'kind':'finite_website_readiness','resources':[{'id':r['id'],'url':r['url'],'kind':r['kind'],'http_status':r.get('status'),'error_code':r.get('error')} for r in resources],'limitations':['最多6资源/10HTTP/4MiB/累计60秒；无JS、无模型调用。','仅官网线索，不认证事实、外部权威或模型实际推荐。','未知和未请求不计通过；robots parser未提供精确命中行。'],'model_calls':0},'summary':{'score':score,'partial_score':round(100*passed/known,1) if known>=60 else None,'coverage_percent':known,'known_weight':known,'total_weight':100,**{k:sum(c['status']==v for c in checks) for k,v in [('passed','pass'),('failed','fail'),('unknown','unknown'),('not_applicable','not_applicable')]},'conclusions':(['观察到含noindex的页面收录声明，请先核对适用范围；这不是训练策略。'] if noindex else [])+['规则技术检测，尚未测试模型实际推荐表现。','证据不足，暂无完整分数。' if score is None else '分数仅描述本次有限页面规则检查。']},'sections':sections,'robots':policy,'evidence':copy.deepcopy(audit['evidence']),'recommendations':recommendations,'model_analysis':{'status':'not_tested','binding':{'audit_id':audit['id'],'url':seed['url'],'market':audit['market'],'brand_aliases':audit['confirmed']['brand']['aliases']},'job_id':None,'report':None}}

class AuditManager:
 def __init__(self,workspace,path,budget_factory=FetchBudget,suggestion_adapter=None):
  self.suggestion_adapter=suggestion_adapter
  if not tools_available():raise AuditError(503,'audit_unavailable')
  self.w=workspace;self.path=pathlib.Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.budget_factory=budget_factory;self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
  try:
   with self.db() as c:
    c.execute('CREATE TABLE IF NOT EXISTS audits(id TEXT PRIMARY KEY,url TEXT NOT NULL,market TEXT NOT NULL,rule TEXT NOT NULL,created INTEGER NOT NULL,payload TEXT NOT NULL)');c.execute('CREATE TABLE IF NOT EXISTS aliases(id TEXT PRIMARY KEY,audit TEXT NOT NULL)');c.execute('CREATE TABLE IF NOT EXISTS revisions(id TEXT,revision INTEGER,payload TEXT,PRIMARY KEY(id,revision))')
    for ident,text in c.execute('SELECT id,payload FROM audits').fetchall():
     a=json.loads(text)
     if a['status'] in ('queued','running'):
      a['status']='awaiting_confirmation' if a['phase']=='preview' else 'failed';a['phase']='confirmation' if a['phase']=='preview' else 'done';a['stage']='interrupted';a.get('competitor_suggestion',{}).update(status='interrupted') if a.get('competitor_suggestion',{}).get('status')=='attempting' else None;a['warnings'].append('服务曾重启；未自动继续抓取。');self.write(a,c)
  except (sqlite3.Error,ValueError,KeyError):raise AuditError(503,'audit_store_unavailable') from None
 @contextlib.contextmanager
 def db(self):
  connection=None
  try:
   connection=sqlite3.connect(self.path,timeout=3)
   with connection:yield connection
  except sqlite3.Error:raise AuditError(503,'audit_store_unavailable') from None
  finally:
   if connection:connection.close()
 def write(self,a,c=None):
  # Public sanitization must not strip internal headers needed for analysis.
  def scrub(v):
   if isinstance(v,str):return self.w.redact_text(v)
   if isinstance(v,list):return [scrub(x) for x in v]
   if isinstance(v,dict):return {self.w.redact_text(k):scrub(x) for k,x in v.items()}
   return v
  data=json.dumps(scrub(a),ensure_ascii=False)
  if c is not None:c.execute('UPDATE audits SET payload=? WHERE id=?',(data,a['id']))
  else:
   with self.db() as connection:connection.execute('UPDATE audits SET payload=? WHERE id=?',(data,a['id']))
 def get_internal(self,ident):
  with self.db() as c:row=c.execute('SELECT payload FROM audits WHERE id=COALESCE((SELECT audit FROM aliases WHERE id=?),?)',(ident,ident)).fetchone()
  if not row:raise AuditError(404,'not_found')
  try:return json.loads(row[0])
  except ValueError:raise AuditError(503,'audit_store_unavailable') from None
 def public(self,a,reused=None):
  result=copy.deepcopy(a);result.pop('_internal',None);result.pop('_confirmation_hash',None)
  if reused is not None:result['reused']=reused
  return result
 def get(self,ident,export=False):
  a=self.get_internal(ident)
  if export and a['report'] is None:raise AuditError(409,'audit_not_confirmed')
  return self.public(a)
 def lookup(self,ident,url,market,refresh=False):
  with self.db() as c:
   row=c.execute('SELECT audits.url,market,payload FROM audits JOIN aliases ON audits.id=aliases.audit WHERE aliases.id=?',(ident,)).fetchone()
   if row:
    if (row[0],row[1])!=(url,market):raise AuditError(400,'invalid_request')
    return self.public(json.loads(row[2]),True)
   if not refresh:
    row=c.execute('SELECT id,payload FROM audits WHERE url=? AND market=? AND rule=? AND created>=? ORDER BY created DESC LIMIT 1',(url,market,RULE,int(time.time())-86400)).fetchone()
    if row:c.execute('INSERT INTO aliases VALUES(?,?)',(ident,row[0]));return self.public(json.loads(row[1]),True)
  return None
 def _rate(self,c):
  if c.execute('SELECT COUNT(*) FROM audits WHERE created>?',(int(time.time())-3600,)).fetchone()[0]>=10:raise AuditError(429,'audit_rate_limited')
 def start(self,ident,url,market):
  import website_check
  check=website_check.Check();check.value['final_url']=url
  a={'schema_version':VERSION,'id':ident,'revision':0,'request_id':ident,'market':market,'status':'queued','phase':'preview','stage':'website','created_at':now(),'website':{'requested_url':url,'final_url':url,'origin':origin(url)},'access':check.value,'candidates':{'brand':None,'products':[],'competitors':[]},'evidence':[],'confirmed':None,'report':None,'warnings':[],'reused':False,'usage':{'http_requests':0,'resources_requested':0,'bytes_received':0,'active_duration_ms':0,'model_calls':0},'_internal':{'resources':[]}}
  with self.db() as c:
   self._rate(c);c.execute('INSERT INTO audits VALUES(?,?,?,?,?,?)',(ident,url,market,RULE,int(time.time()),json.dumps(a)));c.execute('INSERT INTO aliases VALUES(?,?)',(ident,ident))
  self.w.audit_active=ident;snapshot=self.public(a)
  try:self.pool.submit(self.preview,a)
  except RuntimeError:
   self.w.audit_active=None;a.update(status='awaiting_confirmation',phase='confirmation',stage='interrupted');self.write(a);raise AuditError(503,'audit_unavailable') from None
  return snapshot
 def preview(self,a):
  budget=self.budget_factory();budget.admission=lambda:not self.w.stopping() and not self.w.maintenance_requested.is_set()
  try:
   a['status']='running';self.write(a);seed=budget.fetch(a['website']['requested_url'],'seed');a['_internal']['resources']=[seed];a['access']=seed['diagnostics'];a['website'].update(final_url=seed['url'],origin=origin(seed['url']));add_evidence(a,seed);preview_candidates(a,seed)
   if seed.get('error') or not a['candidates']['brand'] or seed['diagnostics']['outcome']=='metadata_only':
    a['stage']='reading_alternate_metadata';self.write(a);preview_fallback(a,budget)
   if seed.get('error'):a['warnings'].append('官网证据不足，仍可手动确认生成包含未知项的完整报告。')
  except Exception:a['warnings'].append('读取未完成，已有证据保留；可手动确认。')
  finally:
   a['usage']=budget.finish();a['_internal']['usage']=a['usage']
   try:self.suggest_competitors(a)
   except Exception:a['competitor_suggestion']={'status':'unavailable','provider':'Pollinations Classic','model_calls':0,'message':'免费竞品建议未完成；未改用收费服务。'}
   a.update(status='awaiting_confirmation',phase='confirmation',stage='confirm_information')
   try:self.write(a)
   finally:
    with self.w.lock:
     if self.w.audit_active==a['id']:self.w.audit_active=None
 def suggest_competitors(self,a):
  from free_competitors import DOCS,Unavailable
  if self.suggestion_adapter is None:return
  brand=a['candidates']['brand']
  if not brand or self.w.stopping() or self.w.maintenance_requested.is_set():return
  suggestion={'status':'attempting','provider':self.suggestion_adapter.provider,'pricing':'anonymous_free_classic','pricing_source':DOCS,'model_calls':1,'maximum_model_calls':1,'requested_at':now(),'verified':False}
  a['competitor_suggestion']=suggestion;a['stage']='suggesting_competitors';self.write(a) # persist intent before the single request
  if self.w.stopping() or self.w.maintenance_requested.is_set():suggestion.update(status='skipped',model_calls=0);return
  try:
   result=self.suggestion_adapter.suggest(brand['name'],a['market'],[p['name'] for p in a['candidates']['products']])
   seen={brand['name'].casefold(),*(v['name'].casefold() for v in a['candidates']['competitors'])}
   for row in result['competitors']:
    if row['name'].casefold() in seen:continue
    seen.add(row['name'].casefold());a['candidates']['competitors'].append({'id':'candidate-'+digest(['free_ai',row['name'],a['id']])[:20],'name':row['name'],'aliases':[row['name']],'kind':'competitor','basis':'model_inference','source_url':None,'source_field':None,'evidence_ids':[],'needs_confirmation':True,'reason':row.get('reason',''),'domains':[]})
   a['candidates']['competitors']=a['candidates']['competitors'][:5]
   suggestion.update(status='complete',model=result.get('model'),raw_response=result.get('raw_response'),completed_at=now())
  except Unavailable as error:suggestion.update(status='unavailable',code=error.code,http_status=error.status,retry_after=error.retry_after,completed_at=now(),message='免费服务暂不可用；未重试、未支付、未切换收费模型。')
  except Exception:suggestion.update(status='unavailable',code='free_service_unavailable',completed_at=now(),message='免费建议未完成；未重试或切换收费模型。')
 def confirm(self,ident,payload):
  a=self.get_internal(ident);confirmed=validate_confirmation(payload,a);identity={k:v for k,v in confirmed.items() if k!='confirmed_at'};key=digest(identity)
  if a.get('_confirmation_hash')==key and a['report'] is not None:return self.public(a,True),200
  if a['status'] in ('queued','running'):raise AuditError(409,'busy')
  if not a['_internal'].get('resources'):
   # Interrupted preview: safe unknown evidence can still become a report.
   r={'id':'resource-1','url':a['website']['final_url'],'requested_url':a['website']['requested_url'],'kind':'seed','captured_at':now(),'status':None,'error':'interrupted','headers':{},'text':'','parsed':None,'diagnostics':a['access']};a['_internal']['resources']=[r]
  with self.db() as c:c.execute('INSERT OR REPLACE INTO revisions VALUES(?,?,?)',(a['id'],a['revision'],json.dumps(a,ensure_ascii=False)))
  a['confirmed']=confirmed;a['_confirmation_hash']=key;a['revision']+=1;a['report']=None;a.update(status='queued',phase='report',stage='reading_policies');self.write(a);self.w.audit_active=a['id'];snapshot=self.public(a)
  try:self.pool.submit(self.report,a)
  except RuntimeError:
   self.w.audit_active=None;a.update(status='failed',phase='done',stage='interrupted');self.write(a);raise AuditError(503,'audit_unavailable') from None
  return snapshot,202
 def report(self,a):
  budget=self.budget_factory(a['usage']);budget.admission=lambda:not self.w.stopping() and not self.w.maintenance_requested.is_set()
  try:
   a['status']='running';self.write(a)
   if not a['_internal'].get('report_resources_complete'):
    if not self.w.stopping() and not self.w.maintenance_requested.is_set():collect_report_resources(a,budget)
    a['_internal']['report_resources_complete']=True
   a['stage']='building_report';a['report']=build_report(a);a['status']='finished' if a['report']['summary']['score'] is not None else 'partial';a['phase']='done';a['stage']='report';a['completed_at']=now()
  except Exception:
   a['warnings'].append('部分规则未完成，未知项保留；未自动重试。')
   try:a['report']=build_report(a);a.update(status='partial',phase='done',stage='report',completed_at=now())
   except Exception:a.update(status='failed',phase='done',stage='audit_unavailable')
  finally:
   a['usage']=budget.finish();a['_internal']['usage']=a['usage']
   try:self.write(a)
   finally:
    with self.w.lock:
     if self.w.audit_active==a['id']:self.w.audit_active=None
