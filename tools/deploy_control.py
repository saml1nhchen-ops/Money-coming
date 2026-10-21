"""Private loopback deployment observations. Never signals or submits model work.

CLI: probe; wait-idle --timeout SECONDS; health. The deployment owner must probe
before sending SIGUSR1 to the exact remote_service process, then wait-idle. It
owns signal release as well; this helper never locates or signals a process.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

class ControlError(Exception):
 def __init__(self,code):self.code=code

class Control:
 def __init__(self,environ=os.environ):
  host=environ.get('SIGNAL_PUBLIC_HOST') or environ.get('RENDER_EXTERNAL_HOSTNAME','')
  password=environ.get('SIGNAL_WORKSPACE_PASSWORD','');port=environ.get('PORT','8080')
  parts=host.split(':')
  if len(parts)>2 or len(parts)==2 and (not parts[1].isdigit() or not 1<=int(parts[1])<=65535) or len(parts[0])>253 or any(not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?',label) for label in parts[0].split('.')) or len(password)<16 or not re.fullmatch(r'[0-9]{1,5}',port) or not 1<=int(port)<=65535:raise ControlError('invalid_configuration')
  self.host=host.lower();self.base='http://127.0.0.1:'+port;self.password=password;self.token=None;self.deadline=None
  # This bypass applies solely to the hardcoded loopback control channel. It
  # does not affect website/model request proxy, networking, or CA settings.
  self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 def request(self,path,body=None):
  headers={'Host':self.host,'Content-Type':'application/json'}
  if self.token:headers['Authorization']='Bearer '+self.token
  req=urllib.request.Request(self.base+path,None if body is None else json.dumps(body).encode(),headers)
  timeout=10
  if self.deadline is not None:
   remaining=self.deadline-time.monotonic()
   if remaining<=0:raise ControlError('idle_timeout')
   timeout=min(timeout,remaining)
  try:
   with self.opener.open(req,timeout=timeout) as response:
    raw=response.read(8*1024*1024+1)
    if len(raw)>8*1024*1024:raise ControlError('invalid_response')
    result=json.loads(raw)
    if not isinstance(result,dict):raise ControlError('invalid_response')
    return result
  except urllib.error.HTTPError as error:
   code={401:'authentication_failed',403:'access_forbidden',404:'deployment_gate_unavailable',429:'rate_limited'}.get(error.code,'control_unavailable' if error.code>=500 else 'invalid_response')
   raise ControlError(code) from None
  except OSError:raise ControlError('control_unavailable') from None
  except ValueError:raise ControlError('invalid_response') from None
 def login(self):
  if self.token:return
  result=self.request('/api/workspace/login',{'password':self.password})
  if not isinstance(result.get('token'),str) or not result['token']:raise ControlError('authentication_failed')
  self.token=result['token'];self.password=None
 def observe(self):
  self.login();s=self.request('/api/geo/state');r=s.get('remote',{})
  if not isinstance(r,dict) or r.get('deployment_gate')!='signals-v1' or type(r.get('maintenance'))!=bool or type(r.get('model_ready'))!=bool or type(s.get('busy'))!=bool:raise ControlError('deployment_gate_unavailable')
  budget=r.get('budget',{})
  if not isinstance(budget,dict) or any(type(budget.get(k))!=int or budget[k]<0 for k in ('limit','reserved','remaining')):raise ControlError('budget_unavailable')
  health=self.request('/healthz')
  if health.get('ok') is not True:raise ControlError('backend_unhealthy')
  revision=health.get('revision','unknown');version=health.get('version','unknown')
  if not isinstance(revision,str) or not re.fullmatch(r'[0-9a-f]{40}',revision):revision='unknown'
  if not isinstance(version,str) or not re.fullmatch(r'[A-Za-z0-9._+-]{1,128}',version):version='unknown'
  return {'ok':True,'revision':revision,'version':version,'host':self.host,'deployment_gate':'signals-v1','maintenance':r['maintenance'],'model_ready':r['model_ready'],'busy':s['busy']}
 def probe(self):return self.observe()
 def wait_idle(self,timeout):
  if not 0<timeout<=3600:raise ControlError('invalid_timeout')
  self.deadline=time.monotonic()+timeout
  try:
   while True:
    state=self.observe()
    if state['maintenance'] and not state['busy']:return state
    remaining=self.deadline-time.monotonic()
    if remaining<=0:raise ControlError('idle_timeout')
    time.sleep(min(.5,remaining))
  finally:self.deadline=None
 def health(self,timeout=None):
  if timeout is not None and not 0<timeout<=3600:raise ControlError('invalid_timeout')
  self.deadline=None if timeout is None else time.monotonic()+timeout
  transient={'control_unavailable','backend_unhealthy','model_not_ready','maintenance_required','backend_busy'}
  try:
   while True:
    try:
     state=self.observe()
     if not state['maintenance']:raise ControlError('maintenance_required')
     if state['busy']:raise ControlError('backend_busy')
     if not state['model_ready']:raise ControlError('model_not_ready')
     return state
    except ControlError as error:
     if error.code=='idle_timeout':raise ControlError('health_timeout') from None
     if timeout is None or error.code not in transient:raise
     remaining=self.deadline-time.monotonic()
     if remaining<=0:raise ControlError('health_timeout') from None
     time.sleep(min(.5,remaining))
  finally:self.deadline=None

def main(argv=None):
 parser=argparse.ArgumentParser(description=__doc__)
 subs=parser.add_subparsers(dest='command',required=True)
 subs.add_parser('probe');health=subs.add_parser('health');health.add_argument('--timeout',type=float);wait=subs.add_parser('wait-idle');wait.add_argument('--timeout',type=float,required=True)
 args=parser.parse_args(argv)
 try:
  control=Control()
  if args.command=='wait-idle':result=control.wait_idle(args.timeout)
  elif args.command=='health':result=control.health(args.timeout)
  else:result=control.probe()
  print(json.dumps(result,separators=(',',':')));return 0
 except ControlError as error:print(json.dumps({'ok':False,'code':error.code},separators=(',',':')));return 1
 except Exception:print('{"ok":false,"code":"control_unavailable"}');return 1
if __name__=='__main__':sys.exit(main())
