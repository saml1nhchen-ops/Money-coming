import json,pathlib,hashlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
NAMES={'niubigeo':'NiubiGEO','potato':'Potato','openseo':'OpenSEO','elmo':'Elmo','yao':'Yao GEO','crawl4ai':'Crawl4AI','claude-seo':'Claude SEO','auriti':'Auriti GEO Optimizer','onvoyage':'Onvoyage GTM','seranking':'SE Ranking SEO','marketing-skills':'Marketing Skills','aaron':'Aaron Marketing','claude-blog':'Claude Blog','notfair':'NotFair','promptfoo':'Promptfoo','beyondseo':'BeyondSEO','oneglanse':'OneGlanse','voyage-agent':'Voyage GEO Agent'}
NATIVE={'auriti':['audit'],'beyondseo':['crawl'],'crawl4ai':['crawl-http'],'niubigeo':['audit'],'potato':['validate','estimate','mock','run'],'promptfoo':['offline-eval'],'yao':['analyze-deepseek'],'claude-blog':['analyze-blog'],'claude-seo':['fetch-page'],'voyage-agent':['run']}
APPS={'openseo','elmo','oneglanse'}
items=[]
for r in json.loads((ROOT/'tools/upstreams.lock.json').read_text('utf-8')):
 base=ROOT/'runtime/upstreams'/r['id'];lic=[];skills=[]
 for f in r.get('license_files',[]):lic.append({'path':f,'text':(base/f).read_text('utf-8',errors='replace')})
 for f in r.get('skills',[]):
  p=base/f
  text=p.read_text('utf-8',errors='replace')
  # Retain complete upstream skill documents and exact source hashes, not summaries.
  skills.append({'path':f,'name':p.parent.name,'text':text,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
 items.append({**r,'name':NAMES[r['id']],'licenses':lic,'skill_documents':skills,'operations':NATIVE.get(r['id'],[]),'requires_service':r['id'] in APPS,'mcp_supported':r['id'] in ['openseo','elmo','seranking'],'integration_boundary':'Native CLI adapter + original skills' if r['id'] in NATIVE else 'External application / MCP + original skills' if r['id'] in APPS else 'Original skill workflows (model required; no agent tools)'})
(ROOT/'dist/upstreams.json').write_text(json.dumps(items,ensure_ascii=False),encoding='utf-8')
print(f'Built catalog: {len(items)} repositories, {sum(len(x["skill_documents"]) for x in items)} original skill documents')
