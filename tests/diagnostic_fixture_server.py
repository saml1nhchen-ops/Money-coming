"""Synthetic captured websites/model responses, real gateway/store/audit/parser."""
import json,os,pathlib,signal,sys,threading
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
from site_readiness_fixture_server import Transport
from test_geo_diagnose import FlowAPI
from geo_audit import AuditManager
from geo_diagnose import DiagnosticManager
from remote_gateway import Workspace,Budget,Server
import audit_fetch as f

def main():
 root=pathlib.Path(sys.argv[1]);api=FlowAPI();transport=Transport()
 with patch('pinned_http.urllib.request.getproxies',return_value={}):
  w=Workspace('synthetic-password-long','public.example',Budget(root/'runtime/budget.json',126),api);w.ready=True;w.reason=None
  w.profiles=[{'id':'gpt','model':'gpt-synthetic-fixture','name':'Synthetic fixture','manufacturer':'OpenAI','protocol':'chat','markets':['CN','US'],'search':False}]
  if os.environ.get('SIGNAL_TEST_THREE_PROFILES')=='1':
   w.profiles.extend([{'id':pid,'model':pid+'-synthetic-fixture','name':'Synthetic '+pid,'manufacturer':vendor,'protocol':'chat','markets':['CN','US'],'search':False} for pid,vendor in [('gemini','Google'),('claude','Anthropic')]])
  w.auditor=AuditManager(w,root/'runtime/audits/index.sqlite3',lambda usage=None:f.FetchBudget(usage,worker=transport))
  w.diagnostics=DiagnosticManager(w,root/'runtime/diagnostics/index.sqlite3',root,poll_interval=.01)
  server=Server(('127.0.0.1',0),w);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  print(json.dumps({'port':server.server_port,'token':w.login('synthetic-password-long','fixture')['token']}),flush=True)
  done=threading.Event();signal.signal(signal.SIGTERM,lambda *_:done.set());signal.signal(signal.SIGINT,lambda *_:done.set());done.wait()
  w.shutdown_requested.set();server.shutdown();server.server_close();w.diagnostics.pool.shutdown(wait=True);w.auditor.pool.shutdown(wait=True)
if __name__=='__main__':main()
