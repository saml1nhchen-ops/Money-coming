"""Independent synthetic boundary checks; derived from a real local HTTP fixture job.
Injected UI variants are explicitly recorded separately from the HTTP job.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

OUT = Path(__file__).resolve().parent
RAW = Path('/tmp/geo-url-acceptance-raw')
RAW.mkdir(exist_ok=True)
checks = []


def check(name, condition, detail=None):
    checks.append({'name': name, 'pass': bool(condition), 'detail': detail})


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:8772/#/w/demo/research')
    page.wait_for_function('geoToken && geoState.runs.length > 0')
    page.evaluate("async()=>{geoMarket='US';let s=await geoFetch('state');let run=s.runs.find(r=>r.market==='US');await researchOpen(run.id)}")
    expect(page.locator('.rq-card')).to_have_count(30)
    job = page.evaluate('geoActive')
    (RAW/'http-partial-job.json').write_text(json.dumps(job, ensure_ascii=False, indent=2))
    check('HTTP fixture partial 30 prompts/33 samples', job['status']=='partial' and len(job['prompts'])==30 and len(job['samples'])==33)
    check('Selected providers retained including direct prefix', all(s['provider'] in job['config']['providers'] for s in job['samples']))
    check('Brand/comparison excluded by backend analysis', all(not s['analysis']['eligible'] for s in job['report']['samples'] if s['analysis']['family']!='discovery'))
    check('Backend complete zero mention sample exists', any(s['status']=='complete' and not s['analysis']['entities'][0]['alias'] for s in job['report']['samples']))

    # Actual authenticated HTTP endpoint checks. Token remains in browser memory.
    http = page.evaluate("""async()=>{
      let results=[];
      for(let item of [
       {name:'no auth',body:{website:'https://cremocompany.com/',market:'US'},auth:false},
       {name:'normal inspect',body:{website:'https://cremocompany.com/',market:'US'},auth:true},
       {name:'blocked scheme',body:{website:'file:///etc/passwd',market:'US'},auth:true},
       {name:'credentials URL',body:{website:'https://user:password@cremocompany.com/',market:'US'},auth:true},
       {name:'port',body:{website:'https://cremocompany.com:9000/',market:'US'},auth:true},
       {name:'fetch failure',body:{website:'https://unsupported.invalid/',market:'US'},auth:true},
       {name:'invalid market',body:{website:'https://cremocompany.com/',market:'XX'},auth:true}]) {
        let r=await fetch('/api/geo/inspect',{method:'POST',headers:{'Content-Type':'application/json',...(item.auth?{Authorization:'Bearer '+geoToken}:{})},body:JSON.stringify(item.body)});
        results.push({name:item.name,status:r.status,body:await r.json()});
      }return results;
    }""")
    (OUT/'http-inspection-results.json').write_text(json.dumps(http,ensure_ascii=False,indent=2))
    check('HTTP inspect success',http[1]['status']==200 and http[1]['body']['diagnosis']['score']==100)
    check('HTTP auth/error responses honest',http[0]['status']==401 and all(x['status']==400 and 'error' in x['body'] and 'diagnosis' not in x['body'] for x in http[2:]))

    page.locator('#question-card-0').focus()
    page.keyboard.press('Enter')
    dialog=page.get_by_role('dialog')
    expect(dialog).to_be_visible()
    check('Enter opens and focus enters',page.evaluate("document.querySelector('[role=dialog]').contains(document.activeElement)"))
    tabs=[]
    for i in range(18):
        page.keyboard.press('Tab')
        tabs.append(page.evaluate("({inside:document.querySelector('[role=dialog]').contains(document.activeElement),tag:document.activeElement.tagName,text:document.activeElement.textContent.slice(0,45)})"))
    check('Tab focus stays in dialog',all(x['inside'] for x in tabs),tabs)
    reverse=[]
    for i in range(12):
        page.keyboard.press('Shift+Tab')
        reverse.append(page.evaluate("document.querySelector('[role=dialog]').contains(document.activeElement)"))
    check('Shift Tab focus stays in closed-details dialog',all(reverse),reverse)
    dialog.locator('details').first.locator('summary').click()
    opened=[]
    for i in range(18):
        page.keyboard.press('Tab' if i%2==0 else 'Shift+Tab')
        opened.append(page.evaluate("document.querySelector('[role=dialog]').contains(document.activeElement)"))
    check('Open-details dynamic focus remains inside',all(opened),opened)
    dialog.locator('details').first.locator('summary').click()
    page.evaluate("document.querySelector('aside a').focus()")
    page.keyboard.press('Tab')
    check('External focus redirected into dialog',page.evaluate("document.querySelector('[role=dialog]').contains(document.activeElement)"))
    page.keyboard.press('Escape')
    check('Escape restores trigger',page.locator('#question-card-0').evaluate('(e)=>e===document.activeElement'))
    page.keyboard.press('Space')
    expect(dialog).to_be_visible()
    page.get_by_role('button',name='关闭问题回答').click()
    check('Space opens/close button restores',page.locator('#question-card-0').evaluate('(e)=>e===document.activeElement'))

    page.locator('#question-card-1').click()
    zero=page.get_by_role('dialog').inner_text()
    check('Complete zero shown as not mentioned', '未提及' in zero and '完整' in zero)
    page.keyboard.press('Escape')
    page.locator('#question-card-2').click()
    check('Actual HTTP 429 shown', 'HTTP 429' in page.get_by_role('dialog').inner_text())
    page.keyboard.press('Escape')
    page.locator('#question-card-3').click()
    check('Missing selected model still shown as unrun',page.locator('.rq-model').count()==2 and '未运行' in page.get_by_role('dialog').inner_text())
    page.keyboard.press('Escape')

    # UI variants deliberately injected from the HTTP-derived job: never real measurements.
    page.evaluate("""()=>{window.acceptanceOriginal=structuredClone(geoActive);clearTimeout(geoTimer);geoActive.status='running';geoActive.report=null;geoActive.samples=[];researchStep=3;render()}""")
    expect(page.locator('.rq-card')).to_have_count(30)
    check('report=null running retains full bank',page.locator('.rq-card').count()==30)
    page.locator('#question-card-0').click()
    check('Running missing samples waiting not zero',page.locator('.rq-model').count()==2 and page.get_by_role('dialog').inner_text().count('等待中')==2)
    page.keyboard.press('Escape')
    page.evaluate("()=>{geoActive.prompts=[];geoActive.stage='generating';render()}")
    check('Empty generating bank does not invent cards',page.locator('.rq-card').count()==0 and '题目正在生成' in page.locator('#question-cards').inner_text())
    page.evaluate("""()=>{
      geoActive=structuredClone(window.acceptanceOriginal);geoActive.report=null;geoActive.status='partial';
      const pid=geoActive.config.providers[0];geoActive.prompts=[{text:'Boundary <script>window.fixtureXSS=1</script>',family:'discovery'}];
      geoActive.samples=[
        {id:'boundary-1',question_index:0,provider:pid,repeat:1,status:'complete',answer:'SYNTHETIC boundary answer '.repeat(250),model_requested:'frozen-request',model_returned:'returned-test',analysis:{eligible:true,family:'discovery',entities:[{own:true,name:'Cremo',alias:'Cremo',rank:{position:2,evidence:'2. Cremo'}}],citations:[{kind:'citation',own:true,url:'https://cremocompany.com/native'},{kind:'retrieved_source',url:'https://source.example/retrieved'},{kind:'answer_link',url:'https://source.example/plain'},{kind:'answer_link',url:'javascript:alert(1)'}]}},
        {id:'boundary-2',question_index:0,provider:pid,repeat:2,status:'complete',truncated:true,answer:'<script>window.fixtureXSS=1</script>',analysis:{entities:[{own:true,alias:'Cremo'}]}},
      ];render();
    }""")
    page.locator('#question-card-0').click()
    dialog=page.get_by_role('dialog')
    text=dialog.inner_text()
    check('Repeats/truncated unknown retained','第 2 次采样' in text and '回答截断' in text and '未知' in text)
    check('Frozen/request/returned model and rank evidence',all(x in text for x in ['frozen-request','returned-test','第 2 位','2. Cremo']))
    dialog.locator('details').first.locator('summary').click()
    text=dialog.inner_text()
    check('All three citation types distinct',all(x in text for x in ['AI 返回的引用','检索来源','回答中的普通链接']))
    check('Unsafe link and text not executed',dialog.locator('a[href^="javascript:"]').count()==0 and page.evaluate('window.fixtureXSS') is None)
    page.evaluate("""()=>{let b=document.createElement('div');b.textContent='SYNTHETIC UI BOUNDARY FIXTURE · 非 Cremo 实测';b.style='position:fixed;top:0;left:0;z-index:99999;background:#ffeb92;padding:5px';document.body.append(b)}""")
    page.screenshot(path=str(OUT/'boundary-desktop.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    check('Long dialog mobile no overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    page.screenshot(path=str(OUT/'boundary-mobile.png'),full_page=True)
    page.keyboard.press('Escape')
    # Candidate confirmation and alias preservation on the final implementation.
    page.set_viewport_size({'width':1440,'height':1000})
    page.evaluate("""()=>{geoActive=null;researchStep=1;geoDraft.US={website:'https://cremocompany.com/',brand:'Cremo | Cremo Company | CREMO US',context:'USER EDITED CONTEXT',inspectedURL:'https://cremocompany.com/',inspectedBrandConfirmed:false,inspection:{website:{url:'https://cremocompany.com/',bytes:12},brand:{name:'Cremo',aliases:['Cremo'],source:'title',needs_confirmation:true},diagnosis:{score:null,checks:[{label:'Test <script>',status:'unknown',evidence:'<script>window.fixtureXSS=1</script>',action:'Review'}],methodology:'Synthetic unknown preserves null'},context:'SITE CONTEXT',warnings:[]}};render()}""")
    expect(page.locator('#website-readiness-score')).to_contain_text('—')
    page.get_by_role('button',name='下一步：选择 AI').click()
    check('Unconfirmed candidate blocks AI next',page.locator('#confirm-inspected-brand').count()==1)
    page.locator('#confirm-inspected-brand').click()
    check('Final alias confirmation preserves exact aliases',page.evaluate('geoDraft.US.brand')=='Cremo | Cremo Company | CREMO US')
    check('Edited background preserved',page.evaluate('geoDraft.US.context')=='USER EDITED CONTEXT')
    check('Website unknown score and escaped metadata', '—' in page.locator('#website-readiness-score').inner_text() and page.evaluate('window.fixtureXSS') is None)
    page.locator('#geo-website').fill('https://unsupported.invalid/')
    page.locator('#inspect-website-button').click()
    expect(page.locator('[role=alert]')).to_contain_text('未生成页面分数')
    check('Inspect failure removes score',page.locator('#website-readiness-score').count()==0)
    check('No browser page errors',not errors,errors)
    browser.close()

(OUT/'browser-boundaries-summary.json').write_text(json.dumps({'synthetic':True,'ui_variants_explicitly_injected':True,'checks':checks},ensure_ascii=False,indent=2))
print(json.dumps({'passed':sum(c['pass'] for c in checks),'total':len(checks),'failed':[c['name'] for c in checks if not c['pass']]},ensure_ascii=False))
raise SystemExit(0 if all(c['pass'] for c in checks) else 1)
