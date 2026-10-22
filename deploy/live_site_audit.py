"""Read-only public website audit with actual tools and gateway; no model calls."""
import http.client,json,pathlib,secrets,sys,tempfile,threading,time,uuid
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'));sys.path.insert(0,str(ROOT/'deploy'))
from remote_gateway import Workspace,Budget,Server
from geo_audit import AuditManager
from connection_diagnostics import publish
class API:
 def call(self,service,path,body=None):
  if (service,path)!=('geo','state'):raise AssertionError('Model calls forbidden in this validation')
  return {'runner':{},'busy':False,'runs':[]}
def main():
 results=[]
 with tempfile.TemporaryDirectory() as tmp:
  p=pathlib.Path(tmp);password=secrets.token_urlsafe(24);w=Workspace(password,'public.example',Budget(p/'unused-budget',0),API());manager=AuditManager(w,p/'audits/index.sqlite3');w.auditor=manager
  server=Server(('127.0.0.1',0),w);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();token=w.login(password,'local-validation')['token']
  def request(method,path,body=None):
   c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10);h={'Host':'public.example','Origin':'https://saml1nhchen-ops.github.io','Authorization':'Bearer '+token}
   if body is not None:h['Content-Type']='application/json'
   c.request(method,path,None if body is None else json.dumps(body),h);r=c.getresponse();data=json.loads(r.read());c.close();assert r.status in (200,202),(r.status,data);return data
  def done(ident):
   deadline=time.monotonic()+90
   while time.monotonic()<deadline:
    a=request('GET','/api/geo/audit?id='+ident)
    if a['status'] not in ('running','queued') and w.audit_active is None:return a
    time.sleep(.2)
   raise AssertionError('Bounded audit did not finish')
  try:
   for url in ('https://cremocompany.com/','https://example.com/'):
    a=request('POST','/api/geo/audit',{'website':url,'market':'US','request_id':str(uuid.uuid4())});a=done(a['id']);c=a['candidates'];name=(c['brand'] or {}).get('name','')
    confirmed={'brand':{'name':name,'aliases':[name] if name else []},'products':[{'name':v['name'],'aliases':v.get('aliases') or [v['name']],'source_candidate_id':v['id']} for v in c['products']],'competitors':[{'name':v['name'],'aliases':v.get('aliases') or [v['name']],'source_candidate_id':v['id']} for v in c['competitors']],'context':''}
    request('POST','/api/geo/audit-confirm',{'id':a['id'],'confirmed':confirmed});a=done(a['id']);export=request('GET','/api/geo/audit-export?id='+a['id']);assert export==a and a['report'] and a['usage']['model_calls']==0;assert a['usage']['http_requests']<=10 and a['usage']['resources_requested']<=6 and a['usage']['bytes_received']<=4*1024*1024;assert not (p/'unused-budget').exists();results.append(a)
  finally:server.shutdown();server.server_close();thread.join();manager.pool.shutdown(wait=True)
 report={'schema':1,'read_only':True,'model_calls':0,'validation':'real HTTP gateway + pinned public fetch + Protego + Trafilatura + confirmed export','audits':results}
 pathlib.Path('connection-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print('Validation completed:',[(a['website']['requested_url'],a['access'].get('outcome'),a['access'].get('http_status'),a['report']['summary']) for a in results]);print('Report:',publish(report))
if __name__=='__main__':main()
