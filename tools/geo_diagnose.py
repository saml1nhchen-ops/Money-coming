"""Website -> representative pages -> fixed rule catalog -> v0.1 diagnostic bundle.

No model calls. Every judged rule cites fetched evidence; rules that the fetched
evidence cannot decide stay unknown for human review instead of scoring zero.
"""
import concurrent.futures,datetime,hashlib,ipaddress,json,pathlib,re,socket,threading,urllib.error,urllib.parse,urllib.request,urllib.robotparser,uuid
from html.parser import HTMLParser
import pinned_http,website_check,website_inspection
ROOT=pathlib.Path(__file__).resolve().parents[1];DATA=ROOT/'runtime/diagnostics'
CATALOG=json.loads((ROOT/'tools/diagnostic_rules.json').read_text('utf-8'))
MAX_PAGES=8;MAX_BYTES=2*1024*1024;UA='SignalGEO/1.0 diagnostic (no-js)'
PARSER_VERSION='signal-html-v1';JUDGE_VERSION='deterministic-v1'
CRAWLERS={'CN':['Baiduspider','Bytespider','Sogou web spider','YisouSpider','360Spider'],
          'US':['GPTBot','OAI-SearchBot','ChatGPT-User','ClaudeBot','Claude-SearchBot','PerplexityBot','Google-Extended','Googlebot','Bingbot']}
READABLE={'CN':200,'US':500}
CATEGORIES=[('about',r'about|company|our-?story|who-?we-?are|关于|品牌故事|公司简介|企业介绍|品牌介绍'),
            ('product',r'products?|shop|store|collections?|catalog|goods|solutions?|services?|产品|商品|服务|解决方案'),
            ('faq',r'faq|help|support|questions|常见问题|帮助|问答'),
            ('contact',r'contact|联系'),
            ('article',r'blog|news|articles?|insights|journal|stories|资讯|新闻|动态|文章|博客')]
POLICY={'privacy':r'privacy|隐私','terms':r'terms|conditions|legal|服务条款|用户协议|使用条款|法律声明'}
PROFILES=('weibo.com','xiaohongshu.com','douyin.com','zhihu.com','baike.baidu.com','bilibili.com','mp.weixin.qq.com','wikipedia.org','wikidata.org','linkedin.com','x.com','twitter.com','facebook.com','instagram.com','youtube.com','tiktok.com','crunchbase.com')
ORG_TYPES={'Organization','Corporation','LocalBusiness','Brand','OnlineStore','Store'}
QUESTION=re.compile(r'[?？]\s*$|^(how|what|why|which|when|where|can|does|is|are|do|should)\b|^(如何|怎么|怎样|为什么|什么|哪些|哪个|是否|能否|可以|多少)',re.I)
TRUST_WORDS=re.compile(r'认证|获奖|奖项|专利|检测报告|质检|用户评价|好评|certified|certification|award|patent|lab[- ]tested|reviews?\b|rated\b',re.I)
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def host(url):
 try:h=(urllib.parse.urlsplit(url).hostname or '').lower()
 except ValueError:return ''
 return h.removeprefix('www.')
def same_site(url,site):h=host(url);return bool(h) and (h==site or h.endswith('.'+site))
class Blocked(Exception):
 def __init__(self,code):self.code=code
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):return None

def fetch(url,limit=MAX_BYTES):
 """Pinned public fetch; never raises for HTTP or network failures."""
 out={'requested_url':url,'url':url,'status':None,'content_type':None,'headers':{},'body':'','bytes':0,'sha256':None,'truncated':False,'fetch_error':None,'fetched_at':stamp()}
 try:pinned_http.require_direct_policy()
 except ValueError:out['fetch_error']='proxy_unsupported';return out
 try:
  for _ in range(6):
   u=urllib.parse.urlsplit(url);port=u.port
   if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or port not in (None,80,443):raise Blocked('invalid_address')
   addresses=socket.getaddrinfo(u.hostname,port or (443 if u.scheme=='https' else 80),type=socket.SOCK_STREAM)
   if not addresses or any(not ipaddress.ip_address(a[4][0].split('%')[0]).is_global for a in addresses):raise Blocked('unsafe_address')
   req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml,application/xml,text/xml,text/plain;q=0.9','Accept-Encoding':'identity'})
   opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),pinned_http.PinnedHTTPHandler(addresses),pinned_http.PinnedHTTPSHandler(addresses),NoRedirect)
   try:
    with opener.open(req,timeout=20) as r:status=r.status;headers=r.headers;raw=r.read(limit+1)
   except urllib.error.HTTPError as e:
    try:
     status=e.code;headers=e.headers;raw=b''
     if status in (301,302,303,307,308) and headers and headers.get('Location'):
      url=website_inspection.normalize_url(urllib.parse.urljoin(url,headers['Location']));out['url']=url;continue
    finally:e.close()
   out.update(status=status,content_type=website_check.content_type(headers.get('Content-Type','')) if headers else None,
              headers={'x-robots-tag':headers.get('X-Robots-Tag','')} if headers else {},truncated=len(raw)>limit)
   raw=raw[:limit];out.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
   charset=(headers.get_content_charset() if headers else None) or 'utf-8'
   try:out['body']=raw.decode(charset,errors='replace')
   except LookupError:out['body']=raw.decode('utf-8',errors='replace')
   return out
  raise Blocked('redirect_limit')
 except Blocked as e:out['fetch_error']=e.code
 except ValueError:out['fetch_error']='invalid_address'
 except OSError as e:out['fetch_error']=website_check.classify(e)
 return out

