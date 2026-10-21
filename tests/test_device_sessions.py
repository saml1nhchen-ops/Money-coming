"""Real SQLite and authenticated HTTP; no external or model requests."""
import concurrent.futures,http.client,json,os,pathlib,sqlite3,sys,tempfile,threading,time,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
from device_sessions import DeviceSessions,StoreUnavailable,SessionLimit,MAX_AGE
from remote_gateway import Workspace,Budget,Server
class API:
 def call(self,*args):return {'runner':{},'busy':False,'runs':[]}
class DurableHTTPTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=pathlib.Path(self.tmp.name)/'auth'/'devices.sqlite3';self.password='synthetic-workspace-password';self.store=DeviceSessions(self.path,self.password);self.w=self.workspace(self.store,self.password)
  self.server=Server(('127.0.0.1',0),self.w);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def workspace(self,store,password):return Workspace(password,'public.example',Budget(pathlib.Path(self.tmp.name)/'budget',126),API(),session_store=store)
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
 def request(self,path,body=None,token=None):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=8);h={'Host':'public.example','Origin':'https://saml1nhchen-ops.github.io'}
  if token:h['Authorization']='Bearer '+token
  if body is not None:h['Content-Type']='application/json'
  c.request('POST' if body is not None else 'GET',path,None if body is None else json.dumps(body),h);r=c.getresponse();result=json.loads(r.read());c.close();return r.status,result
 def login(self,remember=True):return self.request('/api/workspace/login',{'password':self.password,'remember':remember})
 def reboot(self,password=None):
  if password is not None:self.password=password
  self.store=DeviceSessions(self.path,self.password);self.w=self.workspace(self.store,self.password);self.server.workspace=self.w
 def test_capability_legacy_payload_and_same_volume_restart(self):
  self.assertEqual(self.request('/healthz')[1]['capabilities'],{'remember_login':True,'remember_login_max_age_seconds':MAX_AGE})
  status,legacy=self.request('/api/workspace/login',{'password':self.password});self.assertEqual(status,200);self.assertFalse(legacy['remembered']);self.assertFalse(legacy['token'].startswith('td1_'))
  now=time.time();status,trusted=self.login();self.assertEqual(status,200);self.assertTrue(trusted['remembered']);self.assertTrue(trusted['token'].startswith('td1_'));self.assertEqual(self.request('/api/geo/state',token=trusted['token'])[0],200)
  from datetime import datetime
  expires=datetime.fromisoformat(trusted['expires_at']).timestamp();self.assertLess(abs(expires-now-MAX_AGE),2)
  before=self.path.read_bytes();self.assertNotIn(trusted['token'].encode(),before);self.assertNotIn(self.password.encode(),before);self.assertEqual(self.path.stat().st_mode&0o777,0o600);self.assertEqual(self.path.parent.stat().st_mode&0o777,0o700)
  self.reboot();self.assertEqual(self.request('/api/geo/state',token=trusted['token'])[0],200);self.assertEqual(self.request('/api/geo/state',token=legacy['token'])[0],401)
  self.assertEqual(self.store.authenticate(trusted['token'],now=expires-1),True);self.assertEqual(self.store.authenticate(trusted['token'],now=expires),False)
 def test_logout_revokes_one_device_and_expiry_cleanup(self):
  _,first=self.login();_,second=self.login();self.assertEqual(self.request('/api/workspace/logout',{},first['token']), (200,{'ok':True}));self.assertEqual(self.request('/api/geo/state',token=first['token'])[0],401);self.assertEqual(self.request('/api/geo/state',token=second['token'])[0],200)
  with sqlite3.connect(self.path) as c:c.execute('UPDATE trusted_sessions SET created_at=?,expires_at=?',(int(time.time())-MAX_AGE-1,int(time.time())-1))
  self.assertEqual(self.request('/api/geo/state',token=second['token'])[0],401);self.assertEqual(self.login()[0],200)
  with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM trusted_sessions').fetchone()[0],1)
 def test_password_change_and_change_back_never_revive_tokens(self):
  _,old=self.login();original=self.password;self.reboot('rotated-workspace-password');self.assertEqual(self.request('/api/geo/state',token=old['token'])[0],401);_,rotated=self.login();self.reboot(original)
  self.assertEqual(self.request('/api/geo/state',token=old['token'])[0],401);self.assertEqual(self.request('/api/geo/state',token=rotated['token'])[0],401);self.assertEqual(self.login()[0],200)
 def test_schema_validation_capacity_combines_legacy_and_durable(self):
  for value in ('true',1,None):self.assertEqual(self.request('/api/workspace/login',{'password':self.password,'remember':value})[0],400)
  self.assertEqual(self.request('/api/workspace/login',{'password':self.password,'unknown':True})[0],400)
  for _ in range(31):self.store.issue(0)
  status,legacy=self.login(False);self.assertEqual(status,200)
  status,d=self.login();self.assertEqual((status,d['code']),(429,'session_limit_reached'))
  self.assertEqual(self.request('/api/workspace/logout',{},legacy['token'])[0],200);self.assertEqual(self.login()[0],200)
 def test_store_faults_503_and_explicit_legacy_still_works(self):
  _,durable=self.login();_,legacy=self.login(False);self.path.write_bytes(b'corrupt sqlite database')
  for route,body in [('/api/geo/state',None),('/api/workspace/logout',{})]:
   status,d=self.request(route,body,durable['token']);self.assertEqual((status,d['code']),(503,'session_store_unavailable'))
  self.assertEqual(self.request('/api/geo/state',token=legacy['token'])[0],200)
  self.assertEqual(self.login(False)[0],200);status,d=self.login();self.assertEqual((status,d['code']),(503,'session_store_unavailable'))
  status,d=self.request('/healthz');self.assertEqual(status,200);self.assertNotIn('capabilities',d);self.assertNotIn(self.password,str(d));self.assertNotIn(durable['token'],str(d))
 def test_bad_session_fields_are_503_without_cleanup_and_legacy_works(self):
  _,durable=self.login();_,legacy=self.login(False)
  mutations=[('expires_at','not-an-integer'),('created_at','not-an-integer'),('expires_at',-1),('created_at',-1),('expires_at',253402300800),('token_hash','not-a-blob'),('token_hash',b'short'),('generation','bad-generation'),('generation','f'*64)]
  with sqlite3.connect(self.path) as c:original=c.execute('SELECT token_hash,generation,created_at,expires_at FROM trusted_sessions').fetchone()
  for field,value in mutations:
   with self.subTest(field=field,value=value):
    with sqlite3.connect(self.path) as c:c.execute('UPDATE trusted_sessions SET '+field+'=?',(value,))
    self.assertFalse(self.store.usable())
    for route,body in [('/api/geo/state',None),('/api/workspace/logout',{})]:
     status,d=self.request(route,body,durable['token']);self.assertEqual((status,d['code']),(503,'session_store_unavailable'))
    status,d=self.login();self.assertEqual((status,d['code']),(503,'session_store_unavailable'))
    self.w.attempts.clear();self.w.global_attempts.clear()
    self.assertEqual(self.request('/api/geo/state',token=legacy['token'])[0],200);self.assertEqual(self.login(False)[0],200)
    self.assertNotIn('capabilities',self.request('/healthz')[1])
    # Fault detection must not delete or silently repair even expired bad rows.
    with sqlite3.connect(self.path) as c:
     self.assertEqual(c.execute('SELECT '+field+' FROM trusted_sessions').fetchone()[0],value)
     c.execute('UPDATE trusted_sessions SET token_hash=?,generation=?,created_at=?,expires_at=?',original)
    self.assertTrue(self.store.usable())
  with sqlite3.connect(self.path) as c:c.execute("UPDATE trusted_sessions SET expires_at='corrupt'")
  restarted=DeviceSessions(self.path,'rotated-team-password')
  self.assertFalse(restarted.usable())
  with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT expires_at FROM trusted_sessions').fetchone()[0],'corrupt')
 def test_readonly_and_unknown_schema_fail_closed(self):
  _,trusted=self.login();self.path.chmod(0o400)
  self.assertEqual(self.request('/api/geo/state',token=trusted['token'])[0],503);self.path.chmod(0o600)
  with sqlite3.connect(self.path) as c:c.execute('UPDATE auth_meta SET schema_version=99')
  self.reboot();self.assertFalse(self.store.usable());self.assertEqual(self.login()[0],503);self.assertEqual(self.login(False)[0],200)
