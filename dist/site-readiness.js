/* Team diagnosis workflow. Network access stays in the private authenticated transport. */
(() => {
  'use strict';
  if (window.SIGNAL_GEO_MODE !== 'team') return;
  const legacyPage = geoPage, legacyRender = render, legacyChange = geoChange;
  const sessions = new Map();
  let sequence = 0, pollTimer;
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
  function visible() { return onWorkflow() && session().screen!=='shared'; }
  function current(job) { return visible() && job.sequence===sequence && identity().key===job.key && identity().authenticated; }
  function job() { stop(); return {...identity(),sequence,deadline:Date.now()+90000}; }
  function repaint() { if(onWorkflow()) render(); }
  function field(label,id,value,large=false,source='') {
    return `<label class="sr-field"><span>${text(label)}${source?` <small class="sr-muted">${text(source)}</small>`:''}</span>${large?`<textarea id="${id}" maxlength="12000">${text(value || '')}</textarea>`:`<input id="${id}" ${id==='audit-url'?'placeholder="粘贴官网网址，例如 https://example.com" inputmode="url"':''} maxlength="500" value="${text(value || '')}" autocomplete="off">`}</label>`;
  }
  function initialDraft(a) {
    const c = a?.confirmed || a?.candidates || {};
    return {brand:c.brand?.name || '',products:array(c.products).map(v=>v.name).join('\n'),competitors:array(c.competitors).map(v=>v.name).join('\n'),context:c.context || ''};
  }
  function confirmation(s) {
    const a=s.audit;
    return `<section class="sr-card"><h2>这些信息准确吗？</h2><p class="sr-muted">官网：${text(a.website?.final_url || a.website?.requested_url || s.url)}。请核对并修改品牌、产品与竞品。产品和竞品可以留空。</p>${field('品牌名称','audit-brand',s.draft.brand)}${field('重点产品','audit-products',s.draft.products,true)}${field('主要竞品','audit-competitors',s.draft.competitors,true)}<details><summary>查看官网读取情况</summary>${access(a.access)}</details><details><summary>查看自动识别来源与原文</summary>${candidateSources(a)}</details><details><summary>补充背景（选填）</summary>${field('背景说明','audit-context',s.draft.context,true)}</details><div class="sr-actions"><button type="button" data-sr="url">← 修改官网</button><button type="button" data-sr="refresh">重新读取官网</button><button class="primary" type="button" data-sr="confirm" ${s.pending?'disabled':''}>下一步：确认诊断方案</button></div></section>`;
  }
  function candidateSources(a) {
    const c=a.candidates || {}, evidence=array(a.report?.evidence || a.evidence);
    const list=[c.brand,...array(c.products),...array(c.competitors)].filter(Boolean);
    return list.length ? list.map(v=>`<div class="sr-evidence"><b>${text(v.name)}</b>${v.kind==='category'?'<small> · 官网品类候选</small>':''}<p>${v.basis==='model_inference'?'模型推断，无官网原文':text(v.source_url)+' · '+text(v.source_field)}</p>${v.reason?`<p>${text(v.reason)}</p>`:''}${array(v.evidence_ids).map(id=>{const e=evidence.find(e=>e.id===id);return e?`<blockquote>${text(e.excerpt)}</blockquote>`:`<p class="sr-muted">证据编号：${text(id)}</p>`}).join('')}${v.evidence?`<blockquote>${text(v.evidence)}</blockquote>`:''}</div>`).join('') : '<p>未获得可靠识别证据，可手动填写品牌并继续。</p>';
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
    return `<section class="sr-card"><h2>已确认的品牌信息</h2>${[c.brand,...array(c.products),...array(c.competitors)].filter(v=>v?.name).map(v=>`<p><b>${text(v.name)}</b> ${array(v.aliases).length?`（${array(v.aliases).map(text).join('、')}）`:''}</p>`).join('') || '<p>品牌、产品与竞品未填写；报告以官网地址为对象，不补造品牌证据。</p>'}${c.context?`<p>用户提供的背景：${text(c.context)}</p>`:''}</section>`;
  }
  function oldAuditReport(a,full=false) {
    const r=a.report;
    if (!r) return '<section class="sr-card"><h2>暂未生成完整报告</h2><p>请核对信息并确认；读取失败也可以生成包含未知项的报告。</p></section>';
    const resources=array(r.scope?.resources), httpSuccess=resources.filter(v=>v.http_status>=200 && v.http_status<300).length, httpFailed=resources.filter(v=>v.http_status>=400 || v.error_code).length;
    const summary=r.summary || {}, complete=typeof summary.score==='number', evidence=array(r.evidence);
    const fold=(label,body)=>full?`<div><h4>${text(label)}</h4>${body}</div>`:`<details><summary>${text(label)}</summary>${body}</details>`;
    const score=complete?`${text(summary.score)} / 100`:'证据不足，暂无完整分数';
    const partial=!complete && typeof summary.partial_score==='number'?`<p>已知检查部分分：${text(summary.partial_score)} / 100（仅覆盖 ${text(summary.coverage_percent)}%，不能视为完整分数）</p>`:'';
    return `<section class="sr-card"><h1>${text(r.target?.brand || a.confirmed?.brand?.name || r.target?.url || '网站')} · 技术准备度报告</h1><p class="sr-score">${score}</p>${partial}<p>证据覆盖率：${text(summary.coverage_percent)}% · 通过 ${text(summary.passed)} · 不通过 ${text(summary.failed)} · 未知 ${text(summary.unknown)} · 不适用 ${text(summary.not_applicable)}</p><p>官网：${text(r.target?.url)} · 市场：${text(r.target?.market)} · 检测时间：${text(r.generated_at)}</p>${array(summary.conclusions).filter(c=>!['规则技术检测，尚未测试模型实际推荐表现。','分数仅描述本次有限页面规则检查。'].includes(c)).map(c=>`<p>${text(typeof c==='object'?JSON.stringify(c):c)}</p>`).join('')}${fold('查看检测范围与方法',`<p>实际请求 ${text(a.usage?.http_requests)} 次 · 资源 ${array(r.scope?.resources).length} 个。资源 HTTP 成功 ${httpSuccess} / 未成功 ${httpFailed} / 未知 ${Math.max(0,resources.length-httpSuccess-httpFailed)}；HTTP 成功不等于内容检测通过。有限页面检测不代表全站或所有爬虫的实际访问。</p><p>网站技术准备度与真实模型推荐表现分别检测，分数不是推荐概率。</p><p>规则版本：${text(r.rule_version)}</p>${array(r.scope?.limitations).map(v=>`<p>${text(v)}</p>`).join('')}<pre>${text(JSON.stringify(r.scope,null,2))}</pre>`)}${array(a.warnings).map(v=>`<p>${text(typeof v==='object'?JSON.stringify(v):v)}</p>`).join('')}</section>${confirmedSummary(a)}${fold('官网访问检查',access(a.access,full))}<section class="sr-card"><h2>机器人策略</h2><p>robots.txt 状态：${text(({unknown:'未知',not_found:'未发现声明',fetched:'已读取',available:'已读取',ok:'已读取',blocked:'访问被拒绝',failed:'获取失败'})[r.robots?.fetch_status] || '未知')}。未发现声明不同于明确允许；获取失败为未知。训练限制不等于无法被推荐，搜索 / 用户触发策略也不保证外部客户端实际遵守。</p><table><thead><tr><th>目标 UA / 用途</th><th>路径</th><th>有效结果</th></tr></thead><tbody>${array(r.robots?.agents).map(p=>`<tr><td>${text(p.user_agent)}<br>${text(({search:'搜索 / 检索',training:'训练',user_triggered:'用户触发',usage_control:'使用控制'})[p.purpose] || p.purpose)}</td><td>${text(p.path)}</td><td>${text(({allowed:'允许',disallowed:'禁止',not_found:'未发现声明',unknown:'未知'})[p.decision] || '未知')}${fold('规则依据与说明',`<p>解析器：${text(p.parser)}；证据：${array(p.evidence_ids).map(text).join('、')}</p>${array(p.notes).map(n=>`<p>${text(n)}</p>`).join('')}`)}</td></tr>`).join('')}</tbody></table></section>${array(r.sections).map(section=>`<section class="sr-card"><h2>${text(section.title)}</h2>${array(section.checks).map(c=>`<article class="sr-check"><div class="sr-check-head"><h3>${text(c.title)}</h3><span class="sr-status">${text(states[c.status] || '未知')}</span></div><p>${text(c.reason)}</p>${c.action?`<p>建议：${text(c.action)}</p>`:''}${fold('查看规则与证据',`<p>规则 ${text(c.id)} · 权重 ${text(c.weight)} · 方法：${text(c.methodology)}</p>${array(c.evidence_ids).map(id=>{const e=evidence.find(e=>e.id===id);return e?evidenceBlock(e):`<p>证据 ${text(id)}：未提供详情，不能补推结论。</p>`}).join('')}`)}</article>`).join('')}</section>`).join('')}<section class="sr-card"><h2>按优先级排列的建议</h2>${array(r.recommendations).map(v=>`<article class="sr-check"><h3>${text(v.priority)} · ${text(v.action)}</h3><p>复测方式：${text(v.retest)}</p><p>关联检查：${array(v.check_ids).map(text).join('、')} · 证据：${array(v.evidence_ids).map(text).join('、')}</p></article>`).join('') || '<p>暂无额外建议；请结合未知项与扫描范围核对。</p>'}</section><section class="sr-card"><h2>完整证据</h2>${fold('所有来源、抓取时间、失败与未知证据',evidence.map(evidenceBlock).join('') || '<p>未取得页面证据。检测结论应保持未知。</p>')}</section>${a.report?.model_analysis?.status!=='not_tested' && a.report?.model_analysis?.report?`<section class="sr-card"><h2>独立模型实际推荐测试</h2><p>与网站规则检测分开计算。以下保留原完整模型证据与方法，分数不相加。</p><pre>${text(JSON.stringify(a.report.model_analysis.report,null,2))}</pre></section>`:''}`;
  }
  function oldAuditHTML(a) { return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>旧格式官网报告</title><body>'+oldAuditReport(a,true)+'<pre>'+text(JSON.stringify(a,null,2))+'</pre></body></html>'; }
  const oldDiagnosticPage=diagnosticPage;
  const terminal = status => ['finished','partial','failed','interrupted'].includes(status);
  const uuid = value => typeof value==='string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
  const statusLabel = s => ({queued:'等待开始',running:'诊断进行中',finished:'已完成',partial:'部分完成',failed:'未完成',interrupted:'已中断'})[s] || '状态未知';
  const diagnosticError = code => ({sampling_incomplete:'模型分析未完整完成，已保存的官网证据仍可查看。',runner_observation_lost:'暂时无法确认执行结果，请读取最新进度核对。',maintenance:'后台正在更新，请稍后再试。',daily_budget_exceeded:'今日额度不足，请核对额度后再明确开始。',interrupted:'任务曾中断，已有证据仍保留。',diagnostic_failed:'部分诊断步骤未完成，已有证据仍保留。',upstream_failed:'回答服务暂未完成请求，已有结果仍保留。'})[code] || '部分步骤未完成，请结合已有证据核对。';
  const stageLabel = s => ({preparing_material:'整理已保存的官网资料',model_submitting:'准备问答诊断',reconciliation_required:'核对执行状态',website:'读取官网',preview:'读取官网',confirmation:'确认品牌信息',reading_policies:'检查官网',building_report:'整理官网证据',audit:'检查官网',generating:'生成问题',sampling:'收集回答',report:'整理诊断报告',done:'报告完成',starting:'准备诊断',awaiting_confirmation:'确认品牌信息'})[s] || '正在整理诊断';
  function params() { return new URLSearchParams(location.hash.split('?')[1] || ''); }
  function onWorkflow() { return page==='research' || page==='diagnostic'; }
  function route(view='',id='') {
    stop();
    const q=new URLSearchParams();if(view)q.set('view',view);if(id)q.set('diagnostic',id);
    location.hash='/w/'+encodeURIComponent(ws)+'/research'+(q.size?'?'+q:'');
    if(location.hash==='#/w/'+encodeURIComponent(ws)+'/research'+(q.size?'?'+q:''))repaint();
  }
  function workspaceReady() { return window.remoteDiagnosticsContext?.().supported === true; }
  function sameContext(key) { return identity().key===key && onWorkflow(); }
  function connectionHTML() {
    return `<details class="sr-login"><summary>${identity().authenticated?'团队连接管理':'登录团队后台'}</summary>${remoteConnectionMarkup({audit:true})}</details>`;
  }
  function clearDetail(s) {s.detail=null;s.detailID=null;s.detailLoading=false;s.detailLoaded=false;s.detailReadState='idle';s.detailReadError='';s.retestConfirm=false;s.shareURL='';}
  function detailCurrent(j) {return visible() && j.sequence===sequence && identity().key===j.key && remoteDiagnosticsContext().canRead && session().screen==='detail' && session().detailID===j.detailID && params().get('diagnostic')===j.detailID;}
  function bundleMatches(d,publicView=false) {const id=d?.bundle?.run_manifest?.run_id;return !!d?.bundle && (publicView?id==='shared-report':!!d.id && id===d.id);}
  function finalReport(d,publicView=false) {return ['finished','partial'].includes(d?.status) && (!d.stage || d.stage==='done') && d.progress?.runner_status!=='unknown' && bundleMatches(d,publicView);}
  function selectedDetail(s) {return s.screen==='detail' && s.detailID===params().get('diagnostic') && s.detail?.id===s.detailID?s.detail:null;}
  function syncRoute(s) {
    const p=params(),key=location.hash;
    if(s.route===key)return;
    stop();s.route=key;s.pending=false;s.message='';s.dialog=null;
    const shared=p.get('share'),id=p.get('diagnostic');
    if(shared){clearDetail(s);if(s.shareToken!==shared){s.publicDetail=null;s.publicLoaded=false;s.publicLoading=false;s.shareExpires=null;}s.screen='shared';s.shareToken=shared;return;}
    s.shareToken=null;clearDetail(s);
    if(id){s.screen='detail';s.detailID=id;return;}
    const view=p.get('view');if(view==='projects')s.returnScreen='history';
    s.screen=view==='history'?'history':view==='projects'?'projects':view==='legacy'?'legacy':view==='import'?'import':'url';
  }
  async function ensureWorkspace(s) {
    if(!identity().authenticated || !workspaceReady() || s.workspaceLoading || s.workspaceLoaded)return;
    const key=identity().key;s.workspaceLoading=true;
    const results=await Promise.allSettled(['clients','projects','list'].map(action=>remoteWorkspace(action)));
    if(!sameContext(key))return;
    s.workspaceLoading=false;s.workspaceLoaded=true;
    for(let i=0;i<results.length;i++){
      const r=results[i];if(r.status==='fulfilled')s[['clients','projects','diagnostics'][i]]=array(r.value[['clients','projects','diagnostics'][i]]);
      else if(s.screen==='detail')s.workspaceNotice='客户项目列表暂未刷新，不影响已提交的诊断。';else s.message=r.reason.message;
    }
    if(s.refreshWorkspaceAfterLoad){s.refreshWorkspaceAfterLoad=false;s.workspaceLoaded=false;}
    if(!array(s.projects).some(p=>p.id===s.projectID && !p.internal))s.projectID=array(s.projects).find(p=>!p.internal)?.id || '';
    repaint();
  }
  function detailFailure(j,error,clear=false) {
    if(!detailCurrent(j))return;clearTimeout(pollTimer);const s=session();
    if(clear)s.detail=null;
    s.detailLoading=false;s.detailLoaded=true;s.detailReadState=clear?'mismatch':'error';s.detailReadError=error.message || '暂时无法读取最新进度。';s.message='';repaint();
  }
  async function ensureDetail(s) {
    if(s.detailLoading || s.detailLoaded || !s.detailID || !remoteDiagnosticsContext().canRead)return;
    if(!uuid(s.detailID)){s.detailLoaded=true;s.detailReadState='error';s.detailReadError='诊断链接无效。';repaint();return;}
    const j={...job(),detailID:s.detailID};s.detailLoading=true;s.detailReadState='loading';s.detailReadError='';s.message='';repaint();
    try {acceptDiagnostic(j,await remoteWorkspace('detail',j.detailID));}
    catch(e){detailFailure(j,e);}
  }
  async function ensureShared(s) {
    if(s.publicLoading || s.publicLoaded)return;
    const share=s.shareToken,key=location.hash;s.publicLoading=true;
    try{const result=await remoteSharedReport(share);if(location.hash!==key)return;s.publicDetail=result.diagnostic;s.shareExpires=result.expires_at;s.publicLoaded=true;s.publicLoading=false;repaint();}
    catch(e){if(location.hash===key){s.publicLoading=false;s.publicLoaded=true;s.message='分享链接已失效、已撤销或暂时无法读取。';repaint();}}
  }
  function ensure() {
    if(!onWorkflow())return;
    const s=session();syncRoute(s);
    if(s.screen==='shared'){void ensureShared(s);return;}
    if(s.screen==='detail')void ensureDetail(s);
    if(!identity().authenticated || !workspaceReady())return;
    void ensureWorkspace(s);
  }
  function steps(s) {
    const n=s.screen==='confirm'?2:s.screen==='models'?3:s.screen==='detail'?4:s.screen==='progress'&&s.draft?2:1;
    return `<ol class="sr-steps" aria-label="诊断步骤">${['输入官网','确认信息','确认方案','诊断报告'].map((label,i)=>`<li class="${n===i+1?'current':n>i+1?'complete':''}" ${n===i+1?'aria-current="step"':''}><span>${i+1}</span>${label}</li>`).join('')}</ol>`;
  }
  function capabilityNotice() {
    return identity().authenticated && !workspaceReady()?'<p class="sr-warning" role="status">后台正在升级，完整诊断与历史功能尚未就绪。不会自动启动旧版分析。你仍可填写官网，稍后继续。</p>':'';
  }
  function profileOptions(s) {
    const seen=new Set(),profiles=array(geoState.runner?.profiles).filter(p=>array(p.markets).includes(geoMarket) && !seen.has(p.id) && seen.add(p.id));
    if(s.profileIDs===undefined)s.profileIDs=profiles.slice(0,2).map(p=>p.id);
    return profiles;
  }
  function inlineProjectDraft(s) {
    if(!s.inlineProject){
      const client=array(s.clients).find(c=>!c.internal);
      s.inlineProject={clientID:client?.id || '__new__',clientName:'团队项目',projectName:(s.draft?.brand || '官网').slice(0,160)+' · '+(geoMarket==='US'?'美国':'中国')+'诊断'};
    }
    return s.inlineProject;
  }
  function projectSelect(s) {
    const available=array(s.projects).filter(p=>!p.internal),draft=inlineProjectDraft(s);
    return `<label class="sr-field"><span>保存到项目</span><select id="workflow-project" ${s.invalidField==='workflow-project'?'aria-invalid="true" aria-describedby="workflow-project-error"':''}><option value="">请选择项目</option>${available.map(p=>{const client=array(s.clients).find(c=>c.id===p.client_id);return `<option value="${text(p.id)}" ${s.projectID===p.id?'selected':''}>${text(client?.name || '')} / ${text(p.name)}</option>`;}).join('')}</select></label>${s.projectError?`<p id="workflow-project-error" class="sr-warning" role="alert" tabindex="-1">${text(s.projectError)}</p>`:''}<details id="workflow-inline-project" ${!available.length || s.inlineProjectOpen?'open':''}><summary>${available.length?'在本页创建新项目':'首次使用：在本页创建团队项目'}</summary><p>为本次诊断建立保存位置，已填写的信息与选择会保留。创建项目不会开始诊断。</p><label class="sr-field"><span>所属客户</span><select id="workflow-inline-client"><option value="__new__" ${draft.clientID==='__new__'?'selected':''}>新建团队客户</option>${array(s.clients).filter(c=>!c.internal).map(c=>`<option value="${text(c.id)}" ${draft.clientID===c.id?'selected':''}>${text(c.name)}</option>`).join('')}</select></label>${draft.clientID==='__new__'?field('客户名称','workflow-inline-client-name',draft.clientName):''}${field('项目名称','workflow-inline-project-name',draft.projectName)}${s.inlineProjectError?`<p id="workflow-inline-error" class="sr-warning" role="alert" tabindex="-1">${text(s.inlineProjectError)}</p>`:''}<button id="workflow-inline-create" type="button" data-wf="inline-project" ${s.inlineProjectPending?'disabled':''}>${s.inlineProjectPending?'正在创建项目…':'创建并选用项目'}</button></details>`;
  }
  function selectedProfiles(s) {return array(s.profileIDs).filter(id=>profileOptions(s).some(p=>p.id===id));}
  function planMaximum(s) {
    if((s.runMode || 'full')==='website')return 0;
    const pc=array(s.projects).find(p=>p.id===s.projectID)?.config || {},saved=pc.question_context,aliases=[...new Set(confirmed(s).brand.aliases.map(v=>v.toLowerCase()))].sort();
    const matching=saved && saved.website===normalize(s.audit?.website?.requested_url || s.url) && saved.market===geoMarket && JSON.stringify(saved.brand_aliases)===JSON.stringify(aliases);
    return (matching && array(pc.question_set).length===30?0:3)+30*selectedProfiles(s).length;
  }
  function modelConfirm(s) {
    const profiles=profileOptions(s),mode=s.runMode || 'full',selected=selectedProfiles(s),count=planMaximum(s),generation=count-30*selected.length;
    return `<section class="sr-card"><h2>确认本次诊断方案</h2><p>${text(s.draft.brand || s.url)} · ${geoMarket==='US'?'美国市场':'中国市场'}</p>${projectSelect(s)}<fieldset class="wf-choice"><legend>诊断范围</legend><label><input type="radio" name="workflow-mode" value="full" ${mode==='full'?'checked':''}> 官网与 30 道问题（默认）</label><label><input type="radio" name="workflow-mode" value="website" ${mode==='website'?'checked':''}> 仅检查官网</label></fieldset>${mode==='full'?`<div id="workflow-profile-group" tabindex="-1"><h3>选择要比较的 AI</h3><p>每家回答同一组 30 道问题，可选择全部已配置的 AI。</p><div class="sr-actions"><button type="button" data-wf="profiles-all">全选</button><button type="button" data-wf="profiles-none">清空</button></div><div class="wf-profiles">${profiles.map(p=>`<label><input type="checkbox" data-wf-profile="${text(p.id)}" ${selected.includes(p.id)?'checked':''}> ${text(p.name || p.model)}</label>`).join('') || '<p>尚无可用连接，请联系管理员配置；也可以选择仅检查官网。</p>'}</div>${s.profileError?`<p id="workflow-profile-error" class="sr-warning" role="alert">${text(s.profileError)}</p>`:''}</div>`:''}<div class="wf-call-confirm"><p>${mode==='full'?`预计最多 ${count} 次请求：${generation?'生成问题最多 3 次，':'复用项目已保存的 30 道问题，'}收集回答 ${30*selected.length} 次。`:'仅检查官网，不产生模型调用费用。'}</p>${mode==='full'?'<p>服务按实际用量计费，不自动充值；实际金额以服务商账单为准。开始后刷新、返回或离开页面不会撤销后台已提交的任务。</p><label><input id="workflow-cost-consent" type="checkbox" '+(s.costConsent?'checked':'')+'> 我已核对范围与预计请求，确认开始并承担实际费用</label>':''}</div><div id="workflow-start-feedback" aria-live="assertive" aria-atomic="true">${s.startError?`<p id="workflow-start-error" class="sr-warning" role="alert" tabindex="-1">${text(s.startError)}</p>`:s.startNotice?`<p id="workflow-start-notice" role="status" tabindex="-1">${text(s.startNotice)}</p>`:''}</div><div class="sr-actions"><button id="workflow-brand-back" data-wf="brand">← 返回修改信息</button><button class="primary" data-wf="start" ${s.pending || s.inlineProjectPending || !workspaceReady()?'disabled':''}>${s.pending?'正在提交…':'确认并开始诊断'}</button></div></section>`;
  }
  function focusWorkflow(id) {
    requestAnimationFrame(()=>{const target=document.getElementById(id);if(target){target.focus({preventScroll:true});target.scrollIntoView({block:'center',behavior:'smooth'});}});
  }
  function startError(message,field='workflow-start-error') {
    const s=session();s.startError=message;s.startNotice='';s.invalidField=field;
    if(field==='workflow-project'){s.projectError=message;s.inlineProjectOpen=true;}
    if(field==='workflow-profile-group')s.profileError=message;
    repaint();focusWorkflow(field==='workflow-project'?'workflow-project-error':field);
  }
  async function createInlineProject() {
    const s=session();if(s.inlineProjectPending || s.pending)return;
    const draft=inlineProjectDraft(s),clientName=(document.getElementById('workflow-inline-client-name')?.value ?? draft.clientName).trim(),projectName=(document.getElementById('workflow-inline-project-name')?.value ?? draft.projectName).trim();
    draft.clientID=document.getElementById('workflow-inline-client')?.value || draft.clientID;draft.clientName=clientName;draft.projectName=projectName;
    if(!projectName || draft.clientID==='__new__'&&!clientName || projectName.length>200 || clientName.length>200){s.inlineProjectError='请填写客户与项目名称，每个名称不超过 200 个字符。';s.inlineProjectOpen=true;repaint();focusWorkflow('workflow-inline-error');return;}
    const key=identity().key,previousMaximum=planMaximum(s),previousConsent=document.getElementById('workflow-cost-consent')?.checked ?? s.costConsent;
    s.inlineProjectPending=true;s.inlineProjectError='';s.startError='';repaint();
    try{
      let clientID=draft.clientID;
      if(clientID==='__new__'){
        const before=new Set(array(s.clients).map(c=>c.id)),result=await remoteWorkspace('client',{name:clientName});if(!sameContext(key))return;
        s.clients=array(result.clients);clientID=s.clients.find(c=>!before.has(c.id)&&c.name===clientName)?.id;
        if(!clientID)throw Error('客户创建结果未确认，请刷新项目列表后再操作。');draft.clientID=clientID;
      }
      const before=new Set(array(s.projects).map(p=>p.id)),result=await remoteWorkspace('project',{client_id:clientID,name:projectName});if(!sameContext(key))return;
      s.projects=array(result.projects);const created=s.projects.find(p=>!before.has(p.id)&&p.client_id===clientID&&p.name===projectName);
      if(!created)throw Error('项目创建结果未确认，请刷新项目列表后再操作。');
      s.projectID=created.id;s.inlineProjectPending=false;s.inlineProjectOpen=false;s.inlineProjectError='';s.projectError='';s.invalidField='';
      s.costConsent=planMaximum(s)>previousMaximum?false:previousConsent;
      s.startNotice=s.costConsent || (s.runMode || 'full')==='website'?'项目已创建并选用，点击“确认并开始诊断”继续。':'项目已创建并选用，请核对方案和费用后开始。';
      repaint();focusWorkflow('workflow-start-notice');
    }catch(e){if(sameContext(key)){s.inlineProjectPending=false;s.inlineProjectError=e.message+' 不会自动创建或开始诊断。';s.inlineProjectOpen=true;repaint();focusWorkflow('workflow-inline-error');}}
  }
  function progress(s) {
    return `<section class="sr-card sr-progress"><h2>正在读取官网</h2><p>${text(stageLabel(s.audit?.stage))}。完成后会进入信息确认。</p><progress></progress><div class="sr-actions"><button data-wf="preview-resume" ${s.pending?'disabled':''}>读取进度</button><button data-wf="url">返回官网输入</button></div></section>`;
  }
  function filterRows(s) {
    return array(s.diagnostics).filter(d=>(!s.filterClient || d.client_id===s.filterClient) && (!s.filterProject || d.project_id===s.filterProject) && (!s.filterMarket || (d.market || d.config?.market)===s.filterMarket));
  }
  function filters(s) {
    return `<div class="wf-filters"><label>客户 <select id="workflow-filter-client"><option value="">全部客户</option>${array(s.clients).map(c=>`<option value="${text(c.id)}" ${s.filterClient===c.id?'selected':''}>${text(c.name)}</option>`).join('')}</select></label><label>项目 <select id="workflow-filter-project"><option value="">全部项目</option>${array(s.projects).filter(p=>!s.filterClient || p.client_id===s.filterClient).map(p=>`<option value="${text(p.id)}" ${s.filterProject===p.id?'selected':''}>${text(p.name)}</option>`).join('')}</select></label><label>市场 <select id="workflow-filter-market"><option value="">全部市场</option><option value="CN" ${s.filterMarket==='CN'?'selected':''}>中国</option><option value="US" ${s.filterMarket==='US'?'selected':''}>美国</option></select></label></div>`;
  }
  function history(s) {
    const rows=filterRows(s);
    return `<section class="sr-card"><h2>历史诊断</h2>${filters(s)}<div class="sr-actions"><button data-wf="reload">刷新列表</button><button data-wf="projects">客户与项目</button></div>${s.workspaceLoading?'<p>正在读取历史…</p>':rows.length?`<div class="wf-history">${rows.map(d=>`<article class="sr-check"><h3><a href="#/w/${text(ws)}/research?diagnostic=${text(d.id)}">${text(d.brand || d.website || '诊断报告')}</a></h3><p>${text(statusLabel(d.status))} · ${text(d.market==='US'?'美国':d.market==='CN'?'中国':d.market)} · ${text(d.created_at)}</p><p>${text(array(s.projects).find(p=>p.id===d.project_id)?.name || '历史记录')}</p></article>`).join('')}</div>`:'<p>当前筛选下没有诊断记录。</p>'}</section>`;
  }
  function projects(s) {
    return `<section class="sr-card"><h2>客户与项目</h2><p>内部历史记录保留原格式，不用于新诊断或对外分享。客户项目用于诊断与报告交付。</p><form id="workflow-client-form"><label class="sr-field"><span>客户名称</span><input id="workflow-client-name" maxlength="200" required></label><button ${s.managementPending?'disabled':''}>创建客户</button></form><form id="workflow-project-form"><label class="sr-field"><span>所属客户</span><select id="workflow-project-client" required><option value="">请选择</option>${array(s.clients).filter(c=>!c.internal).map(c=>`<option value="${text(c.id)}">${text(c.name)}${c.internal?'（内部）':''}</option>`).join('')}</select></label><label class="sr-field"><span>项目名称</span><input id="workflow-project-name" maxlength="200" required></label><button ${s.managementPending?'disabled':''}>创建项目</button></form><h3>现有项目</h3>${array(s.projects).map(p=>`<p>${text(array(s.clients).find(c=>c.id===p.client_id)?.name)} / ${text(p.name)}${p.internal?'（内部，不可分享）':''}</p><details><summary>品牌、市场与已保存题集</summary><p>品牌：${text(p.config?.brand || '未建立')} · 市场：${text(p.config?.market || '未建立')} · 已保存 ${array(p.config?.question_set).length} 道问题</p><p>题集由诊断建立，并在同官网、品牌与市场范围内复用；复测会冻结原题。</p><ol>${array(p.config?.question_set).map(q=>`<li>${text(q)}</li>`).join('')}</ol></details>`).join('') || '<p>暂无项目。</p>'}<div class="sr-actions"><button data-wf="back-from-projects">返回诊断</button><button data-wf="history">查看历史</button></div></section>`;
  }
  function evidenceHTML(e) {
    return `<article class="sr-evidence"><h4>${text(e.evidence_id || e.id)}</h4><p>来源：${text(e.url)} · ${text(e.provided_at || e.captured_at)}</p><blockquote>${text(e.excerpt || '')}</blockquote><p>${text(e.locator || e.source_field || '')}</p></article>`;
  }
  function questionList(b) {
    const byID=new Map();for(const q of array(b.questions))byID.set(q.question_id,q);for(const a of array(b.answers))if(!byID.has(a.question_id))byID.set(a.question_id,{question_id:a.question_id,question:a.question,question_type:a.question_type});
    return [...byID.values()];
  }
  function safeLink(value) {
    try{const u=new URL(value);if(!['http:','https:'].includes(u.protocol) || u.username || u.password)return '';return u.href;}catch{return '';}
  }
  function answerHTML(a) {
    return `<article class="sr-card wf-answer"><h3>${text(a.platform || '未提供来源')} · ${text(a.status==='success'?'已返回':a.status==='failed'?'失败':a.status==='no_answer'?'未返回回答':'未知')}</h3><p>${text(a.entry || '')} · ${text(a.collected_at || '')}</p>${a.truncated || a.cached?'<p>本条标记为截断或缓存，不能作为完整新采样。</p>':''}<h4>原始回答</h4><pre>${text(a.raw_answer || '没有返回原文。')}</pre><h4>引用来源</h4>${array(a.citations).map(c=>{const url=safeLink(c.url);return url?`<p><a href="${text(url)}" target="_blank" rel="noopener noreferrer">${text(c.title || url)}</a>${c.support?`<blockquote>${text(c.support)}</blockquote>`:''}</p>`:'<p>无效引用地址已忽略。</p>';}).join('') || '<p>未提供可核验引用；不据此推断未访问任何来源。</p>'}<details><summary>本条完整证据</summary><pre>${text(JSON.stringify(a,null,2))}</pre></details></article>`;
  }
  function diagnosticMode(d) {if(d?.config?.mode==='website')return 'website';if(d?.config?.mode==='full' || d?.plan?.answer_calls>0 || array(d?.config?.profile_ids).length)return 'full';return d?.bundle?.run_manifest?.mode==='page'?'website':['full','retest','answers'].includes(d?.bundle?.run_manifest?.mode)?'full':'unknown';}
  function businessRule(r,b,d) {
    const entries={
      'R-access-search':['本次检测路径存在访问限制','核对本次页面的访问规则，并确认需要公开的内容可被读取。'],
      'R-structure-headings':['本次读取未识别出完整的页面标题','核对页面标题和主标题能否被直接读取。'],
      'R-access-response':['本次页面未能顺利读取','核对官网链接和该页面的访问情况。'],
      'R-access-extraction':['本次页面的主要内容未完整读出','核对重要介绍能否以直接可读的文字提供。'],
      'R-entity-identity':['本次页面的品牌信息不够清楚','核对页面是否明确说明品牌名称与业务。'],
      'R-entity-products':['本次页面的产品信息不够完整','补充本页产品名称、用途与适用条件。'],
      'R-trust-contact':['本次页面的联系信息不够完整','核对公开联系信息是否清楚可读。'],
      'R-trust-policy':['本次页面的政策信息不够完整','核对适用政策的公开入口与文字内容。']};
    let [title,action]=entries[r.rule_id] || ['本次页面有一项内容需要改善','结合下方页面证据，核对并完善这项内容。'];
    if(r.rule_id==='R-access-search')try{const u=new URL(d.website || d.config?.website || array(b.evidence).find(e=>e.url)?.url);const keys=[...u.searchParams.keys()];const evidence=array(r.evidence_ids).map(id=>array(b.evidence).find(e=>e.evidence_id===id)?.excerpt || '').join('\n');if(keys.some(k=>/^(gclid|fbclid|utm_.+)$/i.test(k) && evidence.includes(k+'=') && /Disallow:/i.test(evidence))){title='本次带广告参数的网址受访问规则限制';action='使用不含广告跟踪参数的官网链接重新核对。';}}catch{}
    return {title,action};
  }
  function reportHTML(d,full=false) {
    const b=d?.bundle;if(!finalReport(d,!d?.id && b?.run_manifest?.run_id==='shared-report'))return '<section class="sr-card"><h2>本次诊断尚未完成</h2><p>请读取最新进度；过程资料不作为完整报告。</p></section>';
    const score=scoreRules(array(b.rules)),m=b.run_manifest || {},fold=(label,html)=>`<details><summary>${text(label)}</summary>${html}</details>`;
    const value=score.total!==null?`${num(score.total)} / 100`:score.applicable_weight?`${num(score.lower)}–${num(score.upper)} / 100`:'证据不足，无法评分';
    const rules=array(b.rules),unknown=rules.filter(r=>r.status==='unknown'),passed=rules.filter(r=>r.status==='pass'),issues=rules.filter(r=>['fail','partial'].includes(r.status)&&array(r.evidence_ids).some(id=>array(b.evidence).some(e=>e.evidence_id===id))),questions=questionList(b),mode=diagnosticMode(d);
    const details=r=>fold('查看本次页面的依据',`<p>${text(r.reason)}</p><p>${text(r.rule_id)} · ${text(r.dimension)} · 权重 ${text(r.weight)}</p><p>${text(r.rubric)}</p><p>复核方法：${text(r.verification)}</p>${array(r.evidence_ids).map(id=>{const e=array(b.evidence).find(e=>e.evidence_id===id);return e?evidenceHTML(e):`<p>证据 ${text(id)}</p>`;}).join('')}`);
    const metrics=diagnosticMetrics(b),discovery=metrics.filter(g=>g.question_type==='discovery'),aggregate=k=>discovery.reduce((v,g)=>({numerator:v.numerator+g[k].numerator,denominator:v.denominator+g[k].denominator}),{numerator:0,denominator:0}),metric=k=>{const v=aggregate(k);return v.denominator?`${num(v.numerator/v.denominator*100)}%（${v.numerator} / ${v.denominator} 条有效回答）`:'暂无足够有效回答';};
    const noAnswers=!array(b.answers).some(a=>a.status==='success'&&!a.cached&&!a.truncated);
    const conclusions=issues.slice(0,2).map(r=>businessRule(r,b,d).title);if(mode==='full'&&noAnswers)conclusions.unshift('模型分析未完成：本次未取得模型回答。');else if(unknown.length)conclusions.push('部分内容仍需进一步核对。');
    return `<section class="sr-card"><h1>${text(m.brand || '品牌')} · GEO 诊断报告</h1>${d.status==='partial'&&mode==='full'?'<p>本报告保留已取得的结果，部分诊断步骤未完成。</p>':''}<h2>官网准备度</h2><p class="sr-score">${text(value)}</p><p>${score.coverage===null?'现有证据不足以评分。':`已核验${num(score.coverage*100)}%的评分项（按权重）。`}</p>${score.total===null&&score.applicable_weight?`<p>目前还不能确定总分：已确认${num(score.lower)}分，另有${num(score.upper-score.lower)}分待核实。现有证据还不足以确定单一分数。</p>`:''}<p>官网准备度与AI回答表现分别统计。</p><h2>主要结论</h2>${conclusions.slice(0,3).map(v=>`<p>${text(v)}</p>`).join('') || '<p>本次已核验项目中未发现明确缺口；这不覆盖未检测的页面。</p>'}${fold('检测范围与评分依据',`<p>本报告基于保存时取得的页面证据。规则分区间是现有证据的数学边界，不是推荐概率。市场沿用本次选择，未自动调整。</p><pre>${text(JSON.stringify(m,null,2))}</pre>`)}</section>${mode==='full'?`<section class="sr-card"><h2>AI回答表现</h2>${noAnswers?'<h3>模型分析未完成</h3><p>本次未取得模型回答，暂时无法判断实际提及和引用表现。</p>':`<p>自然发现问题中，本品牌被提及：${text(metric('mention'))}。</p><p>本品牌官网获得原生引用：${text(metric('owned_citation'))}。</p>`}${fold('回答统计口径',`<p>仅统计成功、未截断且非缓存的有效回答；提及仅使用明确判定，原生引用仅使用支持且完整捕获的引用。不同题型分别统计，不将原文网址当成原生引用。</p><pre>${text(JSON.stringify(metrics.map(({answers,...row})=>row),null,2))}</pre>`)}</section>`:''}${competitorHTML(b,fold,full)}<section class="sr-card"><h2>官网需要改善的内容</h2>${issues.map(r=>{const v=businessRule(r,b,d);return `<article class="sr-check"><h3>${text(v.title)}</h3><p>${text(v.action)}</p>${details(r)}</article>`;}).join('') || '<p>本次证据中没有足以列为明确问题的项目。</p>'}${fold(`已通过的检查（${passed.length}项）`,passed.map(details).join(''))}${fold(`还需要补充的信息（${unknown.length}项）`,`<p>部分内容仍需进一步核对，不将未知项直接列为优先整改问题。</p>${unknown.map(details).join('')}`)}</section><section class="sr-card"><h2>问题回答与引用证据</h2><p>逐题查看各来源的原文与引用；失败、截断与缺少引用分别保留。</p><div class="wf-questions">${questions.map((q,i)=>full?`<article><h3>${text(q.question)}</h3>${array(b.answers).filter(a=>a.question_id===q.question_id).map(answerHTML).join('') || '<p>尚无回答。</p>'}</article>`:`<button class="wf-question" data-wf-question="${i}"><span>${i+1}</span><b>${text(q.question)}</b><small>${array(b.answers).filter(a=>a.question_id===q.question_id && a.status==='success').length} 条已返回 · 查看原文与引用 →</small></button>`).join('') || (diagnosticMode(d)==='website'?'<p>本次选择仅检查官网，没有问答采集。</p>':diagnosticMode(d)==='full'?'<p>本次未取得模型回答。可读取最新进度，核对本次是否完整完成。</p>':'<p>尚无可显示的问题回答，请核对已保存的诊断范围。</p>')}</div>${fold('平台表现与统计口径',`<pre>${text(JSON.stringify(diagnosticMetrics(b).map(({answers,...row})=>row),null,2))}</pre>`)}</section><section class="sr-card"><h2>优先行动</h2>${issues.slice(0,3).map(r=>{const v=businessRule(r,b,d);return `<article class="sr-check"><h3>${text(v.action)}</h3><p>${text(v.title)}</p>${details(r)}</article>`;}).join('') || '<p>暂无有明确页面证据支持的优先整改行动。</p>'}</section><section class="sr-card"><h2>证据与附录</h2>${fold('页面与事实证据',array(b.evidence).map(evidenceHTML).join('') || '<p>未取得页面证据。</p>')}${fold('完整检查与行动记录',`<pre>${text(JSON.stringify({rules:b.rules,findings:b.findings,failure:d.failure},null,2))}</pre>`)}</section>`;
  }
  function competitorHTML(b,fold,full=false) {
    const performance=b.performance || {},models=array(performance.groups?.discovery?.models || performance.models),brands=new Map();
    for(const model of models)for(const v of array(model.brands)){
      const key=String(v.name);if(!brands.has(key))brands.set(key,{name:v.name,own:v.own,hits:0,total:0});
      const row=brands.get(key);row.hits+=Number(v.mentions)||0;row.total+=Number(v.denominator)||0;
    }
    const own=[...brands.values()].find(v=>v.own),competitors=[...brands.values()].filter(v=>!v.own),gaps=array(b.competitor_gaps).length?array(b.competitor_gaps):array(performance.gaps);
    return `<section class="sr-card"><h2>竞品差距</h2>${competitors.length?`<p>同一组自然发现问题中的实际提及，按有效回答分母合并；不代表推荐概率或市场排名。</p><table><thead><tr><th>品牌</th><th>被提及的有效回答</th><th>提及率</th></tr></thead><tbody>${[own,...competitors].filter(Boolean).map(v=>`<tr><td>${text(v.name)}${v.own?'（本品牌）':''}</td><td>${v.hits} / ${v.total}</td><td>${v.total?num(v.hits/v.total*100)+'%':'未知'}</td></tr>`).join('')}</tbody></table>`:'<p>尚无足够的配对竞品证据，不能据此判断没有差距。</p>'}${gaps.length?`<h3>竞品出现而本品牌缺席的问题</h3>${(full?gaps:gaps.slice(0,3)).map(g=>`<article class="sr-check"><h3>${text(g.prompt || g.question || '配对回答')}</h3><p>出现的竞品：${array(g.competitors).map(text).join('、') || text(g.competitor || g.name || '详见证据')}</p>${fold('查看配对证据与来源',`<pre>${text(JSON.stringify(g,null,2))}</pre>`)}</article>`).join('')}${!full && gaps.length>3?fold('查看其余'+(gaps.length-3)+'道问题',gaps.slice(3).map(g=>`<article class="sr-check"><h3>${text(g.prompt || g.question || '配对回答')}</h3><p>出现的竞品：${array(g.competitors).map(text).join('、') || text(g.competitor || g.name || '详见证据')}</p>${fold('查看配对证据与来源',`<pre>${text(JSON.stringify(g,null,2))}</pre>`)}</article>`).join('')):''}`:competitors.length?'<p>本次未观察到“竞品出现而本品牌缺席”的配对回答；不代表没有其他差距。</p>':''}</section>`;
  }
  function trendHTML(d) {
    const trend=d.trend;
    if(!trend)return '<section class="sr-card"><h2>复测趋势</h2><p>尚无可比基线。手动复测会冻结原题集与采样条件。</p></section>';
    const comparable=trend.comparable===true,points=trend.baseline && trend.current?[{label:'基线',...trend.baseline},{label:'本次',...trend.current}]:array(trend.points || trend.runs);
    const bound=v=>Number.isFinite(v)?Math.max(0,Math.min(100,v)):0;
    return `<section class="sr-card"><h2>复测趋势</h2><p>${comparable?'本次与基线条件可比；分数变化仍不能证明因果效果。':'本次与基线条件不完全一致，不能合并为统一提升数字。'}</p>${array(trend.differences).map(v=>`<p>${text(v)}</p>`).join('')}<table><thead><tr><th>诊断</th><th>准备度 / 证据边界</th><th>证据覆盖</th></tr></thead><tbody>${points.map(v=>`<tr><td>${text(v.label || v.created_at || v.sampled_at)}</td><td>${v.total!==null && Number.isFinite(v.total)?num(v.total):Number.isFinite(v.lower)&&Number.isFinite(v.upper)?num(v.lower)+'–'+num(v.upper):'未知'}<div class="wf-trend-bar" role="img" aria-label="规则分边界 ${text(v.lower)} 至 ${text(v.upper)}"><i style="width:${bound(v.lower)}%"></i><em style="left:${bound(v.lower)}%;width:${Math.max(0,bound(v.upper)-bound(v.lower))}%"></em></div></td><td>${Number.isFinite(v.coverage)?num(v.coverage*100)+'%':'未知'}</td></tr>`).join('')}</tbody></table>${comparable && trend.delta?`<p>规则分边界变化：下界 ${text(trend.delta.lower)}，上界 ${text(trend.delta.upper)}。不等同于曝光或推荐提升。</p>`:''}<details><summary>查看完整比较依据</summary><pre>${text(JSON.stringify(trend,null,2))}</pre></details></section>`;
  }
  function diagnosticProgress(d) {
    const p=d?.progress || {},count=(a,b)=>Number.isFinite(a)&&Number.isFinite(b)&&b>0?`${a} / ${b}`:'等待最新记录';
    const stage=d?.stage==='website' && d?.bundle && diagnosticMode(d)==='full'?'model_submitting':d?.stage;
    return `<p>${text(stageLabel(stage))}。任务保存在后台，可稍后从历史诊断返回。</p>${Number.isFinite(p.questions_generated)?`<p>问题已整理：${text(count(p.questions_generated,p.questions_planned))} · 回答已返回：${text(count(p.answers_complete,p.answers_planned))}</p>`:''}${p.last_read_error?'<p>正在核对最新执行进度，不会重新提交问答任务。</p>':''}<progress></progress>`;
  }
  function detailHTML(s,publicView=false) {
    const d=publicView?s.publicDetail:selectedDetail(s),readError=!publicView && ['error','mismatch'].includes(s.detailReadState),loading=!publicView && (s.detailLoading || s.detailReadState==='loading');
    const ready=(publicView || s.detailReadState==='ready') && finalReport(d,publicView);
    if(publicView && !ready)return '<section class="sr-card"><p>这份分享暂无完整报告，无法展示过程资料。</p></section>';
    const unknownRunner=d?.error_code==='runner_observation_lost';
    const heading=readError?'进度读取暂时中断':loading||!d?'正在读取最新进度':unknownRunner?'执行状态待确认':statusLabel(d.status);
    return `${!publicView?`<section class="sr-card wf-diagnostic-status"><h2>${text(heading)}</h2>${readError?'<p>当前页面暂时无法确认最新进度，后台任务可能仍在继续。重新读取只会查询状态，不会再次开始诊断。</p>':loading?'<p>正在核对当前任务，请稍候。</p>':d&&!terminal(d.status)?diagnosticProgress(d):unknownRunner?'<p>暂时无法确认问答任务的最终结果，不能据此认定任务已停止。请重新读取进度核对。</p>':''}${d?.error_code&&!readError?`<p>${text(d.failure?.reason || diagnosticError(d.error_code))}</p>`:''}${readError?`<details><summary>连接情况</summary><p>${text(s.detailReadError)}</p>${d?`<p>上次保存状态：${text(statusLabel(d.status))}</p>`:''}</details>`:''}<div class="sr-actions"><button data-wf="detail-refresh" ${loading?'disabled':''}>${readError?'重新读取进度':'读取最新进度'}</button><button data-wf="history">历史诊断</button></div></section>`:`<p>只读报告 · 有效期至 ${text(s.shareExpires)}</p>`}${ready?reportHTML(d):d?.legacy&&!readError&&!loading?legacyHTML(d):!readError&&!loading?'<section class="sr-card"><p>报告仍在整理，完成前不显示结论或提供成品导出。</p></section>':''}${ready?trendHTML(d):''}${ready?`<div class="sr-actions"><button class="primary" data-wf="html">导出完整报告（HTML）</button><button data-wf="json">下载证据 JSON</button><button data-wf="print">打印为 PDF</button>${!publicView?'<button data-wf="retest-confirm">手动复测</button>':''}</div>`:''}${!publicView && ready?shareHTML(s,d):''}${ready&&s.retestConfirm?retestHTML(d):''}`;
  }
  function legacyHTML(d) {
    const legacy=d.legacy || {}, payload=legacy.payload || legacy.audit || legacy.flow;
    if(d.legacy_type==='audit' && payload)return `<section class="sr-card"><h2>旧格式官网报告</h2><p>保留原格式，不与 v0.1 总分混算。</p></section>${oldAuditReport(payload)}`;
    if(d.legacy_type==='flow' && payload){geoActive=payload;return `<section class="sr-card"><h2>旧格式模型报告</h2></section>${researchResults()}`;}
    if(legacy.schema==='geo-readiness-v1' && payload)return oldAuditReport(payload);
    if(payload?.config?.providers){geoActive=payload;return researchResults();}
    if(legacy.audit)return `<section class="sr-card"><h2>旧格式官网报告</h2><p>保留原格式；不与 v0.1 诊断总分混算，也不能创建分享。</p></section>${oldAuditReport(legacy.audit)}`;
    if(legacy.flow){geoActive=legacy.flow;return `<section class="sr-card"><h2>旧格式模型报告</h2><p>保留原题卡和原始证据；不自动转成新诊断。</p></section>${researchResults()}`;}
    return '<section class="sr-card"><p>此历史记录没有可显示的报告。</p></section>';
  }
  function shareHTML(s,d) {
    const project=array(s.projects).find(p=>p.id===d.project_id),internal=project?.internal || array(s.clients).find(c=>c.id===project?.client_id)?.internal;
    return `<section class="sr-card"><h2>报告分享</h2><p>${internal?'内部项目不能创建对外分享。':'创建只读快照，有效期 30 天。持有链接的人可查看报告，不可启动任务或修改数据；可随时撤销。'}</p>${!internal?'<button data-wf="share">创建 30 天只读链接</button>':''}${s.shareURL?`<label class="sr-field"><span>请复制并妥善保存此链接</span><input id="workflow-share-url" readonly value="${text(s.shareURL)}"></label>`:''}${array(d.shares).map(v=>`<p>有效至 ${text(v.expires_at)} · ${v.revoked?'已撤销':`<button data-wf-revoke="${text(v.share_id)}">撤销此分享</button>`}</p>`).join('')}</section>`;
  }
  function retestHTML(d) {
    const n=array(d.config?.profile_ids || d.config?.providers).length,calls=d.config?.mode==='website'?0:30*n;
    return `<section class="sr-card wf-call-confirm"><h2>确认手动复测</h2><p>${calls?'复用原品牌、市场、模型和冻结的 30 道问题；重新采集，保留基线用于可比性检查。':'复用原官网、品牌与市场，重新检查并保留基线用于比较。'}</p><p>预计收集回答 ${calls} 次，不重新生成题目。${calls?'将按实际用量计费，实际金额以服务商账单为准。':'本次仅检查官网。'}</p><div class="sr-actions"><button data-wf="retest-cancel">取消</button><button class="primary" data-wf="retest" ${session().pending?'disabled':''}>${calls?'确认费用并开始复测':'确认并重新检查'}</button></div></section>`;
  }
  function pageHTML() {
    const s=session();syncRoute(s);
    if(s.screen==='import')return `<div class="sr-flow"><button data-wf="history">返回历史诊断</button></div>`+oldDiagnosticPage();
    if(s.screen==='legacy'){researchStep=3;return `<div class="sr-flow"><button data-wf="history">返回历史诊断</button></div>`+legacyPage();}
    if(s.screen==='shared')return `<div class="sr-flow" id="site-readiness"><div class="sr-hero"><p class="sr-brand">Signal GEO · 品牌诊断报告</p><h1>品牌诊断报告</h1></div>${s.message?`<p class="sr-warning" role="alert">${text(s.message)}</p>`:detailHTML(s,true)}</div>`;
    const title=s.screen==='history'?'历史诊断':s.screen==='projects'?'客户与项目':s.screen==='detail'?'诊断报告':s.screen==='confirm'?'确认品牌信息':s.screen==='models'?'确认诊断方案':s.screen==='progress'?'正在读取官网':'从官网开始一次诊断';
    let content;
    if(s.screen==='url')content=`<section class="sr-card"><form id="audit-url-form"><div class="sr-url">${field('品牌官网','audit-url',s.url)}<button class="primary" ${s.pending?'disabled':''}>分析官网</button></div><div class="sr-market"><label for="audit-market">市场</label><select id="audit-market"><option value="CN" ${geoMarket==='CN'?'selected':''}>中国</option><option value="US" ${geoMarket==='US'?'selected':''}>美国</option></select></div><p class="sr-muted">先核对品牌、产品与竞品，再确认诊断范围并开始。</p></form></section>`;
    else if(s.screen==='confirm')content=confirmation(s);
    else if(s.screen==='models')content=modelConfirm(s);
    else if(s.screen==='progress')content=progress(s);
    else if(s.screen==='history')content=history(s);
    else if(s.screen==='projects')content=projects(s);
    else content=detailHTML(s);
    return `<div class="sr-flow" id="site-readiness"><div class="sr-hero"><h1>${text(title)}</h1><p>从官网证据、真实回答到可执行行动。</p></div>${['url','confirm','models','progress','detail'].includes(s.screen)?steps(s):''}${s.message?`<p class="sr-warning" role="alert">${text(s.message)}</p>`:''}${capabilityNotice()}${content}${connectionHTML()}</div>`;
  }
  function accept(j,a) {
    if(!current(j))return;const s=session();s.audit=a;s.pending=false;s.message='';
    if(a.status==='awaiting_confirmation' || a.phase==='confirmation' || a.report){if(!s.draft)s.draft=initialDraft(a);s.screen='confirm';}
    else if(['queued','running'].includes(a.status)){s.screen='progress';pollTimer=setTimeout(()=>read(j,a.id),1000);}
    else{s.screen='confirm';s.draft ||= initialDraft(a);s.message='官网读取未完整完成，可以手动填写后继续。';}
    repaint();
  }
  function failure(j,e) {if(current(j)){clearTimeout(pollTimer);const s=session();s.pending=false;s.message=e.message+' 不会自动重新提交。';repaint();}}
  async function read(j,id) {if(!current(j))return;if(Date.now()>j.deadline){failure(j,new Error('等待超时，可手动读取进度。'));return;}try{accept(j,await remoteAudit('read',id));}catch(e){failure(j,e);}}
  async function analyze(refresh=false) {
    const s=session();if(s.pending)return;s.url=document.getElementById('audit-url')?.value || s.url;
    const url=normalize(s.url);if(!url){s.message='请输入公开、安全的 HTTP(S) 官网地址，不包含账号密码或私网地址。';repaint();return;}
    if(!identity().authenticated){s.message='请先展开下方团队登录，再读取官网。';repaint();return;}
    clearDetail(s);s.startRequestID=null;
    const j=job();s.url=url;s.pending=true;s.message='';s.audit=null;s.draft=null;s.screen='progress';
    repaint();try{accept(j,await remoteAudit('preview',{website:url,market:geoMarket,request_id:crypto.randomUUID(),...(refresh?{refresh:true}:{})}));}catch(e){s.screen='url';failure(j,e);}
  }
  function confirmed(s) {
    const sources=s.audit.candidates || {},rows=key=>[...new Set(String(s.draft[key] || '').split('\n').map(v=>v.trim()).filter(Boolean))].map(name=>{const original=array(sources[key]).find(c=>c.name===name);return {name,aliases:original?.aliases?.length?original.aliases:[name],...(original?{source_candidate_id:original.id}:{})};});
    const brand=s.draft.brand.trim(),original=sources.brand;
    return {brand:{name:brand,aliases:brand?(original?.name===brand && original.aliases?.length?original.aliases:[brand]):[]},products:rows('products'),competitors:rows('competitors'),context:s.draft.context || ''};
  }
  async function startDiagnostic() {
    const s=session();if(s.pending || s.inlineProjectPending)return;
    // Read the live form too: native touch controls need not depend on a bubbled change event.
    const project=document.getElementById('workflow-project'),consent=document.getElementById('workflow-cost-consent');
    if(project)s.projectID=project.value;
    if(consent)s.costConsent=consent.checked;
    const rendered=document.querySelectorAll('[data-wf-profile]');
    if(rendered.length)s.profileIDs=[...rendered].filter(el=>el.checked).map(el=>el.dataset.wfProfile);
    if(!workspaceReady()){startError('后台正在升级，暂时不能开始完整诊断。');return;}
    const mode=s.runMode || 'full',ids=selectedProfiles(s);
    if(!array(s.projects).some(p=>p.id===s.projectID&&!p.internal)){startError('请选择保存项目，或在本页创建团队项目后继续。','workflow-project');return;}
    if(mode==='full' && !s.draft.brand.trim()){startError('请返回上一步填写品牌名称。','workflow-brand-back');return;}
    if(mode==='full' && !ids.length){startError('请至少选择一家 AI。','workflow-profile-group');return;}
    const backendLimit=geoState.remote?.limits?.max_models;
    if(mode==='full' && Number.isFinite(backendLimit) && backendLimit>0 && ids.length>backendLimit){startError('后台正在更新，请稍后重新读取状态。已保留你的全部选择，不会减少后自动提交。','workflow-profile-group');return;}
    if(mode==='full' && !s.costConsent){startError('请勾选本次诊断的范围与费用确认。','workflow-cost-consent');return;}
    clearDetail(s);
    const j=job();s.pending=true;s.message='';s.startError='';s.startNotice='';s.startRequestID ||= crypto.randomUUID();repaint();
    const payload={audit_id:s.audit.id,confirmed:confirmed(s),profile_ids:mode==='full'?ids:[],project_id:s.projectID,request_id:s.startRequestID,mode};
    try{const d=await remoteWorkspace('start',payload);if(!current(j))return;if(!uuid(d.id))throw Error('提交结果未确认，请先核对历史诊断。');s.pending=false;s.startRequestID=null;s.detail=d;s.detailLoaded=true;s.detailID=d.id;s.workspaceLoaded=false;route('',d.id);}
    catch(e){if(current(j)){s.pending=false;startError(e.message+' 不会自动重新提交；结果未确认时请先核对历史诊断。');}}
  }
  function acceptDiagnostic(j,d) {
    if(!detailCurrent(j))return;
    if(d?.id!==j.detailID || d.bundle && !bundleMatches(d)){detailFailure(j,new Error('收到的资料与当前诊断不一致，已停止展示，请重新读取。'),true);return;}
    const s=session();
    if(terminal(d.status) && s.lastTerminalRefresh!==d.id){s.lastTerminalRefresh=d.id;s.workspaceLoaded=false;if(s.workspaceLoading)s.refreshWorkspaceAfterLoad=true;}
    s.detail=d;s.pending=false;s.message='';s.detailLoading=false;s.detailLoaded=true;s.detailReadState='ready';s.detailReadError='';
    if(!terminal(d.status))pollTimer=setTimeout(()=>pollDiagnostic(j),1500);repaint();
  }
  async function pollDiagnostic(j) {if(!detailCurrent(j))return;try{acceptDiagnostic(j,await remoteWorkspace('detail',j.detailID));}catch(e){detailFailure(j,e);}}
  async function manage(kind) {
    const s=session();if(s.managementPending)return;
    const name=document.getElementById(kind==='client'?'workflow-client-name':'workflow-project-name')?.value.trim(),client=document.getElementById('workflow-project-client')?.value;
    if(!name || kind==='project'&&!client){s.message='请填写名称并选择所属客户。';repaint();return;}
    const key=identity().key;s.managementPending=true;
    try{await remoteWorkspace(kind,kind==='client'?{name}:{name,client_id:client});if(!sameContext(key))return;s.managementPending=false;s.workspaceLoaded=false;await ensureWorkspace(s);}
    catch(e){if(sameContext(key)){s.managementPending=false;s.message=e.message;repaint();}}
  }
  async function retest() {
    const s=session();if(s.pending || !selectedDetail(s) || s.detailReadState!=='ready' || !finalReport(s.detail))return;
    const j=job();s.pending=true;s.retestRequestID ||= crypto.randomUUID();repaint();
    try{const d=await remoteWorkspace('retest',{id:s.detail.id,request_id:s.retestRequestID});if(!current(j))return;s.pending=false;s.retestConfirm=false;s.retestRequestID=null;s.workspaceLoaded=false;route('',d.id);}
    catch(e){failure(j,e);}
  }
  async function share(revokeID) {
    const s=session();if(s.sharing || !selectedDetail(s) || s.detailReadState!=='ready' || !finalReport(s.detail))return;const j={...identity(),sequence};s.sharing=true;
    try{
      const result=await remoteWorkspace(revokeID?'revoke':'share',revokeID?{share_id:revokeID}:{id:s.detail.id});if(!current(j))return;
      if(!revokeID){const token=result.share_token;if(typeof token!=='string')throw Error('分享响应无效，未生成链接。');const url=new URL(location.href);url.search='';url.hash='/w/demo/research?share='+encodeURIComponent(token);s.shareURL=url.href;}
      else s.shareURL='';
      s.detail=await remoteWorkspace('detail',s.detail.id);if(!current(j))return;s.sharing=false;repaint();
    }catch(e){if(current(j)){s.sharing=false;s.message=e.message;repaint();}}
  }
  function offlineHTML(d) {
    if(!finalReport(d,!d?.id && d?.bundle?.run_manifest?.run_id==='shared-report'))throw Error('诊断尚未完成，不能导出成品报告。');
    const css='body{font:15px/1.7 system-ui,sans-serif;max-width:1100px;margin:30px auto;padding:0 20px;color:#242235}section{margin:22px 0;padding:18px;border:1px solid #ddd;border-radius:10px}table{width:100%;border-collapse:collapse}td,th{padding:10px;border:1px solid #ddd;text-align:left}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f4fa;padding:12px}.sr-score{font-size:32px}h2,h3{break-after:avoid} @media print{body{margin:0}section{break-inside:avoid}}';
    return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none';style-src 'unsafe-inline';script-src 'none';img-src 'none'"><title>Signal GEO · 完整品牌诊断报告</title><style>${css}</style></head><body><p><b>Signal GEO · 品牌诊断报告</b></p><p>完整保存快照 · 可使用浏览器打印为 PDF。网站规则与实际回答表现分别解释。</p>${reportHTML(d,true)}${trendHTML(d)}<section><details><summary>完整保存快照与原始证据</summary><pre>${text(JSON.stringify(d,null,2))}</pre></details></section></body></html>`;
  }
  function download(content,name,type) {const u=URL.createObjectURL(new Blob([content],{type})),a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}
  async function exportReport(format) {
    const s=session(),key=identity().key,hash=location.hash;
    try{const shared=s.screen==='shared',expected=s.detailID;if(!shared && (!selectedDetail(s) || s.detailReadState!=='ready' || !finalReport(s.detail)))throw Error('诊断尚未完成，请先读取最新进度。');const d=shared?s.publicDetail:await remoteWorkspace('export',expected);if(identity().key!==key || location.hash!==hash)return;if((!shared && d?.id!==expected) || !finalReport(d,shared))throw Error('当前资料尚未完成或与所选诊断不一致，未导出。');
      if(format==='json')download(JSON.stringify(d,null,2),'brand-diagnostic.json','application/json;charset=utf-8');
      else if(format==='html')download(offlineHTML(d),'brand-diagnostic.html','text/html;charset=utf-8');
      else{const frame=document.createElement('iframe');frame.title='完整品牌诊断打印报告';frame.style.cssText='position:fixed;left:-10000px;width:1000px;height:1000px';frame.setAttribute('sandbox','allow-same-origin allow-modals');frame.srcdoc=offlineHTML(d);frame.onload=()=>{frame.contentWindow.focus();frame.contentWindow.print();setTimeout(()=>frame.remove(),1000);};document.body.append(frame);}
    }catch(e){if(identity().key===key){s.message=e.message;repaint();}}
  }
  function questionDialog(index) {
    const s=session(),d=s.screen==='shared'?s.publicDetail:selectedDetail(s);if(!finalReport(d,s.screen==='shared'))return;const b=d.bundle,q=questionList(b || {})[index];if(!q)return;
    const answers=array(b.answers).filter(a=>a.question_id===q.question_id);
    drawer(`<div class="card-head"><h2>${text(q.question)}</h2><button onclick="closeOverlay(false)">关闭</button></div>${answers.map(answerHTML).join('') || '<p>本题暂无返回。</p>'}`,'workflow-question',String(index));
  }
  geoPage=pageHTML;
  diagnosticPage=pageHTML;
  render=function(){legacyRender();if(!onWorkflow()){document.body.classList.remove('workflow-shared');return;}
    const s=session();syncRoute(s);const shared=s.screen==='shared';document.body.classList.add('research-mode');
    const view=document.getElementById('view');if(page==='diagnostic' && view)view.innerHTML=pageHTML();
    const nav=document.querySelector('aside nav');if(nav && !shared)nav.innerHTML=`<a href="#/w/${text(ws)}/research">＋ 从官网生成诊断</a><a href="#/w/${text(ws)}/research?view=history">历史诊断</a><a href="#/w/${text(ws)}/research?view=projects">客户与项目</a><a href="#/w/${text(ws)}/research?view=legacy">旧模型报告</a><a href="#/w/${text(ws)}/research?view=import">导入旧诊断证据</a><a href="#/w/${text(ws)}/overview">工作台概览 →</a>`;
    const header=document.querySelector('header .actions > span');if(header)header.textContent=shared?'品牌诊断报告':'品牌 GEO 诊断';
    const subtitle=document.querySelector('.page-head .subtitle');if(subtitle)subtitle.textContent='从官网、问题回答到证据与行动。';
    const notice=document.querySelector('main > .notice');if(notice)notice.textContent=shared?'此报告为只读快照。':'输入官网，确认信息与方案后开始诊断。';
    document.body.classList.toggle('workflow-shared',shared);
    Promise.resolve().then(ensure);
  };
  geoChange=function(m){if(!['CN','US'].includes(m))return;stop();return legacyChange(m);};
  document.addEventListener('submit',e=>{if(e.target.id==='audit-url-form'){e.preventDefault();void analyze();}if(e.target.id==='workflow-client-form'){e.preventDefault();void manage('client');}if(e.target.id==='workflow-project-form'){e.preventDefault();void manage('project');}});
  document.addEventListener('input',e=>{const s=session(),keys={'audit-brand':'brand','audit-products':'products','audit-competitors':'competitors','audit-context':'context'};if(e.target.id==='workflow-inline-client-name')inlineProjectDraft(s).clientName=e.target.value;else if(e.target.id==='workflow-inline-project-name')inlineProjectDraft(s).projectName=e.target.value;else if(e.target.id==='audit-url')s.url=e.target.value;else if(keys[e.target.id]&&s.draft)s.draft[keys[e.target.id]]=e.target.value;},true);
  document.addEventListener('change',e=>{
    const s=session(),id=e.target.id;
    if(id==='audit-market'){geoChange(e.target.value);return;}
    if(id==='workflow-inline-client'){inlineProjectDraft(s).clientID=e.target.value;s.inlineProjectOpen=true;repaint();return;}
    if(id==='workflow-project'){const before=planMaximum(s);s.projectID=e.target.value;if(planMaximum(s)>before)s.costConsent=false;s.projectError='';s.startError='';s.invalidField='';repaint();}
    if(id==='workflow-cost-consent')s.costConsent=e.target.checked;
    if(e.target.name==='workflow-mode'){s.runMode=e.target.value;s.costConsent=false;repaint();}
    if(e.target.hasAttribute('data-wf-profile')){const key=e.target.dataset.wfProfile;s.profileIDs=e.target.checked?[...new Set([...array(s.profileIDs),key])]:array(s.profileIDs).filter(v=>v!==key);s.profileError='';s.startError='';s.costConsent=false;repaint();}
    for(const [field,name] of [['workflow-filter-client','filterClient'],['workflow-filter-project','filterProject'],['workflow-filter-market','filterMarket']])if(id===field){s[name]=e.target.value;if(name==='filterClient')s.filterProject='';repaint();}
  },true);
  document.addEventListener('click',e=>{
    const question=e.target.closest('[data-wf-question]');if(question){questionDialog(Number(question.dataset.wfQuestion));return;}
    const rev=e.target.closest('[data-wf-revoke]');if(rev){void share(rev.dataset.wfRevoke);return;}
    const button=e.target.closest('[data-wf],[data-sr]');if(!button)return;
    const action=button.dataset.wf || button.dataset.sr,s=session();e.preventDefault();
    if(action==='profiles-all' || action==='profiles-none'){s.profileIDs=action==='profiles-all'?profileOptions(s).map(p=>p.id):[];s.profileError='';s.startError='';s.startNotice='';s.costConsent=false;repaint();return;}
    if(action==='confirm'){s.screen='models';s.message='';s.costConsent=false;s.startError='';s.startNotice='';repaint();return;}
    if(action==='refresh'){void analyze(true);return;}
    if(action==='inline-project'){void createInlineProject();return;}
    if(action==='start'){void startDiagnostic().catch(()=>{session().pending=false;startError('提交未能完成，请核对项目与方案后重试；不会自动开始诊断。');});return;}
    if(action==='preview-resume'&&s.audit?.id){void read(job(),s.audit.id);return;}
    if(['html','json','print'].includes(action)){void exportReport(action);return;}
    if(action==='share'){void share();return;}
    if(action==='retest'){void retest();return;}
    if(action==='retest-confirm' || action==='retest-cancel'){s.retestConfirm=action==='retest-confirm';repaint();return;}
    if(action==='detail-refresh'){stop();s.detailLoaded=false;s.detailLoading=false;void ensureDetail(s);return;}
    if(action==='history'){route('history');return;}
    if(action==='projects'){s.returnScreen=s.screen;s.screen='projects';repaint();return;}
    if(action==='reload'){s.workspaceLoaded=false;void ensureWorkspace(s);return;}
    if(action==='back-from-projects'){s.screen=s.returnScreen || 'history';s.returnScreen=null;repaint();return;}
    if(action==='brand'){s.screen='confirm';repaint();return;}
    if(action==='url'){stop();s.pending=false;s.screen='url';repaint();}
  },true);
  window.addEventListener('remote-enrichment-invalidated',()=>{stop();});
  window.addEventListener('hashchange',()=>{stop();if(onWorkflow()){const s=session();syncRoute(s);s.detailLoading=false;s.publicLoading=false;repaint();}});
  window.addEventListener('pagehide',stop);
  window.siteReadinessHTML=oldAuditHTML;
  window.siteReadinessReport=oldAuditReport;
  window.unifiedDiagnosticHTML=offlineHTML;
  window.unifiedDiagnosticReport=reportHTML;
  if(onWorkflow())repaint();
})();
