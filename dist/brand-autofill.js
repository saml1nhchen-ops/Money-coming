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
  window.brandAutofillMarkup = () => `<section id="brand-autofill" class="ru-help" aria-live="polite"><p>读取官网；有已验证的免费 Gemini 时最多请求 1 次补充候选，不调用收费模型。建议需确认，可随时手动填写。</p><div id="brand-autofill-content">${markup(record())}</div><button type="button" id="brand-autofill-read">重新读取官网 / 查看缓存</button></section>`;
  function markup(r) {
    if (!r) return '<p>完成官网输入后自动读取；请先登录团队后台，也可手动填写。</p>';
    let html = `<p role="status">${esc(r.message || '')}</p>`;
    const result = r.result;
    if (!result) return html;
    const candidates = [result.brand,...(result.products || []),...(result.competitors || [])].filter(Boolean);
    html += candidates.map((c,i) => `<div><button type="button" data-brand-candidate="${i}">采用${c.kind==='competitor'?'竞品':c.kind==='brand'?'品牌':'产品'}候选：${esc(c.name)}</button> <span>${c.basis==='model_inference'?'模型推断，待确认':c.basis==='domain_fallback'?'域名回退，待确认':'网页候选，待确认'}</span><details><summary>查看来源与依据</summary><p>${esc(c.source_url || '无已验证网页来源')} · ${esc(c.source_field || '')}</p><p>${esc(c.evidence || c.reason || '')}</p></details></div>`).join('');
    if (result.website?.captured_at) html += `<p>网页读取时间：${esc(result.website.captured_at)}${result.reused?' · 复用 24 小时内缓存':''}</p>`;
    if (result.billing) html += `<p>模型调用：${esc(result.billing.model_calls)} / 1；实际账单金额未知。</p>`;
    return html;
  }
  function paint() { const el = document.getElementById('brand-autofill-content'); if (el) el.innerHTML = markup(record()); }
  function apply(job,result) {
    if (!current(job) || researchStep !== 1) return;
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
    const message = pending ? (result.stage==='suggestion'?'官网候选已保留，正在检查免费 Gemini 建议。':'正在读取官网…') : suggestion==='free_model_unavailable' ? '尚未提供可验证的免费 Gemini，已保留网页识别，可手动填写竞品。' : result.website?.status==='failed' ? '官网读取失败，可手动填写；不会自动重试模型。' : '候选已准备，请核对并编辑后继续。';
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
