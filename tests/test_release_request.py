"""Synthetic GitHub API and real isolated git repositories, no external calls."""
import copy,importlib.util,io,json,os,pathlib,subprocess,tempfile,unittest,urllib.error
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_request',ROOT/'deploy/release_request.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
TAG='v0.3.1'
def formal():return {'id':123,'tag_name':TAG,'draft':False,'prerelease':False,'published_at':'2026-11-01T10:11:12Z','target_commitish':'main'}
class FakeAPI:
 def __init__(self,sha,tag=True,release=True,race=None,annotated=False,tag_name=TAG):
  self.tag_name=tag_name;self.sha=sha;self.tag=tag;self.release=formal() if release else None;self.calls=[];self.race=race;self.annotated=annotated
  if self.release:self.release['tag_name']=tag_name
 def request(self,method,path,body=None):
  self.calls.append((method,path,body))
  if path=='/git/ref/tags/'+self.tag_name:return {'object':{'type':'tag' if self.annotated else 'commit','sha':'b'*40 if self.annotated else self.sha}} if self.tag else None
  if path=='/git/tags/'+'b'*40:return {'object':{'type':'commit','sha':self.sha}}
  if method=='GET' and path=='/releases/tags/'+self.tag_name:return copy.deepcopy(self.release)
  if method=='POST' and path=='/git/refs':
   self.tag=True;self.sha=body['sha']
   if self.race:raise r.APIError(self.race)
   return {}
  if method=='POST' and path=='/releases':
   self.release=formal()
   if self.race:raise r.APIError(self.race)
   return copy.deepcopy(self.release)
  raise AssertionError((method,path))
class RequestTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.repo=pathlib.Path(self.tmp.name)
  self.git('init','-q','-b','main');self.git('config','user.email','offline@example.test');self.git('config','user.name','Offline test')
  for name in ('.github/workflows/request-release.yml','.github/workflows/release-backend.yml','deploy/release_request.py'):
   p=self.repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('synthetic automation')
  self.git('add','.');self.git('commit','-qm','Synthetic automation');self.sha=self.git('rev-parse','HEAD');self.git('update-ref','refs/remotes/origin/main',self.sha);self.git('tag',TAG);self.git('tag','release-request/'+TAG)
 def git(self,*args):return subprocess.check_output(['git',*args],cwd=self.repo,text=True,stderr=subprocess.DEVNULL).strip()
 def test_request_creation_and_identity_idempotence(self):
  api=FakeAPI(self.sha,tag=False,release=False);result=r.request_release(api,TAG,self.sha,self.repo);self.assertEqual(result['revision'],self.sha);self.assertEqual(result['release_id'],'123');writes=[c for c in api.calls if c[0]=='POST'];self.assertEqual(len(writes),2)
  api.calls=[];self.assertEqual(r.request_release(api,TAG,self.sha,self.repo),result);self.assertFalse(any(c[0]=='POST' for c in api.calls))
 def test_creation_races_only_reread_and_verify(self):
  for status in (409,422):
   api=FakeAPI(self.sha,tag=False,release=False,race=status);self.assertEqual(r.request_release(api,TAG,self.sha,self.repo)['revision'],self.sha)
 def test_conflicting_tag_and_nonformal_releases_fail_without_mutation(self):
  api=FakeAPI('c'*40)
  with self.assertRaises(r.Rejected):r.request_release(api,TAG,self.sha,self.repo)
  self.assertFalse(any(c[0]=='POST' for c in api.calls))
  for mutation in ({'draft':True},{'prerelease':True},{'published_at':None},{'tag_name':'v9.0.0'},{'id':True},{'published_at':'2026-99-01T01:02:03Z'}):
   api=FakeAPI(self.sha);api.release.update(mutation)
   with self.assertRaises(r.Rejected):r.request_release(api,TAG,self.sha,self.repo)
   self.assertFalse(any(c[0]=='POST' for c in api.calls))
 def test_real_lightweight_and_annotated_tag_peeling(self):
  self.assertEqual(r.request_revision('refs/tags/release-request/'+TAG,self.repo),self.sha)
  self.git('tag','-d',TAG,'release-request/'+TAG);self.git('tag','-a',TAG,'-m','annotated');self.git('tag','-a','release-request/'+TAG,'-m','annotated request')
  self.assertNotEqual(self.git('rev-parse','refs/tags/release-request/'+TAG),self.sha);self.assertEqual(r.request_revision('refs/tags/release-request/'+TAG,self.repo),self.sha)
  self.assertEqual(r.resolve_release(FakeAPI(self.sha,annotated=True),TAG,self.sha,self.repo)['revision'],self.sha)
 def test_main_ancestor_and_automation_presence_required(self):
  self.git('checkout','-qb','untrusted');(self.repo/'untrusted').write_text('x');self.git('add','.');self.git('commit','-qm','untrusted');self.git('tag','release-request/v0.3.2')
  with self.assertRaises(r.Rejected):r.request_revision('refs/tags/release-request/v0.3.2',self.repo)
  self.git('update-ref','refs/remotes/origin/main',self.git('rev-parse','HEAD'));self.git('rm','deploy/release_request.py');self.git('commit','-qm','Missing helper');self.git('tag','release-request/v0.3.3');self.git('update-ref','refs/remotes/origin/main',self.git('rev-parse','HEAD'))
  with self.assertRaises(r.Rejected):r.request_revision('refs/tags/release-request/v0.3.3',self.repo)
 def test_resolve_does_not_trust_target_commitish(self):
  api=FakeAPI(self.sha);api.release['target_commitish']='irrelevant-branch';self.assertEqual(r.resolve_release(api,TAG,self.sha,self.repo)['revision'],self.sha)
  api.sha='d'*40;api.release['target_commitish']=self.sha
  with self.assertRaises(r.Rejected):r.resolve_release(api,TAG,self.sha,self.repo)
  with self.assertRaises(r.Rejected):r.resolve_release(FakeAPI(self.sha),TAG,'e'*40,self.repo)
  with self.assertRaises(r.Rejected):r.resolve_release(FakeAPI(self.sha,release=False),TAG,self.sha,self.repo)
  with self.assertRaises(r.Rejected):r.resolve_release(FakeAPI(self.sha),TAG,self.sha,self.repo,event={'release':{'id':999}})
 def test_request_callgate_and_native_release_gate(self):
  event={'deleted':False,'forced':False};ref='refs/tags/release-request/'+TAG;r.gate('push',ref,event,TAG,self.sha,called=True)
  for name,ref2,e,expected,called in [('push',ref,event,self.sha,False),('push','refs/heads/main',event,self.sha,True),('push',ref,{'deleted':True,'forced':False},self.sha,True),('push',ref,{'deleted':False,'forced':True},self.sha,True),('workflow_dispatch',ref,event,self.sha,True),('push',ref,event,'',True)]:
   with self.assertRaises(r.Rejected):r.gate(name,ref2,e,TAG,expected,called)
  native={'action':'published','release':formal()};r.gate('release','refs/tags/'+TAG,native,TAG,'')
  for mutation in ({'draft':True},{'prerelease':True}):
   bad=copy.deepcopy(native);bad['release'].update(mutation)
   with self.assertRaises(r.Rejected):r.gate('release','refs/tags/'+TAG,bad,TAG,'')
 def test_native_formal_tag_compatibility_without_relaxing_request_semver(self):
  tag='production-2026.11_1';self.git('tag',tag);event={'action':'published','release':{**formal(),'tag_name':tag}}
  r.gate('release','refs/tags/'+tag,event,tag,'');self.assertEqual(r.resolve_release(FakeAPI(self.sha,tag_name=tag),tag,'',self.repo)['revision'],self.sha)
  with self.assertRaises(r.Rejected):r.gate('push','refs/tags/release-request/'+tag,{'deleted':False,'forced':False},tag,self.sha,True)
 def test_api_403_and_error_body_never_exposed(self):
  api=r.API('saml1nhchen-ops/Money-coming','synthetic-secret');body=io.BytesIO(b'synthetic-secret vendor body')
  error=urllib.error.HTTPError('https://api.github.com/',403,'denied',{},body)
  with patch.object(api.opener,'open',side_effect=error) as call:
   with self.assertRaises(r.APIError) as caught:api.request('POST','/git/refs',{})
  self.assertEqual(caught.exception.status,403);self.assertEqual(call.call_count,1);self.assertEqual(body.tell(),0);self.assertNotIn('synthetic-secret',str(caught.exception))
 def test_safe_cli_diagnostic_preserves_api_status_without_token(self):
  import contextlib
  event=self.repo/'event.json';event.write_text(json.dumps({'deleted':False,'forced':False}));output=self.repo/'output'
  environ={'GITHUB_EVENT_PATH':str(event),'GITHUB_EVENT_NAME':'push','GITHUB_REF':'refs/tags/release-request/'+TAG,'GITHUB_REPOSITORY':'saml1nhchen-ops/Money-coming','GH_TOKEN':'synthetic-secret','GITHUB_OUTPUT':str(output)}
  error=io.StringIO()
  with patch.dict(os.environ,environ,clear=True),patch.object(r,'request_revision',return_value=self.sha),patch.object(r,'request_release',side_effect=r.APIError(403)),contextlib.redirect_stderr(error):self.assertEqual(r.main(['request']),1)
  self.assertIn('HTTP 403',error.getvalue());self.assertNotIn('synthetic-secret',error.getvalue());self.assertFalse(output.exists())
 def test_non_race_post_errors_are_not_retried(self):
  api=FakeAPI(self.sha,tag=False,release=False,race=403)
  with self.assertRaises(r.APIError):r.request_release(api,TAG,self.sha,self.repo)
  self.assertEqual(len([c for c in api.calls if c[0]=='POST']),1)
if __name__=='__main__':unittest.main()
