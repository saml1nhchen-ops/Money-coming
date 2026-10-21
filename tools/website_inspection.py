"""Finite checks on fetched page evidence, without model calls or visibility claims."""
import json
import re
import urllib.parse
from html.parser import HTMLParser


def normalize_url(value):
 if not isinstance(value,str) or not value.strip() or len(value)>4096:
  raise ValueError('请输入有效的官网地址')
 value=value.strip()
 if any(ord(c)<32 for c in value) or '\\' in value:
  raise ValueError('官网地址无效')
 if '://' not in value:value='https://'+value
 try:
  u=urllib.parse.urlsplit(value);port=u.port
  if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or port not in (None,80,443):
   raise ValueError()
  host=u.hostname.encode('idna').decode('ascii').lower()
  if ':' in host:host='['+host+']'
  path=urllib.parse.quote(u.path or '/',safe="/%:@!$&'()*+,;=-._~")
  query=urllib.parse.quote(u.query,safe="%:@!$&'()*+,;=/?-._~")
  return urllib.parse.urlunsplit((u.scheme,host+(':'+str(port) if port else ''),path,query,''))
 except (ValueError,UnicodeError):raise ValueError('请输入公开官网的 HTTP(S) 地址') from None


class WebsiteExtractor(HTMLParser):
 def __init__(self):
  super().__init__(convert_charrefs=True)
  self.skip=0;self.parts=[];self.body_parts=[];self.title_parts=[];self.h1_parts=[]
  self.title_depth=0;self.h1_depth=0;self.head_depth=0;self.meta={};self.ld=[];self.script_type=None;self.script_parts=[]
 def handle_starttag(self,t,attrs):
  a=dict(attrs)
  if t=='head':self.head_depth+=1
  if t=='title':self.title_depth+=1
  if t=='h1':self.h1_depth+=1
  if t=='meta':
   key=(a.get('property') or a.get('name') or '').lower()
   content=' '.join((a.get('content') or '').split())[:500]
   if key and content:self.meta.setdefault(key,content)
  if t=='script':self.script_type=(a.get('type') or '').lower();self.script_parts=[]
  if t in ('script','style','noscript','svg'):self.skip+=1
 def handle_endtag(self,t):
  if t=='script':
   if self.script_type=='application/ld+json':
    try:self.ld.append(json.loads(''.join(self.script_parts)))
    except (ValueError,RecursionError):pass
   self.script_type=None;self.script_parts=[]
  if t in ('script','style','noscript','svg') and self.skip:self.skip-=1
  if t=='title' and self.title_depth:self.title_depth-=1
  if t=='h1' and self.h1_depth:self.h1_depth-=1
  if t=='head' and self.head_depth:self.head_depth-=1
 def handle_data(self,s):
  if self.script_type=='application/ld+json':self.script_parts.append(s)
  if self.skip:return
  s=' '.join(s.split())
  if not s:return
  self.parts.append(s)
  if self.title_depth:self.title_parts.append(s)
  if self.h1_depth:self.h1_parts.append(s)
  if not self.head_depth and not self.title_depth:self.body_parts.append(s)
 def metadata(self):
  return {'title':' '.join(self.title_parts)[:500],'description':self.meta.get('description',''),
          'h1':' '.join(self.h1_parts)[:500],'site_name':self.meta.get('og:site_name',''),
          'structured_names':structured_names(self.ld),'readable_characters':len('\n'.join(self.body_parts))}


def structured_names(objects):
 result=[]
 def visit(obj,depth=0):
  if depth>12 or len(result)>=20:return
  if isinstance(obj,list):
   for v in obj:visit(v,depth+1)
  elif isinstance(obj,dict):
   types=obj.get('@type',[]);types=[types] if isinstance(types,str) else types
   if isinstance(types,list) and any(t in ('Organization','Corporation','LocalBusiness','Brand','WebSite') for t in types):
    name=obj.get('name')
    if isinstance(name,str) and name.strip():result.append({'name':' '.join(name.split())[:200],'source':'JSON-LD '+str(next(t for t in types if t in ('Organization','Corporation','LocalBusiness','Brand','WebSite'))) + '.name'})
   for k,v in obj.items():
    if isinstance(v,(dict,list)):visit(v,depth+1)
 for obj in objects:visit(obj)
 return result


def inspect_snapshot(snapshot,market):
 if market not in ('CN','US'):raise ValueError('请选择中国或美国市场')
 meta=snapshot.get('metadata',{});is_html=snapshot.get('is_html',False)
 warnings=[]
 if meta.get('site_name'):name=meta['site_name'][:200];source='meta[property="og:site_name"]';confirmation=False
 elif meta.get('structured_names'):
  item=meta['structured_names'][0];name=item['name'];source=item['source'];confirmation=True
 elif meta.get('title'):
  name=re.split(r'\s+[|–—-]\s+|[|｜]',meta['title'],maxsplit=1)[0].strip()[:200]
  source='title';confirmation=True
 else:name=urllib.parse.urlsplit(snapshot['url']).hostname or '';source='domain_fallback';confirmation=True
 if not name:name=urllib.parse.urlsplit(snapshot['url']).hostname or '';source='domain_fallback';confirmation=True
 if confirmation:warnings.append('品牌为页面元信息候选或域名回退，请确认名称与别名后再采样。')
 chars=meta.get('readable_characters',len(snapshot.get('text','')))
 checks=[]
 for key,label,value,action in [
  ('title','页面标题',meta.get('title'),'为此页面提供描述业务主题的 title。'),
  ('meta_description','页面描述',meta.get('description'),'为此页面补充准确的 meta description。'),
  ('h1','主标题',meta.get('h1'),'为此页面设置清晰的 H1 主标题。')]:
  status=('pass' if value else 'fail') if is_html else 'unknown'
  checks.append({'id':key,'label':label,'status':status,'evidence':value or ('已读取 HTML，未观察到此字段。' if is_html else '当前响应不是 HTML，无法判断此结构。'),'action':('保留并核对页面内容是否准确。' if status=='pass' else action if status=='fail' else '使用可读取的 HTML 页面复查。')})
 checks.append({'id':'readable_text','label':'可读正文','status':'pass' if chars>=100 else 'fail','evidence':f'响应中可读正文 {chars} 字符；阈值为 100 字符。','action':'人工复核正文的准确性与适用市场。' if chars>=100 else '补充可读取正文；若页面依赖 JavaScript，请提供服务端可读页面。'})
 enough=chars>=100 and all(c['status']!='unknown' for c in checks)
 score=25*sum(c['status']=='pass' for c in checks) if enough else None
 if chars<100:warnings.append('可读正文不足 100 字符，证据不足以给出总分；未执行 JavaScript。')
 if not is_html:warnings.append('响应为纯文本，HTML 结构检查保留 unknown，总分不可用。')
 methodology=('website-readiness-v1；市场 '+market+'。title、meta_description、h1、readable_text 各占 25 分；前三项检查非空，正文检查至少 100 字符。仅全部结构可观察且正文达到阈值时计算通过项之和，否则 score=null；unknown 不计作零分。'
              '单次抓取页面的有限基础准备度，不是完整六维 GEO 评分、AI 可见度、推荐率或外部模型实测。未核验语义正确性、其他页面或 JavaScript 渲染结果。')
 return {'website':{k:snapshot[k] for k in ('url','captured_at','content_sha256','bytes')},
         'brand':{'name':name,'aliases':[name] if name else [],'source':source,'needs_confirmation':confirmation},
         'diagnosis':{'scope':'website_readiness','score':score,'checks':checks,'methodology':methodology},
         'context':snapshot.get('text','')[:18000],'warnings':warnings}
