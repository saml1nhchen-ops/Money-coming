import concurrent.futures,json,uuid
from native_service import run_job,job_result
def go(url):
 i=str(uuid.uuid4());run_job(i,{'tool':'crawl4ai','operation':'crawl-http','url':url,'brand':'L’Oréal Paris'})
 r=job_result(i);print(json.dumps({'url':url,'id':i,'status':r['status'],'stdout':r['stdout'],'stderr':r['stderr'][-500:]},ensure_ascii=False),flush=True)
with concurrent.futures.ThreadPoolExecutor(2) as pool:list(pool.map(go,['https://www.lorealparis.com.cn/','https://www.lorealparisusa.com/']))
