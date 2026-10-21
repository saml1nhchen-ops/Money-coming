/* Team-only HTTPS connection. The only persisted value is the backend origin. */
(() => {
  'use strict';
  if (window.SIGNAL_GEO_MODE !== 'team') return;
  const nativePage = geoPage, nativeRender = render, nativeStart = geoStart;
  const nativeSave = researchSave, nativePayload = geoPayload, nativeChange = geoChange;
  const nativeResults = researchResults, nativeSelect = researchSelect, nativeAdvanced = researchAdvanced;
  const connection = {url:'',expiresAt:0,busy:false,offline:false,verified:false,message:'',notice:'',rememberChoice:true,remembered:false,saved:false};
  let token = '', epoch = 0, expiryTimer = null, submission = false;
  const pending = new Set(), AUTH_PREFIX = 'signal-team-auth:v1:', MAX_TIMER = 2147483646;
  const error = (message, code = 'request_failed') => Object.assign(new Error(message), {code});
  const messages = {
    maintenance:'后台正在更新，已暂停新分析；已有任务和报告会保留。',
    invalid_request:'参数不符合后台要求，请核对官网、30 道题目及已选模型。', unauthorized:'团队密码错误或登录已失效，请重新登录。',
    origin_forbidden:'后台未允许当前页面来源，请管理员核对 Pages 跨域设置。', not_found:'接口或任务不存在，请刷新列表。',
    busy:'团队已有分析正在运行，请等待结束或明确停止后再开始。', request_too_large:'内容过长，请缩短背景或题目。',
    rate_limited:'请求过于频繁，请稍后手动重试。', session_limit_reached:'登录设备已达到后台上限，请退出不再使用的设备后重试。',
    session_store_unavailable:'后台保持登录服务暂不可用。已有凭据已保留；可稍后刷新，或主动取消保持登录后重新输入密码取得短期会话。',
    daily_budget_exceeded:'今日调用额度不足，请次日或管理员调整额度后再明确开始。',
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
  const authKey = url => AUTH_PREFIX + encodeURIComponent(url);
  function validRecord(value,url,expired=false) {
    try {
      const r = typeof value === 'string' ? JSON.parse(value) : value;
      if (!r || r.version !== 1 || r.backend_url !== url || origin(r.backend_url) !== url || typeof r.token !== 'string' || !/^[\x21-\x7e]{16,4096}$/.test(r.token) || typeof r.remembered !== 'boolean' || Object.keys(r).some(k=>!['version','backend_url','token','expires_at','remembered'].includes(k))) return null;
      const expiry = Date.parse(r.expires_at);
      return Number.isFinite(expiry) && (expired || expiry > Date.now()) ? r : null;
    } catch { return null; }
  }
  function readRecord(url) { try { const r = validRecord(localStorage.getItem(authKey(url)),url,true); if (r && Date.parse(r.expires_at) <= Date.now()) { forget(url,r.token); return null; } return r; } catch { return null; } }
  function forget(url,credential) {
    try { const r = validRecord(localStorage.getItem(authKey(url)),url,true); if (r?.token === credential) localStorage.removeItem(authKey(url)); } catch {}
  }
  function saveRecord(url,credential,expires_at,remembered) {
    try { localStorage.setItem(authKey(url),JSON.stringify({version:1,backend_url:url,token:credential,expires_at,remembered})); return true; } catch { return false; }
  }
  function rememberURL(url) { try { localStorage.setItem('signal-analysis-backend',url); } catch {} }
  function configuredOrigin() { try { return origin(window.SIGNAL_TEAM_BACKEND_URL || ''); } catch { return ''; } }
  try { connection.url = origin(localStorage.getItem('signal-analysis-backend') || ''); } catch {}
  if (!connection.url) connection.url = configuredOrigin();
  // The repair switch can select only the trusted deployment configuration, never a query-supplied host or credential.
  let repairRequested = false;
  const repairURL = new URL(location.href);
  if (repairURL.searchParams.has('reset_backend')) {
    if (repairURL.searchParams.getAll('reset_backend').length === 1 && repairURL.searchParams.get('reset_backend') === '1') {
      const configured = configuredOrigin();
      if (configured) { connection.url = configured; rememberURL(configured); repairRequested = true; }
    }
    repairURL.searchParams.delete('reset_backend'); history.replaceState(null,'',repairURL);
  }
  function capture() { if (page === 'research') researchSave(); }
  function paint() { if (page === 'research') render(); }
  function clear(message = '请重新登录。') {
    epoch++; for (const controller of pending) controller.abort(); pending.clear();
    token = ''; geoToken = ''; connection.expiresAt = 0; connection.offline = false; connection.busy = false; connection.verified = false; connection.saved = false; connection.remembered = false;
    clearTimeout(expiryTimer); clearTimeout(geoTimer); submission = false;
    connection.message = message; connection.notice = '';
    geoState = {runner:{configured:false,profiles:[]},runs:[]}; geoActive = null; geoPlanView = null;
    for (const draft of Object.values(geoDraft)) { delete draft.questions; delete draft.last; delete draft.loadedQuestions; }
    const questions = $('#geo-questions'); if (questions) questions.value = '';
    const password = $('#remote-password'); if (password) password.value = '';
    if ($('#overlay')?.dataset.kind === 'question') closeOverlay(false);
  }
  function current(generation) { if (generation !== epoch) throw error('连接状态已改变，旧请求结果已忽略。', 'cancelled'); }
  function expire() {
    if (token && connection.expiresAt <= Date.now()) { forget(connection.url,token); clear('登录已到期，请重新输入团队密码。'); paint(); return true; }
    return false;
  }
  function scheduleExpiry() {
    clearTimeout(expiryTimer); if (!token || expire()) return;
    const generation = epoch, credential = token, url = connection.url;
    expiryTimer = setTimeout(()=>{ if (generation === epoch && token === credential && connection.url === url && !expire()) scheduleExpiry(); },Math.min(connection.expiresAt-Date.now(),MAX_TIMER));
  }
  function ready() { return Boolean(token && connection.verified && !connection.offline && Date.now() < connection.expiresAt && geoState.remote?.ready === true); }
  function canRun(calls = 1) {
    const remaining = geoState.remote?.budget?.remaining;
    return ready() && !geoState.busy && !submission && Number.isFinite(remaining) && remaining >= calls;
  }
  async function revoke(url,credential) {
    const controller = new AbortController(), timer = setTimeout(()=>controller.abort(),20000);
    try { const r = await fetch(url+'/api/workspace/logout',{method:'POST',credentials:'omit',redirect:'error',cache:'no-store',signal:controller.signal,headers:{Authorization:'Bearer '+credential,'Content-Type':'application/json'},body:'{}'}); return r.ok; }
    catch { return false; } finally { clearTimeout(timer); }
  }
  async function request(path, body, settings = {}) {
    const generation = settings.generation ?? epoch, auth = settings.token ?? token, url = settings.url || connection.url;
    current(generation);
    const controller = new AbortController(); pending.add(controller);
    let timedOut = false;
    const paid = /\/api\/geo\/(start|sample)$/.test(path);
    const timer = setTimeout(() => { timedOut = true; controller.abort(); }, paid ? 135000 : 20000);
    try {
      let response;
      try {
        response = await fetch(url+path,{method:body === undefined ? 'GET' : 'POST',credentials:'omit',redirect:'error',cache:'no-store',signal:controller.signal,
          headers:{...(auth ? {Authorization:'Bearer '+auth} : {}),...(body === undefined ? {} : {'Content-Type':'application/json'})},...(body === undefined ? {} : {body:JSON.stringify(body)})});
      } catch {
        current(generation);
        const message = paid ? '提交结果未确认，请先刷新团队任务列表核对，避免重复提交收费。' : '后台连接失败，已保存的登录不会被删除。请检查网络后手动刷新。';
        throw Object.assign(error((timedOut ? '后台请求超时。' : '')+message+' 实际请求后台：'+url,'network'),{connectionFailure:true});
      }
      if (generation !== epoch && path === '/api/workspace/login') {
        try { const abandoned = await response.json(); if (validRecord({version:1,backend_url:url,token:abandoned.token,expires_at:abandoned.expires_at,remembered:!!abandoned.remembered},url)) void revoke(url,abandoned.token); } catch {}
        current(generation);
      }
      current(generation);
      if (settings.expectedStatus && response.status !== settings.expectedStatus) throw error('后台健康状态未确认。','health_unconfirmed');
      if (response.status === 401) {
        if (auth && auth === token && url === connection.url) { forget(url,auth); clear('登录已失效，请重新登录。'); paint(); }
        throw error(auth ? '登录已失效，请重新登录。' : '团队密码错误或登录失败，请重新输入。','unauthorized');
      }
      let data; try { data = await response.json(); } catch { throw Object.assign(error('后台响应格式错误，请联系管理员。','invalid_response'),{connectionFailure:true}); }
      current(generation);
      if (!response.ok) throw Object.assign(error(messages[data?.code] || '后台请求失败，请刷新状态或联系管理员。',data?.code || 'request_failed'),{connectionFailure:response.status >= 500});
      if (!data || typeof data !== 'object' || Array.isArray(data)) throw Object.assign(error('后台响应格式错误。','invalid_response'),{connectionFailure:true});
      return data;
    } finally { clearTimeout(timer); pending.delete(controller); }
  }
  async function restore(record) {
    if (!record || record.backend_url !== connection.url) return;
    clear('正在验证此设备保存的登录…');
    token = record.token; geoToken = 'team-session'; connection.expiresAt = Date.parse(record.expires_at); connection.saved = true; connection.remembered = record.remembered; connection.busy = true;
    const generation = epoch; scheduleExpiry(); paint();
    await geoRefresh(false);
    if (generation === epoch) { connection.busy = false; paint(); }
  }
  window.remoteBackendChanged = async function(value) {
    let url; try { url = origin(value); } catch { return; }
    if (url === connection.url) return;
    const wasAuthenticated = Boolean(token);
    capture(); clear('已切换后台，请验证此后台的登录。'); connection.url = url; rememberURL(url);
    const fullURL = document.querySelector('#remote-current-url code'); if (fullURL) fullURL.textContent = url;
    const record = readRecord(url); if (record) await restore(record); else if (wasAuthenticated) paint();
  };
  async function probeConfigured(url) {
    const generation = epoch; connection.busy = true; connection.message = '正在检查配置的后台：'+url; paint();
    try {
      const health = await request('/healthz',undefined,{token:'',generation,url,expectedStatus:200}); current(generation);
      connection.message = (health.capabilities?.remember_login === true ? '后台在线，支持最长 30 天保持登录；请首次输入团队密码。' : '后台在线，尚未声明长期登录支持；请首次输入团队密码。')+' 实际后台：'+url+'。此检查不代表模型或业务已就绪。';
    } catch (e) { if (generation === epoch) connection.message = '尚无法确认此设备到后台的连接：'+url+'。'+e.message; }
    finally { if (generation === epoch) { connection.busy = false; paint(); } }
  }
  window.remoteUseConfiguredBackend = async function() {
    const url = configuredOrigin();
    if (!url) { connection.message = '尚未配置可用的 HTTPS 后台地址。'; paint(); return; }
    capture(); clear('已选择配置的后台；如无已保存登录，请输入团队密码。');
    connection.url = url; rememberURL(url); paint();
    const record = readRecord(url); if (record) await restore(record); else await probeConfigured(url);
  };
  window.remotePasswordLogin = function() { capture(); clear('请重新输入团队密码。'); paint(); };
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
    return `<section class="ru-remote" id="remote-connection" aria-label="团队后台连接"><h2>连接团队分析后台</h2><p id="remote-current-url" class="mono" style="overflow-wrap:anywhere">当前后台：<code>${esc(connection.url || '尚未选择')}</code></p><button type="button" onclick="remoteUseConfiguredBackend()">使用已配置的后台</button><p>授权团队成员共享模型连接、报告和停止权限。B.AI 密钥由管理员配置在服务器，团队密码仅用于身份验证。</p>${token ? `<p><b>${connection.offline ? '后台连接失败' : !connection.verified ? '正在验证保存的登录' : s?.ready ? '团队后台已连接 · 运行依赖已就绪' : '团队已登录 · 暂不能开始分析'}</b> · 登录有效至 ${esc(new Date(connection.expiresAt).toLocaleString())}</p><p class="mono">${esc(connection.url)}</p><div class="actions"><button onclick="geoRefresh()">刷新后台状态</button><button onclick="remotePasswordLogin()">重新登录 / 更换后台</button><button onclick="remoteLogout()">退出此设备</button></div>` : `<form onsubmit="remoteLogin(event)"><label class="ru-field" for="remote-backend-url"><span>HTTPS 后台地址</span><input id="remote-backend-url" type="url" value="${esc(connection.url)}" placeholder="https://你的团队分析后台" autocomplete="off" onchange="remoteBackendChanged(this.value)" required></label><label class="ru-field" for="remote-password"><span>团队密码</span><input id="remote-password" type="password" autocomplete="off" required></label><label><input id="remote-remember" type="checkbox" ${connection.rememberChoice ? 'checked' : ''}> 在此设备保持登录（仅可信设备）</label><button class="primary" ${connection.busy ? 'disabled' : ''}>${connection.busy ? '正在登录…' : '连接并登录'}</button><button type="button" onclick="remoteLogout()">取消 / 退出此设备</button></form>`}<p class="ru-help">默认保持登录，后台支持时最长 30 天；只保存此后台的登录令牌和到期时间，不保存团队密码或供应商密钥。登录与恢复只读取状态，不自动开始分析。</p>${connection.notice ? `<p class="ru-help" role="status">${esc(connection.notice)}</p>` : ''}${connection.message ? `<p class="ru-warning" role="status">${esc(connection.message)}</p>` : ''}${token && s?.ready !== true ? `<p class="ru-warning">${esc(messages[s?.reason] || '后台就绪状态未知，请刷新或联系管理员。')}</p>` : ''}${token ? `<p>中国 / 美国分开测量 · ${esc(limits?.count ?? '未知')} 题 · 最多 ${esc(limits?.max_models ?? '未知')} 个模型 · 每题 ${esc(limits?.repeats ?? '未知')} 次</p><p>UTC ${esc(budget?.date ?? '未知日期')}：已预约 ${esc(budget?.reserved ?? '未知')} / ${esc(budget?.limit ?? '未知')} 次，剩余 ${esc(budget?.remaining ?? '未知')} 次。预约调用数不是实际账单，失败或停止不自动退还。</p>${!Number.isFinite(budget?.remaining) ? '<p class="ru-warning">预算状态未知，已暂停新付费任务，请刷新状态。</p>' : budget.remaining === 0 ? '<p class="ru-warning">今日额度已用完；已有报告仍可查看和导出。</p>' : ''}<details><summary>服务端固定模型与目录时间</summary>${geoState.runner.profiles.length ? geoState.runner.profiles.map(p => `<p><code>${esc(p.model)}</code> · ${esc(p.protocol)} · ${esc((p.markets || []).join('/'))} · 目录可见，调用兼容性需实际验证。</p>`).join('') : '<p>模型目录暂不可用，不代表测评分数为零。</p>'}<p>${esc(geoState.runner.fetched_at || '后台未提供目录时间')}</p></details>` : ''}</section>`;
  };
  window.remoteLogin = async function(event) {
    event?.preventDefault(); if (connection.busy) return;
    capture(); const field = $('#remote-password'); let password = field?.value || '';
    const remember = $('#remote-remember')?.checked !== false; connection.rememberChoice = remember;
    if (field) field.value = '';
    let generation;
    try {
      const url = origin($('#remote-backend-url')?.value.trim() || '');
      const previous = token && connection.url === url ? token : readRecord(url)?.token;
      clear('正在确认后台登录能力…'); generation = epoch; connection.url = url; rememberURL(url); connection.busy = true; paint();
      let supported = false, legacyConfirmed = false;
      try { const health = await request('/healthz',undefined,{token:'',generation,url,expectedStatus:200}); supported = health.capabilities?.remember_login === true; legacyConfirmed = !supported; }
      catch (e) { current(generation); }
      current(generation);
      const unconfirmed = '无法确认后台 '+url+' 的健康状态或长期登录能力；本次只按原登录协议尝试一次，不自动重试。';
      connection.notice = supported ? '' : legacyConfirmed ? '后台健康检查未声明长期登录支持，本次使用原协议 1 小时会话；服务器重启后需重新登录。' : unconfirmed;
      const result = await request('/api/workspace/login',supported ? {password,remember} : {password},{token:'',generation,url}); password = '';
      current(generation);
      const record = validRecord({version:1,backend_url:url,token:result.token,expires_at:result.expires_at,remembered:result.remembered === true},url);
      if (!record) throw error('后台登录响应无效，请联系管理员。');
      token = record.token; geoToken = 'team-session'; connection.expiresAt = Date.parse(record.expires_at); connection.remembered = record.remembered;
      if (remember) {
        connection.saved = saveRecord(url,token,result.expires_at,record.remembered);
        if (!connection.saved) connection.notice = '此设备无法保存登录，本次仅在当前页面有效。';
        else if (record.remembered) connection.notice = '已在此可信设备保持登录，到期时间以后台返回值为准。';
        else connection.notice = supported ? '已保存本次短期登录，仅至后台返回的到期时间有效；未获得 30 天持久登录。' : legacyConfirmed ? '后台健康检查未声明长期登录支持，已保存原协议 1 小时会话；服务器重启后需重新登录，未获得 30 天持久登录。' : unconfirmed+' 本次会话仅至后台实际返回的到期时间有效。';
      } else { if (previous) forget(url,previous); connection.notice = supported ? '本次仅在当前页面登录，不保存令牌。' : legacyConfirmed ? '本次使用原协议 1 小时会话，不保存令牌；服务器重启后需重新登录。' : unconfirmed+' 本次不保存令牌。'; }
      scheduleExpiry();
      if (previous && previous !== token) {
        const replacement = token;
        void revoke(url,previous).then(ok=>{ if (!ok && epoch === generation && token === replacement) { connection.notice += ' 旧会话撤销未确认，可能到期前仍有效。'; paint(); } });
      }
      await geoRefresh(false);
    } catch (e) { if (generation === undefined || generation === epoch) connection.message = e.message; }
    finally { password = ''; if (generation === undefined || generation === epoch) { connection.busy = false; paint(); } }
  };
  window.remoteLogout = async function() {
    capture(); const oldToken = token || readRecord(connection.url)?.token, url = connection.url;
    if (oldToken) forget(url,oldToken);
    clear('已清除此设备登录，正在确认后台注销。'); const generation = epoch; paint();
    const ok = oldToken ? await revoke(url,oldToken) : true;
    if (generation === epoch) { connection.message = ok ? '已退出，此会话已撤销；团队报告保留在后台。' : '已清除此设备登录，但后台注销未确认，原会话可能在到期前仍有效。'; paint(); }
  };
  geoFetch = async function(path, body) {
    const name = path.split('?')[0];
    if (name === 'resume') throw error('团队模式不提供续跑，请核对已有证据后明确开始新任务。', 'unsupported');
    if (!token || expire()) { clear('请先连接团队后台并登录。'); paint(); throw error('请先连接团队后台并登录。', 'unauthorized'); }
    if (['start','sample'].includes(name) && !ready()) throw error('后台连接尚未验证或未就绪，请先刷新状态后再明确开始分析。','not_ready');
    const generation = epoch;
    try { const result = await request('/api/geo/' + path,payload(name,body),{generation}); current(generation); if (name === 'state') connection.offline = false; return result; }
    catch (e) { if (generation === epoch && token) { if (e.connectionFailure) { connection.offline = true; connection.verified = false; } connection.message = e.message; } throw e; }
  };
  geoRefresh = async function(doCapture = true) {
    if (doCapture) capture(); if (!token) { paint(); return; }
    const generation = epoch;
    try {
      const state = await geoFetch('state'); current(generation);
      geoState = {...state,runner:{...state.runner,profiles:Array.isArray(state.runner?.profiles) ? state.runner.profiles : []},runs:Array.isArray(state.runs) ? state.runs : []};
      normalize(); connection.verified = true; connection.offline = false; connection.message = '';
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
  window.addEventListener('storage', event => {
    if (event.key !== null && event.key !== authKey(connection.url)) return;
    let raw; try { raw = localStorage.getItem(authKey(connection.url)); } catch { return; }
    if (event.key !== null && raw !== event.newValue) return; // Ignore a delayed event superseded by a newer login.
    const record = validRecord(raw,connection.url);
    if (record) { if (record.token !== token || Date.parse(record.expires_at) !== connection.expiresAt) void restore(record); }
    else if (token) {
      const old = validRecord(event.oldValue,connection.url,true);
      if (connection.saved || old?.token === token) { clear('此设备的登录已在另一个标签页退出。'); paint(); }
    }
  });
  window.addEventListener('pagehide', () => clear('页面已离开。'));
  window.addEventListener('pageshow', event => { if (event.persisted) { const record = readRecord(connection.url); if (record) void restore(record); else paint(); } });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && token) { if (!expire()) scheduleExpiry(); } });
  geoToken = ''; normalize(); if (page === 'research') paint();
  const remembered = readRecord(connection.url); if (remembered) void restore(remembered); else if (repairRequested) void probeConfigured(connection.url);
})();
