"""Validate formal releases and idempotently create requested releases.

All API paths are fixed to this repository. Never moves refs or edits/deletes an
existing release. Release target_commitish is intentionally never trusted.
"""
import argparse,datetime,json,os,pathlib,re,subprocess,sys,urllib.error,urllib.request
REPOSITORY='saml1nhchen-ops/money-coming'
FORMAL_TAG=re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z')
TAG=re.compile(r'v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z')
SHA=re.compile(r'[a-f0-9]{40}\Z')
class Rejected(Exception):pass
class APIError(Rejected):
 def __init__(self,status):self.status=status;super().__init__('GitHub API request failed (HTTP '+str(status)+')')
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
class API:
 def __init__(self,repository,token):
  if repository.lower()!=REPOSITORY or not token:raise Rejected('Repository or token configuration is invalid')
  self.base='https://api.github.com/repos/'+repository;self.token=token;self.opener=urllib.request.build_opener(NoRedirect)
 def request(self,method,path,body=None):
  req=urllib.request.Request(self.base+path,None if body is None else json.dumps(body).encode(),{'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json'},method=method)
  try:
   with self.opener.open(req,timeout=30) as response:
    raw=response.read(2*1024*1024+1)
    if len(raw)>2*1024*1024:raise Rejected('GitHub response exceeds limit')
    return json.loads(raw)
  except urllib.error.HTTPError as error:
   if error.code==404 and method=='GET':return None
   raise APIError(error.code) from None
  except (OSError,ValueError):raise Rejected('GitHub API unavailable or invalid response') from None

def git_revision(tag,cwd=None):
 if not FORMAL_TAG.fullmatch(tag):raise Rejected('Invalid formal release tag')
 try:
  p=subprocess.run(['git','rev-parse','--verify','refs/tags/'+tag+'^{commit}'],cwd=cwd,text=True,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,check=True)
 except (OSError,subprocess.CalledProcessError):raise Rejected('Formal git tag is missing or not a commit') from None
 revision=p.stdout.strip()
 if not SHA.fullmatch(revision):raise Rejected('Invalid tag commit')
 return revision

