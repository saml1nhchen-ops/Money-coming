"""Public, read-only connection probes. No login, credentials or model calls."""
import base64,datetime,http.client,json,os,pathlib,re,socket,ssl,sys,urllib.error,urllib.request,subprocess
HOST='43.154.242.184.sslip.io';BASE='https://'+HOST;ORIGIN='https://saml1nhchen-ops.github.io'
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):return None
SAFE_CODES={'unauthorized','origin_forbidden','host_forbidden','not_found','backend_unavailable','session_store_unavailable','rate_limited','invalid_request','upstream_failed','maintenance'}
CORS=('Access-Control-Allow-Origin','Access-Control-Allow-Methods','Access-Control-Allow-Headers','Access-Control-Allow-Credentials','Vary')
def safe_body(body,health=False):
 try:d=json.loads(body)
 except (ValueError,TypeError):return {'json':False}
 if not isinstance(d,dict):return {'json':False}
 if not health:return {'code':d.get('code') if d.get('code') in SAFE_CODES else 'unavailable'}
 result={}
 if type(d.get('ok'))==bool:result['ok']=d['ok']
 for key,pattern in [('revision',r'[a-f0-9]{40}|unknown'),('version',r'[A-Za-z0-9._+-]{1,128}')]:
  if isinstance(d.get(key),str) and re.fullmatch(pattern,d[key]):result[key]=d[key]
 cap=d.get('capabilities')
 if isinstance(cap,dict):
  result['capabilities']={}
  if type(cap.get('remember_login'))==bool:result['capabilities']['remember_login']=cap['remember_login']
  age=cap.get('remember_login_max_age_seconds')
  if type(age)==int and 0<=age<=31536000:result['capabilities']['remember_login_max_age_seconds']=age
 return result
def cors_headers(headers):
 result={}
 for name in CORS:
  value=headers.get(name)
  if not isinstance(value,str):continue
  # Do not export arbitrary server header values: only known CORS tokens.
  if name=='Access-Control-Allow-Origin':result[name]=value if value in (ORIGIN,'*','null') else 'other'
  elif name=='Access-Control-Allow-Credentials':result[name]=value if value in ('true','false') else 'other'
  else:
   allowed={'get','post','options','head','content-type','authorization','origin','accept','*'}
   result[name]=[v.strip().lower() if v.strip().lower() in allowed else 'other' for v in value.split(',')][:16]
 return result
def error_kind(error):
 if isinstance(error,ssl.SSLCertVerificationError):return 'tls_verification_failed'
 if isinstance(error,socket.gaierror):return 'dns_failed'
 if isinstance(error,(TimeoutError,socket.timeout)):return 'timeout'
 if isinstance(error,urllib.error.URLError):return error_kind(error.reason)
 return 'connection_failed'
def probe(opener,method,path,origin=False,preflight=None):
 headers={}
 if origin:headers['Origin']=ORIGIN
 if preflight:
  headers['Access-Control-Request-Method']=preflight;headers['Access-Control-Request-Headers']='Content-Type, Authorization'
 req=urllib.request.Request(BASE+path,headers=headers,method=method)
 try:
  try:response=opener.open(req,timeout=20)
  except urllib.error.HTTPError as error:response=error
  with response:
   body=response.read(65537);result={'method':method,'path':path,'origin':origin,'status':response.status,'cors':cors_headers(response.headers)}
   if len(body)<=65536 and method!='OPTIONS':result['body']=safe_body(body,path=='/healthz')
   result['expected_status']=response.status==(204 if method=='OPTIONS' else 200 if path=='/healthz' else 401)
   if origin:result['cors_origin_matches']=response.headers.get('Access-Control-Allow-Origin')==ORIGIN
   if preflight:
    result['preflight_method_allowed']=preflight.lower() in result['cors'].get('Access-Control-Allow-Methods',[])
    result['preflight_headers_allowed']=all(v in result['cors'].get('Access-Control-Allow-Headers',[]) for v in ('content-type','authorization'))
   return result
 except Exception as error:return {'method':method,'path':path,'origin':origin,'error':error_kind(error)}