class PageParser(HTMLParser):
 def __init__(self):
  super().__init__(convert_charrefs=True)
  self.lang='';self.meta={};self.canonical='';self.title=[];self.headings={'h1':[],'h2':[],'h3':[]};self.links=[];self.ld=[];self.times=[]
  self.text=[];self.lists=0;self.tables=0;self.skip=0;self.stack=[];self.link=None;self.script=None;self.list_stack=[];self.table_rows=[];self.li_link=None;self.script_parts=[]
 def handle_starttag(self,t,attrs):
  a={k:(v or '') for k,v in attrs}
  if t=='html' and not self.lang:self.lang=a.get('lang','').strip().lower()
  if t=='meta':
   key=(a.get('name') or a.get('property') or '').strip().lower()
   if key and a.get('content'):self.meta.setdefault(key,' '.join(a['content'].split())[:500])
  if t=='link' and 'canonical' in a.get('rel','').lower().split() and not self.canonical:self.canonical=a.get('href','').strip()
  if t=='a':self.link={'href':a.get('href','').strip(),'text':[]}
  if t=='time' and a.get('datetime'):self.times.append(a['datetime'][:40])
  if t=='script':self.script=a.get('type','').strip().lower();self.script_parts=[]
  if t in ('script','style','noscript','svg','template'):self.skip+=1
  if t in ('title','h1','h2','h3'):self.stack.append([t,[]])
  if t in ('ul','ol'):self.list_stack.append([0,0])
  if t=='li' and self.list_stack:self.list_stack[-1][0]+=1;self.li_link=False
  if t=='a' and self.list_stack and self.li_link is False:self.li_link=True;self.list_stack[-1][1]+=1
  if t=='table':self.table_rows.append(0)
  if t=='tr' and self.table_rows:self.table_rows[-1]+=1
 def handle_endtag(self,t):
  if t=='a' and self.link is not None:
   if len(self.links)<400:self.links.append({'href':self.link['href'],'text':' '.join(self.link['text'])[:200]})
   self.link=None
  if t=='script':
   if self.script=='application/ld+json':
    try:self.ld.append(json.loads(''.join(self.script_parts)))
    except (ValueError,RecursionError):pass
   self.script=None
  if t in ('script','style','noscript','svg','template') and self.skip:self.skip-=1
  if self.stack and self.stack[-1][0]==t:
   tag,parts=self.stack.pop();value=' '.join(parts).strip()[:300]
   (self.title if tag=='title' else self.headings[tag]).append(value)
  if t in ('ul','ol') and self.list_stack:
   items,linked=self.list_stack.pop()
   if items>=3 and linked*2<items:self.lists+=1
  if t=='table' and self.table_rows:
   if self.table_rows.pop()>=2:self.tables+=1
 def handle_data(self,s):
  if self.script=='application/ld+json':self.script_parts.append(s)
  if self.skip:return
  s=' '.join(s.split())
  if not s:return
  if self.link is not None:self.link['text'].append(s)
  for item in self.stack:item[1].append(s)
  if not self.stack or self.stack[0][0]!='title':self.text.append(s)

def walk_ld(objects):
 found=[]
 def visit(o,depth=0):
  if depth>12 or len(found)>200:return
  if isinstance(o,list):
   for v in o:visit(v,depth+1)
  elif isinstance(o,dict):
   types=o.get('@type',[]);types=[types] if isinstance(types,str) else [x for x in types if isinstance(x,str)] if isinstance(types,list) else []
   found.append((types,o))
   for v in o.values():
    if isinstance(v,(dict,list)):visit(v,depth+1)
 visit(objects);return found

def analyze_page(f,category):
 page={'url':f['url'],'requested_url':f['requested_url'],'category':category,'status':f['status'],'fetch_error':f['fetch_error'],'sha256':f['sha256'],'fetched_at':f['fetched_at'],'truncated':f['truncated'],
       'ok':f['status']==200 and f['content_type'] in ('text/html','application/xhtml+xml') and not f['fetch_error']}
 if not page['ok']:return page
 p=PageParser()
 try:p.feed(f['body']);p.close()
 except Exception:pass
 ld=walk_ld(p.ld);text='\n'.join(p.text)
 links=[];external=[]
 for l in p.links:
  href=l['href']
  if not href or href.startswith(('#','javascript:')):continue
  if href.startswith(('mailto:','tel:')):links.append({'url':href,'text':l['text']});continue
  try:absolute=website_inspection.normalize_url(urllib.parse.urljoin(f['url'],href))
  except ValueError:continue
  links.append({'url':absolute,'text':l['text']})
 dates=[x for types,o in ld for k in ('dateModified','datePublished') if isinstance(o.get(k),str) for x in [o[k][:40]]]
 dates+=[p.meta[k] for k in ('article:modified_time','article:published_time','og:updated_time') if k in p.meta]+p.times
 page.update(lang=p.lang,title=(p.title[0] if p.title else '')[:300],description=p.meta.get('description',''),meta_robots=(p.meta.get('robots','')+' '+f['headers'].get('x-robots-tag','')).lower(),
  canonical=urllib.parse.urljoin(f['url'],p.canonical) if p.canonical else '',h1=p.headings['h1'][:10],h2=len(p.headings['h2']),h3=len(p.headings['h3']),
  questions=sum(bool(QUESTION.search(h)) for h in p.headings['h2']+p.headings['h3']),lists=p.lists,tables=p.tables,readable=len(text),excerpt=text[:400],
  links=links,ld_types=sorted({t for types,_ in ld for t in types}),
  org_names=[o['name'].strip()[:200] for types,o in ld if ORG_TYPES&set(types) and isinstance(o.get('name'),str) and o['name'].strip()],
  site_names=[o['name'].strip()[:200] for types,o in ld if 'WebSite' in types and isinstance(o.get('name'),str) and o['name'].strip()]+([p.meta['og:site_name']] if p.meta.get('og:site_name') else []),
  same_as=[u for types,o in ld for u in ([o['sameAs']] if isinstance(o.get('sameAs'),str) else o.get('sameAs') if isinstance(o.get('sameAs'),list) else []) if isinstance(u,str)][:50],
  authors=bool(p.meta.get('author') or any(o.get('author') for types,o in ld if {'Article','NewsArticle','BlogPosting'}&set(types)) or re.search(r'(作者|文\s*/|By\s+[A-Z][a-z]+)',text[:3000])),
  postal=any('PostalAddress' in types or isinstance(o.get('address'),(dict,str)) and ORG_TYPES&set(types) for types,o in ld),
  icp=bool(re.search(r'ICP\s*备\s*\d+|ICP证',text)),trust_words=bool(TRUST_WORDS.search(text)),dates=dates[:50])
 return page

