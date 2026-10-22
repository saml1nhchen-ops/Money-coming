/* Team-only website candidates. Never starts research or selects a supplier model. */
(() => {
  'use strict';
  if (window.SIGNAL_GEO_MODE !== 'team') return;
  let sequence = 0, timer, pollTimer, active = null, armed = null;
  const records = new Map(), edits = {CN:{},US:{}}, automatic = {CN:{},US:{}};
  const fields = {'ru-brand':'brand','ru-products':'skus','ru-competitors':'competitors'};
  function normalized(value) {
    try { const u = new URL(/^https?:\/\//i.test(value.trim()) ? value.trim() : 'https://'+value.trim());
      if (!['http:','https:'].includes(u.protocol) || !u.hostname.includes('.') || u.username || u.password) return '';
      u.hash = ''; return u.href;
    } catch { return ''; }
  }
  function identity() {
    const c = window.remoteEnrichmentContext?.();
    const url = normalized(document.getElementById('geo-website')?.value ?? geoDraft[geoMarket].website ?? '');
    return c ? {...c,market:geoMarket,url,key:JSON.stringify([c.backend,c.epoch,geoMarket,url])} : null;
  }
  function current(job) { const now = identity(); return active === job && now?.authenticated && now.key === job.key && job.sequence === sequence; }
  function invalidate() { sequence++; clearTimeout(timer); clearTimeout(pollTimer); active = null; armed = null; }
  function record() { return records.get(identity()?.key); }
  window.brandAutofillMarkup = () => `<section id="brand-autofill" class="ru-help" aria-live="polite"><p>读取官网；有已验证的免费 Gemini 时最多请求 1 次补充候选，不调用收费模型。建议需确认，可随时手动填写。</p><div id="brand-autofill-content">${markup(record())}</div><button type="button" id="brand-autofill-read">检测官网 / 查看结果</button></section>`;
  function websiteCheck(result) {
    const w = result.website || {}, d = w.diagnostics;
    if (!d) return '<section class="ru-website-check" aria-label="官网检测"><h3>官网检测</h3><p>这是后台读取官网的结果，与你的浏览器能否打开不一定相同。</p><p>此缓存暂无检测详情；当前按钮仅查看已有结果。已有候选仍可核对，可改用具体产品页或手动填写。</p></section>';
    const labels = {readable:'网页可读',limited:'疑似限流或自动访问限制',blocked:'访问被拒绝',unreachable:'暂时无法连接',unsupported:'暂不支持读取此内容',unsafe:'地址未通过安全检查',challenge:'疑似验证码或访问挑战'};
    const advice = {readable:'请核对品牌和产品候选后继续。未提取到产品不代表官网没有产品；此检测不执行网页 JavaScript。',limited:'HTTP 429 可能表示限流或自动访问限制，不能据此确定为反爬。可稍后手动重试、改用产品页或手动填写；不会自动重试或绕过。',blocked:'HTTP 403 或其他访问拒绝不能据此确定为反爬。可改用可公开访问的产品页或手动填写。',challenge:'页面可能要求验证码或访问验证，即使 HTTP 200 也不视为正常官网内容。请手动填写或改用公开产品页；不会尝试绕过。',unreachable:'可稍后手动检测、核对官网地址或手动填写。',unsupported:'可改用公开 HTML 产品页或手动填写；不执行网页 JavaScript。',unsafe:'请核对公开官网地址或手动填写。'};
    const number = value => Number.isFinite(value) && value >= 0 ? esc(value) : '未知';
    const outcome = d.http_status === 429 ? 'limited' : d.outcome;
    const names = {address:'地址安全',dns:'域名解析',tls:'HTTPS 证书',http:'HTTP 响应',content:'页面内容'};
    const states = {passed:'通过',failed:'未通过',unknown:'未知',skipped:'未检查'};
    const redirects = Array.isArray(d.redirects) ? d.redirects.slice(0,5) : [];
    const findings = Array.isArray(d.findings) ? d.findings : [];
    const checks = Array.isArray(d.checks) ? d.checks : [];
    const count = outcome === 'readable' ? `<p>网页品牌候选：${result.brand && ['website_metadata','website_text'].includes(result.brand.basis)?1:0}；网页产品 / 类别候选：${(result.products || []).filter(c=>['website_metadata','website_text'].includes(c.basis)).length}。未提取到产品不代表没有产品。</p>` : '';
    return `<section class="ru-website-check" aria-label="官网检测"><h3>官网检测 · ${esc(labels[outcome] || '检测结果未知')}</h3><p>这是后台读取官网的结果，与你的浏览器能否打开不一定相同。</p><p>HTTP：${number(d.http_status)} · 可读字数：${number(d.readable_characters)} · 跳转数：${redirects.length}</p><details><summary>查看检查项与读取详情</summary><p>内容类型：${esc(d.content_type || '未知')} · 内容字节：${number(d.bytes)} · 耗时：${number(d.duration_ms)} ms</p><p>最终地址：${esc(d.final_url || w.url || '未知')}</p>${d.checked_at?`<p>检测时间：${esc(d.checked_at)}</p>`:''}<ul>${checks.map(c=>`<li>${esc(names[c.id] || c.id || '检查项')}：${esc(states[c.status] || '未知')} · ${esc(c.message || '')}</li>`).join('')}</ul></details>${count}${findings.map(f=>`<p>${esc(f.message || '')}</p>`).join('')}<p><b>建议：</b>${esc(advice[outcome] || '请核对官网地址，也可手动填写。')}</p>${d.retry_after?`<p>服务端建议等待（Retry-After）：${esc(String(d.retry_after).slice(0,100))}</p>`:''}<details><summary>查看跳转链（${redirects.length} 次）</summary>${redirects.length?redirects.map(r=>`<p>${esc(r.url || '')} · HTTP ${number(r.status)} → ${esc(r.location || '')}</p>`).join(''):'<p>未记录跳转。</p>'}</details></section>`;
  }
  function markup(r) {
    if (!r) return '<p>完成官网输入后自动读取；请先登录团队后台，也可手动填写。</p>';
    let html = `<p role="status">${esc(r.message || '')}</p>`;
    const result = r.result;
    if (!result) return html;
    html += websiteCheck(result);
    const candidates = result.website?.diagnostics?.outcome === 'challenge' ? [] : [result.brand,...(result.products || []),...(result.competitors || [])].filter(Boolean);
    html += candidates.map((c,i) => `<div><button type="button" data-brand-candidate="${i}">采用${c.kind==='competitor'?'竞品':c.kind==='brand'?'品牌':'产品'}候选：${esc(c.name)}</button> <span>${c.basis==='model_inference'?'模型推断，待确认':c.basis==='domain_fallback'?'域名回退，待确认':'网页候选，待确认'}</span><details><summary>查看来源与依据</summary><p>${esc(c.source_url || '无已验证网页来源')} · ${esc(c.source_field || '')}</p><p>${esc(c.evidence || c.reason || '')}</p></details></div>`).join('');
    if (result.website?.captured_at) html += `<p>网页读取时间：${esc(result.website.captured_at)}${result.reused?' · 复用 24 小时内缓存':''}</p>`;
    if (result.billing) html += `<p>模型调用：${esc(result.billing.model_calls)} / 1；实际账单金额未知。</p>`;
    return html;
  }
  function paint() { const el = document.getElementById('brand-autofill-content'); if (el) el.innerHTML = markup(record()); }
  function apply(job,result) {
    if (!current(job) || researchStep !== 1 || result.website?.diagnostics?.outcome === 'challenge') return;
    const d = geoDraft[job.market];
    for (const [id,key] of Object.entries(fields)) {
      if (key === 'competitors') continue;
      const el = document.getElementById(id);
      if (!el) continue;
      const value = el.value;
      if (edits[job.market][key] || (value.trim() && value !== automatic[job.market][key])) continue;
      const selected = key === 'brand' ? [result.brand].filter(c=>c && c.basis!=='domain_fallback') : (result.products || []).filter(c=>c.basis!=='model_inference' && c.basis!=='domain_fallback');
      const next = selected.map(c=>c.name).join(key==='brand'?'':'\n');
      if (next) { if (el) el.value = next; d[key] = next; automatic[job.market][key] = next; }
    }
  }
  function receive(job,result) {
    if (!current(job)) return;
    const pending = ['queued','running'].includes(result.status);
    const suggestion = result.model_suggestion?.status;
    const message = result.website?.diagnostics?.outcome === 'challenge' ? '官网疑似访问挑战，尚未读取正常内容；可手动填写。' : pending ? (result.stage==='suggestion'?'官网候选已保留，正在检查免费 Gemini 建议。':'正在读取官网…') : result.website?.status==='failed' ? '官网读取失败，请查看官网检测结果；可手动填写，不会自动重试模型。' : suggestion==='free_model_unavailable' ? '尚未提供可验证的免费 Gemini，已保留网页识别，可手动填写竞品。' : '候选已准备，请核对并编辑后继续。';
    records.set(job.key,{result,message,state:pending?'pending':'complete'}); apply(job,result); paint();
    if (pending && result.id) pollTimer = setTimeout(async()=>{
      if (!current(job)) return;
      if (Date.now() > job.deadline) { failed(job,new Error('识别等待超时，服务器可能仍在处理。')); return; }
      try { receive(job,await remoteEnrich(result.id)); } catch(e) { failed(job,e); }
    },1200);
  }
  function failed(job,e) {
    if (!current(job)) return;
    const previous = records.get(job.key);
    clearTimeout(pollTimer);
    records.set(job.key,{...previous,state:'unknown',message:e.message+' 结果未确认，不会自动重新提交；可手动读取缓存或填写。'}); paint();
  }
  async function start(explicit=false) {
    clearTimeout(timer);
    const c = identity();
    const previous = records.get(c?.key);
    if (!c?.url || (!explicit && armed !== c.key) || (active?.key === c.key && previous?.state === 'pending') || (!explicit && previous)) return;
    if (!c.authenticated) { if(c) records.set(c.key,{message:'请先登录团队后台，也可手动填写。登录后不会自动提交识别。'}); paint(); return; }
    invalidate(); const job = {...c,sequence,deadline:Date.now()+150000}; active = job;
    researchSave(); records.set(c.key,{...previous,state:'pending',message:explicit && previous?.result?.id ? '正在读取已有识别结果…' : '正在读取官网…'}); paint();
    // Known resources resume read-only, except explicit zero-call website failures. Unknown POST outcomes are
    // retrievable only by explicit action and the server's URL/market deduplication.
    const websiteRetry = explicit && previous?.result?.website?.status === 'failed' && previous.result.billing?.model_calls === 0 && previous.result.stage === 'done';
    const request = explicit && previous?.result?.id && !websiteRetry ? previous.result.id : {website:c.url,market:c.market,request_id:crypto.randomUUID()};
    try { receive(job,await remoteEnrich(request)); } catch(e) { failed(job,e); }
  }
  document.addEventListener('input',event=>{
    const id = event.target.id, key = fields[id];
    if (key) edits[geoMarket][key] = true;
    if (id !== 'geo-website') return;
    const keyNow = identity()?.key;
    if (active?.key !== keyNow) invalidate(); else clearTimeout(timer);
    armed = keyNow; paint(); timer = setTimeout(()=>start(),700);
  });
  document.addEventListener('focusout',event=>{ if(event.target.id==='geo-website') void start(); });
  document.addEventListener('click',event=>{
    if (event.target.closest('#brand-autofill-read')) { void start(true); return; }
    const button = event.target.closest('[data-brand-candidate]'); if (!button) return;
    const r = record()?.result; if (!r) return;
    const c = [r.brand,...(r.products||[]),...(r.competitors||[])].filter(Boolean)[Number(button.dataset.brandCandidate)];
    if (!c) return;
    const key = c.kind==='brand'?'brand':c.kind==='competitor'?'competitors':'skus';
    const id = Object.keys(fields).find(id=>fields[id]===key), el = document.getElementById(id); if (!el) return;
    el.value = key==='brand' ? c.name : [...new Set([...el.value.split('\n').filter(Boolean),c.name])].join('\n');
    edits[geoMarket][key] = true; researchSave();
  });
  const change = geoChange;
  geoChange = function(market) { invalidate(); return change(market); };
  window.addEventListener('remote-enrichment-invalidated',invalidate);
  window.addEventListener('pagehide',invalidate);
  const websiteRow = document.getElementById('geo-website')?.closest('.ru-two');
  if (websiteRow && !document.getElementById('brand-autofill')) websiteRow.insertAdjacentHTML('afterend',brandAutofillMarkup());
})();
