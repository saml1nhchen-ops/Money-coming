"""Real gateway and offline parsers; synthetic website transport only."""
import json,pathlib,signal,sys,threading
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
from test_geo_audit import Synthetic,API
import audit_fetch as f
from geo_audit import AuditManager
from remote_gateway import Workspace,Budget,Server
class Transport(Synthetic):
 def __call__(self,operation,args,timeout):
  if operation in ('parse','robots'):return f.isolated(operation,args,timeout)
  if operation=='dns' and args[0]=='failed.example':raise f.AuditFetchError('dns_failed')
  return super().__call__(operation,args,timeout)
def main():
 root=pathlib.Path(sys.argv[1]);transport=Transport();api=API()
 with patch('pinned_http.urllib.request.getproxies',return_value={}):
  w=Workspace('synthetic-password-long','public.example',Budget(root/'unused-budget',0),api)
  manager=AuditManager(w,root/'audits/index.sqlite3',lambda usage=None:f.FetchBudget(usage,worker=transport));w.auditor=manager
  server=Server(('127.0.0.1',0),w);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  print(json.dumps({'port':server.server_port,'token':w.login('synthetic-password-long','fixture')['token']}),flush=True)
  done=threading.Event();signal.signal(signal.SIGTERM,lambda *_:done.set());signal.signal(signal.SIGINT,lambda *_:done.set());done.wait()
  server.shutdown();server.server_close();manager.pool.shutdown(wait=True)
if __name__=='__main__':main()
