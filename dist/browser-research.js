/* The original three-step research UI, backed by the in-memory browser engine. */
(() => {
  'use strict';
  const broker = window.browserBaiResearchBroker, factory = window.BrowserResearchEngine;
  if (!broker || !factory) return;
  const nativeFetch = geoFetch, nativeLoad = geoLoad, nativeRefresh = geoRefresh;
  const nativeOpen = geoOpen, nativeOptions = geoOptions, nativeToggle = researchToggle;
  const nativeModel = researchModel, nativeSave = researchSave, nativePayload = geoPayload;
  const nativePage = geoPage, nativeBrand = researchBrand, nativeSelect = researchSelect;
  const nativeResults = researchResults, beforeRender = render;
  let activeId = null, queued = false, engine;
  const browser = () => typeof geoBrowser === 'function' && geoBrowser();
  function normalizeSelection() {
    const d = geoDraft[geoMarket], all = geoState.runner.profiles || [], chosen = [], vendors = new Set();
    for (const id of d.providers || []) {
      const p = all.find(p => p.id === id && p.markets.includes(geoMarket));
      if (p && !vendors.has(p.manufacturer) && chosen.length < 2) { chosen.push(id); vendors.add(p.manufacturer); }
    }
    d.providers = chosen;
    if (!chosen.includes(d.generator)) d.generator = chosen[0] || '';
    d.count = '30'; d.repeats = '1';
  }
  function snapshot() {
    if (!browser() || !engine) return;
    geoState = engine.state();
    geoToken = geoState.runner.configured ? 'browser-research' : '';
    normalizeSelection();
    if (activeId) {
      try {
        const job = engine.get(activeId);
        geoActive = job.config.market === geoMarket ? job : null;
        if (geoActive && job.prompts.length) {
          const d = geoDraft[geoMarket], version = job.id + ':' + job.prompts.length;
          if (d.loadedQuestions !== version) { d.questions = job.prompts.map(p => p.text).join('\n'); d.loadedQuestions = version; }
        }
      } catch { geoActive = null; activeId = null; }
    }
  }
  function refreshView() {
    if (!browser()) return;
    if (page === 'research') geoCapture();
    snapshot();
    if (page === 'research') render();
  }
  function schedule() {
    if (queued) return;
    queued = true;
    queueMicrotask(() => { queued = false; refreshView(); });
  }
  if (browser()) {
    for (const draft of Object.values(geoDraft)) { delete draft.questions; delete draft.last; delete draft.loadedQuestions; }
  }
  engine = factory.create({transport: broker, onUpdate: schedule});
  broker.subscribe(event => {
    if (event.type === 'reset') {
      if (document.getElementById('overlay')?.dataset.kind === 'question') closeOverlay(false);
      engine.reset(); activeId = null; geoActive = null; geoPlanView = null; clearTimeout(geoTimer);
      for (const draft of Object.values(geoDraft)) { delete draft.questions; delete draft.last; delete draft.loadedQuestions; }
      const questions = document.getElementById('geo-questions'); if (questions) questions.value = '';
    }
    schedule();
  });
  window.browserResearchConnect = function() {
    if (!browser()) { window.open('http://127.0.0.1:8771/#/w/demo/bai', '_blank', 'noopener'); return; }
    researchSave(); window.browserBaiOpen();
  };
  window.browserResearchClear = function() { if (browser()) window.browserBaiClear(); };
  geoFetch = async function(path, body) {
    if (!browser()) return nativeFetch(path, body);
    const [name, query = ''] = path.split('?'), id = new URLSearchParams(query).get('id');
    if (body && JSON.stringify(body) !== JSON.stringify(broker.safeDraft(body))) throw Error('测量信息包含当前密钥，请移除后再操作。');
    switch (name) {
      case 'state': return engine.state();
      case 'plan': return engine.plan(body, {manual: Boolean(body?.manual)});
      case 'start': { const job = engine.start(body); activeId = job.id; return job; }
      case 'sample': { const job = engine.sample(body); activeId = job.id; return job; }
      case 'run': activeId = id; return engine.get(id);
      case 'export': return engine.export(id);
      case 'stop': return engine.stop(body?.id);
      case 'analyze': { const job = engine.reanalyze(body); activeId = job.id; return job; }
      case 'resume': throw Error('浏览器模式不支持续跑。请先导出已有证据，再明确开始新任务。');
      default: throw Error('浏览器模式不提供该接口，也不会抓取官网或产生官网技术分数。');
    }
  };
  geoLoad = async function() { if (!browser()) return nativeLoad(); snapshot(); if (page === 'research') render(); };
  geoRefresh = async function(capture = true) {
    if (!browser()) return nativeRefresh(capture);
    if (capture && page === 'research') geoCapture(); snapshot(); if (page === 'research') render();
  };
  geoOpen = async function(id) {
    if (!browser()) return nativeOpen(id);
    try {
      geoCapture(); clearTimeout(geoTimer);
      const job = engine.get(id); if (job.config.market !== geoMarket) return;
      activeId = id; snapshot(); if (page === 'research') render();
    } catch (error) { researchMessage = error.message; if (page === 'research') render(); }
  };
  researchSave = function() { nativeSave(); if (browser()) normalizeSelection(); };
  geoCapture = researchSave;
  geoPayload = function() { const body = nativePayload(); if (browser()) { normalizeSelection(); body.count = 30; body.repeats = 1; body.providers = [...geoDraft[geoMarket].providers]; body.generator = geoDraft[geoMarket].generator; } return body; };
  geoOptions = function() {
    if (!browser()) return nativeOptions();
    const d = geoDraft[geoMarket];
    return geoState.runner.profiles.filter(p => d.providers.includes(p.id)).map(p => `<option value="${esc(p.id)}" ${p.id === d.generator ? 'selected' : ''}>${esc(p.model)}</option>`).join('') || '<option value="">先选择回答模型</option>';
  };
  researchToggle = function(vendor) {
    if (!browser()) return nativeToggle(vendor);
    researchSave(); const d = geoDraft[geoMarket], group = researchChoices().find(g => g.vendor === vendor);
    if (!group) return;
    const ids = new Set(group.ps.map(p => p.id));
    if (group.selected) d.providers = d.providers.filter(id => !ids.has(id));
    else if (researchChoices().filter(g => g.selected).length >= 2) { researchMessage = '最多选择两家厂商，每家一个固定模型。'; render(); return; }
    else d.providers.push(group.p.id);
    researchMessage = ''; normalizeSelection(); render();
  };
  researchModel = function(vendor, id) { if (!browser()) return nativeModel(vendor, id); nativeModel(vendor, id); normalizeSelection(); render(); };
  function connectionMarkup() {
    const s = broker.snapshot();
    return `<section class="ru-browser-connection" id="research-ai-connection" aria-label="本页 AI 连接"><div><b>${s.configured ? 'B.AI 目录已连接' : '连接 AI，开始三步分析'}</b><p>${s.configured ? `${s.profiles.length} 个固定文本模型 · 目录可见，Chat Completions 兼容性需实际调用验证。` : '在本页填写密钥，读取实际模型目录；不跳转、不刷新。'}</p></div><div class="actions"><button class="primary" onclick="browserResearchConnect()">${s.configured ? '更换密钥 / 重新连接' : '连接 B.AI'}</button>${s.configured || s.busy ? '<button onclick="browserResearchClear()">退出并清除本页任务</button>' : ''}<a class="button" href="team.html#/w/demo/research">团队共享后台</a></div><p class="ru-help">可在连接窗口选择记住此设备，下次自动连接；退出会清除保存的密钥。报告仍只在本页内存。连接和查看计划不调用聊天模型；只有明确开始才产生聊天费用。${s.busy ? '本页已有任务或连接正在运行。' : ''}</p>${s.connection_notice ? `<p role="status" class="ru-help">${esc(s.connection_notice)}</p>` : ''}</section>`;
  }
  researchBrand = function() {
    let html = nativeBrand();
    if (browser()) html = html.replace('告诉我们品牌和官网，系统会生成适合这个市场的 30 道问题。', '填写品牌、产品与背景，生成适合所选市场的 30 道候选问题。') + '<p class="ru-help">浏览器模式未抓取官网：官网仅作对象标识，生成依据你填写的品牌、产品、竞品和背景，不代表官网事实或技术 SEO 诊断。</p>';
    return html;
  };
  researchSelect = function() {
    const html = nativeSelect(); if (!browser()) return html;
    const n = researchChoices().filter(g => g.selected).length;
    return html + `<p class="ru-help">固定 30 题、每题每模型 1 次。自动流程最多 3 + 30 × ${n} = ${3 + 30 * n} 次聊天调用（最多 63 次）；只生成最多 3 次，审核后手工采样另计最多 ${30 * n} 次。生成每次最多 4096 输出 token、回答每次最多 2048；token 上限不是价格，实际费用未知。不重试、不补题、不换模型。</p><p class="ru-help">浏览器模式使用你填写的品牌和产品信息出题，不读取官网内容。每家 AI 选择一个固定模型，最多两家。运行期间请保持页面打开，完成后及时导出报告。</p>`;
  };
  researchResults = function() {
    const html = nativeResults(); if (!browser()) return html;
    const scope = '<p class="ru-help">浏览器模式未抓取官网，官网仅作对象标识；本报告分析本次 API 模型回答，不提供技术 SEO 分数、真实搜索量或 AI App 全市场排名。普通正文链接不算原生引用。</p>';
    return scope + html + (geoActive && !geoActive.report && typeof questionCards === 'function' ? questionCards(geoActive) : '');
  };
  geoPage = function() { const html = nativePage(); return browser() ? connectionMarkup() + html.replace('从官网出发，用真实回答了解品牌表现。', '填写品牌背景，生成同一题库，核对真实 API 回答与证据。') : html; };
  render = function() {
    consumeDraftLink();
    if (browser()) snapshot();
    beforeRender();
    if (page !== 'research' || !browser()) return;
    const selected = geoDraft[geoMarket].providers.length;
    for (const button of document.querySelectorAll('[onclick^="geoStart("],[onclick="geoGenerateOnly()"]')) button.disabled = !geoToken || !selected || geoState.busy;
    const subtitle = document.querySelector('.page-head .subtitle'); if (subtitle) subtitle.textContent = '本页连接 AI · 30 道候选题 · 同题采样与原始证据';
  };
  // Explicit draft links carry public brand information only; never run a task.
  function consumeDraftLink() {
    if (!browser() || page !== 'research') return;
    const url = new URL(location.href), params = url.searchParams;
    const brand = params.get('draft_brand');
    if (brand && brand.length <= 200) {
      const market = params.get('draft_market') === 'US' ? 'US' : 'CN';
      const d = geoDraft[market];
      { // An explicit draft link replaces its supplied public form fields.
        geoMarket = market;
        d.brand = brand;
        const website = params.get('draft_website') || '';
        try { const u = new URL(website); if (u.protocol === 'https:' && !u.username && !u.password && website.length <= 500) d.website = u.href; } catch {}
        for (const field of ['skus', 'context']) {
          const value = params.get('draft_' + field);
          if (value && value.length <= 2000) d[field] = value;
        }
        researchStep = 1;
      }
      for (const key of [...params.keys()]) if (key.startsWith('draft_')) params.delete(key);
      history.replaceState(null, '', url);
    }
  }
  snapshot();
  if (browser() && page === 'research') render();
})();
