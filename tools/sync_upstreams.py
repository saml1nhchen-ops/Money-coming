"""Download real upstream repositories, preserve licenses, and lock exact commits."""
import concurrent.futures, json, os, pathlib, subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1]
REPOS={
 'niubigeo':'Albert-Weasker/niubigeo','potato':'onism1767-creator/potato',
 'openseo':'every-app/open-seo','elmo':'elmohq/elmo','yao':'yaojingang/yao-geo-skills',
 'crawl4ai':'unclecode/crawl4ai','claude-seo':'AgriciDaniel/claude-seo',
 'auriti':'Auriti-Labs/geo-optimizer-skill','onvoyage':'onvoyage-ai/gtm-engineer-skills',
 'seranking':'seranking/seo-skills','marketing-skills':'coreyhaines31/marketingskills',
 'aaron':'aaron-he-zhu/aaron-marketing-skills','claude-blog':'AgriciDaniel/claude-blog',
 'notfair':'nowork-studio/notfair-plugin','promptfoo':'promptfoo/promptfoo',
 'beyondseo':'beyondtahir/beyondseo','oneglanse':'oneglanse/oneglanse',
 'voyage-agent':'onvoyage-ai/voyage-geo-agent'}
GIT=os.environ.get('SIGNAL_GIT','git')
def git(args,cwd=None):
 r=subprocess.run([GIT,*args],cwd=cwd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=600)
 if r.returncode: raise RuntimeError(r.stderr[-1200:])
 return r.stdout.strip()
def sync(item):
 key,repo=item; dest=ROOT/'runtime'/'upstreams'/key
 try:
  locked={r['id']:r for r in json.loads((ROOT/'tools/upstreams.lock.json').read_text('utf-8'))} if (ROOT/'tools/upstreams.lock.json').exists() else {}
  if not (dest/'.git').exists():
   dest.parent.mkdir(parents=True,exist_ok=True)
   git(['clone','--depth','1','https://github.com/'+repo+'.git',str(dest)])
  pin=locked.get(key,{}).get('commit')
  head=git(['rev-parse','HEAD'],dest)
  if pin and head!=pin:
   git(['fetch','--depth','1','origin',pin],dest);git(['checkout','--detach',pin],dest);head=pin
  licenses=[str(p.relative_to(dest)).replace('\\','/') for p in dest.iterdir() if p.is_file() and p.name.lower().startswith(('license','copying','notice'))]
  skills=[str(p.relative_to(dest)).replace('\\','/') for p in dest.rglob('SKILL.md') if '.git' not in p.parts and 'node_modules' not in p.parts and '.raw' not in p.parts]
  entry={'id':key,'repository':repo,'url':'https://github.com/'+repo,'commit':head,'license_files':licenses,'skills':skills,'downloaded':True}
  print(key+': '+head[:12]+' · '+str(len(skills))+' skills',flush=True)
  return entry
 except Exception as e:
  print(key+': ERROR '+str(e),flush=True);return {'id':key,'repository':repo,'error':str(e),'downloaded':False}
if __name__=='__main__':
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(sync,REPOS.items()))
 (ROOT/'tools/upstreams.lock.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 if any(not r['downloaded'] for r in results):raise SystemExit(1)
