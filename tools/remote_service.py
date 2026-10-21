"""Container entry point. Owns its children; never attaches to existing listeners."""
import json, os, pathlib, re, shutil, signal, socket, subprocess, sys, threading, time
from remote_gateway import Budget, Failure, LocalAPI, Server, Workspace
ROOT=pathlib.Path(__file__).resolve().parents[1]
def choose_models(models,environ=os.environ):
 ids={m['id'] for m in models if isinstance(m,dict) and isinstance(m.get('id'),str)};selected=[]
 for family,var in [('gpt','SIGNAL_GPT_MODEL'),('gemini','SIGNAL_GEMINI_MODEL')]:
  candidates=sorted(i for i in ids if re.search(r'(?:^|[/\s-])'+family+r'(?:-|\d)',i,re.I) and not re.search(r'auto|router|latest|dynamic|image|audio|realtime|embedding|tts|search',i,re.I))
  explicit=environ.get(var)
  if explicit and explicit not in candidates:raise Failure(503,'required_models_unavailable')
  if not candidates:raise Failure(503,'required_models_unavailable')
  selected.append(explicit or candidates[0])
 return selected
def prepare_dependencies(root=ROOT):
 target=root/'runtime/upstreams/niubigeo';seed=pathlib.Path(os.environ.get('SIGNAL_UPSTREAM_SEED','/opt/niubigeo'))
 if not target.exists() and seed.exists():target.parent.mkdir(parents=True,exist_ok=True);target.symlink_to(seed,target_is_directory=True)
 return bool(shutil.which('node') and (target/'node_modules/tsx/dist/cli.mjs').is_file())
def bootstrap(w,environ=os.environ):
 if not environ.get('SIGNAL_BAI_API_KEY'):w.reason='missing_bai_key';return
 try:
  state=w.api.call('bai','connect',{'key':environ['SIGNAL_BAI_API_KEY']})
  for model in choose_models(state.get('models',[]),environ):state=w.api.call('bai','profile',{'model':model,'name':model,'protocol':'chat','markets':['CN','US'],'search':False})
  w.profiles=state['profiles'];w.fetched_at=state.get('fetched_at')
  for p in w.profiles:p['manufacturer']='OpenAI' if re.search(r'(?:^|[/\s-])gpt',p['model'],re.I) else 'Google'
  if len(w.profiles)!=2:w.reason='required_models_unavailable';return
 except Failure as e:w.reason=e.code if e.code=='required_models_unavailable' else 'catalog_unavailable';return
 except Exception:w.reason='catalog_unavailable';return
 if not prepare_dependencies():w.reason='runtime_unavailable';return
 w.ready=True;w.reason=None
class Services:
 def __init__(self,root=ROOT):self.root=root;self.children=[];self.api=LocalAPI()
 def start(self):
  # Preflight every port before starting any child, protecting existing processes.
  for port in (8770,8771,8772):
   with socket.socket() as s:
    if s.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('Required loopback port already occupied')
  self.root.joinpath('runtime').mkdir(parents=True,exist_ok=True)
  try:
   for port,filename,service,path in [(8770,'native_service.py','native','ai/providers'),(8771,'bai_service.py','bai','state'),(8772,'geo_flow.py','geo','state')]:
    # Legacy services never receive edge or vendor credentials in their environment.
    env={k:v for k,v in os.environ.items() if k not in ('SIGNAL_BAI_API_KEY','SIGNAL_WORKSPACE_PASSWORD')}
    child=subprocess.Popen([sys.executable,str(self.root/'tools'/filename)],cwd=self.root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);self.children.append(child)
    for attempt in range(100):
     if child.poll() is not None:raise RuntimeError('Loopback service exited')
     try:self.api.call(service,path);break
     except Exception:time.sleep(.1)
    else:raise RuntimeError('Loopback service unavailable')
  except Exception:self.stop();raise
 def stop(self):
  for child in reversed(self.children):
   if child.poll() is None:child.terminate()
  for child in self.children:
   try:child.wait(timeout=5)
   except subprocess.TimeoutExpired:child.kill();child.wait()
 def healthy(self):return bool(self.children) and all(c.poll() is None for c in self.children)
