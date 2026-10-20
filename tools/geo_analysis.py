"""Deterministic, evidence-based mentions, explicit list positions and citations.

No model judging costs. Unnumbered mention order is never a recommendation rank.
"""
import re, urllib.parse
import ai_api as shared
import geo_plan

def host(url):
 try:
  u=urllib.parse.urlsplit(url)
  return (u.hostname or '').lower().removeprefix('www.') if u.scheme in ('http','https') and not u.username and not u.password else ''
 except ValueError:return ''

def owned(domain,domains):
 return any(domain==d or domain.endswith('.'+d) for d in domains if d)

def entities(config):
 return [{'name':config['brand_aliases'][0],'aliases':config['brand_aliases'],'domains':[host(config['website'])],'own':True}]+[{**c,'own':False} for c in config.get('competitors',[])]

def positions(text,items):
 # Positions are only extracted from explicit numbered recommendation headings.
 # A brand appearing later in explanatory text does not inherit the item's rank.
 result={}
 for line in text.splitlines():
  m=re.match(r'^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:[（(])?(\d{1,2})(?:[.、)）:]|\s*[-–]\s)\s*(.+)',line)
  if not m:continue
  n=int(m[1]);lead=m[2].strip().replace('**','')
  if not 1<=n<=50:continue
  lead=re.split(r'[:：]|\s[—–]\s|[。!?！？]',lead,maxsplit=1)[0][:180]
  # Discard prose lists (e.g. "1. Avoid Brand") rather than claiming a rank.
  if re.search(r'不推荐|避免|不适合|avoid\b|not recommend|do not|don.t buy',lead,re.I):continue
  for e in items:
   if shared.mention(lead,e['aliases']) and e['name'] not in result:result[e['name']]={'position':n,'evidence':line.strip(),'basis':'explicit_numbered_item'}
 return result

def sample_analysis(s,config):
 items=entities(config);answer=s.get('answer','');narrative=re.sub(r'https?://[^\s<>\]\)"\u3000]+','',answer);rank=positions(narrative,items);sku_ranks=positions(narrative,config.get('skus',[]))
 mentions=[{'name':e['name'],'own':e['own'],'alias':shared.mention(narrative,e['aliases']),'prompted':bool(shared.mention(s['prompt'],e['aliases'])),'rank':rank.get(e['name'])} for e in items]
 eligible=s['status']=='complete' and not any(m['prompted'] for m in mentions) and not any(shared.mention(s['prompt'],k['aliases']) for k in config.get('skus',[]))
 citations=[];seen=set()
 for field,kind in [('citations','citation'),('retrieved_sources','retrieved_source')]:
  for c in s.get(field,[]):
   url=c.get('url','');domain=host(url)
   if not domain or (url,kind) in seen:continue
   seen.add((url,kind));entity=next((e for e in items if owned(domain,e.get('domains',[]))),None)
   citations.append({'url':url,'domain':domain,'title':str(c.get('title','')),'kind':kind,'owner':entity['name'] if entity else '其他来源','own':bool(entity and entity['own'])})
 # Plain links are retained separately; they are not provider-confirmed citations.
 for url in re.findall(r'https?://[^\s<>\]\)"\u3000]+',answer):
  url=url.rstrip('.,;，。；');domain=host(url)
  if domain and not any(c['url']==url for c in citations):citations.append({'url':url,'domain':domain,'title':'','kind':'answer_link','owner':'未分类','own':False})
 own_hit=bool(mentions[0]['alias']) or any(c['kind']=='citation' and c['own'] for c in citations)
 competitors_hit=[e['name'] for e,m in zip(items,mentions) if not e['own'] and (m['alias'] or any(c['kind']=='citation' and c['owner']==e['name'] for c in citations))]
 return {'eligible':eligible,'family':geo_plan.question_family(s['prompt'],config),'entities':mentions,'citations':citations,'competitor_gap':eligible and not own_hit and bool(competitors_hit),'winning_competitors':competitors_hit,'skus':[{'name':k['name'],'alias':shared.mention(narrative,k['aliases']),'prompted':bool(shared.mention(s['prompt'],k['aliases'])),'rank':sku_ranks.get(k['name'])} for k in config.get('skus',[])]}

