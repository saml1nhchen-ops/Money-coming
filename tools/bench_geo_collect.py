"""Opt-in real provider benchmark; prints timing and token totals, never credentials or answers."""
from collections import Counter
import argparse, concurrent.futures, pathlib, statistics, tempfile, time, uuid
from unittest.mock import patch
from repo_env import load_repo_env
load_repo_env()
import ai_api
import geo_flow


def usage_totals(samples):
 totals={'input':0,'output':0,'reasoning':0}
 for sample in samples:
  usage=sample.get('usage') or {}
  totals['input']+=usage.get('input_tokens',usage.get('prompt_tokens',usage.get('promptTokenCount',0))) or 0
  totals['output']+=usage.get('output_tokens',usage.get('completion_tokens',usage.get('candidatesTokenCount',0))) or 0
  details=usage.get('output_tokens_details') or usage.get('completion_tokens_details') or {}
  totals['reasoning']+=details.get('reasoning_tokens',usage.get('thoughtsTokenCount',0)) or 0
 return totals


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--questions',type=int,default=3)
 parser.add_argument('--prompts-file',type=pathlib.Path,help='UTF-8 file with one question per nonblank line; overrides --questions')
 parser.add_argument('--market',choices=('CN','US'),default='US')
 parser.add_argument('--china-families',action='store_true',help='Benchmark the seven China families with route pools')
 parser.add_argument('--providers',nargs='+',help='Registry provider IDs; uses configured routes')
 args=parser.parse_args()
 if args.china_families:args.providers=['hunyuan','deepseek','kimi','zhipu','minimax','qwen','doubao'];args.market='CN'
 if not args.providers:parser.error('Use --providers or --china-families')
 if not 1<=args.questions<=300:parser.error('questions must be 1–300')
 if args.prompts_file:
  try:questions=[line.strip() for line in args.prompts_file.read_text(encoding='utf-8').splitlines() if line.strip()]
  except (OSError,UnicodeError):parser.error('Cannot read prompts file as UTF-8')
  if not 1<=len(questions)<=300 or any(len(q)>4000 for q in questions):parser.error('Use 1–300 questions, each under 4000 characters')
 else:questions=[f'Name three products for everyday use in scenario {n+1}. Answer briefly.' for n in range(args.questions)]
 configs={pid:ai_api.resolved(ai_api.provider(pid)) for pid in args.providers}
 if any(c is None for c in configs.values()):parser.error('All selected providers must be configured')
 providers=['direct:'+pid for pid in args.providers]
 cfg={'market':args.market,'website':'https://example.com','brand_aliases':['Example'],'skus':[],'competitors':[], 'repeats':1,'providers':providers,'configuration':{'direct:'+pid:{k:v for k,v in c.items() if k!='key'} for pid,c in configs.items()}}
 bank=[{'text':question} for question in questions]
 job={'id':str(uuid.uuid4()),'config':cfg,'prompts':bank,'samples':[],'calls':[],'planned_max_calls':len(providers)*len(bank)}
 with tempfile.TemporaryDirectory(prefix='geo-bench-') as tmp,concurrent.futures.ThreadPoolExecutor(max_workers=ai_api.env_int('SIGNAL_GEO_CONCURRENCY',sum(sum(r['concurrency'] for r in ai_api.registry.route_pool(ai_api.provider(pid))) or 4 for pid in args.providers),1,4096)) as pool:
  root=pathlib.Path(tmp);(root/'runs').mkdir();(root/'flows'/job['id']).mkdir(parents=True)
  def direct_bridge(path,body=None):
   if path=='run':return ai_api.start_run(body,pool)
   run=ai_api.get_run(path.split('id=',1)[1])
   return run
  with patch.object(geo_flow,'direct_bridge',direct_bridge),patch.object(geo_flow,'DATA',root/'flows'),patch.object(ai_api,'results_dir',return_value=root/'runs'):
   started=time.monotonic();geo_flow.collect(job);elapsed=time.monotonic()-started
  for pid in providers:
   rows=[s for s in job['samples'] if s['provider']==pid];times=[s['latency_ms']/1000 for s in rows]
   tokens=usage_totals(rows)
   if times:print(f'{pid}: success={sum(s["status"]=="complete" for s in rows)} input_tokens={tokens["input"]} output_tokens={tokens["output"]} reasoning_tokens={tokens["reasoning"]} calls={len(rows)} complete={sum(s["status"]=="complete" for s in rows)} median={statistics.median(times):.2f}s max={max(times):.2f}s')
  samples=job['samples'];attempts=[a for s in samples for a in s.get('attempts',[])]
  split=Counter((s.get('route_platform','unknown'),s.get('route_model','unknown')) for s in samples if s['status']=='complete')
  for (platform,model),count in sorted(split.items()):print(f'{platform}/{model}: complete={count}')
  tokens=usage_totals(samples)
  print(f'total: input_tokens={tokens["input"]} output_tokens={tokens["output"]} reasoning_tokens={tokens["reasoning"]} calls={len(job["calls"])} wall={elapsed:.2f}s completion={sum(s["status"]=="complete" for s in samples)}/{job["planned_max_calls"]} HTTP429={sum(a.get("http_status")==429 for a in attempts)} failovers={sum(s.get("failovers",0) for s in samples)}')
 return 0

if __name__=='__main__':raise SystemExit(main())
