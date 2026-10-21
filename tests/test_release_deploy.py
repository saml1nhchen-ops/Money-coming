"""Exercise rollout/rollback control flow with synthetic Docker and TLS responses."""
import fcntl,json,os,pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
OLD='sha256:'+'1'*64
NEW='sha256:'+'2'*64
REV='a'*40
OLDREV='b'*40
REF='ghcr.io/saml1nhchen-ops/money-coming/backend@sha256:'+'3'*64
FAKE=r'''#!/usr/bin/env python3
import json,os,pathlib,sys
state_path=pathlib.Path(os.environ['FAKE_STATE']);s=json.loads(state_path.read_text());a=sys.argv[1:];kind=pathlib.Path(sys.argv[0]).name
s['events'].append([kind,*a])
def finish(code=0,value=None):
 state_path.write_text(json.dumps(s))
 if value is not None:print(value)
 raise SystemExit(code)
def version():return s['new_revision'] if s['image']==s['new'] else s['old_revision']
if kind=='curl':
 if s['mode'] in ('tls_fail','rollback_fail') and s['image']==s['new'] or s['mode']=='rollback_fail' and s.get('up',0)>1:finish(22)
 pathlib.Path(a[a.index('-o')+1]).write_text(json.dumps({'ok':True,'revision':version()}));finish()
if a[:1]==['pull']:finish(1 if s['mode']=='pull_fail' else 0)
if a[:2]==['image','inspect']:
 fmt=a[a.index('--format')+1];ref=a[-1]
 if '.Id' in fmt:finish(value=s['new'])
 finish(value=('c'*40 if s['mode']=='wrong_revision' else s['new_revision']) if ref in (s['ref'],s['new']) else s['old_revision'])
if a[:1]==['inspect']:
 fmt=a[a.index('--format')+1]
 finish(value=s['image'] if '.Image' in fmt else s['volume'])
if a[:1]!=['compose']:finish(99)
assert a[a.index('-p')+1]=='geo-backend'
if a[-3:]==['ps','-q','backend']:finish(value='one-container')
if 'exec' in a:
 if 'tools/deploy_control.py' in a:
  command=a[a.index('tools/deploy_control.py')+1]
  if s['mode']=='old_gate':finish(69)
  if command=='wait-idle' and (s['mode']=='busy' or not s['maintenance']):finish(1)
  if command=='health' and (not s['maintenance'] or s['mode']=='private_fail' and s['image']==s['new'] or s['mode']=='rollback_fail' and s.get('up',0)>1):finish(1)
  finish(value=json.dumps({'host':'backend.example.test','revision':version(),'model_ready':True,'maintenance':s['maintenance'],'busy':False}))
 if a[-1] in ('SIGUSR1','SIGUSR2'):
  s['maintenance']=a[-1]=='SIGUSR1';finish()
 finish(99)
if 'up' in a:
 assert a[-1]=='backend' and '--no-build' in a and '--no-deps' in a
 files=[a[i+1] for i,v in enumerate(a) if v=='-f'];override=pathlib.Path(files[-1]).read_text()
 image_line=next(x for x in override.splitlines() if x.strip().startswith('image:'))
 image=json.loads(image_line.split(':',1)[1].strip());s['image']=s['new'] if image==s['ref'] else image
 assert s['image'] in (s['old'],s['new'])
 s['maintenance']=True;s['up']=s.get('up',0)+1;finish()
finish(99)
'''
class ReleaseDeployment(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name);(self.root/'.env').write_text('')
  (self.root/'compose.yaml').write_text('services: {}');self.bin=self.root/'bin';self.bin.mkdir()
  for name in ('docker','curl'):
   p=self.bin/name;p.write_text(FAKE);p.chmod(0o755)
  self.state=self.root/'fake.json';self.state.write_text(json.dumps(dict(mode='ok',image=OLD,old=OLD,new=NEW,ref=REF,new_revision=REV,old_revision=OLDREV,volume='geo-backend_signal-geo-runtime',maintenance=False,events=[])))
  self.env={**os.environ,'PATH':str(self.bin)+':'+os.environ['PATH'],'SIGNAL_DEPLOY_PROJECT_DIR':str(self.root),'FAKE_STATE':str(self.state),'SIGNAL_DEPLOY_HEALTH_TIMEOUT':'1','SIGNAL_DEPLOY_ROLLBACK_TIMEOUT':'1','SIGNAL_DEPLOY_LOCK_TIMEOUT':'1'}
 def data(self):return json.loads(self.state.read_text())
 def mode(self,value):
  s=self.data();s['mode']=value;self.state.write_text(json.dumps(s))
 def run_script(self,ref=REF,revision=REV,ident='101',published='2026-10-21T18:00:00Z',tag='v1.0.0'):return subprocess.run(['bash',str(ROOT/'deploy/release-deploy.sh'),ref,revision,ident,published,tag],env=self.env,text=True,capture_output=True,timeout=20)
 def status(self):return json.loads((self.root/'.deploy/release-status.json').read_text())['status']
 def test_success_and_exact_release_idempotence(self):
  r=self.run_script();self.assertEqual(r.returncode,0,r.stderr);s=self.data();self.assertEqual(s['image'],NEW);self.assertFalse(s['maintenance']);self.assertEqual(s['up'],1);self.assertEqual(self.status(),'healthy')
  r=self.run_script();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(self.data()['up'],1);self.assertIn('already healthy',r.stdout)
 def test_invalid_reference_or_commit_rejected_before_docker(self):
  for ref,rev in [('ghcr.io/other/repo:latest',REV),(REF,'main')]:
   self.assertNotEqual(self.run_script(ref,rev).returncode,0)
  self.assertEqual(self.data()['events'],[])
 def test_old_gate_never_receives_signal(self):
  self.mode('old_gate');r=self.run_script();self.assertNotEqual(r.returncode,0);self.assertFalse(any('SIGUSR1' in e for e in self.data()['events']));self.assertEqual(self.data()['image'],OLD)
 def test_pull_or_metadata_failure_leaves_live_service_unchanged(self):
  for mode in ('pull_fail','wrong_revision'):
   self.mode(mode);self.assertNotEqual(self.run_script().returncode,0);self.assertEqual(self.data()['image'],OLD);self.assertFalse(self.data()['maintenance']);self.assertFalse(any('SIGUSR1' in e for e in self.data()['events']))
 def test_active_job_timeout_reopens_admission_without_restart(self):
  self.mode('busy');r=self.run_script();self.assertNotEqual(r.returncode,0);s=self.data();self.assertEqual(s['image'],OLD);self.assertFalse(s['maintenance']);self.assertNotIn('up',s);self.assertEqual(self.status(),'blocked')
 def test_private_failure_rolls_back_local_image(self):
  self.mode('private_fail');r=self.run_script();self.assertNotEqual(r.returncode,0,r.stdout);s=self.data();self.assertEqual(s['image'],OLD);self.assertEqual(s['up'],2);self.assertFalse(s['maintenance']);self.assertEqual(self.status(),'rolled_back')
 def test_public_tls_failure_is_not_hidden_by_private_health(self):
  self.mode('tls_fail');r=self.run_script();self.assertNotEqual(r.returncode,0);self.assertEqual(self.data()['image'],OLD);self.assertEqual(self.status(),'rolled_back')
 def test_failed_rollback_closes_admission_and_blocks_next_deployment(self):
  self.mode('rollback_fail');r=self.run_script();self.assertNotEqual(r.returncode,0);self.assertTrue(self.data()['maintenance']);self.assertEqual(self.status(),'rollback_failed');before=len(self.data()['events']);self.assertNotEqual(self.run_script().returncode,0);self.assertEqual(len(self.data()['events']),before)
 def test_server_lock_prevents_interleaved_deployment(self):
  folder=self.root/'.deploy';folder.mkdir()
  with (folder/'release.lock').open('w') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);r=self.run_script();self.assertNotEqual(r.returncode,0);self.assertEqual(self.data()['events'],[])
 def test_interrupted_deployment_is_not_used_as_healthy_baseline(self):
  folder=self.root/'.deploy';folder.mkdir();(folder/'release-status.json').write_text(json.dumps({'status':'preparing','previous_image':OLD}))
  self.assertNotEqual(self.run_script().returncode,0);self.assertEqual(self.data()['events'],[])
 def test_same_image_new_release_advances_order_without_restart(self):
  self.assertEqual(self.run_script().returncode,0)
  newer=self.run_script(ident='102',published='2026-10-23T18:00:00Z',tag='v1.0.1');self.assertEqual(newer.returncode,0,newer.stderr)
  current=json.loads((self.root/'.deploy/current-release.json').read_text());self.assertEqual(current['release_id'],102);self.assertEqual(self.data()['up'],1)
  before=len(self.data()['events']);late=self.run_script(ident='103',published='2026-10-22T18:00:00Z',tag='v1.0.2');self.assertNotEqual(late.returncode,0);self.assertEqual(len(self.data()['events']),before)
 def test_late_old_release_is_rejected(self):
  folder=self.root/'.deploy';folder.mkdir();(folder/'current-release.json').write_text(json.dumps({'published_at':'2026-10-22T18:00:00Z','release_id':102}))
  self.assertNotEqual(self.run_script().returncode,0);self.assertEqual(self.data()['events'],[])
 def test_same_release_cannot_change_digest(self):
  folder=self.root/'.deploy/releases';folder.mkdir(parents=True);(folder/'101.json').write_text(json.dumps({'image':'different-digest'}))
  self.assertNotEqual(self.run_script().returncode,0);self.assertEqual(self.data()['events'],[])
 def test_forced_ssh_command_cannot_run_a_shell(self):
  import importlib.util,shlex
  spec=importlib.util.spec_from_file_location('forced',ROOT/'deploy/ssh-release-command.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  good=['sudo','-n','/usr/local/sbin/signal-geo-deploy',REF,REV,'101','2026-10-21T18:00:00Z','v1.0.0']
  self.assertEqual(module.validated_command(shlex.join(good))[0],'/usr/bin/sudo')
  for command in ['bash','sudo -n cat /home/ubuntu/geo-backend/.env',shlex.join(good)+'; whoami',shlex.join(good)+' extra',shlex.join(good[:-1]+['$(whoami)'])]:
   with self.assertRaises(ValueError):module.validated_command(command)
 def test_workflow_shell_syntax(self):
  import yaml
  workflow=yaml.load((ROOT/'.github/workflows/release-backend.yml').read_text(),Loader=yaml.BaseLoader)
  for job in workflow['jobs'].values():
   for step in job['steps']:
    if 'run' in step:
     result=subprocess.run(['bash','-n'],input=step['run'],text=True,capture_output=True);self.assertEqual(result.returncode,0,result.stderr)
 def test_formal_release_workflow_only(self):
  import yaml
  workflow=yaml.load((ROOT/'.github/workflows/release-backend.yml').read_text(),Loader=yaml.BaseLoader)
  self.assertEqual(workflow['on'],{'release':{'types':['published']}})
  self.assertEqual(workflow['jobs']['build']['steps'][0]['with']['ref'],'refs/tags/${{ github.event.release.tag_name }}');self.assertIn('draft == false',workflow['jobs']['build']['if']);self.assertIn('prerelease == false',workflow['jobs']['build']['if']);self.assertEqual(workflow['concurrency']['cancel-in-progress'],'false')
  deploy=workflow['jobs']['deploy'];self.assertEqual(deploy['needs'],'build');self.assertEqual(deploy['environment'],'production')
if __name__=='__main__':unittest.main()
