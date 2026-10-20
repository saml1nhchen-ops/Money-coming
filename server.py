#!/usr/bin/env python3
"""Signal GEO single-user loopback development server. No external dependencies."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import sqlite3, json, uuid, hashlib, datetime, urllib.parse, re, os
ROOT=Path(__file__).resolve().parent
DB=ROOT/'work'/'signal.db'
DB.parent.mkdir(exist_ok=True)
def connect():
 c=sqlite3.connect(DB,timeout=20);c.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)');return c
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def require(x,msg):
 if not x:raise ValueError(msg)
def obj(s,key,ident,w):
 x=next((x for x in s[key] if x['id']==ident and x['workspace']==w),None)
 require(x is not None,'Object not found in current workspace');return x
def validate_answer(a):
 for k in ['prompt_text','topic','market','locale','platform','collected_at','status']:
  require(isinstance(a.get(k),str) and a[k].strip(),k+' is required')
 require(a['market'] in ['us','cn'],'Unsupported market')
 require(a['status'] in ['success','failed'],'Invalid status')
 require(a['status']=='failed' or isinstance(a.get('raw_answer'),str) and a['raw_answer'].strip(),'raw_answer required')
 dt=datetime.datetime.fromisoformat(a['collected_at'].replace('Z','+00:00'));require(dt.tzinfo is not None,'Timestamp timezone required')
 require(isinstance(a.get('citations',[]),list),'citations must be an array')
 for cit in a.get('citations',[]):
  u=urllib.parse.urlparse(cit.get('url',''));require(u.scheme in ['http','https'] and u.hostname,'Unsafe citation URL')
def action(s,w,act,p):
 work=next((x for x in s['workspaces'] if x['id']==w),None);require(work,'Workspace not found')
 base={'id':str(uuid.uuid4()),'workspace':w,'created_at':stamp()}
 if act in ['project','fact','prompt','draft','experiment']:
  for k in {'project':['title','goal','stop','market'],'fact':['title','text','source','market'],'prompt':['text','topic','market','locale'],'draft':['title','target','market'],'experiment':['title','hypothesis','stop','market']}[act]:require(isinstance(p.get(k),str) and p[k].strip(),k+' is required')
  require(p['market'] in ['us','cn'],'Unsupported market')
 if act=='import':
  require(not work['demo'],'Import into a real workspace only');require(isinstance(p.get('rows'),list) and len(p['rows'])<=5000,'Max 5000 rows')
  for a in p['rows']:validate_answer(a)
  existing={a.get('fingerprint') for a in s['answers'] if a['workspace']==w}
  for a in p['rows']:
   key=digest({k:a.get(k) for k in ['prompt_text','topic','market','locale','platform','collected_at','status','raw_answer','citations','citation_supported','collection_region']})
   if key in existing:continue
   pr=next((x for x in s['prompts'] if x['workspace']==w and x['text']==a['prompt_text'] and x['market']==a['market'] and x['locale']==a['locale']),None)
   if not pr:
    pr={**base,'id':str(uuid.uuid4()),'text':a['prompt_text'],'topic':a['topic'],'market':a['market'],'locale':a['locale'],'version':1,'history':[],'active':True,'type':'discovery'};s['prompts'].append(pr)
   allowed={k:a.get(k) for k in ['external_id','prompt_text','topic','market','locale','platform','collected_at','status','raw_answer','citations','citation_supported','collection_region']}
   s['answers'].append({**allowed,**base,'id':str(uuid.uuid4()),'prompt_id':pr['id'],'prompt_version':pr['version'],'source_type':'manual_import','fingerprint':key});existing.add(key)
 elif act=='prompt':s['prompts'].append({**p,**base,'version':1,'history':[],'active':True})
 elif act=='edit_prompt':
  x=obj(s,'prompts',p['id'],w);require(p.get('text','').strip(),'Prompt text required');x['history'].append({'version':x['version'],'text':x['text']});x['text']=p['text'];x['version']+=1
 elif act=='toggle_prompt':
  x=obj(s,'prompts',p['id'],w);x['active']=not x['active']
 elif act=='project':
  if p.get('answer_id'):obj(s,'answers',p['answer_id'],w)
  s['projects'].insert(0,{**p,**base,'status':'triage'})
 elif act=='fact':s['facts'].insert(0,{**p,**base,'status':'needs_review','version':1})
 elif act=='approve_fact':
  f=obj(s,'facts',p['id'],w);f['status']='approved';f['approved_at']=stamp()
 elif act=='draft':
  fs=[f for f in s['facts'] if f['workspace']==w and f['status']=='approved' and f['market']==p['market']];require(fs,'Approve facts for this market first')
  if p.get('project'):obj(s,'projects',p['project'],w)
  s['artifacts'].insert(0,{**p,**base,'body':'\n\n'.join(f['text']+' ['+f['id'][:6]+']' for f in fs),'facts':[f['id'] for f in fs],'version':1,'status':'draft','history':[]})
 elif act=='save_artifact':
  a=obj(s,'artifacts',p['id'],w);require(p.get('body','').strip() and p.get('target','').strip(),'Body and target are required')
  a['history'].append({'version':a['version'],'body':a['body'],'target':a['target'],'status':a['status'],'approval':a.get('approval')});a.update(body=p['body'],target=p['target'],version=a['version']+1,status='draft',approval=None)
 elif act=='artifact_status':
  a=obj(s,'artifacts',p['id'],w);new=p['status'];require((a['status'],new) in [('draft','in_review'),('in_review','approved'),('in_review','draft')],'Invalid transition')
  if new in ['in_review','approved']:
   fs=[obj(s,'facts',i,w) for i in a['facts']];require(all(f['status']=='approved' and f['market']==a['market'] for f in fs),'Fact approval or scope conflict')
   approved={f['text']+' ['+f['id'][:6]+']' for f in fs};require(all(b.strip() in approved for b in a['body'].split('\n\n') if b.strip()),'Draft contains unbound changes. Add and approve the exact supporting fact before submitting.')
  a['status']=new
  if new=='approved':a['approval']={'version':a['version'],'hash':digest([a['body'],a['target'],a['facts']]),'at':stamp(),'actor':'local-user'}
 elif act=='receipt':
  a=obj(s,'artifacts',p['id'],w);require(a['status']=='approved' and a.get('approval',{}).get('hash')==digest([a['body'],a['target'],a['facts']]),'Current version approval required')
  for k in ['url','date','evidence']:require(p.get(k,'').strip(),k+' required')
  require(urllib.parse.urlparse(p['url']).scheme in ['http','https'],'HTTP(S) URL required');a.update(status='applied',receipt={**p,'at':stamp(),'verification':'unverified'})
 elif act=='experiment':
  ids=p.get('baseline',[])
  for i in ids:
   a=obj(s,'answers',i,w);require(a['market']==p['market'] and a['status']=='success','Invalid baseline')
  s['experiments'].insert(0,{**p,**base,'status':'planned','baseline':ids,'dataset_version':s['revision']})
 elif act=='brand':
  require(not work['demo'],'Demo brand configuration is fixed');require(p.get('brand','').strip(),'Brand required');require(isinstance(p.get('aliases'),list) and all(isinstance(a,str) and a.strip() for a in p['aliases']),'Nonempty aliases required')
  require(isinstance(p.get('domains'),list),'Domains must be a list')
  for d in p['domains']:require(re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,63}',d),'Invalid domain')
  work.setdefault('history',[]).append({k:work[k] for k in ['brand','aliases','domains']});work.update(brand=p['brand'],name=p['brand'],aliases=list(dict.fromkeys([p['brand']]+p['aliases'])),domains=p['domains'])
 else:raise ValueError('Unknown action')
 s['audit'].insert(0,{**base,'action':act,'object':str(p.get('id') or p.get('title') or p.get('text') or ''),'actor':'local-user'})
 s['revision']+=1
 return s
class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw):super().__init__(*a,directory=str(ROOT/'dist'),**kw)
 def reply(self,code,d):
  b=json.dumps(d,ensure_ascii=False).encode();self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(b)
 def do_GET(self):
  if self.path=='/api/bootstrap':
   with connect() as c:r=c.execute('SELECT body FROM state WHERE id=1').fetchone()
   self.reply(200,{**json.loads(r[0]),'seeded':True} if r else {'workspaces':[],'seeded':False});return
  super().do_GET()
 def do_POST(self):
  host=self.headers.get('Host','');origin=self.headers.get('Origin')
  if host not in ['127.0.0.1:8765','localhost:8765'] or origin and origin not in ['http://127.0.0.1:8765','http://localhost:8765']:
   self.reply(403,{'error':'Loopback same-origin requests only'});return
  c=None
  try:
   length=int(self.headers.get('Content-Length',0));require(0<length<=8*1024*1024,'Body exceeds 8 MB or is empty');p=json.loads(self.rfile.read(length));c=connect();c.execute('BEGIN IMMEDIATE');r=c.execute('SELECT body FROM state WHERE id=1').fetchone()
   if self.path=='/api/seed':
    require(r is None,'Already initialized');c.execute('INSERT INTO state VALUES (1,?)',(json.dumps(p,ensure_ascii=False),));c.commit();self.reply(200,{'ok':True});return
   require(self.path=='/api/action' and r,'Unknown endpoint or uninitialized database');s=json.loads(r[0])
   if p.get('revision')!=s['revision']:
    c.rollback();self.reply(409,{'error':'Another tab changed the data. Reload to get the latest revision; your current input remains in this form.'});return
   s=action(s,p['workspace'],p['action'],p['payload']);c.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(s,ensure_ascii=False),));c.commit();self.reply(200,s)
  except (ValueError,KeyError,TypeError) as e:
   if c:c.rollback()
   self.reply(400,{'error':str(e)})
  except Exception:
   if c:c.rollback()
   self.reply(500,{'error':'Storage error; input has been preserved. Check local server logs.'})
  finally:
   if c:c.close()
if __name__=='__main__':
 print('Signal GEO local: http://127.0.0.1:8765',flush=True)
 ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