def request_revision(ref,cwd=None):
 match=re.fullmatch(r'refs/tags/release-request/(v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))',ref)
 if not match:raise Rejected('Invalid release request ref')
 try:
  revision=subprocess.check_output(['git','rev-parse','--verify',ref+'^{commit}'],cwd=cwd,text=True,stderr=subprocess.DEVNULL).strip()
  head=subprocess.check_output(['git','rev-parse','--verify','HEAD^{commit}'],cwd=cwd,text=True,stderr=subprocess.DEVNULL).strip()
  if not SHA.fullmatch(revision) or head!=revision:raise Rejected('Request checkout does not match request tag')
  subprocess.run(['git','merge-base','--is-ancestor',revision,'refs/remotes/origin/main'],cwd=cwd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  for path in ('.github/workflows/request-release.yml','.github/workflows/release-backend.yml','deploy/release_request.py'):
   subprocess.run(['git','cat-file','-e',revision+':'+path],cwd=cwd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 except (OSError,subprocess.CalledProcessError):raise Rejected('Request commit is not trusted main history with automation') from None
 return revision

def gate(event_name,ref,event,tag,expected,called=False):
 if not isinstance(event,dict):raise Rejected('Invalid workflow event')
 if not (TAG if called else FORMAL_TAG).fullmatch(tag):raise Rejected('Invalid formal release tag')
 if expected and not SHA.fullmatch(expected):raise Rejected('Invalid expected revision')
 if called:
  if event_name!='push' or not expected or ref!='refs/tags/release-request/'+tag or event.get('deleted') is not False or event.get('forced') is not False:raise Rejected('Only a non-forced request-tag creation may invoke deployment')
 else:
  release=event.get('release',{})
  if not isinstance(release,dict):raise Rejected('Invalid release event')
  if event_name!='release' or event.get('action')!='published' or release.get('tag_name')!=tag or release.get('draft') is not False or release.get('prerelease') is not False:raise Rejected('Only published formal releases may deploy')

def remote_revision(api,tag):
 obj=api.request('GET','/git/ref/tags/'+tag)
 if obj is None:return None
 obj=obj.get('object') if isinstance(obj,dict) else None;seen=set()
 for _ in range(8):
  if not isinstance(obj,dict) or not SHA.fullmatch(str(obj.get('sha',''))):raise Rejected('Invalid remote tag object')
  kind,sha=obj.get('type'),obj['sha']
  if kind=='commit':return sha
  if kind!='tag' or sha in seen:raise Rejected('Remote tag does not resolve to a commit')
  seen.add(sha);annotation=api.request('GET','/git/tags/'+sha);obj=annotation.get('object') if isinstance(annotation,dict) else None
 raise Rejected('Remote tag nesting exceeds limit')

def release_metadata(release,tag,revision):
 if not isinstance(release,dict) or release.get('tag_name')!=tag or type(release.get('id'))!=int or release['id']<1 or release.get('draft') is not False or release.get('prerelease') is not False:raise Rejected('Existing release is not the requested published formal release')
 published=release.get('published_at')
 if not isinstance(published,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z',published):raise Rejected('Release is not published')
 try:datetime.datetime.strptime(published,'%Y-%m-%dT%H:%M:%SZ')
 except ValueError:raise Rejected('Invalid release publication date') from None
 return {'tag':tag,'revision':revision,'release_id':str(release['id']),'published_at':published}

def request_release(api,tag,expected,cwd=None):
 if not TAG.fullmatch(tag) or not SHA.fullmatch(expected):raise Rejected('Invalid release request')
 try:
  actual=subprocess.check_output(['git','rev-parse','--verify','HEAD^{commit}'],cwd=cwd,text=True,stderr=subprocess.DEVNULL).strip()
 except (OSError,subprocess.CalledProcessError):raise Rejected('Request checkout unavailable') from None
 if actual!=expected:raise Rejected('Request checkout differs from expected revision')
 revision=remote_revision(api,tag)
 if revision is None:
  try:api.request('POST','/git/refs',{'ref':'refs/tags/'+tag,'sha':expected})
  except APIError as error:
   if error.status not in (409,422):raise
  revision=remote_revision(api,tag)
 if revision!=expected:raise Rejected('Existing formal tag conflicts with requested commit')
 release=api.request('GET','/releases/tags/'+tag)
 if release is None:
  try:api.request('POST','/releases',{'tag_name':tag,'target_commitish':expected,'name':tag,'body':'Formal release requested by the validated request-tag workflow. Deployment is explicitly invoked by the same workflow.','draft':False,'prerelease':False})
  except APIError as error:
   if error.status not in (409,422):raise
  release=api.request('GET','/releases/tags/'+tag)
 if remote_revision(api,tag)!=expected:raise Rejected('Formal tag changed during release creation')
 return release_metadata(release,tag,expected)

def resolve_release(api,tag,expected='',cwd=None,event=None):
 revision=git_revision(tag,cwd)
 if expected and revision!=expected:raise Rejected('Local formal tag differs from expected revision')
 if remote_revision(api,tag)!=revision:raise Rejected('Remote and checked out formal tags disagree')
 release=api.request('GET','/releases/tags/'+tag);result=release_metadata(release,tag,revision)
 if event is not None and event.get('release',{}).get('id')!=int(result['release_id']):raise Rejected('Release event identity differs from API')
 return result

def main(argv=None):
 parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['request','resolve']);args=parser.parse_args(argv)
 try:
  event=json.loads(pathlib.Path(os.environ['GITHUB_EVENT_PATH']).read_text())
  if not isinstance(event,dict):raise Rejected('Invalid workflow event')
  name=os.environ.get('GITHUB_EVENT_NAME','');ref=os.environ.get('GITHUB_REF','');called=bool(os.environ.get('INPUT_RELEASE_TAG'))
  tag=os.environ.get('INPUT_RELEASE_TAG') or (ref.removeprefix('refs/tags/release-request/') if name=='push' else event.get('release',{}).get('tag_name',''))
  expected=os.environ.get('EXPECTED_REVISION','')
  if name=='push':
   request_commit=request_revision(ref)
   if expected and expected!=request_commit:raise Rejected('Request tag differs from expected revision')
   expected=request_commit
  gate(name,ref,event,tag,expected,called or args.mode=='request')
  api=API(os.environ.get('GITHUB_REPOSITORY',''),os.environ.get('GH_TOKEN',''))
  result=request_release(api,tag,expected) if args.mode=='request' else resolve_release(api,tag,expected,event=event if name=='release' else None)
  if os.environ.get('EXPECTED_RELEASE_ID') and result['release_id']!=os.environ['EXPECTED_RELEASE_ID']:raise Rejected('Release identity changed')
  if os.environ.get('EXPECTED_PUBLISHED_AT') and result['published_at']!=os.environ['EXPECTED_PUBLISHED_AT']:raise Rejected('Release publication changed')
  with pathlib.Path(os.environ['GITHUB_OUTPUT']).open('a') as output:
   for key,value in result.items():output.write(key+'='+value+'\n')
  print('Validated published formal release '+result['tag']+' at '+result['revision']+'. Explicit reusable deployment follows.');return 0
 except Rejected as error:print('Release validation failed: '+str(error)+'. Existing refs/releases were not moved or deleted.',file=sys.stderr);return 1
 except (OSError,ValueError,KeyError):print('Release validation failed: invalid runner configuration or event data. Existing refs/releases were not moved or deleted.',file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