def summarize(rows,config,family='discovery'):
 summaries=[]
 for pid in config['providers']:
  allrows=[s for s in rows if s['provider']==pid and s['analysis']['family']==family];ok=[s for s in allrows if s['status']=='complete' and (s['analysis']['eligible'] if family=='discovery' else True)];brands=[]
  for e in entities(config):
   hits=[s for s in ok if next(m for m in s['analysis']['entities'] if m['name']==e['name'])['alias']]
   ranked=[next(m for m in s['analysis']['entities'] if m['name']==e['name'])['rank']['position'] for s in ok if next(m for m in s['analysis']['entities'] if m['name']==e['name'])['rank']]
   brands.append({'name':e['name'],'own':e['own'],'mentions':len(hits),'denominator':len(ok),'score':round(100*len(hits)/len(ok),1) if ok else None,'average_rank':round(sum(ranked)/len(ranked),2) if ranked else None,'ranked_samples':len(ranked),'top3':sum(n<=3 for n in ranked),'citation_answers':sum(any(c['owner']==e['name'] and c['kind']=='citation' for c in s['analysis']['citations']) for s in ok)})
  skus=[]
  for k in config.get('skus',[]):
   hits=sum(bool(next(v for v in s['analysis']['skus'] if v['name']==k['name'])['alias']) for s in ok)
   ranked=[next(v for v in s['analysis']['skus'] if v['name']==k['name'])['rank']['position'] for s in ok if next(v for v in s['analysis']['skus'] if v['name']==k['name'])['rank']]
   skus.append({'name':k['name'],'mentions':hits,'denominator':len(ok),'score':round(100*hits/len(ok),1) if ok else None,'average_rank':round(sum(ranked)/len(ranked),2) if ranked else None,'ranked_samples':len(ranked)})
  summaries.append({'provider':pid,'attempted':len(allrows),'complete':sum(s['status']=='complete' for s in allrows),'eligible':len(ok),'brands':brands,'skus':skus})
 return summaries

def analyze(samples,config,prompts=None):
 rows=[{**s,'analysis':sample_analysis(s,config)} for s in samples];summaries=summarize(rows,config)
 domains={}
 for s in rows:
  for c in s['analysis']['citations']:
   key=(c['domain'],c['kind']);d=domains.setdefault(key,{'domain':key[0],'kind':key[1],'owner':c['owner'],'urls':set(),'sample_ids':set()});d['urls'].add(c['url']);d['sample_ids'].add(s.get('id',str(rows.index(s))))
 bank=prompts or [];families={k:[p for p in bank if geo_plan.question_family(p['text'],config)==k] for k in ('discovery','brand','comparison')}
 groups={k:{'question_count':len(v),'models':summarize(rows,config,k)} for k,v in families.items()}
 dimensions=[{'dimension':d,'label':geo_plan.LABELS.get(d,d),'questions':sum(p.get('dimension')==d for p in bank)} for d in sorted({p.get('dimension','manual') for p in bank})]
 stability=[]
 for pid in config['providers']:
  for i,p in enumerate(bank):
   selected=[s for s in rows if s['provider']==pid and s.get('question_index')==i and s['analysis']['eligible']]
   hits=[bool(s['analysis']['entities'][0]['alias']) for s in selected]
   stability.append({'provider':pid,'question_index':i,'question':p['text'],'family':geo_plan.question_family(p['text'],config),'valid_repeats':len(hits),'planned_repeats':config.get('repeats',1),'mentions':sum(hits),'mention_rate':round(100*sum(hits)/len(hits),1) if hits else None,'varied':len(set(hits))>1})
 return {'samples':rows,'models':summaries,'groups':groups,'dimensions':dimensions,'stability':stability,'coverage':{'planned_answers':len(bank)*len(config['providers'])*config.get('repeats',1),'attempted':len(rows),'complete':sum(s['status']=='complete' for s in rows),'questions':len(bank)},'gaps':[{'sample_id':s.get('id'),'provider':s['provider'],'prompt':s['prompt'],'competitors':s['analysis']['winning_competitors']} for s in rows if s['analysis']['competitor_gap']],'sources':[{**d,'urls':sorted(d['urls']),'sample_ids':sorted(d['sample_ids']),'answer_count':len(d['sample_ids'])} for d in domains.values()],'methodology':{'version':'geo-evidence-v2','score':'discovery: complete answers without any tracked name; brand/comparison metrics reported separately','rank':'explicit numbered item position, not inferred sentiment or market-wide rank','citations':'provider citations, retrieved sources, and answer links reported separately','demand':'model-generated candidate questions; no user frequency data','manufacturer':'One selected model per manufacturer; no claim to measure all models or consumer apps'}}