def sitemap_urls(body):
 locs=re.findall(r'<loc>\s*([^<\s]+)\s*</loc>',body,re.I)[:2000];lastmod=re.findall(r'<lastmod>\s*([^<\s]+)\s*</lastmod>',body,re.I)[:2000]
 return locs,lastmod,bool(re.search(r'<sitemapindex',body,re.I))

def discover(home,sitemap,site):
 """Pick one representative page per category: nav links first, then sitemap."""
 chosen={};candidates=[(l['url'],l['text']) for l in home.get('links',[]) if l['url'].startswith('http')]+[(u,'') for u in sitemap]
 for url,text in candidates:
  if not same_site(url,site) or url.rstrip('/')==home['url'].rstrip('/') or re.search(r'\.(pdf|jpe?g|png|gif|zip|mp4|xml)(\?|$)',url,re.I):continue
  path=urllib.parse.unquote(urllib.parse.urlsplit(url).path)
  for name,pattern in CATEGORIES:
   if name not in chosen and (re.search(pattern,path,re.I) or text and re.search(pattern,text,re.I)):chosen[name]=url;break
 extra=[u for u,_ in candidates if same_site(u,site) and u not in chosen.values() and u.rstrip('/')!=home['url'].rstrip('/') and not re.search(r'\.(pdf|jpe?g|png|gif|zip|mp4|xml)(\?|$)|login|cart|account|signin|register',u,re.I)]
 picked=list(chosen.items())
 for u in extra:
  if len(picked)>=MAX_PAGES-1:break
  if u not in [x for _,x in picked]:picked.append(('other',u))
 return picked[:MAX_PAGES-1]

def collect(website,fetcher=fetch):
 home_url=website_inspection.normalize_url(website)
 home=analyze_page(fetcher(home_url),'home');site=host(home['url'] if home['ok'] else home_url)
 root=urllib.parse.urlunsplit((urllib.parse.urlsplit(home['url']).scheme,urllib.parse.urlsplit(home['url']).netloc,'/','',''))
 robots=fetcher(urllib.parse.urljoin(root,'/robots.txt'),256*1024)
 declared=re.findall(r'^\s*sitemap:\s*(\S+)',robots['body'],re.I|re.M) if robots['status']==200 else []
 sitemap={'url':None,'status':None,'urls':[],'lastmod':[],'fetch':None}
 for url in (declared[:3] or [urllib.parse.urljoin(root,'/sitemap.xml')]):
  try:url=website_inspection.normalize_url(url)
  except ValueError:continue
  sm=fetcher(url);sitemap.update(url=url,status=sm['status'],fetch=sm)
  if sm['status']!=200:continue
  locs,lastmod,index=sitemap_urls(sm['body'])
  if index and locs:
   child=fetcher(locs[0]);sitemap['children']=[{'url':locs[0],'status':child['status']}]
   if child['status']==200:locs,more,_=sitemap_urls(child['body']);lastmod+=more
  sitemap.update(urls=locs,lastmod=lastmod)
  if locs:break
 pages=[home]
 if home['ok']:
  for category,url in discover(home,sitemap['urls'],site):pages.append(analyze_page(fetcher(url),category))
 return {'site':site,'home_url':home_url,'root':root,'pages':pages,'robots':robots,'sitemap':sitemap}

def rule_status(ratio,full=1,half=.5):return 'pass' if ratio>=full else 'partial' if ratio>=half else 'fail'

