/* Browser-only B.AI adapter. Provider credentials never leave this closure. */
(() => {
  'use strict';
  const BASE = 'https://api.b.ai/v1';
  const MODEL_TIMEOUT = 20000, CHAT_TIMEOUT = 120000, MAX_BYTES = 8 * 1024 * 1024;
  const nativeFetch = baiFetch, nativePage = baiPage, nativeApiPage = apiPage;
  const nativeConnectModal = baiConnectModal, nativeConnect = baiConnect, nativeModelModal = baiModelModal;
  const nativeRender = render;
  let direct = !baiLocal(), key = '', epoch = 0, connecting = false, running = false;
  let models = [], profiles = new Map(), runs = new Map(), fetchedAt = null, notice = '';
  const pending = new Set();
  const clone = value => JSON.parse(JSON.stringify(value));
  const stamp = () => new Date().toISOString();
  const failure = (message, code = 'request_failed') => Object.assign(new Error(message), {code});
  function current(generation) { if (generation !== epoch) throw failure('连接已更改或已退出，旧请求结果已忽略。', 'cancelled'); }
  function paint() { if (page === 'bai') { baiCapture(); render(); } else if (page === 'apis') { apiCapture(); render(); } }
  function scrub(value, secret = key) {
    if (typeof value === 'string') return secret ? value.split(secret).join('[REDACTED]') : value;
    if (Array.isArray(value)) return value.map(item => scrub(item, secret));
    if (value && typeof value === 'object') {
      return Object.fromEntries(Object.entries(value)
        .filter(([name]) => !['key','apikey','authorization','token','headers','requestheaders'].includes(name.toLowerCase().replace(/[_-]/g, '')))
        .map(([name, item]) => [scrub(name, secret), scrub(item, secret)]));
    }
    return value;
  }
  function snapshot() {
    return clone({configured: Boolean(key), models, profiles: [...profiles.values()], fetched_at: fetchedAt,
      base_url: BASE, browser_direct: true, busy: running || connecting,
      billing: '浏览器直连 · 按 API 实际用量计费 · 无自动重试或模型切换'});
  }
  function sync() {
    if (!direct) return;
    baiToken = 'browser-direct'; // Mode marker, never a provider credential.
    baiState = snapshot();
    baiRuns = clone(scrub([...runs.values()].reverse()));
    if (baiActive) baiActive = baiRuns.find(run => run.id === baiActive.id) || null;
  }
  function reset(message = '已退出，密钥与本页任务证据已清除。') {
    epoch++;
    for (const controller of pending) controller.abort();
    pending.clear();
    key = ''; connecting = false; running = false;
    models = []; profiles.clear(); runs.clear(); fetchedAt = null; notice = message;
    clearTimeout(baiTimer);
    if (direct) {
      baiSelected.clear(); baiActive = null; baiRuns = [];
      sync();
    }
    const input = document.getElementById('bai-key');
    if (input) input.value = '';
  }
  async function readJSON(response) {
    if (Number(response.headers.get('content-length')) > MAX_BYTES) {
      await response.body?.cancel();
      throw failure('B.AI 响应超过大小限制，已停止本批后续请求。', 'response_too_large');
    }
    let text = '';
    if (response.body?.getReader) {
      const reader = response.body.getReader(), decoder = new TextDecoder();
      let bytes = 0;
      try {
        while (true) {
          const part = await reader.read();
          if (part.done) break;
          bytes += part.value.byteLength;
          if (bytes > MAX_BYTES) { await reader.cancel(); throw failure('B.AI 响应超过大小限制，已停止本批后续请求。', 'response_too_large'); }
          text += decoder.decode(part.value, {stream: true});
        }
        text += decoder.decode();
      } finally { reader.releaseLock(); }
    } else {
      text = await response.text();
      if (new TextEncoder().encode(text).length > MAX_BYTES) throw failure('B.AI 响应超过大小限制，已停止本批后续请求。', 'response_too_large');
    }
    try {
      const data = JSON.parse(text);
      if (!data || typeof data !== 'object' || Array.isArray(data)) throw Error();
      return data;
    } catch { throw failure('B.AI 返回了无法解析的响应，已停止本批后续请求。', 'invalid_response'); }
  }
  function credentialForms(credential) {
    if (!credential) return [];
    const forms = [credential];
    try {
      forms.push(encodeURIComponent(credential), encodeURI(credential));
      forms.push(new URLSearchParams({value: credential}).toString().slice('value='.length));
    } catch {}
    return [...new Set(forms.filter(Boolean))];
  }
  function hasSecret(value, credential) {
    const lower = value.toLowerCase();
    if (credentialForms(credential).some(secret => lower.includes(secret.toLowerCase()))) return true;
    return /\bbearer\s+[^\s,;'"<>]+|\bsk-[a-z0-9._~-]+|\bghp_[a-z0-9_]+|\bgithub_pat_[a-z0-9_]+|\bgh[ours]_[a-z0-9_]+|\bxox[baprs]-[a-z0-9-]+/i.test(value);
  }
  function redactDiagnostic(value, credential) {
    let safe = value.replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ');
    for (const secret of credentialForms(credential)) {
      const escaped = secret.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      safe = safe.replace(new RegExp(escaped, 'gi'), '[REDACTED]');
    }
    safe = safe
      .replace(/\bbearer\s+[^\s,;'"<>]+/gi, '[REDACTED]')
      .replace(/\b(?:authorization|api[_-]?key|token|key)\s*[:=]\s*["']?[^\s,;'"<>]+/gi, '[REDACTED]')
      .replace(/\bsk-[a-z0-9._~-]+|\bghp_[a-z0-9_]+|\bgithub_pat_[a-z0-9_]+|\bgh[ours]_[a-z0-9_]+|\bxox[baprs]-[a-z0-9-]+/gi, '[REDACTED]');
    return safe.slice(0, 600).trim();
  }
  function safeDiagnosticId(value, credential, maxLength) {
    return typeof value === 'string' && value.length <= maxLength && /^[A-Za-z0-9_.:-]+$/.test(value) && !hasSecret(value, credential) ? value : '';
  }
  async function serverErrorDiagnostics(response, credential) {
    try {
      const data = await readJSON(response);
      const values = [data.error?.code, data.error?.type, data.code];
      let code = '';
      for (const value of values) {
        code = safeDiagnosticId(value, credential, 64);
        if (code) break;
      }
      const rawMessage = typeof data.error?.message === 'string' ? data.error.message : data.message;
      const message = typeof rawMessage === 'string' ? redactDiagnostic(rawMessage, credential) : '';
      const requestId = safeDiagnosticId(response.headers.get('x-request-id') || response.headers.get('request-id'), credential, 128);
      return {code, message, requestId};
    } catch { /* A body read or parse failure must leave the HTTP status intact. */ }
    const requestId = safeDiagnosticId(response.headers.get('x-request-id') || response.headers.get('request-id'), credential, 128);
    return {code: '', message: '', requestId};
  }
  async function request(path, body, credential, generation) {
    if (!['/models', '/chat/completions'].includes(path)) throw failure('浏览器直连只支持模型目录和 Chat Completions。');
    current(generation);
    const controller = new AbortController(); pending.add(controller);
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; controller.abort(); }, path === '/models' ? MODEL_TIMEOUT : CHAT_TIMEOUT);
    try {
      const response = await fetch(BASE + path, {
        method: body === undefined ? 'GET' : 'POST', credentials: 'omit', redirect: 'error', cache: 'no-store',
        signal: controller.signal,
        headers: {Authorization: 'Bearer ' + credential, ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
        ...(body === undefined ? {} : {body: JSON.stringify(body)})
      });
      current(generation);
      if (!response.ok) {
        const diagnostics = await serverErrorDiagnostics(response, credential);
        current(generation);
        const messages = {
          401: '身份验证未通过（HTTP 401），仅凭此响应不能确定是密钥、访问权限还是接入方式的问题。',
          403: 'B.AI 拒绝访问，请检查账号权限、模型权限或服务访问限制。',
          429: 'B.AI 触发限流或额度限制，请检查余额和调用限制后再手动开始。'
        };
        const message = messages[response.status] || 'B.AI 请求未成功（HTTP ' + response.status + '），请检查所选模型和 Chat Completions 支持情况。';
        throw failure(message + (diagnostics.code ? ' 服务端错误码：' + diagnostics.code : '') +
          (diagnostics.message ? ' 服务端说明：' + diagnostics.message : '') +
          (diagnostics.requestId ? ' 请求编号：' + diagnostics.requestId : ''), 'http_' + response.status);
      }
      const result = await readJSON(response);
      current(generation);
      if (result.error || result.success === false) throw failure('B.AI 返回接口错误，请检查密钥、额度及所选模型的 Chat Completions 支持情况。', 'provider_error');
      return result;
    } catch (error) {
      current(generation);
      if (timedOut) throw failure('B.AI 请求超过 ' + (path === '/models' ? '20' : '120') + ' 秒，已取消等待并停止后续请求；已提交的请求仍可能计费，请勿自动重试。', 'timeout');
      if (error.code) throw error;
      throw failure('浏览器未能完成 B.AI 请求，可能是网络、跨域（CORS）、服务访问限制或连接中断。请检查网络和浏览器提示后再手动操作。', 'network');
    } finally { clearTimeout(timer); pending.delete(controller); }
  }
  async function digest(text) {
    if (!crypto.subtle) throw failure('当前页面不支持安全摘要，请使用 HTTPS 页面或本机浏览器服务。', 'runtime');
    const buffer = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return [...new Uint8Array(buffer)].map(b => b.toString(16).padStart(2, '0')).join('');
  }
  function normalizeKey(value) {
    const invalid = () => failure('密钥格式错误：请只粘贴单行完整密钥，可带一次 Bearer / Authorization: Bearer 前缀；不要包含多行说明、内部空白或不匹配的包装。', 'invalid_key_format');
    if (typeof value !== 'string' || /[\r\n\u2028\u2029]/u.test(value)) throw invalid();
    const edges = /^[\s\u200B-\u200D\u2060\uFEFF]+|[\s\u200B-\u200D\u2060\uFEFF]+$/gu;
    let result = value.replace(edges, ''), unwrapped = false;
    function unwrap() {
      if (unwrapped) return;
      const pairs = [['**', '**'], ['"', '"'], ["'", "'"], ['`', '`'], ['“', '”'], ['‘', '’']];
      const pair = pairs.find(([left, right]) => result.startsWith(left) && result.endsWith(right) && result.length > left.length + right.length);
      if (pair) { result = result.slice(pair[0].length, -pair[1].length).replace(edges, ''); unwrapped = true; }
    }
    unwrap();
    const prefix = /^(?:Authorization[ \t]*:[ \t]*)?Bearer[ \t]+/i.exec(result);
    if (prefix) result = result.slice(prefix[0].length).replace(edges, '');
    unwrap();
    if (!result || result.length > 4096 || /[\s\p{Cc}\p{Cf}]/u.test(result) || /^["'`*“”‘’]|["'`*“”‘’]$/u.test(result) || /^(?:Authorization|Bearer)(?::|$)/i.test(result)) throw invalid();
    return result;
  }
  async function connect(payload) {
    if (connecting) throw failure('正在连接，请等待或先退出当前连接。');
    let candidate = normalizeKey(payload?.key);
    reset('正在读取账号模型目录；不会发送聊天请求。');
    const generation = epoch; connecting = true; sync(); paint();
    try {
      const raw = await request('/models', undefined, candidate, generation);
      if (!Array.isArray(raw.data)) throw failure('B.AI 模型目录格式无效，请检查接口状态后重新连接。', 'invalid_response');
      const found = new Map();
      for (const item of raw.data) {
        if (typeof item?.id !== 'string' || !item.id.trim() || item.id.length > 200 || item.id.includes(candidate) || /[\r\n]/.test(item.id)) continue;
        found.set(item.id, {id: item.id, name: scrub(String(item.name || item.id).slice(0, 200), candidate)});
      }
      if (!found.size) throw failure('当前密钥未返回可选择的模型，请检查模型权限后重新连接。');
      current(generation);
      key = candidate; models = [...found.values()]; fetchedAt = stamp();
      notice = '模型目录已读取。请选择支持 Chat Completions 的聊天模型，再明确提交题目；目录可见不代表调用已验证。';
      return snapshot();
    } finally {
      candidate = '';
      if (generation === epoch) { connecting = false; sync(); paint(); }
    }
  }
  async function profile(payload) {
    if (!key) throw failure('请先连接 B.AI 并读取模型目录。');
    if (running) throw failure('本批正在运行，请完成或退出连接后再修改模型。');
    if (payload.protocol !== 'chat' || payload.search) throw failure('浏览器直连仅支持 Chat Completions 文本接口，不支持 Responses、Messages 或联网工具。');
    if (!models.some(model => model.id === payload.model)) throw failure('请选择此密钥实际返回的模型 ID。');
    if (/(^|[/:._-])(auto|router|latest|dynamic)(?=$|[/:._-])/i.test(payload.model)) throw failure('请选择固定聊天模型，不使用 Auto、Router、Latest 或 Dynamic 路由别名。');
    const markets = payload.markets;
    if (!Array.isArray(markets) || !markets.length || markets.some(m => !['CN', 'US'].includes(m))) throw failure('请选择中国和/或美国市场。');
    const name = String(payload.name || payload.model).trim().slice(0, 120);
    if (!name || name.includes(key)) throw failure('请输入有效的模型显示名称。');
    const generation = epoch;
    const id = 'browser-bai-' + (await digest(payload.model + '|chat|false')).slice(0, 16);
    current(generation);
    profiles.set(id, {id, name, model: payload.model, protocol: 'chat', markets: [...new Set(markets)].sort(), search: false, provider: 'bai', base_url: BASE});
    return snapshot();
  }
  const normalize = text => String(text).normalize('NFKC').toLowerCase().replace(/ß/g, 'ss').replace(/ς/g, 'σ').replace(/’/g, "'").replace(/\s+/gu, ' ').trim();
  function mention(text, aliases) {
    const normalized = normalize(text);
    for (const alias of aliases) {
      const target = normalize(alias);
      if (!target) continue;
      const escaped = target.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const expression = (/[a-z0-9]/i.test(target[0]) ? '(?<![\\p{L}\\p{N}_])' : '') + escaped + (/[a-z0-9]/i.test(target.at(-1)) ? '(?![\\p{L}\\p{N}_])' : '');
      if (new RegExp(expression, 'u').test(normalized)) return alias;
    }
    return null;
  }
  function aggregate(run) {
    return run.providers.map(provider => {
      const attempts = run.samples.filter(sample => sample.provider === provider);
      const complete = attempts.filter(sample => sample.status === 'complete');
      const discovery = complete.filter(sample => !sample.brand_prompted);
      return {provider, attempted: attempts.length, complete: complete.length, discovery_complete: discovery.length,
        brand_mention_score: discovery.length ? Math.round(1000 * discovery.filter(sample => sample.brand_match).length / discovery.length) / 10 : null,
        skus: run.skus.map(sku => {
          const eligible = discovery.filter(sample => !sample.sku_prompted?.[sku.name]);
          const hits = eligible.filter(sample => sample.sku_matches?.[sku.name]).length;
          return {name: sku.name, mentions: hits, denominator: eligible.length, score: eligible.length ? Math.round(1000 * hits / eligible.length) / 10 : null};
        })};
    });
  }
  function source(value, list) {
    if (!value || typeof value !== 'object') return;
    const url = value.url || value.uri;
    if (typeof url !== 'string') return;
    try { if (!['http:', 'https:'].includes(new URL(url).protocol)) return; } catch { return; }
    list.push({url, title: typeof value.title === 'string' ? value.title : ''});
  }
  function parse(raw) {
    const choice = raw.choices?.[0], message = choice?.message;
    if (!choice || !message || typeof message !== 'object') throw failure('B.AI 未返回有效的聊天回答，已停止后续请求。', 'invalid_response');
    const content = message.content;
    let text = typeof content === 'string' ? content : Array.isArray(content) ? content.filter(p => p && typeof p.text === 'string').map(p => p.text).join('\n') : '';
    text = text.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
    const citations = [], sources = [];
    for (const item of Array.isArray(message.annotations) ? message.annotations : []) source(item?.url_citation || item, citations);
    for (const item of Array.isArray(raw.citations) ? raw.citations : []) source(typeof item === 'string' ? {url: item} : item, citations);
    for (const item of Array.isArray(raw.search_results) ? raw.search_results : []) source(item, sources);
    for (const item of Array.isArray(raw.search_info?.search_results) ? raw.search_info.search_results : []) source(item, sources);
    return {answer: text, complete: choice.finish_reason === 'stop' && Boolean(text), finish_reason: typeof choice.finish_reason === 'string' ? choice.finish_reason : 'unknown',
      model_returned: typeof raw.model === 'string' ? raw.model : null, usage: raw.usage || null,
      citations, retrieved_sources: sources, search_observed: sources.length > 0, citation_coverage: 'returned_metadata_only'};
  }
  function prepare(payload) {
    if (!key) throw failure('请先连接 B.AI 密钥。');
    if (running || connecting) throw failure('已有请求正在运行，请等待或先退出连接。');
    const {market, providers: ids, prompts, brand_aliases: aliases, skus = []} = payload;
    if (!['CN', 'US'].includes(market)) throw failure('请选择中国或美国市场。');
    if (!Array.isArray(ids) || !ids.length || ids.length > 16 || new Set(ids).size !== ids.length) throw failure('请选择 1–16 个不同模型。');
    if (!Array.isArray(prompts) || !prompts.length || prompts.length > 10 || ids.length * prompts.length > 64 || prompts.some(p => typeof p !== 'string' || !p.trim() || p.length > 4000)) throw failure('请输入 1–10 道题目，每题不超过 4000 字符，每批最多 64 次请求。');
    if (!Array.isArray(aliases) || !aliases.length || aliases.some(a => typeof a !== 'string' || !a.trim() || a.length > 200)) throw failure('请填写品牌名称与精确别名，每个不超过 200 字符。');
    if (!Array.isArray(skus) || skus.length > 50 || skus.some(s => !s || typeof s.name !== 'string' || !s.name.trim() || !Array.isArray(s.aliases) || !s.aliases.length || s.aliases.some(a => typeof a !== 'string' || !a.trim() || a.length > 200)) || new Set(skus.map(s => s.name)).size !== skus.length) throw failure('最多填写 50 个不同 SKU，每项需要名称和精确别名。');
    const configuration = {};
    for (const id of ids) {
      const selected = profiles.get(id);
      if (!selected || !selected.markets.includes(market)) throw failure('所选模型不适用于当前市场，请重新选择。');
      configuration[id] = clone(selected);
    }
    const metadata = {market, providers: ids.slice(), prompts: prompts.slice(), brand_aliases: aliases.slice(), skus: clone(skus), website: typeof payload.website === 'string' ? payload.website : ''};
    // Never send a credential accidentally pasted into measurement fields as a prompt.
    const containsKey = value => typeof value === 'string' ? value.includes(key) : Array.isArray(value) ? value.some(containsKey) : value && typeof value === 'object' ? Object.entries(value).some(([name, item]) => name.includes(key) || containsKey(item)) : false;
    if (containsKey(metadata)) throw failure('测量信息中包含当前密钥，请移除后再开始。');
    return {...metadata, configuration};
  }
  async function execute(run, generation) {
    run.status = 'running';
    for (const provider of run.providers) {
      for (let index = 0; index < run.prompts.length; index++) {
        if (generation !== epoch) return;
        const p = run.configuration[provider], prompt = run.prompts[index], started = performance.now();
        const sample = {provider, channel: 'bai', protocol: 'chat', model_requested: p.model, question_index: index, prompt,
          captured_at: stamp(), status: 'failed', entry_type: 'model_api', search_requested: false,
          brand_prompted: Boolean(mention(prompt, run.brand_aliases))};
        let stop = false;
        try {
          const raw = await request('/chat/completions', {model: p.model, messages: [{role: 'user', content: prompt}], stream: false, max_tokens: 2048}, key, generation);
          current(generation);
          const safe = scrub(raw);
          Object.assign(sample, parse(safe));
          sample.status = sample.complete ? 'complete' : 'incomplete';
          sample.brand_match = mention(sample.answer, run.brand_aliases);
          sample.sku_matches = Object.fromEntries(run.skus.map(s => [s.name, mention(sample.answer, s.aliases)]));
          sample.sku_prompted = Object.fromEntries(run.skus.map(s => [s.name, Boolean(mention(prompt, s.aliases))]));
          const rawName = provider + '-' + index + '-raw.json';
          sample.raw_sha256 = await digest(JSON.stringify(safe, null, 2));
          current(generation);
          sample.raw_file = rawName;
          run.raw_evidence[rawName] = safe;
        } catch (error) {
          if (generation !== epoch) return;
          sample.status = 'failed'; sample.complete = false;
          sample.error = error.code ? error.message : '本地处理回答失败，已停止后续请求。';
          stop = true;
        }
        if (generation !== epoch) return;
        sample.latency_ms = Math.round(performance.now() - started);
        run.samples.push(scrub(sample)); run.summary = aggregate(run);
        if (stop) {
          run.status = run.samples.some(s => s.status === 'complete' || s.status === 'incomplete') ? 'partial' : 'failed';
          run.error = '本批已停止，剩余 ' + (run.planned - run.samples.length) + ' 次未发送。' + sample.error;
          run.finished_at = stamp(); running = false; sync(); paint(); return;
        }
        sync(); paint();
      }
    }
    if (generation !== epoch) return;
    run.status = run.samples.some(s => s.status !== 'complete') ? 'partial' : 'finished';
    run.finished_at = stamp(); running = false; sync(); paint();
  }
  async function adapter(path, body) {
    const endpoint = path.split('?')[0];
    if (endpoint === 'connect' && body) return connect(body);
    if (endpoint === 'clear') { reset(); return snapshot(); }
    if (endpoint === 'state' && !body) return snapshot();
    if (endpoint === 'profile' && body) return profile(body);
    if (endpoint === 'runs' && !body) return {runs: clone([...runs.values()].reverse())};
    if (['run', 'export'].includes(endpoint) && !body) {
      const id = new URLSearchParams(path.split('?')[1]).get('id'), run = runs.get(id);
      if (!run) throw failure('当前页面没有这份任务，刷新或退出会清除内存记录。');
      const result = clone(scrub(run));
      if (endpoint !== 'export') delete result.raw_evidence;
      return result;
    }
    if (endpoint === 'run' && body) {
      const prepared = prepare(body), id = crypto.randomUUID();
      const run = {...prepared, id, entry_type: 'model_api', channel: 'bai', browser_direct: true, created_at: stamp(), status: 'queued',
        planned: prepared.providers.length * prepared.prompts.length, samples: [], summary: [], raw_evidence: {},
        methodology: 'api-mention-v1; complete unprompted exact-alias mention rate; failed/incomplete excluded; no recommendation or market-population claim',
        evidence_note: 'Raw provider JSON is credential-redacted before in-memory retention/export; SHA256 is over redacted JSON with two-space indentation. No request headers or credentials are exported.'};
      run.summary = aggregate(run); runs.set(id, run); running = true;
      // Only this explicit run action starts paid calls. Each request is awaited once.
      void execute(run, epoch).catch(() => {
        if (!runs.has(id)) return;
        run.status = 'failed'; run.error = '本页处理被中断，后续请求已停止；已完成证据保留。';
        running = false; sync(); paint();
      });
      return {id, status: run.status, planned: run.planned};
    }
    throw failure('浏览器直连不支持此操作，仅支持 Chat Completions 手动题集采样。');
  }
  baiFetch = async function(path, body) { return direct ? adapter(path, body) : nativeFetch(path, body); };
  window.browserBaiOpen = function() {
    if (!direct) { clearTimeout(baiTimer); direct = true; reset('浏览器直连已启用，请填写 B.AI 密钥。'); }
    if (page === 'apis') {
      apiCapture(); baiMarket = apiMarket;
      baiDraft[baiMarket] = {...baiDraft[baiMarket], ...apiDraft[apiMarket]};
      window.addEventListener('hashchange', () => { if (page === 'bai') { sync(); baiConnectModal(); paint(); } }, {once: true});
      go('bai'); return;
    }
    sync(); baiConnectModal(); paint();
  };
  window.browserBaiClear = function() { if (!direct) return; reset(); closeOverlay(); paint(); };
  baiConnectModal = function() {
    if (!direct) return nativeConnectModal();
    baiCapture();
    modal(head('浏览器直接连接 B.AI') + `<p>密钥仅保存在当前页面内存，不写入浏览器存储、URL 或导出。刷新、离开页面或退出会清除密钥和本页证据。</p><p>连接只读取模型目录，不发送聊天请求。随后请添加固定聊天模型，手动填写 1–10 道题目并点击运行；这不是 30 题官网自动诊断。</p>${input('B.AI API Key','bai-key','','password')}<p class="mono">${BASE}/models</p><button class="primary" id="bai-connect" onclick="baiConnect()">连接并读取模型</button><button onclick="browserBaiClear()">取消并清除连接</button><p id="bai-connect-error" class="error" role="alert"></p>`);
    $('#bai-key').autocomplete = 'off';
    $('#bai-key').spellcheck = false;
    $('#bai-key').focus();
  };
  baiConnect = async function() {
    if (!direct) return nativeConnect();
    const field = $('#bai-key'), button = $('#bai-connect');
    let candidate = field?.value || '';
    if (field) field.value = '';
    if (button) button.disabled = true;
    try {
      await adapter('connect', {key: candidate}); candidate = '';
      closeOverlay(); sync(); paint(); toast('模型目录已读取，请添加固定聊天模型并手动提交题目。');
    } catch (error) {
      if (error.code === 'cancelled') return;
      notice = error.code ? error.message : '连接未完成，请检查网络和服务访问条件后手动重试。';
      const alert = $('#bai-connect-error'); if (alert) alert.textContent = notice;
      if ($('#bai-connect')) $('#bai-connect').disabled = false;
      sync(); paint();
    } finally { candidate = ''; }
  };
  const nativeAddModel = baiAddModel;
  baiAddModel = async function() {
    if (!direct) return nativeAddModel();
    const generation = epoch;
    try {
      await adapter('profile', {model: $('#bai-model')?.value, name: $('#bai-name')?.value, protocol: $('#bai-protocol')?.value,
        search: Boolean($('#bai-search')?.checked), markets: [$('#bai-cn')?.checked ? 'CN' : null, $('#bai-us')?.checked ? 'US' : null].filter(Boolean)});
      current(generation); closeOverlay(); sync(); paint();
    } catch (error) {
      if (generation !== epoch) return;
      const alert = $('#bai-model-error'); if (alert) alert.textContent = error.code ? error.message : '添加模型未完成，请重新选择。';
    }
  };
  baiModelModal = function() {
    if (!direct) return nativeModelModal();
    baiCapture();
    modal(head('添加固定聊天模型') + `<p>仅支持 Chat Completions 文本聊天。请选择账号目录中的固定聊天模型；目录可见不代表接口协议已验证。</p><label for="bai-model">账号实际返回的模型 ID</label><select id="bai-model" style="width:100%">${models.map(m => `<option value="${esc(m.id)}">${esc(m.name)} · ${esc(m.id)}</option>`).join('')}</select>${input('显示名称（可留空，使用完整模型 ID）','bai-name','')}<input id="bai-protocol" type="hidden" value="chat"><input id="bai-search" type="checkbox" hidden><p>Chat Completions · 不请求联网工具 · 每次最多 2048 输出 token</p><label><input id="bai-cn" type="checkbox" ${baiMarket === 'CN' ? 'checked' : ''}> 中国市场</label><label><input id="bai-us" type="checkbox" ${baiMarket === 'US' ? 'checked' : ''}> 美国市场</label><button class="primary" onclick="baiAddModel()">添加到采样列表</button><p id="bai-model-error" class="error" role="alert"></p>`);
  };
  baiPage = function() {
    const html = nativePage();
    const banner = `<section class="card" id="browser-bai-connection"><div class="card-head"><h2>网页直接连接 B.AI</h2><span class="tag">${direct ? '浏览器直连' : '可选直连'}</span></div><p>使用现有手动题集采样：1–10 道问题，每批最多 64 次请求；不是 30 题官网自动诊断。仅请求固定的 ${BASE}，不会抓取品牌官网。</p><p>密钥和本页任务证据只在当前页面内存；刷新、离开或退出后清除。请先导出需要保留的证据。</p><div class="actions"><button class="primary" onclick="browserBaiOpen()" ${connecting ? 'disabled' : ''}>${key ? '更换密钥 / 重新连接' : '填写密钥并连接'}</button>${direct ? '<button onclick="browserBaiClear()">退出并清除本页数据</button>' : ''}</div>${notice ? `<p class="${key ? 'notice' : 'error'}" role="status">${esc(notice)}</p>` : ''}</section>`;
    if (!direct) return banner + html;
    return banner + html.replace(/<a class="primary button" href="http:\/\/127\.0\.0\.1:8771[^>]*>[^<]*<\/a>/, '')
      .replace(/<div class="notice">[\s\S]*?<\/div>/, '<div class="notice">浏览器直连 · 聊天请求串行发送 · 不自动重试、不换模型。网络失败或接口拒绝后停止剩余请求；取消等待不保证撤销服务端已提交调用。</div>');
  };
  apiPage = function() {
    return `<section class="card" id="browser-bai-api-entry"><h2>B.AI 网页直连</h2><p>无需本机执行器。填写 B.AI 密钥后读取真实模型目录，自选聊天模型与 1–10 道手动题目，明确提交后才调用模型。密钥仅保存在当前页面内存。</p><button class="primary" onclick="browserBaiOpen()">打开 B.AI 直连并连接</button></section>` + nativeApiPage();
  };
  render = function() {
    if (direct) sync();
    nativeRender();
    if (!direct || page !== 'bai') return;
    const start = $('#bai-start'); if (start) start.disabled = !key || running || connecting;
    const add = document.querySelector('button[onclick="baiModelModal()"]'); if (add) add.disabled = !key || running || connecting;
    if (baiActive?.error) {
      const error = document.createElement('p'); error.className = 'error'; error.setAttribute('role', 'alert'); error.textContent = baiActive.error;
      start?.parentElement?.appendChild(error);
    }
    const header = document.querySelector('.header-right .tag'); if (header) header.textContent = '浏览器直连 · 手动题集';
  };
  window.addEventListener('pagehide', () => { reset('页面已离开，密钥与本页证据已清除。'); });
  window.addEventListener('pageshow', event => { if (event.persisted) paint(); });
  if (direct) sync();
  if (page === 'bai' || page === 'apis') paint();
})();
