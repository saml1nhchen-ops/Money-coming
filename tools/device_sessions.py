"""Independent persistent device sessions; only salted binding and token hashes.

Lock order: the caller's Workspace lock, then this module's SQLite transaction.
Every operation uses its own bounded connection. Corruption is never repaired by
removing/replacing the database, and an old generation cannot mint new sessions.
"""
import contextlib,hashlib,hmac,os,pathlib,re,secrets,sqlite3,time,urllib.parse
MAX_AGE=2592000
class StoreUnavailable(Exception):pass
class SessionLimit(Exception):pass
class GenerationChanged(Exception):pass

class DeviceSessions:
 def __init__(self,path,password):
  self.path=pathlib.Path(path);self.generation=None
  try:self._initialize(password)
  except (StoreUnavailable,OSError,ValueError,sqlite3.Error):pass
 def _connect(self):
  try:
   if not self.path.is_file() or self.path.stat().st_mode&0o222==0:raise StoreUnavailable()
   connection=sqlite3.connect('file:'+urllib.parse.quote(str(self.path.resolve()),safe='/')+'?mode=rw',uri=True,timeout=3,isolation_level=None)
   connection.execute('PRAGMA busy_timeout=3000');return connection
  except (OSError,sqlite3.Error):raise StoreUnavailable() from None
 def _validate_meta(self,row):
  if not row or type(row[0])!=int or row[0]!=1 or not isinstance(row[1],bytes) or len(row[1])!=32 or not isinstance(row[2],bytes) or len(row[2])!=32 or not isinstance(row[3],str) or not re.fullmatch(r'[0-9a-f]{64}',row[3]):raise StoreUnavailable()
 def _validate_sessions(self,connection,generation):
  rows=connection.execute('SELECT token_hash,generation,created_at,expires_at FROM trusted_sessions LIMIT 33').fetchall()
  if len(rows)>32:raise StoreUnavailable()
  for token_hash,current,created,expires in rows:
   if not isinstance(token_hash,bytes) or len(token_hash)!=32 or not isinstance(current,str) or not re.fullmatch(r'[0-9a-f]{64}',current) or current!=generation or type(created)!=int or type(expires)!=int or not 0<=created<expires<=253402300799 or expires-created!=MAX_AGE:raise StoreUnavailable()
 @contextlib.contextmanager
 def _transaction(self,check=True):
  connection=None
  try:
   connection=self._connect();connection.execute('BEGIN IMMEDIATE')
   if check:
    row=connection.execute('SELECT schema_version,password_salt,password_binding,generation FROM auth_meta WHERE singleton=1').fetchone()
    self._validate_meta(row);self._validate_sessions(connection,row[3])
    if not self.generation:raise StoreUnavailable()
    if row[3]!=self.generation:raise GenerationChanged()
   yield connection
   connection.execute('COMMIT')
  except (OSError,sqlite3.Error,ValueError):raise StoreUnavailable() from None
  finally:
   if connection is not None:
    try:
     if connection.in_transaction:connection.execute('ROLLBACK')
    finally:connection.close()
 def _initialize(self,password):
  parent=self.path.parent
  if not parent.exists():parent.mkdir(mode=0o700,parents=True,exist_ok=True)
  created=False
  try:
   fd=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd);created=True
  except FileExistsError:pass
  # Tighten only this dedicated DB, never the reports/budget/runtime directory.
  if created:os.chmod(self.path,0o600)
  with self._transaction(check=False) as connection:
   if created:
    connection.execute('CREATE TABLE auth_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),schema_version INTEGER NOT NULL,password_salt BLOB NOT NULL,password_binding BLOB NOT NULL,generation TEXT NOT NULL)')
    connection.execute('CREATE TABLE trusted_sessions(token_hash BLOB PRIMARY KEY,generation TEXT NOT NULL,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL)')
    connection.execute('CREATE INDEX trusted_sessions_expiry ON trusted_sessions(expires_at)')
    row=None
   else:
    row=connection.execute('SELECT schema_version,password_salt,password_binding,generation FROM auth_meta WHERE singleton=1').fetchone()
    self._validate_meta(row);self._validate_sessions(connection,row[3])
   if row:
    binding=hashlib.pbkdf2_hmac('sha256',password.encode(),row[1],600000,32)
    if hmac.compare_digest(binding,row[2]):self.generation=row[3];return
   salt=secrets.token_bytes(32);binding=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600000,32);generation=secrets.token_hex(32)
   connection.execute('DELETE FROM trusted_sessions')
   connection.execute('INSERT OR REPLACE INTO auth_meta VALUES(1,1,?,?,?)',(salt,binding,generation))
  self.generation=generation
 def usable(self):
  try:
   with self._transaction() as connection:connection.execute('SELECT token_hash FROM trusted_sessions LIMIT 1').fetchone()
   return True
  except (StoreUnavailable,GenerationChanged):return False
 def _cleanup_count(self,connection,now):
  connection.execute('DELETE FROM trusted_sessions WHERE expires_at<=? OR generation!=?',(now,self.generation))
  return connection.execute('SELECT COUNT(*) FROM trusted_sessions WHERE generation=?',(self.generation,)).fetchone()[0]
 def issue(self,legacy_count,now=None):
  now=int(time.time() if now is None else now)
  with self._transaction() as connection:
   if self._cleanup_count(connection,now)+legacy_count>=32:raise SessionLimit()
   token='td1_'+secrets.token_urlsafe(32);expires=now+MAX_AGE
   connection.execute('INSERT INTO trusted_sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).digest(),self.generation,now,expires))
  return token,expires
 def check_capacity(self,legacy_count,now=None):
  with self._transaction() as connection:
   if self._cleanup_count(connection,int(time.time() if now is None else now))+legacy_count>=32:raise SessionLimit()
 def authenticate(self,token,now=None):
  if not isinstance(token,str) or not re.fullmatch(r'td1_[A-Za-z0-9_-]{43}',token):return False
  with self._transaction() as connection:
   row=connection.execute('SELECT expires_at FROM trusted_sessions WHERE token_hash=? AND generation=?',(hashlib.sha256(token.encode()).digest(),self.generation)).fetchone()
   return bool(row and row[0]>int(time.time() if now is None else now))
 def revoke(self,token):
  with self._transaction() as connection:connection.execute('DELETE FROM trusted_sessions WHERE token_hash=? AND generation=?',(hashlib.sha256(token.encode()).digest(),self.generation))
