/* Team-only HTTPS connection. The only persisted value is the backend origin. */
(() => {
  'use strict';
  if (window.SIGNAL_GEO_MODE !== 'team') return;
  const nativePage = geoPage, nativeRender = render, nativeStart = geoStart;
  const nativeSave = researchSave, nativePayload = geoPayload, nativeChange = geoChange;
  const nativeResults = researchResults, nativeSelect = researchSelect, nativeAdvanced = researchAdvanced;
  const connection = {url:'', expiresAt:0, busy:false, offline:false, message:''};
  let token = '', epoch = 0, expiryTimer = null, submission = false;
  const pending = new Set();
  const error = (message, code = 'request_failed') => Object.assign(new Error(message), {code});
  const messages = {
    invalid_request:'参数不符合后台要求，请核对官网、30 道题目及已选模型。', unauthorized:'团队密码错误或登录已失效，请重新登录。',
    origin_forbidden:'后台未允许当前页面来源，请管理员核对 Pages 跨域设置。', not_found:'接口或任务不存在，请刷新列表。',
    busy:'团队已有分析正在运行，请等待结束或明确停止后再开始。', request_too_large:'内容过长，请缩短背景或题目。',
    rate_limited:'请求过于频繁，请稍后手动重试。', daily_budget_exceeded:'今日调用额度不足，请次日或管理员调整额度后再明确开始。',
    budget_unavailable:'后台预算记录不可用，已暂停新分析，请联系管理员。', backend_unavailable:'后台未就绪，请刷新状态或联系管理员。',
    missing_bai_key:'后台尚未配置 B.AI 密钥，请管理员在服务器配置；团队登录不会配置模型。',
    catalog_unavailable:'后台无法读取模型目录，请管理员检查网络和密钥后刷新。', model_catalog_unavailable:'后台模型目录不可用，请管理员检查网络和密钥。',
    required_models_unavailable:'后台缺少要求的固定文本模型，请管理员检查模型配置。', runtime_unavailable:'后台运行依赖未就绪，请联系管理员。',
    upstream_failed:'模型执行服务请求失败；已有证据保留，不会自动重试付费请求。'
  };
  function origin(value) {
    let url; try { url = new URL(value); } catch { throw error('请输入有效的 HTTPS 后台地址。', 'invalid_url'); }
    if (url.protocol !== 'https:' || url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw error('后台地址只能是 HTTPS 域名和可选端口，不含路径、账号或查询参数。', 'invalid_url');
    return url.origin;
  }
  try { connection.url = origin(localStorage.getItem('signal-analysis-backend') || ''); } catch {}
  function capture() { if (page === 'research') researchSave(); }
  function paint() { if (page === 'research') render(); }
  function clear(message = '已退出，请重新登录。') {
    epoch++; for (const controller of pending) controller.abort(); pending.clear();
    token = ''; geoToken = ''; connection.expiresAt = 0; connection.offline = false; connection.busy = false;
    clearTimeout(expiryTimer); clearTimeout(geoTimer); submission = false;
    connection.message = message;
    geoState = {runner:{configured:false,profiles:[]},runs:[]}; geoActive = null; geoPlanView = null;
    for (const draft of Object.values(geoDraft)) { delete draft.questions; delete draft.last; delete draft.loadedQuestions; }
    const questions = $('#geo-questions'); if (questions) questions.value = '';
    const password = $('#remote-password'); if (password) password.value = '';
    if ($('#overlay')?.dataset.kind === 'question') closeOverlay(false);
  }
  function current(generation) { if (generation !== epoch) throw error('连接状态已改变，旧请求结果已忽略。', 'cancelled'); }
  function ready() { return Boolean(token && !connection.offline && Date.now() < connection.expiresAt && geoState.remote?.ready === true); }
  function canRun(calls = 1) {
    const remaining = geoState.remote?.budget?.remaining;
    return ready() && !geoState.busy && !submission && Number.isFinite(remaining) && remaining >= calls;
  }
  async function request(path, body, settings = {}) {
    const generation = settings.generation ?? epoch, auth = settings.token ?? token;
    current(generation);
    const controller = new AbortController(); pending.add(controller);
    let timedOut = false;
    const paid = /\/api\/geo\/(start|sample)$/.test(path);
    const timer = setTimeout(() => { timedOut = true; controller.abort(); }, paid ? 135000 : 20000);
    try {
      let response;
      try {
        response = await fetch((settings.url || connection.url) + path, {method:body === undefined ? 'GET' : 'POST',
          credentials:'omit', redirect:'error', cache:'no-store', signal:controller.signal,
          headers:{...(auth ? {Authorization:'Bearer ' + auth} : {}), ...(body === undefined ? {} : {'Content-Type':'application/json'})},
          ...(body === undefined ? {} : {body:JSON.stringify(body)})});
      } catch {
        current(generation);
        const message = paid ? '提交结果未确认，请先刷新团队任务列表核对，避免重复提交收费。' : '后台连接失败，请检查地址、网络与服务状态后手动刷新。';
        throw Object.assign(error(timedOut ? '后台请求超时。' + message : message, 'network'), {connectionFailure:true});
      }
      current(generation);
      if (response.status === 401) {
        if (auth && auth === token) { clear('登录已失效，请重新登录。'); paint(); }
        throw error(auth ? '登录已失效，请重新登录。' : '团队密码错误或登录失败，请重新输入。', 'unauthorized');
      }
      let data; try { data = await response.json(); } catch { throw Object.assign(error('后台响应格式错误，请联系管理员。', 'invalid_response'), {connectionFailure:true}); }
      current(generation);
      if (!response.ok) throw error(messages[data?.code] || '后台请求失败，请刷新状态或联系管理员。', data?.code || 'request_failed');
      if (!data || typeof data !== 'object' || Array.isArray(data)) throw Object.assign(error('后台响应格式错误。', 'invalid_response'), {connectionFailure:true});
      return data;
    } finally { clearTimeout(timer); pending.delete(controller); }
  }
  function normalize() {
    const draft = geoDraft[geoMarket], profiles = geoState.runner.profiles || [], seen = new Set();
    draft.providers = [...new Set(draft.providers || [])].filter(id => {
      const p = profiles.find(p => p.id === id && p.markets?.includes(geoMarket));
      const vendor = p?.manufacturer || p?.model;
      if (!p || seen.has(vendor) || seen.size >= 2) return false;
      seen.add(vendor); return true;
    });
    if (!draft.providers.includes(draft.generator)) draft.generator = draft.providers[0] || '';
    draft.count = '30'; draft.repeats = '1';
  }
  const common = ['website','market','brand_aliases','skus','competitors','focus','context','count','repeats','providers','generator'];
  function payload(name, body) {
    if (body === undefined) return undefined;
    const fields = {inspect:['website','market'],plan:[...common,'generate_only','manual'],start:[...common,'generate_only'],sample:[...common,'prompts'],analyze:['id','brand_aliases','skus','competitors'],stop:['id']}[name];
    if (!fields) throw error('该操作不属于团队接口。');
    return Object.fromEntries(fields.filter(key => Object.hasOwn(body,key)).map(key => [key,body[key]]));
  }
  window.remoteCanRun = canRun;
  window.remoteNormalizeSelection = normalize;
  window.remoteConnectionMarkup = function() {
    const s = geoState.remote, budget = s?.budget, limits = s?.limits;
    return `<section class="ru-remote" id="remote-connection" aria-label="团队后台连接"><h2>连接团队分析后台</h2><p>授权团队成员共享模型连接、报告和停止权限。B.AI 密钥由管理员配置在服务器，团队密码仅用于身份验证。</p>${token ? `<p><b>${connection.offline ? '后台连接失败' : s?.ready ? '团队后台已连接 · 运行依赖已就绪' : '团队已登录 · 暂不能开始分析'}</b> · 登录有效至 ${esc(new Date(connection.expiresAt).toLocaleTimeString())}</p><p class="mono">${esc(connection.url)}</p><div class="actions"><button onclick="geoRefresh()">刷新后台状态</button><button onclick="remoteLogout()">退出 / 更换后台</button></div>` : `<form onsubmit="remoteLogin(event)"><label class="ru-field" for="remote-backend-url"><span>HTTPS 后台地址</span><input id="remote-backend-url" type="url" value="${esc(connection.url)}" placeholder="https://你的团队分析后台" autocomplete="off" required></label><label class="ru-field" for="remote-password"><span>团队密码</span><input id="remote-password" type="password" autocomplete="off" required></label><button class="primary" ${connection.busy ? 'disabled' : ''}>${connection.busy ? '正在登录…' : '连接并登录'}</button></form>`}<p class="ru-help">只记住后台地址；密码和令牌仅在当前页面内存。刷新后重新登录。登录只读取状态，不自动生成题目或调用聊天模型。</p>${connection.message ? `<p class="ru-warning" role="status">${esc(connection.message)}</p>` : ''}${token && s?.ready !== true ? `<p class="ru-warning">${esc(messages[s?.reason] || '后台就绪状态未知，请刷新或联系管理员。')}</p>` : ''}${token ? `<p>中国 / 美国分开测量 · ${esc(limits?.count ?? '未知')} 题 · 最多 ${esc(limits?.max_models ?? '未知')} 个模型 · 每题 ${esc(limits?.repeats ?? '未知')} 次</p><p>UTC ${esc(budget?.date ?? '未知日期')}：已预约 ${esc(budget?.reserved ?? '未知')} / ${esc(budget?.limit ?? '未知')} 次，剩余 ${esc(budget?.remaining ?? '未知')} 次。预约调用数不是实际账单，失败或停止不自动退还。</p>${!Number.isFinite(budget?.remaining) ? '<p class="ru-warning">预算状态未知，已暂停新付费任务，请刷新状态。</p>' : budget.remaining === 0 ? '<p class="ru-warning">今日额度已用完；已有报告仍可查看和导出。</p>' : ''}<details><summary>服务端固定模型与目录时间</summary>${geoState.runner.profiles.length ? geoState.runner.profiles.map(p => `<p><code>${esc(p.model)}</code> · ${esc(p.protocol)} · ${esc((p.markets || []).join('/'))} · 目录可见，调用兼容性需实际验证。</p>`).join('') : '<p>模型目录暂不可用，不代表测评分数为零。</p>'}<p>${esc(geoState.runner.fetched_at || '后台未提供目录时间')}</p></details>` : ''}</section>`;
  };
  window.remoteLogin = async function(event) {
    event?.preventDefault(); if (connection.busy) return;
    capture(); const field = $('#remote-password'); let password = field?.value || '';
    if (field) field.value = '';
    let generation;
    try {
      const url = origin($('#remote-backend-url')?.value.trim() || '');
      clear(''); generation = epoch; connection.url = url; localStorage.setItem('signal-analysis-backend',url);
      connection.busy = true; paint();
      const result = await request('/api/workspace/login',{password},{token:'',generation}); password = '';
      current(generation); const expires = Date.parse(result.expires_at);
      if (typeof result.token !== 'string' || !result.token || !Number.isFinite(expires) || expires <= Date.now()) throw error('后台登录响应无效，请联系管理员。');
      token = result.token; geoToken = 'team-session'; connection.expiresAt = expires;
      expiryTimer = setTimeout(() => { capture(); clear('登录已到期，请重新登录。'); paint(); }, Math.min(expires-Date.now(),2147483647));
      await geoRefresh(false);
    } catch (e) { if (generation === undefined || generation === epoch) connection.message = e.message; }
    finally { password = ''; if (generation === undefined || generation === epoch) { connection.busy = false; paint(); } }
  };
  window.remoteLogout = async function() {
    capture(); const oldToken = token, url = connection.url;
    clear('已退出，团队报告仍保存在后台。'); const generation = epoch; connection.busy = true; paint();
    try { if (oldToken) await request('/api/workspace/logout',{}, {token:oldToken,url,generation}); }
    catch (e) { if (generation === epoch) connection.message = '已清除本页登录，后台注销未确认；原会话最迟在有效期结束时失效。'; }
    finally { if (generation === epoch) { connection.busy = false; paint(); } }
  };
  geoFetch = async function(path, body) {
    const name = path.split('?')[0];
    if (name === 'resume') throw error('团队模式不提供续跑，请核对已有证据后明确开始新任务。', 'unsupported');
    if (!token || Date.now() >= connection.expiresAt) { clear('请先连接团队后台并登录。'); paint(); throw error('请先连接团队后台并登录。', 'unauthorized'); }
    const generation = epoch;
    try { const result = await request('/api/geo/' + path,payload(name,body),{generation}); current(generation); if (name === 'state') connection.offline = false; return result; }
    catch (e) { if (generation === epoch && token) { if (e.connectionFailure) connection.offline = true; connection.message = e.message; } throw e; }
  };
  geoRefresh = async function(doCapture = true) {
    if (doCapture) capture(); if (!token) { paint(); return; }
    const generation = epoch;
    try {
      const state = await geoFetch('state'); current(generation);
      geoState = {...state,runner:{...state.runner,profiles:Array.isArray(state.runner?.profiles) ? state.runner.profiles : []},runs:Array.isArray(state.runs) ? state.runs : []};
      normalize(); connection.message = '';
    } catch (e) { if (generation === epoch) connection.message = e.message; }
    paint();
  };
  geoLoad = async function() { paint(); };
  geoPayload = function() { const body = nativePayload(); normalize(); const d = geoDraft[geoMarket]; return {...body,market:geoMarket,count:30,repeats:1,providers:[...d.providers],generator:d.generator}; };
  geoOptions = function() { const d = geoDraft[geoMarket]; return geoState.runner.profiles.filter(p => d.providers?.includes(p.id) && p.markets?.includes(geoMarket)).map(p => `<option value="${esc(p.id)}" ${d.generator === p.id ? 'selected' : ''}>${esc(p.model)}</option>`).join('') || '<option value="">先选择回答模型</option>'; };
  researchToggle = function(vendor) {
    capture(); const d = geoDraft[geoMarket], group = researchChoices().find(g => g.vendor === vendor); if (!group) return;
    const ids = new Set(group.ps.map(p => p.id));
    if (group.selected) d.providers = d.providers.filter(id => !ids.has(id));
    else if ((d.providers || []).length >= 2) { researchMessage = '最多选择两家厂商，每家一个固定模型。'; paint(); return; }
    else d.providers = [...(d.providers || []),group.p.id];
    researchMessage = ''; normalize(); paint();
  };
  geoChange = function(market) { if (!['CN','US'].includes(market)) return; nativeChange(market); normalize(); paint(); };
  geoStart = async function(manual, generateOnly = false) {
    if (submission) return;
    capture(); normalize(); const d = geoDraft[geoMarket], providers = d.providers || [];
    const prompts = (d.questions || '').split('\n').map(p => p.trim()).filter(Boolean), calls = manual ? 30*providers.length : generateOnly ? 3 : 3+30*providers.length;
    let message = '';
    if (!token) message = '请先连接团队后台并登录。';
    else if (!ready()) message = '后台未就绪或连接已中断，请查看连接状态并刷新。';
    else if (!providers.length || providers.length > 2) message = '请选择 1–2 个固定文本模型。';
    else if (manual && (prompts.length !== 30 || new Set(prompts).size !== 30 || prompts.some(p => p.length > 4000))) message = '手工采样需要恰好 30 道不同问题，每题不超过 4000 字符。';
    else if (!canRun(calls)) message = '后台已有任务或调用额度不足，请刷新状态并核对计划。';
    if (message) { researchMessage = message; paint(); return; }
    submission = true; const generation = epoch; paint();
    try { await nativeStart(manual,generateOnly); } finally { if (generation === epoch) { submission = false; paint(); } }
  };
  researchSelect = function() { return nativeSelect().replace(/<a class="button primary" href="http:\/\/127\.0\.0\.1:8771[^>]*>[^<]*<\/a>/g,'<a class="button primary" href="#remote-connection">连接团队后台</a>'); };
  researchAdvanced = function() { return nativeAdvanced().replace(/<p><a href="http:\/\/127\.0\.0\.1:8771[\s\S]*?<\/p>/g,'<p class="ru-help">供应商密钥仅在服务器配置；目录可见不等于实际调用已验证。每家使用一个固定模型，不自动切换或重试。</p>'); };
  researchResults = function() { const html = nativeResults().replace(/<button onclick="geoResume\(\)">[^<]*<\/button>/g,''); return html + (geoActive && !geoActive.report && typeof questionCards === 'function' ? questionCards(geoActive) : ''); };
  geoPage = function() { return remoteConnectionMarkup() + nativePage(); };
  function consumeDraft() {
    if (page !== 'research') return; const url = new URL(location.href), params = url.searchParams, brand = params.get('draft_brand');
    if (brand && brand.length <= 200) {
      geoMarket = params.get('draft_market') === 'US' ? 'US' : 'CN'; const draft = geoDraft[geoMarket]; draft.brand = brand;
      const website = params.get('draft_website') || '';
      try { const parsed = new URL(website); if (parsed.protocol === 'https:' && !parsed.username && !parsed.password && website.length <= 500) draft.website = parsed.href; } catch {}
      for (const field of ['skus','context']) { const value = params.get('draft_' + field); if (value && value.length <= 2000) draft[field] = value; }
      researchStep = 1;
    }
    if ([...params.keys()].some(key => key.startsWith('draft_'))) { for (const key of [...params.keys()]) if (key.startsWith('draft_')) params.delete(key); history.replaceState(null,'',url); }
  }
  render = function() {
    consumeDraft(); nativeRender(); if (page !== 'research') return;
    const selected = geoDraft[geoMarket].providers?.length || 0;
    for (const button of document.querySelectorAll('[onclick^="geoStart("],[onclick="geoGenerateOnly()"]')) {
      const action = button.getAttribute('onclick'), calls = action === 'geoGenerateOnly()' ? 3 : action.includes('true') ? 30*selected : 3+30*selected;
      button.disabled = !selected || !canRun(calls);
    }
    // Team entry never asks a browser for vendor credentials or exposes loopback setup.
    for (const link of document.querySelectorAll('aside nav a[href*="127.0.0.1"]')) { link.href = '#remote-connection'; link.textContent = '⚙ 团队后台连接'; link.removeAttribute('target'); }
    for (const link of document.querySelectorAll('#view a[href*="127.0.0.1"]')) { link.href = '#remote-connection'; link.textContent = '连接团队后台'; link.removeAttribute('target'); }
    const tag = document.querySelector('.header-right .tag'); if (tag) tag.textContent = token ? '团队共享工作台' : '团队模式 · 待登录';
  };
  window.addEventListener('pagehide', () => clear('页面已离开，请重新登录团队后台。'));
  window.addEventListener('pageshow', event => { if (event.persisted) paint(); });
  geoToken = ''; normalize(); if (page === 'research') paint();
})();
