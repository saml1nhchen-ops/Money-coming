/* Team-only, deterministic website readiness. All network access uses the private remote closure. */
(() => {
  'use strict';
  if (window.SIGNAL_GEO_MODE !== 'team') return;
  const legacyPage = geoPage, legacyRender = render, legacyChange = geoChange, legacyStart = geoStart;
  const sessions = new Map();
  let sequence = 0, pollTimer, mode = 'website', modelBinding = null;
  const states = {pass:'通过',fail:'不通过',unknown:'未知',not_applicable:'不适用'};
  const array = value => Array.isArray(value) ? value : [];
  const text = value => esc(value === undefined || value === null ? '未知' : String(value));
  function normalize(value) {
    try {
      const raw = String(value || '').trim(), u = new URL(/^https?:\/\//i.test(raw) ? raw : 'https://'+raw);
      if (!['https:','http:'].includes(u.protocol) || u.username || u.password || !u.hostname.includes('.') || u.hostname==='localhost' || /^127\.|^0\.|^10\.|^192\.168\.|^169\.254\.|^172\.(1[6-9]|2\d|3[01])\./.test(u.hostname) || /\.(local|internal)$/i.test(u.hostname)) return '';
      u.hash=''; return u.href;
    } catch { return ''; }
  }
  function identity() {
    const c = window.remoteEnrichmentContext?.() || {};
    return {...c,key:JSON.stringify([c.backend,c.epoch,geoMarket,typeof ws==='undefined'?'':ws]),market:geoMarket};
  }
  function session() {
    const c = identity();
    if (!sessions.has(c.key)) sessions.set(c.key,{screen:'url',url:'',audit:null,draft:null,message:'',pending:false});
    return sessions.get(c.key);
  }
  function stop() { sequence++; clearTimeout(pollTimer); }
  function visible() { return page==='research' && mode==='website'; }
  function current(job) { return visible() && job.sequence===sequence && identity().key===job.key && identity().authenticated; }
  function job() { stop(); return {...identity(),sequence,deadline:Date.now()+90000}; }
  function repaint() { if(page==='research') render(); }
  function field(label,id,value,large=false,source='') {
    return `<label class="sr-field"><span>${text(label)}${source?` <small class="sr-muted">${text(source)}</small>`:''}</span>${large?`<textarea id="${id}" maxlength="12000">${text(value || '')}</textarea>`:`<input id="${id}" ${id==='audit-url'?'placeholder="粘贴官网网址，例如 https://example.com" inputmode="url"':''} maxlength="500" value="${text(value || '')}" autocomplete="off">`}</label>`;
  }
  function provenance(s,key) {
    const initial = initialDraft({candidates:s.audit?.candidates}), changed = s.draft?.[key] !== initial[key];
    return changed ? '用户提供 / 已修改' : s.draft?.[key] ? '官网识别，待核对' : '未识别，可手动补充';
  }
  function initialDraft(a) {
    const c = a?.confirmed || a?.candidates || {};
    return {brand:c.brand?.name || '',products:array(c.products).map(v=>v.name).join('\n'),competitors:array(c.competitors).map(v=>v.name).join('\n'),context:c.context || ''};
  }
  function confirmation(s) {
    const a=s.audit;
    return `<section class="sr-card"><span class="sr-status">02 / 核对识别信息</span><h2>这些信息准确吗？</h2><p class="sr-muted">官网：${text(a.website?.final_url || a.website?.requested_url || s.url)}。品牌与产品来自本次网页；没有可靠证据的竞品留空。你可以修改，产品和竞品均可不填。</p>${a.reused?`<p class="sr-warning">使用已有检测结果（${text(a.created_at)}）；如信息为空，可点击下方重新读取，不必重复使用旧结果。</p>`:''}${access(a.access)}<p class="sr-muted">品牌与产品分别识别。首页可能只提供品类，候选不代表销量排名；正文未提取不等于品牌不存在。</p>${field('品牌名称','audit-brand',s.draft.brand,false,provenance(s,'brand'))}${field('产品 / 品类（候选，每行一个）','audit-products',s.draft.products,true,provenance(s,'products'))}${field('竞品（选填，每行一个）','audit-competitors',s.draft.competitors,true,provenance(s,'competitors'))}<details><summary>查看自动识别来源与原文</summary>${candidateSources(a)}</details><details><summary>补充背景（选填）</summary>${field('背景说明','audit-context',s.draft.context,true,'用户提供')}</details><div class="sr-actions"><button type="button" data-sr="url">← 修改官网</button><button type="button" data-sr="refresh">重新读取官网</button><button class="primary" type="button" data-sr="confirm" ${s.pending?'disabled':''}>确认并生成网站 GEO 报告</button></div></section>`;
  }
  function candidateSources(a) {
    const c=a.candidates || {}, evidence=array(a.report?.evidence || a.evidence);
    const list=[c.brand,...array(c.products),...array(c.competitors)].filter(Boolean);
    return list.length ? list.map(v=>`<div class="sr-evidence"><b>${text(v.name)}</b>${v.kind==='category'?'<small> · 官网品类候选</small>':''}<p>${text(v.source_url)} · ${text(v.source_field)}</p>${array(v.evidence_ids).map(id=>{const e=evidence.find(e=>e.id===id);return e?`<blockquote>${text(e.excerpt)}</blockquote>`:`<p class="sr-muted">证据编号：${text(id)}</p>`}).join('')}${v.evidence?`<blockquote>${text(v.evidence)}</blockquote>`:''}</div>`).join('') : '<p>未获得可靠识别证据，可手动填写品牌并继续。</p>';
  }
  function access(d,full=false) {
    if (!d) return '<section class="sr-card"><h2>官网访问诊断</h2><p>暂无诊断证据，不能据此判断外部爬虫是否能够访问。</p></section>';
    const labels={metadata_only:'已取得页面信息，正文不足',readable:'页面可读',limited:'疑似限流或自动访问限制',blocked:'访问被拒绝',challenge:'疑似验证码或访问挑战',unreachable:'暂时无法连接',unsupported:'不支持读取此内容',unsafe:'地址未通过安全检查'};
    const outcome=d.http_status===429?'limited':d.outcome;
    return `<section class="sr-card"><h2>官网访问诊断 · ${text(labels[outcome] || '结果未知')}</h2><p>这是后台读取官网的结果，与你的浏览器或外部爬虫能否打开不一定相同。</p><p>HTTP：${text(d.http_status)} · 可读字数：${text(d.readable_characters)} · 跳转数：${array(d.redirects).length}</p>${['limited','blocked'].includes(outcome)?'<p>可能存在限流或访问限制，不能据此确定为反爬。可以手动填写后继续；不会自动重试或绕过。</p>':''}${outcome==='metadata_only'?'<p>HTTP 请求成功，但初始 HTML 正文不足；可能需要 JavaScript 才能展示产品。已读取的品牌元信息仍会保留，不能把未提取到产品当作品牌没有产品。</p>':''}${outcome==='challenge'?'<p>即使 HTTP 200，也未读取到可确认的正常页面内容。不会尝试绕过验证。</p>':''}<details ${full?'open':''}><summary>检查项与跳转链</summary><p>最终地址：${text(d.final_url)} · 检测时间：${text(d.checked_at)}</p>${array(d.checks).map(c=>`<p>${text(c.id)}：${text(({passed:'通过',failed:'未通过',skipped:'未检查',unknown:'未知'})[c.status] || '未知')} · ${text(c.message)}</p>`).join('')}${array(d.findings).map(f=>`<p>${text(f.message)}</p>`).join('')}${array(d.redirects).map(r=>`<p>${text(r.url)} · ${text(r.status)} → ${text(r.location)}</p>`).join('')}</details></section>`;
  }
  function evidenceBlock(e) {
    return `<div class="sr-evidence"><b>${text(e.id)}</b><p>来源：${text(e.url)} · HTTP ${text(e.http_status)} · ${text(e.captured_at)}</p><p>字段：${text(e.source_field)} · 类型：${text(e.content_type)} · 资源：${text(e.resource_id)}</p>${e.excerpt?`<blockquote>${text(e.excerpt)}</blockquote>`:''}${e.error_code?`<p>获取限制：${text(e.error_code)}</p>`:''}${e.sha256?`<p>内容 SHA256：${text(e.sha256)}</p>`:''}${array(e.redirects).map(r=>`<p>${text(r.url)} · ${text(r.status)} → ${text(r.location)}</p>`).join('')}</div>`;
  }
  function confirmedSummary(a) {
    const c=a.confirmed;if(!c)return '';
    const origins={website_metadata:'官网来源',website_text:'官网来源',user_provided:'用户提供',user_modified:'用户修改'};
    return `<section class="sr-card"><h2>已确认的品牌信息</h2>${[c.brand,...array(c.products),...array(c.competitors)].filter(v=>v?.name).map(v=>`<p><b>${text(v.name)}</b> · ${text(origins[v.basis] || '用户确认')} ${array(v.aliases).length?`（${array(v.aliases).map(text).join('、')}）`:''}</p>`).join('') || '<p>品牌、产品与竞品未填写；报告以官网地址为对象，不补造品牌证据。</p>'}${c.context?`<p>用户提供的背景：${text(c.context)}</p>`:''}</section>`;
  }
  function reportHTML(a,full=false) {
    const r=a.report;
    if (!r) return '<section class="sr-card"><h2>暂未生成完整报告</h2><p>请核对信息并确认；读取失败也可以生成包含未知项的报告。</p></section>';
    const resources=array(r.scope?.resources), httpSuccess=resources.filter(v=>v.http_status>=200 && v.http_status<300).length, httpFailed=resources.filter(v=>v.http_status>=400 || v.error_code).length;
    const summary=r.summary || {}, complete=typeof summary.score==='number', evidence=array(r.evidence);
    const fold=(label,body)=>full?`<div><h4>${text(label)}</h4>${body}</div>`:`<details><summary>${text(label)}</summary>${body}</details>`;
    const score=complete?`${text(summary.score)} / 100`:'证据不足，暂无完整分数';
    const partial=!complete && typeof summary.partial_score==='number'?`<p>已知检查部分分：${text(summary.partial_score)} / 100（仅覆盖 ${text(summary.coverage_percent)}%，不能视为完整分数）</p>`:'';
    return `<section class="sr-card"><span class="sr-status">规则型网站 GEO 检测</span><h1>${text(r.target?.brand || a.confirmed?.brand?.name || r.target?.url || '网站')} · 技术准备度报告</h1><p class="sr-warning"><b>${r.model_analysis?.report?'规则技术分与下方独立模型测试分开计算。':'规则技术检测，尚未测试模型实际推荐表现。'}</b>规则分不是被推荐概率、曝光率或模型偏好，也不验证官网事实真实性。网站检测全程 0 次模型调用。</p><p class="sr-score">${score}</p>${partial}<p>证据覆盖率：${text(summary.coverage_percent)}% · 通过 ${text(summary.passed)} · 不通过 ${text(summary.failed)} · 未知 ${text(summary.unknown)} · 不适用 ${text(summary.not_applicable)}</p><p>官网：${text(r.target?.url)} · 市场：${text(r.target?.market)} · 检测时间：${text(r.generated_at)} · 规则版本：${text(r.rule_version)}</p>${array(summary.conclusions).map(c=>`<p>${text(typeof c==='object'?JSON.stringify(c):c)}</p>`).join('')}<h3>扫描范围与限制</h3><p>实际请求 ${text(a.usage?.http_requests)} 次 · 资源 ${array(r.scope?.resources).length} 个。资源 HTTP 成功 ${httpSuccess} / 未成功 ${httpFailed} / 未知 ${Math.max(0,resources.length-httpSuccess-httpFailed)}；HTTP 成功不等于内容检测通过。有限页面检测不代表全站或所有爬虫的实际访问。</p>${array(r.scope?.limitations).map(v=>`<p>${text(v)}</p>`).join('')}${fold('全部资源与覆盖范围',`<pre>${text(JSON.stringify(r.scope,null,2))}</pre>`)}${array(a.warnings).map(v=>`<p>${text(typeof v==='object'?JSON.stringify(v):v)}</p>`).join('')}</section>${confirmedSummary(a)}${access(a.access,full)}<section class="sr-card"><h2>机器人策略</h2><p>robots.txt 状态：${text(({unknown:'未知',not_found:'未发现声明',fetched:'已读取',available:'已读取',ok:'已读取',blocked:'访问被拒绝',failed:'获取失败'})[r.robots?.fetch_status] || '未知')}。未发现声明不同于明确允许；获取失败为未知。训练限制不等于无法被推荐，搜索 / 用户触发策略也不保证外部客户端实际遵守。</p><table><thead><tr><th>目标 UA / 用途</th><th>路径</th><th>有效结果</th></tr></thead><tbody>${array(r.robots?.agents).map(p=>`<tr><td>${text(p.user_agent)}<br>${text(({search:'搜索 / 检索',training:'训练',user_triggered:'用户触发',usage_control:'使用控制'})[p.purpose] || p.purpose)}</td><td>${text(p.path)}</td><td>${text(({allowed:'允许',disallowed:'禁止',not_found:'未发现声明',unknown:'未知'})[p.decision] || '未知')}${fold('规则依据与说明',`<p>解析器：${text(p.parser)}；证据：${array(p.evidence_ids).map(text).join('、')}</p>${array(p.notes).map(n=>`<p>${text(n)}</p>`).join('')}`)}</td></tr>`).join('')}</tbody></table></section>${array(r.sections).map(section=>`<section class="sr-card"><h2>${text(section.title)}</h2>${array(section.checks).map(c=>`<article class="sr-check"><div class="sr-check-head"><h3>${text(c.title)}</h3><span class="sr-status">${text(states[c.status] || '未知')}</span></div><p>${text(c.reason)}</p>${c.action?`<p>建议：${text(c.action)}</p>`:''}${fold('查看规则与证据',`<p>规则 ${text(c.id)} · 权重 ${text(c.weight)} · 方法：${text(c.methodology)}</p>${array(c.evidence_ids).map(id=>{const e=evidence.find(e=>e.id===id);return e?evidenceBlock(e):`<p>证据 ${text(id)}：未提供详情，不能补推结论。</p>`}).join('')}`)}</article>`).join('')}</section>`).join('')}<section class="sr-card"><h2>按优先级排列的建议</h2>${array(r.recommendations).map(v=>`<article class="sr-check"><h3>${text(v.priority)} · ${text(v.action)}</h3><p>复测方式：${text(v.retest)}</p><p>关联检查：${array(v.check_ids).map(text).join('、')} · 证据：${array(v.evidence_ids).map(text).join('、')}</p></article>`).join('') || '<p>暂无额外建议；请结合未知项与扫描范围核对。</p>'}</section><section class="sr-card"><h2>完整证据</h2>${fold('所有来源、抓取时间、失败与未知证据',evidence.map(evidenceBlock).join('') || '<p>未取得页面证据。检测结论应保持未知。</p>')}</section>${a.report?.model_analysis?.status!=='not_tested' && a.report?.model_analysis?.report?`<section class="sr-card"><h2>独立模型实际推荐测试</h2><p>与网站规则检测分开计算。以下保留原完整模型证据与方法，分数不相加。</p><pre>${text(JSON.stringify(a.report.model_analysis.report,null,2))}</pre></section>`:''}`;
  }
  function connectionHTML() {
    return `<details class="sr-login"><summary>${identity().authenticated?'团队已登录 · 连接管理':'登录团队后台（网站检测不需要模型密钥）'}</summary>${remoteConnectionMarkup({audit:true})}</details>`;
  }
  function steps(s) {
    const active=s.screen==='confirm'?2:s.screen==='report'?3:s.screen==='progress' && s.draft?3:1;
    return `<ol class="sr-steps" aria-label="网站检测步骤">${['输入官网','确认信息','网站报告'].map((label,i)=>`<li class="${active===i+1?'current':active>i+1?'complete':''}" ${active===i+1?'aria-current="step"':''}><span>${i+1}</span>${label}</li>`).join('')}</ol>`;
  }
  function pageHTML() {
    const s=session();
    if (mode==='model') return `<div class="sr-flow"><div class="sr-actions"><button data-sr="return">← 返回网站 GEO 报告</button></div><p class="sr-warning">独立的真实模型测试：将调用模型并按实际用量计费。仍需选择模型、核对预算并明确点击开始；网站规则分与模型表现分开计算。</p></div>`+legacyPage();
    return `<div class="sr-flow" id="site-readiness"><div class="sr-hero"><span class="sr-status">网站 GEO · 规则与证据</span><h1>${s.screen==='url'?'让官网更容易被理解':s.screen==='confirm'?'核对你的品牌信息':s.screen==='report'?'网站 GEO 检测报告':'正在检测官网'}</h1><p>先读取官网并确认品牌信息，再生成网站 GEO 报告。全程通过规则和工具检测，不调用模型。</p></div>${steps(s)}${s.message?`<p class="sr-warning" role="alert">${text(s.message)}</p>`:''}${s.screen==='url'?`<section class="sr-card"><form id="audit-url-form"><div class="sr-url">${field('品牌官网','audit-url',s.url)}<button class="primary" ${s.pending?'disabled':''}>分析官网</button></div><div class="sr-market"><label for="audit-market">市场</label><select id="audit-market"><option value="CN" ${geoMarket==='CN'?'selected':''}>中国</option><option value="US" ${geoMarket==='US'?'selected':''}>美国</option></select></div><p class="sr-muted">只需公开官网地址；随后可核对品牌、产品和竞品。产品和竞品可留空。</p></form></section>`:s.screen==='confirm'?confirmation(s):s.screen==='report'?`${reportHTML(s.audit)}<div class="sr-actions"><button data-sr="edit">返回修改识别信息</button><button data-sr="refresh">重新检测官网</button><button class="primary" data-sr="html">导出完整报告（HTML）</button><button data-sr="json">下载证据 JSON</button><button data-sr="print">打印为 PDF</button></div><section class="sr-card sr-model-entry"><h2>进一步验证真实模型表现</h2><p>网站规则分不代表模型会推荐你的品牌。</p><button data-sr="models">进一步测试模型实际推荐表现（可选，调用模型并计费）</button><p><button data-sr="history">查看历史模型报告与问题证据</button></p></section>`:progress(s)}${connectionHTML()}</div>`;
  }
  function progress(s) {
    const stage=s.audit?.stage || '', labels=['读取策略','检测可读内容','检查可信度','整理报告'];
    const stages={website:0,reading_policies:0,robots:0,policies:0,content:1,readability:1,trust:2,building_report:3,report:3,done:3};
    const stageLabels={website:'读取官网',reading_policies:'读取策略',robots:'读取机器人策略',policies:'读取策略',content:'检测可读内容',readability:'检测可读内容',trust:'检查可信度',building_report:'整理报告',report:'整理报告',done:'报告完成',interrupted:'处理曾中断',audit_unavailable:'检测工具暂不可用'};
    const index=stages[stage] ?? 0;
    return `<section class="sr-card sr-progress"><h2>${s.audit?.phase==='preview'?'正在读取官网并识别信息':'正在生成完整规则报告'}</h2><p>当前阶段：${text(stageLabels[stage] || '读取官网')}。全程 0 次模型调用。</p><progress max="4" value="${index+1}"></progress><ol>${labels.map((label,i)=>`<li>${i<index?'✓ ':i===index?'进行中 · ':''}${label}</li>`).join('')}</ol><button data-sr="resume" ${s.pending?'disabled':''}>读取当前进度</button><button data-sr="url">返回官网输入</button></section>`;
  }
  function accept(j,a) {
    if (!current(j)) return;
    const s=session(); if(s.audit?.id!==a.id || s.audit?.revision!==a.revision)s.modelAnalysis=null; s.audit=a; s.pending=false; s.message='';
    if (a.status==='awaiting_confirmation' || a.phase==='confirmation' || (j.preview && a.report)) {
      if (!s.draft) s.draft=initialDraft(a);
      s.screen='confirm';
    } else if (a.report && ['finished','partial','failed'].includes(a.status)) s.screen='report';
    else if (['queued','running'].includes(a.status)) {
      s.screen='progress'; pollTimer=setTimeout(()=>read(j,a.id),1000);
    } else { s.screen=s.draft?'confirm':'url'; s.message='检测未能完成，可重新读取结果或修改官网。已有证据仍保留。'; }
    repaint();
  }
  function failure(j,e) {
    if(!current(j))return;
    clearTimeout(pollTimer);const s=session();s.pending=false;s.message=e.message+' 不会自动重新提交。';repaint();
  }
  async function read(j,id) {
    if(!current(j))return;
    if(Date.now()>j.deadline){failure(j,new Error('等待超时，后台可能仍在处理，可手动读取进度。'));return;}
    try {accept(j,await remoteAudit('read',id));}catch(e){failure(j,e);}
  }
  async function analyze(refresh=false) {
    const s=session();if(s.pending)return;
    s.url=document.getElementById('audit-url')?.value || s.url;
    const url=normalize(s.url);
    if(!url){s.message='请输入公开、安全的 HTTP(S) 官网域名，不包含账号密码或私网地址。';repaint();return;}
    if(!identity().authenticated){s.message='请先展开下方团队登录，再分析官网。网站检测不需要模型密钥。';repaint();return;}
    const j={...job(),preview:true};s.url=url;s.pending=true;s.message='';s.audit=null;s.draft=null;s.modelAnalysis=null;s.screen='progress';repaint();
    try{accept(j,await remoteAudit('preview',{website:url,market:geoMarket,request_id:crypto.randomUUID(),...(refresh?{refresh:true}:{})}));}catch(e){s.screen='url';failure(j,e);}
  }
  function confirmed(s) {
    const sources=s.audit.candidates || {};
    const rows=key=>[...new Set(String(s.draft[key] || '').split('\n').map(v=>v.trim()).filter(Boolean))].map(name=>{
      const original=array(sources[key]).find(c=>c.name===name);
      return {name,aliases:original?.aliases?.length ? original.aliases : [name],...(original?{source_candidate_id:original.id}:{})};
    });
    const brand=s.draft.brand.trim(), original=sources.brand;
    return {brand:{name:brand,aliases:brand?(original?.name===brand && original.aliases?.length?original.aliases:[brand]):[]},products:rows('products'),competitors:rows('competitors'),context:s.draft.context || ''};
  }
  async function confirm() {
    const s=session();if(s.pending || !s.audit?.id)return;
    modelBinding=null;s.modelAnalysis=null;
    const j=job(), body={id:s.audit.id,confirmed:confirmed(s)};s.pending=true;s.message='';s.screen='progress';repaint();
    try{accept(j,await remoteAudit('confirm',body));}catch(e){s.screen='confirm';failure(j,e);}
  }
  function offlineHTML(a) {
    const css='body{font:15px/1.7 system-ui,sans-serif;max-width:1100px;margin:30px auto;padding:0 20px;color:#242235}section{border:1px solid #ddd;border-radius:10px;margin:20px 0;padding:20px}table{width:100%;border-collapse:collapse}td,th{padding:10px;border:1px solid #ddd;text-align:left;vertical-align:top}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f4f8;padding:12px}.sr-warning{background:#fff8e7;padding:15px}.sr-score{font-size:30px} @media print{body{margin:0}section{break-inside:avoid}pre{white-space:pre-wrap}}';
    return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; script-src 'none'"><title>网站 GEO 完整报告</title><style>${css}</style></head><body><p>完整离线报告 · 可使用浏览器打印为 PDF。网站规则与实际模型测试分别解释，分数不相加。</p>${reportHTML(a,true)}<section><h2>完整审计数据（含所有未知项、来源与确认信息）</h2><pre>${text(JSON.stringify(a,null,2))}</pre></section></body></html>`;
  }
  function download(content,name,type) {
    const u=URL.createObjectURL(new Blob([content],{type})),a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);
  }
  async function exported(s) {
    const a=await remoteAudit('export',s.audit.id);
    if(s.modelAnalysis?.auditID===a.id && s.modelAnalysis.revision===a.revision && a.report) a.report.model_analysis=s.modelAnalysis.result;
    return a;
  }
  async function exportReport(format) {
    const s=session(),j={...identity(),sequence};
    if(!s.audit?.id)return;
    try{
      const a=await exported(s);if(!current(j))return;
      const content=format==='json'?JSON.stringify(a,null,2):offlineHTML(a);
      if(format==='print') {
        const frame=document.createElement('iframe');frame.title='完整网站 GEO 打印报告';frame.style.cssText='position:fixed;left:-10000px;top:0;width:1000px;height:1000px;border:0';frame.setAttribute('sandbox','allow-same-origin allow-modals');frame.srcdoc=content;frame.onload=()=>{frame.contentWindow.focus();frame.contentWindow.print();setTimeout(()=>frame.remove(),1000);};document.body.append(frame);
      } else download(content,'website-geo-'+a.id+'.'+format,format==='json'?'application/json;charset=utf-8':'text/html;charset=utf-8');
    }catch(e){if(current(j)){s.message=e.message;repaint();}}
  }
  function enterModels(history=false) {
    const s=session();stop();
    if(!history && s.audit?.confirmed){
      const c=s.audit.confirmed,d=geoDraft[geoMarket];d.website=s.audit.website?.final_url || s.url;d.brand=[...new Set([c.brand.name,...array(c.brand.aliases)].filter(Boolean))].join(' | ');d.skus=array(c.products).map(v=>[v.name,...array(v.aliases)].join(' | ')).join('\n');d.competitors=array(c.competitors).map(v=>[v.name,...array(v.aliases)].join(' | ')+(array(v.domains).length?' ; '+v.domains.join(','):'')).join('\n');d.context=c.context || '';
      modelBinding=c.brand.name.trim()?{key:identity().key,auditID:s.audit.id,revision:s.audit.revision,url:normalize(d.website),market:geoMarket,brand:d.brand.split('|').map(v=>v.trim()).filter(Boolean),jobID:null,merged:null}:null;researchStep=c.brand.name.trim()?2:1;researchMessage=c.brand.name.trim()?'':'请先补充真实品牌名称，再选择模型并确认付费测试。';
    }else{modelBinding=null;researchStep=3;}
    mode='model';repaint();
  }
  function matches(config,b) {
    return config && normalize(config.website)===b.url && config.market===b.market && JSON.stringify(config.brand_aliases || [])===JSON.stringify(b.brand);
  }
  async function mergeModel() {
    const b=modelBinding,j=geoActive;
    if(!b?.jobID || b.key!==identity().key || j?.id!==b.jobID || !matches(j.config,b) || ['queued','running'].includes(j.status) || b.merged || b.loading)return;
    b.loading=true;
    try{
      const full=await geoFetch('export?id='+encodeURIComponent(j.id));
      if(modelBinding!==b || identity().key!==b.key || !matches(full.config || full.job?.config,b))return;
      b.merged={status:j.status==='finished'?'tested':j.status==='partial'?'partial':'failed',binding:{audit_id:b.auditID,url:b.url,market:b.market,brand_aliases:b.brand},job_id:j.id,report:full};
      const s=session();if(s.audit?.id===b.auditID && s.audit.revision===b.revision && s.audit.report){s.audit.report.model_analysis=b.merged;s.modelAnalysis={auditID:b.auditID,revision:b.revision,result:b.merged};}
    }catch{}finally{b.loading=false;}
  }
  geoPage=pageHTML;
  render=function(){legacyRender();if(page!=='research')return;
    const nav=document.querySelector('aside nav');if(nav)nav.innerHTML=`<a href="#/w/${text(ws)}/research" data-sr="home">＋ 检测官网</a><a href="#/w/${text(ws)}/research" data-sr="report">▤ 网站 GEO 报告</a><a href="#/w/${text(ws)}/research" data-sr="history">历史模型报告</a><a href="#/w/${text(ws)}/overview">全部工作台功能 →</a>`;
    const header=document.querySelector('header .actions > span');if(header)header.textContent=mode==='model'?'模型实际推荐测试（可选）':'网站 GEO 检测';
    const subtitle=document.querySelector('.page-head .subtitle');if(subtitle)subtitle.textContent='从官网证据出发，核对信息并生成完整规则报告。';
    const notice=document.querySelector('main > .notice');if(notice)notice.textContent='网站技术检测全程 0 次模型调用；规则分与模型实际推荐表现分别计算。';
    if(mode==='model')void mergeModel();
  };
  geoChange=function(m){stop();modelBinding=null;return legacyChange(m);};
  geoStart=async function(...args){
    const b=modelBinding,old=geoActive?.id;if(b)researchSave();
    const eligible=b && identity().key===b.key && normalize(geoDraft[geoMarket].website)===b.url && JSON.stringify((geoDraft[geoMarket].brand || '').split('|').map(v=>v.trim()).filter(Boolean))===JSON.stringify(b.brand);
    await legacyStart(...args);
    if(eligible && modelBinding===b && geoActive?.id!==old && matches(geoActive?.config,b)){b.jobID=geoActive.id;void mergeModel();}
  };
  document.addEventListener('submit',e=>{if(e.target.id==='audit-url-form'){e.preventDefault();void analyze();}});
  document.addEventListener('input',e=>{
    const s=session(),keys={'audit-brand':'brand','audit-products':'products','audit-competitors':'competitors','audit-context':'context'};
    if(e.target.id==='audit-url'){s.url=e.target.value;return;}
    const key=keys[e.target.id];if(key && s.draft){s.draft[key]=e.target.value;const label=e.target.closest('label')?.querySelector('small');if(label)label.textContent='用户提供 / 已修改';}
  });
  document.addEventListener('change',e=>{if(e.target.id==='audit-market')geoChange(e.target.value);});
  document.addEventListener('click',e=>{
    const b=e.target.closest('[data-sr]');if(!b)return;e.preventDefault();
    const action=b.dataset.sr,s=session();
    if(action==='confirm'){void confirm();return;}
    if(action==='refresh'){void analyze(true);return;}
    if(['html','json','print'].includes(action)){void exportReport(action);return;}
    if(action==='models' || action==='history'){enterModels(action==='history');return;}
    stop();mode='website';s.pending=false;s.message='';
    if(action==='url' || action==='home')s.screen='url';
    if(action==='edit'){s.draft ||= initialDraft(s.audit);s.screen='confirm';}
    if(action==='return' || action==='report')s.screen=s.audit?.report?'report':s.draft?'confirm':'url';
    if(action==='resume' && s.audit?.id){const j=job();s.pending=true;void read(j,s.audit.id);}
    repaint();
  });
  window.addEventListener('remote-enrichment-invalidated',()=>{stop();modelBinding=null;mode='website';});
  window.addEventListener('hashchange',()=>{stop();if(visible()){const s=session();s.pending=false;if(s.screen==='progress' && s.audit?.id){const j=job();void read(j,s.audit.id);}}});
  window.addEventListener('pagehide',stop);
  // Pure helpers also support deterministic offline export tests, without credentials.
  window.siteReadinessHTML=offlineHTML;
  window.siteReadinessReport=reportHTML;
  if(page==='research')repaint();
})();
