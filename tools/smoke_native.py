"""Real keyless adapter smoke runs; never calls a paid model or consumer account."""
import concurrent.futures,json,uuid
from native_service import run_job,job_result,RUNTIME,save_json
cases=[
 {'tool':'auriti','operation':'audit','url':'https://example.com'},
 {'tool':'beyondseo','operation':'crawl','url':'https://example.com','max_pages':1},
 {'tool':'potato','operation':'validate'},
 {'tool':'potato','operation':'mock'},
 {'tool':'promptfoo','operation':'offline-eval','samples':[{'answer':'Aster Home is a synthetic test answer.','contains':'Aster Home'}]},
 {'tool':'claude-blog','operation':'analyze-blog','context':'# Saved test article\n\nThis is a short synthetic fixture for native content analysis, not a customer report.'},
 {'tool':'claude-seo','operation':'fetch-page','url':'https://example.com'},
 {'tool':'crawl4ai','operation':'crawl-http','url':'https://example.com'},
]
def go(p):
 id=str(uuid.uuid4());run_job(id,p);r=job_result(id);print(p['tool']+' '+p['operation']+': '+r['status']+' '+str(r.get('error','')),flush=True)
 if r['status']!='succeeded':print(r['stderr'][-1800:],flush=True)
 return {k:r.get(k) for k in ['id','tool','operation','status','error','commit']}
if __name__=='__main__':
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(go,cases))
 save_json(RUNTIME/'smoke-results.json',results)
 if any(r['status']!='succeeded' for r in results):raise SystemExit(1)