def collect():
 report={'schema':1,'target':BASE,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'read_only':True}
 try:report['dns']={'addresses':sorted({a[4][0] for a in socket.getaddrinfo(HOST,443,type=socket.SOCK_STREAM)})}
 except OSError as error:report['dns']={'error':error_kind(error)}
 context=ssl.create_default_context()
 try:
  if any(urllib.request.getproxies().get(k) for k in ('http','https','all')):
   report['tls']={'verified':False,'error':'proxy_configured_direct_tls_probe_skipped'}
  else:
   with socket.create_connection((HOST,443),timeout=20) as raw:
    with context.wrap_socket(raw,server_hostname=HOST) as tls:
     cert=tls.getpeercert();report['tls']={'verified':True,'protocol':tls.version(),'not_before':cert.get('notBefore'),'not_after':cert.get('notAfter')}
 except Exception as error:report['tls']={'verified':False,'error':error_kind(error)}
 opener=urllib.request.build_opener(NoRedirect,urllib.request.HTTPSHandler(context=context))
 report['http']=[probe(opener,'GET','/healthz'),probe(opener,'GET','/healthz',True),probe(opener,'OPTIONS','/api/workspace/login',True,'POST'),probe(opener,'OPTIONS','/api/geo/state',True,'GET'),probe(opener,'GET','/api/geo/state',True)]
 return report
def browser_probe():
 # Do not pass the reporting token (or other runner credentials) into Node/Chrome.
 env={k:v for k,v in os.environ.items() if not re.search(r'TOKEN|SECRET|PASSWORD|CREDENTIAL|API_KEY|PRIVATE_KEY',k,re.I)}
 try:
  result=subprocess.run(['node',str(pathlib.Path(__file__).with_name('browser_connection_diagnostics.mjs'))],env=env,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=48)
  if len(result.stdout)>32768:return {'error':'browser_report_too_large'}
  report=json.loads(result.stdout)
  if not isinstance(report,dict):return {'error':'browser_invalid_report'}
  return report
 except subprocess.TimeoutExpired:return {'error':'browser_probe_timeout'}
 except (OSError,ValueError):return {'error':'browser_unavailable'}
def api(opener,repository,token,method,path,body):
 req=urllib.request.Request('https://api.github.com/repos/'+repository+path,json.dumps(body).encode(),{'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json'},method=method)
 try:
  with opener.open(req,timeout=30) as response:response.read(65536)
 except Exception:raise RuntimeError('Diagnostic report publication failed; production was not changed') from None
def publish(report,environ=os.environ):
 repository=environ.get('GITHUB_REPOSITORY','');run=environ.get('GITHUB_RUN_ID','');sha=environ.get('GITHUB_SHA','');token=environ.get('GH_TOKEN','')
 if repository.lower()!='saml1nhchen-ops/money-coming' or not re.fullmatch(r'[0-9]+',run) or not re.fullmatch(r'[a-f0-9]{40}',sha) or not token:raise RuntimeError('Invalid diagnostic publication configuration')
 branch='diagnostic-results/'+run;opener=urllib.request.build_opener(NoRedirect)
 api(opener,repository,token,'POST','/git/refs',{'ref':'refs/heads/'+branch,'sha':sha})
 content=base64.b64encode(json.dumps(report,indent=2,sort_keys=True).encode()).decode()
 api(opener,repository,token,'PUT','/contents/connection-report.json',{'message':'Read-only connection diagnostics '+run,'branch':branch,'content':content})
 return branch
def main():
 report=collect();report['browser']=browser_probe();pathlib.Path('connection-report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
 summary=os.environ.get('GITHUB_STEP_SUMMARY')
 if summary:
  with pathlib.Path(summary).open('a') as out:out.write('Read-only connection diagnostics\n\n```json\n'+json.dumps(report,indent=2,sort_keys=True)+'\n```\n')
 try:
  branch=publish(report);print('Read-only report saved to '+branch+'/connection-report.json');return 0
 except RuntimeError:print('Diagnostic report publication failed; production was not changed.',file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