def evaluate(c,cfg,answers):
 """Return {rule_id: (status, reason, evidence_ids, target_page)}."""
 pages=c['pages'];home=pages[0];ok=[p for p in pages if p['ok']];market=cfg['market'];aliases=cfg['aliases'];site=c['site']
 ev=lambda p:p['evidence_id'];home_ev=[ev(home)];found=lambda cat:next((p for p in ok if p['category']==cat),None)
 named=lambda text:any(a.lower() in (text or '').lower() for a in aliases)
 out={};limit=READABLE[market];na={}
 if home['ok']:out['R-A1']=('pass' if home['url'].startswith('https://') else 'partial',f"首页最终地址 {home['url']} 返回 HTTP 200。",home_ev,home['url'])
 else:out['R-A1']=('fail',f"首页请求失败：{home['fetch_error'] or 'HTTP '+str(home['status'])}。",home_ev,home['url'])
 r=c['robots'];agents=CRAWLERS[market]
 if r['status']==200:
  parser=urllib.robotparser.RobotFileParser();parser.parse(r['body'].splitlines())
  blocked=[a for a in agents if not parser.can_fetch(a,home['url'])]
  out['R-A2']=('pass' if not blocked else 'fail' if len(blocked)==len(agents) else 'partial',('被屏蔽：'+'、'.join(blocked) if blocked else '已检查的爬虫均允许抓取首页')+f"（检查 {'、'.join(agents)}）。",['E-ROBOTS'],c['robots']['url'])
 elif r['status'] in (404,410):out['R-A2']=('pass',f"robots.txt 返回 HTTP {r['status']}，按标准视为允许全部抓取。",['E-ROBOTS'],r['url'])
 else:out['R-A2']=('unknown',f"robots.txt 读取失败（{r['fetch_error'] or 'HTTP '+str(r['status'])}），无法判断爬虫权限。",[],r['url'])
 s=c['sitemap']
 if s['urls']:out['R-A3']=('pass',f"站点地图 {s['url']} 含 {len(s['urls'])} 个 URL。",['E-SITEMAP'],s['url'])
 elif s['status'] in (404,410) or s['status']==200:out['R-A3']=('fail',f"站点地图 {s['url']} 返回 HTTP {s['status']}，未读取到 URL。",['E-SITEMAP'],s['url'] or c['root'])
 else:out['R-A3']=('unknown','站点地图请求异常，无法判断。',[],s['url'] or c['root'])
 if ok:
  enough=[p for p in ok if p['readable']>=limit]
  out['R-A4']=(rule_status(len(enough)/len(ok)),f"{len(enough)}/{len(ok)} 个页面无脚本可读正文达到 {limit} 字符；最少 {min(p['readable'] for p in ok)} 字符。",[ev(p) for p in ok],min(ok,key=lambda p:p['readable'])['url'])
  noindex=[p for p in ok if 'noindex' in p['meta_robots']]
  out['R-A5']=('fail' if home in noindex else 'partial' if noindex else 'pass',('noindex 页面：'+'、'.join(p['url'] for p in noindex) if noindex else f"{len(ok)} 个抽样页面均未发现 noindex。"),[ev(p) for p in (noindex or ok)],(noindex or ok)[0]['url'])
  orgs=[n for p in ok for n in p['org_names']];sites=[n for p in ok for n in p['site_names']]
  out['R-E1']=('pass',f"结构化数据组织名称：{orgs[0]}。",[ev(next(p for p in ok if p['org_names']))],home['url']) if orgs else ('partial',f"只有网站名称：{sites[0]}，缺少组织结构化数据。",[ev(next(p for p in ok if p['site_names']))],home['url']) if sites else ('fail','抽样页面未发现组织、品牌或网站名称结构化数据。',[ev(p) for p in ok],home['url'])
  profiles=sorted({host(u) for p in ok for u in p['same_as']+[l['url'] for l in p['links']] if any(host(u)==d or host(u).endswith('.'+d) for d in PROFILES)})
  out['R-E2']=('pass' if len(profiles)>=2 else 'partial' if profiles else 'fail',f"识别到 {len(profiles)} 个官方档案域名"+('：'+'、'.join(profiles[:8]) if profiles else '')+'。',[ev(p) for p in ok],home['url'])
  about=found('about')
  out['R-E3']=(('pass' if about['readable']>=2*limit else 'partial'),f"关于页 {about['url']} 可读正文 {about['readable']} 字符（阈值 {2*limit}）。",[ev(about)],about['url']) if about else ('fail','首页链接与站点地图中未找到关于页。',home_ev+(['E-SITEMAP'] if s['urls'] else []),home['url'])
  signals=[]
  if any(l['url'].startswith('tel:') for p in ok for l in p['links']):signals.append('电话')
  if any(l['url'].startswith('mailto:') for p in ok for l in p['links']):signals.append('邮箱')
  if any(p['postal'] for p in ok):signals.append('地址结构化数据')
  if found('contact'):signals.append('联系页')
  if any(p['icp'] for p in ok):signals.append('ICP 备案号')
  out['R-E4']=('pass' if len(signals)>=2 else 'partial' if signals else 'fail',('识别到：'+'、'.join(signals) if signals else '未识别到电话、邮箱、地址、联系页或备案信息')+'。',[ev(p) for p in ok],(found('contact') or home)['url'])
  if home['ok']:
   in_title=named(home['title']);in_other=any(named(h) for h in home['h1']) or any(named(n) for n in home['org_names'])
   out['R-E5']=('pass' if in_title and in_other else 'partial' if in_title or in_other else 'fail',f"首页 title「{home['title'][:80]}」{'含' if in_title else '不含'}品牌名；H1 或组织名称{'含' if in_other else '不含'}品牌名。",home_ev,home['url'])
  faq=found('faq');faq_schema=[p for p in ok if 'FAQPage' in p['ld_types']];q_pages=[p for p in ok if p['questions']>=3]
  if faq_schema or faq and faq['questions']>=3:target=(faq_schema or [faq])[0];out['R-Q1']=('pass',f"{target['url']} 含 FAQPage 结构化数据或 {target['questions']} 个问题式标题。",[ev(target)],target['url'])
  elif faq or q_pages:target=faq or q_pages[0];out['R-Q1']=('partial',f"{target['url']} 有问答内容，但问题式标题 {target['questions']} 个且无 FAQPage 结构化数据。",[ev(target)],target['url'])
  else:out['R-Q1']=('fail','抽样页面未发现 FAQ 页面、FAQPage 结构化数据或问题式标题。',[ev(p) for p in ok],home['url'])
  product=found('product') or next((p for p in ok if {'Product','Service','Offer'}&set(p['ld_types'])),None)
  if product:
   schema=bool({'Product','Service','Offer','ItemList'}&set(product['ld_types']));structured=product['lists']+product['tables']>0
   out['R-Q2']=('pass' if schema and structured else 'partial',f"产品/服务页 {product['url']}：结构化数据{'有' if schema else '无'}，列表或表格{'有' if structured else '无'}。",[ev(product)],product['url'])
  else:out['R-Q2']=('fail','首页链接与站点地图中未找到产品或服务页。',home_ev+(['E-SITEMAP'] if s['urls'] else []),home['url'])
  external=sorted({host(l['url']) for p in ok if p is not home for l in p['links'] if l['url'].startswith('http') and not same_site(l['url'],site) and not any(host(l['url'])==d or host(l['url']).endswith('.'+d) for d in PROFILES)})
  inner=[p for p in ok if p is not home]
  if inner:out['R-T1']=('pass' if len(external)>=3 else 'partial' if external else 'fail',f"非首页抽样页面链接到 {len(external)} 个外部站点"+('：'+'、'.join(external[:8]) if external else '')+'。',[ev(p) for p in inner],inner[0]['url'])
  else:out['R-T1']=('unknown','只抓取到首页，无法判断内容页引用。',[],home['url'])
  article=found('article')
  if article:out['R-T2']=('pass' if article['authors'] else 'partial' if article['dates'] else 'fail',f"文章页 {article['url']}：作者{'有' if article['authors'] else '无'}，日期{'有' if article['dates'] else '无'}。",[ev(article)],article['url'])
  else:na['R-T2']='抽样页面未发现文章或资讯页，本规则不适用；如有内容栏目请人工复核。'
  http_pages=[p for p in ok if not p['url'].startswith('https://')]
  out['R-T3']=('fail' if http_pages else 'pass',('HTTP 页面：'+'、'.join(p['url'] for p in http_pages[:5]) if http_pages else f"{len(ok)} 个页面均为 HTTPS")+'。',[ev(p) for p in (http_pages or ok)],(http_pages or ok)[0]['url'])
  policy=[k for k,pat in POLICY.items() if any(re.search(pat,l['text']+' '+urllib.parse.unquote(urllib.parse.urlsplit(l['url']).path),re.I) for l in home.get('links',[]))]
  out['R-T4']=('pass' if len(policy)==2 else 'partial' if policy else 'fail',{2:'首页链接含隐私政策与服务条款。',1:'首页只链接了'+('隐私政策' if policy==['privacy'] else '服务条款')+'。',0:'首页未发现隐私政策或服务条款链接。'}[len(policy)],home_ev,home['url'])
  rated=[p for p in ok if {'AggregateRating','Review'}&set(p['ld_types'])];worded=[p for p in ok if p['trust_words']]
  out['R-T5']=('pass','评价结构化数据：'+rated[0]['url']+'。',[ev(rated[0])],rated[0]['url']) if rated else ('partial','正文出现认证、奖项、检测或评价表述（未结构化）：'+worded[0]['url']+'。',[ev(worded[0])],worded[0]['url']) if worded else ('fail','抽样页面未发现评价结构化数据或认证、奖项类表述。',[ev(p) for p in ok],home['url'])
  single=[p for p in ok if len(p['h1'])==1]
  out['R-S1']=(rule_status(len(single)/len(ok)),f"{len(single)}/{len(ok)} 个页面恰好 1 个 H1。",[ev(p) for p in ok],next((p for p in ok if len(p['h1'])!=1),home)['url'])
  sectioned=[p for p in ok if p['h2']>=2]
  out['R-S2']=(rule_status(len(sectioned)/len(ok),.5,1e-9),f"{len(sectioned)}/{len(ok)} 个页面含至少 2 个 H2。",[ev(p) for p in ok],home['url'])
  complete=[p for p in ok if p['title'] and p['description']];titles=[p['title'] for p in ok if p['title']]
  unique=len(set(titles))==len(titles)
  out['R-S3']=('pass' if len(complete)==len(ok) and unique else rule_status(len(complete)/len(ok),2,.5),f"{len(complete)}/{len(ok)} 个页面 title 与 description 齐全；title {'互不重复' if unique else '存在重复'}。",[ev(p) for p in ok],next((p for p in ok if p not in complete),home)['url'])
  listed=[p for p in ok if p['lists']+p['tables']]
  out['R-S4']=(rule_status(len(listed)/len(ok),.5,1e-9),f"{len(listed)}/{len(ok)} 个页面含内容列表或表格。",[ev(p) for p in ok],home['url'])
  dates=[d for p in ok for d in p['dates']]+s['lastmod'];parsed=[]
  for d in dates:
   try:x=datetime.datetime.fromisoformat(d.strip().replace('Z','+00:00'));parsed.append(x if x.tzinfo else x.replace(tzinfo=datetime.timezone.utc))
   except ValueError:pass
  now=datetime.datetime.now(datetime.timezone.utc);recent=[d for d in parsed if (now-d).days<=365]
  out['R-M1']=('pass' if recent else 'partial' if parsed else 'fail',f"识别到 {len(parsed)} 个日期"+(f"，最近 {max(parsed).date().isoformat()}" if parsed else '')+'。',[ev(p) for p in ok]+(['E-SITEMAP'] if s['lastmod'] else []),home['url'])
  prefix='zh' if market=='CN' else 'en';matched=[p for p in ok if p['lang'].startswith(prefix)]
  out['R-M2']=(rule_status(len(matched)/len(ok),1,1e-9),f"{len(matched)}/{len(ok)} 个页面 lang 以 {prefix} 开头；首页 lang=\"{home['lang'] or '未设置'}\"。",[ev(p) for p in ok],next((p for p in ok if p not in matched),home)['url'])
  canon=[p for p in ok if p['canonical'] and same_site(p['canonical'],site)]
  out['R-M3']=(rule_status(len(canon)/len(ok),.8,1e-9),f"{len(canon)}/{len(ok)} 个页面设置了本站 canonical。",[ev(p) for p in ok],next((p for p in ok if p not in canon),home)['url'])
  branded=[p for p in ok if named(p['title'])]
  out['R-M4']=(rule_status(len(branded)/len(ok),.8,.5),f"{len(branded)}/{len(ok)} 个页面 title 含品牌名或别名。",[ev(p) for p in ok],next((p for p in ok if p not in branded),home)['url'])
 eligible=[a for a in answers if a['question_type']=='discovery' and a['status']=='success' and not a['truncated'] and isinstance(a['mention'],bool)]
 if eligible:
  hits=sum(a['mention'] for a in eligible);rate=hits/len(eligible)
  out['R-Q3']=('pass' if rate>=.5 else 'partial' if rate>=.2 else 'fail',f"发现类有效回答 {hits}/{len(eligible)} 次提及品牌（{rate:.0%}）。",[a['evidence_id'] for a in eligible],home['url'])
  cited=[a for a in eligible if a['citations']]
  if cited:
   own=[a for a in cited if any(same_site(x['url'],site) for x in a['citations'])];share=len(own)/len(cited)
   out['R-Q4']=('pass' if share>=.2 else 'partial' if own else 'fail',f"带引用的发现类回答 {len(own)}/{len(cited)} 引用了自有网站。",[a['evidence_id'] for a in cited],home['url'])
 else:out['R-Q3']=('unknown','未关联品牌分析任务，或任务中没有完整的发现类回答，无法判断 AI 提及。',[],home['url'])
 out.setdefault('R-Q4',('unknown','没有带平台引用的发现类回答（未开启联网检索的模型通常不返回引用），无法判断自有网站引用。',[],home['url']))
 return out,na

