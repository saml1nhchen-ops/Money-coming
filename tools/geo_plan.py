"""Brand baseline design and one fixed model per manufacturer."""
import hashlib,math,re
import ai_api as shared

LABELS={'category':'品类推荐','benefit':'功效需求','audience':'人群与肤质','budget':'预算','scenario':'使用场景','sku':'产品属性','brand':'品牌认知','comparison':'品牌比较'}
VENDORS=[('deepseek','DeepSeek'),('qwen','阿里千问'),('glm','智谱'),('minimax','MiniMax'),('kimi','月之暗面'),('moonshot','月之暗面'),('hy3','腾讯混元'),('hy4','腾讯混元'),('hunyuan','腾讯混元'),('mimo','小米'),('gpt','OpenAI'),('claude','Anthropic'),('gemini','Google'),('llama','Meta'),('nemotron','NVIDIA')]

def vendor(p):
 model=(p.get('model') or '').lower()
 for prefix,label in VENDORS:
  if re.search(r'(?:^|[/\s-])'+re.escape(prefix),model):return label
 provider=p.get('provider','')
 if provider not in ('bai','custom','openrouter',''):return provider
 return '未识别:'+model

def blueprint(count):
 # Allocate 70/15/15 with largest remainders, then interleave for even batches.
 weights={'discovery':.70,'brand':.15,'comparison':.15}
 totals={k:math.floor(count*w) for k,w in weights.items()}
 for k in sorted(weights,key=lambda k:count*weights[k]-totals[k],reverse=True)[:count-sum(totals.values())]:totals[k]+=1
 used={k:0 for k in totals};rows=[];dims=list(LABELS)[:6]
 for i in range(count):
  family=max((k for k in totals if used[k]<totals[k]),key=lambda k:(i+1)*totals[k]/count-used[k])
  dimension=dims[used[family]%6] if family=='discovery' else family;used[family]+=1
  rows.append({'index':i,'family':family,'dimension':dimension})
 return [rows[i:i+10] for i in range(0,count,10)]

def fingerprint(prompts):
 return hashlib.sha256('\n'.join(p['text'] for p in prompts).encode()).hexdigest()

def question_key(text):return re.sub(r'[^\w]','',shared.normalize(text))

def question_family(text,cfg):
 named=sum(bool(shared.mention(text,e['aliases'])) for e in [{'aliases':cfg['brand_aliases']},*cfg.get('competitors',[])])
 if named>=2 or named and re.search(r'\bvs\b|versus|compar|alternative|相比|对比|比较|替代',text,re.I):return 'comparison'
 if named or any(shared.mention(text,k['aliases']) for k in cfg.get('skus',[])):return 'brand'
 return 'discovery'

def plan(cfg,manual=False):
 generation=0 if manual else len(blueprint(cfg['count']))
 answers=0 if cfg.get('generate_only') else cfg['count']*len(cfg['providers'])*cfg['repeats']
 return {'questions':cfg['count'],'manufacturers':len(cfg['providers']),'repeats':cfg['repeats'],'generation_calls':generation,'answer_calls':answers,'maximum_calls':generation+(0 if cfg.get('generate_only') else answers),'generation_batches':generation,'answer_batches':math.ceil(answers/64),'batch_limit':64,'families':{'discovery':sum(x['family']=='discovery' for b in blueprint(cfg['count']) for x in b),'brand':sum(x['family']=='brand' for b in blueprint(cfg['count']) for x in b),'comparison':sum(x['family']=='comparison' for b in blueprint(cfg['count']) for x in b)},'estimated_input_tokens':generation*2000+answers*500,'estimated_output_tokens':generation*2000+answers*1500,'cost_note':'Token 数为规划假设；不含额外思考与搜索，不是账单或固定报价'}