def should_hold_maintenance(environ,receipt=None):
 if environ.get('SIGNAL_DEPLOY_MAINTENANCE')!='1':return False
 nonce=environ.get('SIGNAL_DEPLOY_NONCE','')
 if not re.fullmatch(r'[0-9a-f]{32}',nonce):return True
 revision=environ.get('SIGNAL_BUILD_REVISION','unknown')
 if not re.fullmatch(r'[0-9a-f]{40}',revision):revision='unknown'
 return not (isinstance(receipt,dict) and receipt.get('status')=='healthy' and receipt.get('nonce')==nonce and receipt.get('revision')==revision)
def read_deployment_receipt():
 # Fixed read-only deployment mount; never follow an alternate receipt path.
 try:
  with pathlib.Path('/run/signal-deploy/healthy.json').open('rb') as stream:raw=stream.read(4096)
  if len(raw)>=4096:return None
  return json.loads(raw)
 except (OSError,ValueError):return None
def install_maintenance_signals(w,environ=os.environ):
 if environ.get('SIGNAL_DEPLOY_MAINTENANCE')=='1':
  w.maintenance_requested.set()
  if not should_hold_maintenance(environ,read_deployment_receipt()):w.maintenance_requested.clear()
 # Signal handlers never wait for the admission lock or perform I/O.
 signal.signal(signal.SIGUSR1,lambda *_:w.maintenance_requested.set())
 signal.signal(signal.SIGUSR2,lambda *_:w.maintenance_requested.clear())
def main():
 host=os.environ.get('SIGNAL_PUBLIC_HOST') or os.environ.get('RENDER_EXTERNAL_HOSTNAME','')
 limit=os.environ.get('SIGNAL_DAILY_CALL_LIMIT','126')
 if not re.fullmatch(r'[0-9]+',limit):raise ValueError('Invalid daily limit')
 w=Workspace(os.environ.get('SIGNAL_WORKSPACE_PASSWORD',''),host,Budget(ROOT/'runtime/remote-budget.json',int(limit)))
 install_maintenance_signals(w)
 w.budget.state() # Fail closed on a damaged persistent ledger before any model connection.
 prepare_dependencies();services=Services();services.start();w.api=services.api
 server=None
 try:
  bootstrap(w);server=Server(('0.0.0.0',int(os.environ.get('PORT','8080'))),w)
  def drain():
   # This lock waits for any already admitted POST to publish its active job.
   # Only then can an idle observation mean there is no pending submission.
   w.begin_shutdown()
   try:
    state=w.api.call('geo','state')
    ids={r['id'] for r in state.get('runs',[]) if r.get('status') in ('queued','running')}
    if w.active:ids.add(w.active)
    for rid in ids:w.api.call('geo','stop',{'id':rid})
   except Exception:pass
   deadline=time.monotonic()+10
   while time.monotonic()<deadline:
    try:
     if not w.api.call('geo','state').get('busy'):break
    except Exception:break
    time.sleep(.2)
   server.shutdown()
  def stop(*args):
   # Signal handler never waits on the workspace lock or a network request.
   if w.shutdown_requested.is_set():return
   w.shutdown_requested.set()
   threading.Thread(target=drain,daemon=True).start()
  signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
  def monitor():
   while not w.stopping():
    if not services.healthy():stop();return
    time.sleep(1)
  threading.Thread(target=monitor,daemon=True).start();server.serve_forever(poll_interval=.2)
 finally:
  if server:server.server_close()
  services.stop()
if __name__=='__main__':
 try:main()
 except Exception:print('Remote service startup failed; check non-secret deployment configuration.',file=sys.stderr);sys.exit(1)