def answer_records(job,cfg,site):
 """Map a finished research run to v0.1 answer records."""
 import geo_analysis
 rows=(job.get('report') or {}).get('samples') or [{**s,'analysis':geo_analysis.sample_analysis(s,job['config'])} for s in job.get('samples',[])]
 records=[];lang='zh-CN' if cfg['market']=='CN' else 'en-US'
 for i,s in enumerate(rows):
  a=s.get('analysis',{});answer=(s.get('answer') or '').strip();status={'complete':'success','failed':'failed'}.get(s.get('status'),'unknown')
  if status=='unknown' and answer:status='success'
  if status=='success' and not answer:status='no_answer'
  own=(a.get('entities') or [{}])[0]
  cites=[{'url':x['url']} for x in a.get('citations',[]) if x.get('kind')=='citation' and str(x.get('url','')).startswith(('http://','https://'))]
  model=(job['config'].get('configuration',{}).get(s.get('provider'),{}) or {}).get('model') or s.get('model_requested') or s.get('provider') or 'unknown'
  records.append({'evidence_id':'A-'+str(i+1),'question_id':'Q-'+str(int(s.get('question_index',0))+1),'question':s.get('prompt') or '（未记录题目）','question_version':1,
   'question_type':a.get('family') if a.get('family') in ('discovery','brand','comparison') else 'discovery','platform':model,'entry':'API · '+(s.get('channel') or 'bai')+' · '+(s.get('protocol') or 'chat'),
   'market':cfg['market'],'language':lang,'status':status,'raw_answer':answer,'mention':(bool(own.get('alias')) if status=='success' else None),
   'recommendation':(True if own.get('rank') else None) if status=='success' else None,'citation_supported':bool(s.get('search_observed')),'citation_complete':False,
   'citation_type':'api_native','citations':cites,'truncated':s.get('status')=='incomplete','cached':False,'collected_at':s.get('captured_at') or job.get('created_at') or stamp(),
   'source_run':job['id'],'raw_sha256':s.get('raw_sha256','')})
 return records