class StoreTransactionTests(unittest.TestCase):
 def test_two_store_instances_concurrent_capacity_is_atomic(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=pathlib.Path(tmp)/'devices';a=DeviceSessions(path,'synthetic-team-password');b=DeviceSessions(path,'synthetic-team-password')
   def issue(i):
    try:return (a if i%2 else b).issue(0)[0]
    except SessionLimit:return None
   with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:tokens=list(pool.map(issue,range(64)))
   self.assertEqual(len([t for t in tokens if t]),32)
   with sqlite3.connect(path) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM trusted_sessions').fetchone()[0],32)
 def test_failed_commit_rolls_back_logout_before_reporting_success(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=DeviceSessions(pathlib.Path(tmp)/'devices','synthetic-team-password');token,_=store.issue(0);original=store._connect
   class FailCommit:
    def __init__(self):self.connection=original()
    def execute(self,sql,*args):
     if sql=='COMMIT':raise sqlite3.OperationalError('Synthetic disk failure')
     return self.connection.execute(sql,*args)
    @property
    def in_transaction(self):return self.connection.in_transaction
    def close(self):self.connection.close()
   with patch.object(store,'_connect',side_effect=FailCommit):
    with self.assertRaises(StoreUnavailable):store.revoke(token)
   self.assertTrue(store.authenticate(token))
 def test_unknown_database_is_not_replaced_and_transaction_timeout_is_failure(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=pathlib.Path(tmp)/'devices';path.write_bytes(b'broken');store=DeviceSessions(path,'synthetic-team-password');self.assertFalse(store.usable());self.assertEqual(path.read_bytes(),b'broken')
  with tempfile.TemporaryDirectory() as tmp:
   path=pathlib.Path(tmp)/'devices';store=DeviceSessions(path,'synthetic-team-password');token,_=store.issue(0);lock=sqlite3.connect(path);lock.execute('BEGIN IMMEDIATE')
   try:
    start=time.monotonic()
    with self.assertRaises(StoreUnavailable):store.authenticate(token)
    self.assertLess(time.monotonic()-start,4)
   finally:lock.rollback();lock.close()
if __name__=='__main__':unittest.main()
