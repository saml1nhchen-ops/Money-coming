"""Isolated upstream runtimes; never installs into the user's global Python."""
import concurrent.futures,json,os,pathlib,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
def install(key):
 dest=pathlib.Path(os.environ.get('SIGNAL_SHORT_RUNTIMES',str(ROOT/'runtime/venvs')))/key; dest.parent.mkdir(parents=True,exist_ok=True)
 py=dest/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
 log=ROOT/'runtime'/('install-'+key+'.log')
 with log.open('w',encoding='utf-8') as f:
  if not py.exists():subprocess.run([sys.executable,'-m','venv',str(dest)],stdout=f,stderr=f,check=True)
  extra=['-r',str(ROOT/'runtime/upstreams'/key/'requirements.txt')] if key in ['claude-seo','claude-blog'] else ['-e',str(ROOT/'runtime/upstreams'/key)]
  r=subprocess.run([str(py),'-m','pip','install',*extra],stdout=f,stderr=f)
 print(key+': '+('installed' if r.returncode==0 else 'FAILED (see '+str(log)+')'),flush=True)
 return {'id':key,'installed':r.returncode==0,'python':str(py)}
if __name__=='__main__':
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as p:
  results=list(p.map(install,sys.argv[1:] or ['potato','auriti','beyondseo','crawl4ai','voyage-agent','claude-seo','claude-blog']))
 previous=json.loads((ROOT/'runtime/installed.json').read_text('utf-8')) if (ROOT/'runtime/installed.json').exists() else []
 results=list({r['id']:r for r in previous+results}.values())
 (ROOT/'runtime/installed.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
 if not all(r['installed'] for r in results):raise SystemExit(1)