def build_bundle(c,cfg,flow=None,run_id=None):
 run_id=run_id or str(uuid.uuid4());rules=CATALOG['rules'];evidence=[]
 for n,p in enumerate(c['pages']):
  p['evidence_id']='E-HOME' if n==0 else 'E-PAGE-'+str(n+1)
  log=p['fetch_error'] or ('HTTP '+str(p['status']) if not p['ok'] else '')
  evidence.append({'evidence_id':p['evidence_id'],'source_type':'page_snapshot' if p['ok'] else 'fetch_log','provided_at':p['fetched_at'],'url':p['url'],
   'hash':p['sha256'] or hashlib.sha256(('fetch-failure '+p['url']+' '+log).encode()).hexdigest(),'locator':'html (no JavaScript)' if p['ok'] else 'request log',
   'excerpt':((p.get('title') or '')+' · '+p.get('excerpt','')).strip(' ·')[:400] if p['ok'] else '请求失败：'+log,'integrity':'truncated' if p['truncated'] else 'complete' if p['ok'] else 'failed',
   'entry':'Signal GEO HTTP fetch · '+p['category']})
 r=c['robots'];evidence.append({'evidence_id':'E-ROBOTS','source_type':'robots_txt','provided_at':r['fetched_at'],'url':r['url'],'hash':r['sha256'] or hashlib.sha256(('robots '+str(r['fetch_error'])).encode()).hexdigest(),
  'locator':'robots.txt','excerpt':(r['body'][:400] if r['status']==200 else f"HTTP {r['status']} {r['fetch_error'] or ''}").strip() or '（空文件）','integrity':'complete' if r['status'] else 'failed','entry':'Signal GEO HTTP fetch'})
 s=c['sitemap'];sm=s['fetch']
 if sm:evidence.append({'evidence_id':'E-SITEMAP','source_type':'sitemap','provided_at':sm['fetched_at'],'url':sm['url'],'hash':sm['sha256'] or hashlib.sha256(('sitemap '+str(sm['fetch_error'])).encode()).hexdigest(),
  'locator':'sitemap <loc>/<lastmod>','excerpt':f"HTTP {s['status']} · {len(s['urls'])} 个 URL"+('：'+' '.join(s['urls'][:5]) if s['urls'] else ''),'integrity':'complete' if s['status']==200 else 'failed','entry':'Signal GEO HTTP fetch'})
 answers=answer_records(flow,cfg,c['site']) if flow else []
 results,na=evaluate(c,cfg,answers);known={e['evidence_id'] for e in evidence}|{a['evidence_id'] for a in answers}
 out_rules=[];findings=[]
 for rule in rules:
  rid=rule['rule_id']
  if rid in na:status,reason,ids,target='not_applicable',na[rid],[],c['pages'][0]['url']
  else:status,reason,ids,target=results.get(rid,('unknown','首页不可读取或缺少所需证据，无法判定；请补充证据后人工复核。',[],c['pages'][0]['url']))
  ids=[i for i in dict.fromkeys(ids) if i in known]
  if status in ('pass','partial','fail') and not ids:status='unknown'
  out_rules.append({'rule_id':rid,'title':rule['title'],'dimension':rule['dimension'],'weight':rule['weight'],'status':status,'partial_credit':CATALOG['partial_credit'],'reason':reason,
   'evidence_ids':ids,'target_page':target,'rubric':rule['rubric'],'verification':rule['verification'],'version':CATALOG['version'],'na_reason':na.get(rid,''),'method':JUDGE_VERSION})
  if status in ('fail','partial'):
   findings.append({'finding_id':'F-'+rid[2:],'scope':rule['title'],'status':status,'finding_type':'supported_gap','priority':'P1' if status=='fail' and rule['weight']>=5 else 'P2',
    'question_ids':[],'evidence_ids':ids,'rule_ids':[rid],'target_pages':[target],'observed_gap':reason,'alternative_explanations':rule['alternative'],'recommended_action':rule['action'],
    'owner':rule['owner'],'effort_band':rule['effort'],'verification':rule['verification'],'priority_reason':f"规则权重 {rule['weight']}，判定为{'未满足' if status=='fail' else '部分满足'}。",'candidate':'','publication_status':'unpublished'})
  elif status=='unknown':
   findings.append({'finding_id':'F-'+rid[2:],'scope':rule['title'],'status':'unknown','finding_type':'unknown','priority':'待验证','question_ids':[],'evidence_ids':[],'rule_ids':[rid],'target_pages':[target],
    'observed_gap':reason,'alternative_explanations':rule['alternative'],'recommended_action':'补充证据后人工判定：'+rule['verification'],'owner':rule['owner'],'effort_band':'小','verification':rule['verification'],
    'priority_reason':'证据不足，尚未计入得分。','candidate':'','publication_status':'unpublished'})
 pages_ok=[p for p in c['pages'] if p['ok']];urls=sorted(p['url'] for p in c['pages'])
 domains=sorted({c['site']}|{'www.'+c['site']} if c['site'] and not re.fullmatch(r'[\d.]+',c['site']) else set())
 manifest={'run_id':run_id,'brand':cfg['brand'],'domains':[d for d in domains if re.fullmatch(r'([a-z0-9-]+\.)+[a-z0-9-]+',d)] or ['unknown.invalid'],'market':cfg['market'],'language':'zh-CN' if cfg['market']=='CN' else 'en-US',
  'mode':'full' if flow else 'page','rule_version':CATALOG['version'],'parser_version':PARSER_VERSION,'judge_version':JUDGE_VERSION,
  'question_set_version':(flow.get('prompt_hash') or flow['id']) if flow else 'none','page_set_version':'pages-'+hashlib.sha256('\n'.join(urls).encode()).hexdigest()[:12],
  'configuration':f"signal-diagnose-v1; market={cfg['market']}; max_pages={MAX_PAGES}; readable_threshold={READABLE[cfg['market']]}",'sampled_at':c['pages'][0]['fetched_at'],
  'page_weighting':f"首页 + 按导航与站点地图选取的代表页，共抓取 {len(c['pages'])} 页（可读 {len(pages_ok)} 页），页面等权",'planned':len(c['pages']),'attempted':len(c['pages']),
  'source_flow':flow['id'] if flow else None}
 return {'schema_version':'v0.1','demo':False,'generator':{'name':'signal-geo-diagnose','version':'1','generated_at':stamp(),'aliases':cfg['aliases'],'website':cfg['website']},
         'run_manifest':manifest,'rules':out_rules,'evidence':evidence,'answers':answers,'findings':findings}

