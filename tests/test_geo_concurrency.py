import os,pathlib,sys,threading,time,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import geo_flow as f
from tests.test_geo_flow import config,sample

class ConcurrentCollection(unittest.TestCase):
 def job(self):
  cfg=config();cfg['providers']=['p','q']
  return {'id':'fixture','config':cfg,'prompts':[{'text':f'Question {n}'} for n in range(12)],'samples':[],'calls':[],'planned_max_calls':24}
 def test_caps_and_slow_provider_isolation(self):
  job=self.job();lock=threading.Lock();counts={'p':0,'q':0};peaks=counts.copy();fast=threading.Event()
  def call(j,pid,prompts,kind):
   with lock:
    counts[pid]+=1;peaks[pid]=max(peaks[pid],counts[pid]);self.assertLessEqual(sum(counts.values()),4)
   if pid=='p':self.assertTrue(fast.wait(2))
   else:fast.set()
   time.sleep(.005)
   with lock:counts[pid]-=1
   return {'id':pid+prompts[0],'samples':[sample('Brand',provider=pid)]}
  with patch.dict(os.environ,{'SIGNAL_GEO_CONCURRENCY':'4','SIGNAL_GEO_PROVIDER_CONCURRENCY':'2'}),patch.object(f,'persist'),patch.object(f,'call',side_effect=call) as calls:
   f.collect(job);self.assertEqual(calls.call_count,24);f.collect(job);self.assertEqual(calls.call_count,24)
  self.assertEqual(peaks,{'p':2,'q':2});self.assertEqual([s['provider'] for s in job['samples']],['p']*12+['q']*12)
 def test_block_stops_new_submissions(self):
  job=self.job();counts={'p':0,'q':0}
  def call(j,pid,prompts,kind):
   counts[pid]+=1
   return {'id':pid+prompts[0],'samples':[sample('',provider=pid,status='failed',error='Provider HTTP 429')] if pid=='p' else [sample('Brand',provider=pid)]}
  with patch.dict(os.environ,{'SIGNAL_GEO_PROVIDER_CONCURRENCY':'2'}),patch.object(f,'persist'),patch.object(f,'call',side_effect=call):f.collect(job)
  self.assertLessEqual(counts['p'],2);self.assertEqual(counts['q'],12);self.assertIn('p',job['blocked_models'])
 def test_plan_and_submitted_resume(self):
  job=self.job();job['planned_max_calls']=2
  job['calls']=[{'kind':'sampling','provider':'p','repeat':1,'question_index':0,'planned':1}]
  with patch.object(f,'persist'),patch.object(f,'call',return_value={'id':'x','samples':[sample('Brand')]}) as call:
   f.collect(job);self.assertEqual(call.call_count,1)
 def test_cancel_drains_inflight(self):
  job=self.job()
  def call(*args):
   f.CANCEL.add(job['id']);return {'id':'x','samples':[sample('Brand')]}
  try:
   with patch.object(f,'persist'),patch.object(f,'call',side_effect=call):
    with self.assertRaises(ValueError):f.collect(job)
   self.assertTrue(job['samples']);self.assertEqual(job['inflight'],[])
  finally:f.CANCEL.discard(job['id'])
 def test_real_call_uses_thread_local_spec_and_polls_quickly(self):
  job=self.job();job['config']['configuration']={'p':{'protocol':'chat','model':'fixture'}}
  exported={'id':'run','samples':[sample('Brand')]};states=iter([{'id':'run','status':'running'},{'id':'run','status':'finished'}])
  def bridge(path,body=None):
   if path=='run':return {'id':'run','planned':1}
   if path.startswith('export'):return exported
   return next(states)
  f.CALL_CONTEXT.spec={'question_index':7,'repeat':2}
  try:
   with patch.object(f,'bridge',side_effect=bridge),patch.object(f,'persist'),patch.object(f.shared,'save'),patch.object(f,'folder',return_value=pathlib.Path('/tmp')),patch.object(f.time,'sleep') as sleep:
    f.call(job,'p',['Question'],'sampling')
   self.assertEqual(job['calls'][0]['question_index'],7);self.assertEqual(job['calls'][0]['repeat'],2);sleep.assert_called_once_with(.25)
  finally:del f.CALL_CONTEXT.spec
