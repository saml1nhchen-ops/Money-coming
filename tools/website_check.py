"""Safe, finite diagnostics for the existing pinned website fetch only."""
import copy,datetime,email.utils,re,socket,ssl,time,urllib.error
MESSAGES={
 'address_ok':'官网地址格式已校验。','invalid_address':'请输入公开官网的 HTTP(S) 地址。','dns_ok':'域名已解析并检查返回地址。','dns_failed':'官网域名解析失败，请核对网址。',
 'unsafe_address':'官网必须解析为公开网络地址；已拒绝私网或本机目标。','proxy_unsupported':'当前后台暂时无法安全读取该官网，请手动填写背景或使用产品页。',
 'tls_ok':'已按官网域名完成证书验证。','tls_skipped':'HTTP 页面未使用 TLS。','tls_certificate_failed':'官网证书或域名验证失败，未忽略证书错误。','tls_failed':'官网 TLS 连接未能完成。',
 'http_ok':'已收到官网 HTTP 响应。','http_limited':'官网返回 HTTP 429，可能是限流或自动访问限制，不能据此确定反爬；请稍后手动重试或改用产品页。',
 'http_blocked':'官网返回 HTTP 403，访问被拒绝，不能据此确定反爬；可改用产品页或手动填写。','http_error':'官网返回非成功 HTTP 状态；未自动重试。',
 'connection_timeout':'官网连接或读取超时，未自动重试。','connection_failed':'官网连接失败，请核对网址或稍后手动重试。','redirect_limit':'官网重定向次数过多；已停止读取。',
 'unsupported_content':'官网返回的不是网页文本。','content_too_large':'网页超过 2 MB，请使用具体产品页。','content_too_short':'网页可读内容过少；可能需要 JavaScript，未执行页面脚本。',
 'content_ok':'已读取网页文本；仅检查本次返回内容。','website_challenge':'HTTP 返回内容疑似访问验证或挑战页，未将其识别为正常品牌或产品；未尝试绕过。',
 'products_absent':'本次页面未提取到产品证据，不代表该品牌没有产品。'}
class WebsiteCheckError(ValueError):
 def __init__(self,code,diagnostics):self.code=code;self.diagnostics=copy.deepcopy(diagnostics);super().__init__(MESSAGES.get(code,MESSAGES['connection_failed']))
def safe_retry_after(value):
 if not isinstance(value,str) or not 0<len(value)<=100 or any(ord(c)<32 or ord(c)>126 for c in value):return None
 if re.fullmatch(r'[0-9]{1,10}',value):return value
 try:
  date=email.utils.parsedate_to_datetime(value)
  if date is not None and date.tzinfo is not None and re.fullmatch(r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), [0-9]{2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [0-9]{4} [0-9]{2}:[0-9]{2}:[0-9]{2} GMT',value):return value
 except (ValueError,TypeError,OverflowError):pass
 return None
def content_type(value):
 if not isinstance(value,str):return None
 match=re.match(r'^\s*([A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+)(?:\s*;|\s*$)',value)
 return match[1].lower() if match else None
def challenge(html,metadata):
 title=metadata.get('title','');chars=metadata.get('readable_characters',0)
 if not isinstance(chars,int) or chars>3000:return False
 title_signal=bool(re.search(r'just a moment|attention required|checking your browser|verify (?:that )?you are human|security (?:check|verification)|安全验证|人机验证|访问验证',title,re.I))
 platform=bool(re.search(r'cf-chl-|/cdn-cgi/challenge-platform|challenge-platform',html,re.I))
 captcha=bool(re.search(r'g-recaptcha|h-captcha|cf-turnstile|captcha[-_]?(?:form|container)',html,re.I))
 visible=' '.join((metadata.get('title',''),metadata.get('h1','')))
 return title_signal and (platform or captcha) or chars<1500 and captcha and bool(re.search(r'verify (?:that )?you are human|complete (?:the )?(?:captcha|security check)|人机验证|请完成验证',visible,re.I))
def classify(error):
 if isinstance(error,urllib.error.URLError):return classify(error.reason) if isinstance(error.reason,BaseException) else 'connection_failed'
 if isinstance(error,ssl.SSLCertVerificationError):return 'tls_certificate_failed'
 if isinstance(error,ssl.SSLError):return 'tls_failed'
 if isinstance(error,socket.gaierror):return 'dns_failed'
 if isinstance(error,(TimeoutError,socket.timeout)):return 'connection_timeout'
 return 'connection_failed'
class Check:
 def __init__(self):
  self.started=time.monotonic();self.value={'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'duration_ms':0,'outcome':'unreachable','http_status':None,'final_url':'','redirects':[],'content_type':None,'bytes':None,'readable_characters':None,'checks':[{'id':key,'status':'unknown','message':'尚无足够证据判断。'} for key in ('address','dns','tls','http','content')],'findings':[],'retry_after':None,'possible_access_restriction':False}
 def check(self,key,status,code):
  row=next(r for r in self.value['checks'] if r['id']==key);row.update(status=status,message=MESSAGES[code])
 def finding(self,code):
  if not any(f['code']==code for f in self.value['findings']):self.value['findings'].append({'code':code,'message':MESSAGES[code]})
 def finish(self,outcome):self.value['outcome']=outcome;self.value['duration_ms']=max(0,int((time.monotonic()-self.started)*1000));return copy.deepcopy(self.value)
 def fail(self,code,outcome='unreachable',check=None):
  if check:self.check(check,'failed',code)
  if code in ('http_limited','http_blocked','website_challenge'):self.value['possible_access_restriction']=True
  self.finding(code);raise WebsiteCheckError(code,self.finish(outcome))