def validate(d):
 if not isinstance(d,dict) or set(d)-{'website','market','brand','aliases','flow_id'}:raise ValueError('诊断参数无效')
 if d.get('market') not in ('CN','US'):raise ValueError('请选择中国或美国市场')
 website=website_inspection.normalize_url(d.get('website'))
 brand=d.get('brand');aliases=d.get('aliases',[])
 if not isinstance(brand,str) or not brand.strip() or len(brand)>200:raise ValueError('请填写品牌名称')
 if not isinstance(aliases,list) or len(aliases)>10 or any(not isinstance(a,str) or len(a)>200 for a in aliases):raise ValueError('别名最多 10 个')
 flow=d.get('flow_id')
 if flow is not None and (not isinstance(flow,str) or not re.fullmatch(r'[a-f0-9-]{36}',flow)):raise ValueError('分析任务 ID 无效')
 names=list(dict.fromkeys(x.strip() for x in [brand,*aliases] if x.strip()))
 return {'website':website,'market':d['market'],'brand':brand.strip(),'aliases':names,'flow_id':flow}

class Store:
 """One diagnosis at a time; results persist under runtime/diagnostics/<id>/."""
 def __init__(self,path=DATA,fetcher=fetch,flows=None):
  self.path=pathlib.Path(path);self.fetcher=fetcher;self.flows=flows;self.lock=threading.Lock();self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=1);self.active=None
  self.path.mkdir(parents=True,exist_ok=True)
  for p in self.path.glob('*/job.json'):
   try:
    j=json.loads(p.read_text('utf-8'))
    if j['status'] in ('queued','running'):j.update(status='interrupted',failure='后台曾重启，诊断未完成；请重新开始。');self.save(j)
   except (ValueError,KeyError,OSError):pass
 def folder(self,jid):
  if not re.fullmatch(r'[a-f0-9-]{36}',jid or ''):raise ValueError('诊断 ID 无效')
  return self.path/jid
 def save(self,job):
  f=self.folder(job['id']);f.mkdir(parents=True,exist_ok=True);tmp=f/'job.tmp'
  tmp.write_text(json.dumps(job,ensure_ascii=False),'utf-8');tmp.replace(f/'job.json')
 def get(self,jid):return json.loads((self.folder(jid)/'job.json').read_text('utf-8'))
 def list(self):
  rows=[]
  for p in sorted(self.path.glob('*/job.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:50]:
   try:j=json.loads(p.read_text('utf-8'))
   except (ValueError,OSError):continue
   b=j.get('bundle') or {};rows.append({k:j.get(k) for k in ('id','created_at','finished_at','status','failure')}|{'brand':j['config']['brand'],'market':j['config']['market'],'website':j['config']['website'],
    'mode':'full' if j['config'].get('flow_id') else 'page','rules':len(b.get('rules',[])),'unknown':sum(r['status']=='unknown' for r in b.get('rules',[]))})
  return {'busy':self.active is not None,'diagnoses':rows}
 def start(self,d):
  cfg=validate(d);flow=None
  if cfg['flow_id']:
   if self.flows is None:raise ValueError('当前服务无法读取分析任务')
   try:flow=self.flows(cfg['flow_id'])
   except (OSError,ValueError):raise ValueError('找不到所选分析任务') from None
   if flow.get('status') not in ('finished','partial') or not flow.get('samples'):raise ValueError('所选分析任务尚未完成或没有回答')
   if flow['config'].get('market')!=cfg['market']:raise ValueError('所选分析任务的市场与诊断市场不一致')
  with self.lock:
   if self.active:raise ValueError('已有诊断正在运行，请稍后')
   job={'id':str(uuid.uuid4()),'created_at':stamp(),'status':'queued','config':cfg};self.active=job['id'];self.save(job)
  self.pool.submit(self.run,job,flow);return job
 def run(self,job,flow):
  try:
   job['status']='running';self.save(job)
   c=collect(job['config']['website'],self.fetcher)
   job['bundle']=build_bundle(c,job['config'],flow,job['id']);job['status']='finished'
   job['pages']=[{k:p.get(k) for k in ('url','category','status','fetch_error','readable','sha256')} for p in c['pages']]
  except Exception as e:job['status']='failed';job['failure']=str(e) if isinstance(e,ValueError) else '诊断处理失败；未生成分数。'
  finally:
   job['finished_at']=stamp();self.save(job)
   with self.lock:self.active=None
