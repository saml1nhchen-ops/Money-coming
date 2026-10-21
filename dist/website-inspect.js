/* Deterministic webpage checks, separate from model-answer visibility. */
let websiteInspectBusy = false;
function researchWebsiteKey(value) {
  try { const u = new URL(/^https?:\/\//i.test(value) ? value : 'https://' + value); return u.href; }
  catch { return ''; }
}
function researchCurrentInspection(d = geoDraft[geoMarket]) {
  return d.inspection && d.inspectedURL === researchWebsiteKey(d.website || '') ? d.inspection : null;
}
function researchBrandPending() {
  const d = geoDraft[geoMarket];
  return Boolean(researchCurrentInspection(d)?.brand?.needs_confirmation && !d.inspectedBrandConfirmed);
}
async function researchInspectWebsite() {
  researchSave();
  const market = geoMarket, d = geoDraft[market], website = researchWebsiteKey(d.website || '');
  researchMessage = '';
  if (!website || !d.website?.trim()) { researchMessage = '请先输入有效的官网 URL。'; render(); return; }
  if (!geoLocal()) { researchMessage = '请先连接分析后台并登录，再读取官网。网页检查不需要模型连接。'; render(); return; }
  websiteInspectBusy = true;
  render();
  try {
    if (!geoToken) await geoLoad();
    const result = await geoFetch('inspect', {website, market});
    // Ignore an old response if the market or edited URL changed while loading.
    if (market !== geoMarket || website !== researchWebsiteKey(d.website || '')) return;
    researchSave();
    if (website !== researchWebsiteKey(d.website || '')) return;
    const previousContext = d.inspection?.context;
    d.inspection = result;
    d.website = result.website.url;
    d.inspectedURL = researchWebsiteKey(d.website);
    d.inspectedBrandConfirmed = !result.brand.needs_confirmation;
    if (!result.brand.needs_confirmation) d.brand = [result.brand.name, ...(result.brand.aliases || [])].filter((v, i, a) => v && a.indexOf(v) === i).join(' | ');
    if (result.context && (!d.context?.trim() || d.context === previousContext)) d.context = result.context;
    localStorage.setItem('signal-research-drafts', JSON.stringify(geoDraft));
  } catch (e) {
    if (market === geoMarket) { d.inspection = null; researchMessage = '官网读取失败：' + e.message + '。未生成页面分数，可检查 URL 后重试。'; }
  } finally {
    websiteInspectBusy = false;
    render();
  }
}
function researchConfirmInspectedBrand() {
  researchSave();
  const d = geoDraft[geoMarket], result = researchCurrentInspection(d);
  if (!result) return;
  const candidate = (d.brand || '').split('|')[0].trim() || result.brand.name;
  if (!candidate) { researchMessage = '请填写品牌名称后确认。'; render(); return; }
  d.brand = (d.brand || '').trim() || [candidate, ...(result.brand.aliases || [])].filter((v, i, a) => v && a.indexOf(v) === i).join(' | ');
  d.inspectedBrandConfirmed = true;
  researchMessage = '';
  localStorage.setItem('signal-research-drafts', JSON.stringify(geoDraft));
  render();
}
function researchInspectionMarkup() {
  const d = geoDraft[geoMarket], result = researchCurrentInspection(d);
  const connection = !geoState.runner.profiles.length ? '<p class="ru-help">尚未连接模型。仍可读取官网并完成页面检查；生成题目与采样需要另外连接 AI。</p>' : '';
  const action = `<div class="ru-inspect-actions"><button class="primary" id="inspect-website-button" ${websiteInspectBusy ? 'disabled' : ''} onclick="researchInspectWebsite()">${websiteInspectBusy ? '正在读取官网…' : '读取官网并诊断'}</button><span>无需模型 · 不产生模型调用费用</span></div>${connection}`;
  if (!result) return action + (d.inspection ? '<p class="ru-help">官网 URL 已更改，请重新读取以更新页面诊断。</p>' : '');
  const diagnosis = result.diagnosis, pending = researchBrandPending();
  return action + `<section id="website-inspection" class="ru-inspection" aria-label="网页准备度诊断"><div class="ru-inspection-head"><div><span class="ru-kicker">官网页面检查</span><h3>网页准备度</h3><p>检查网页可读信息；不代表 AI 提及、推荐或市场排名。</p></div><strong id="website-readiness-score">${diagnosis.score === null || diagnosis.score === undefined ? '—' : esc(diagnosis.score)}<small> / 100</small></strong></div>
    <p class="ru-help">品牌来源：${esc(result.brand.source || '未提供')}。${pending ? `候选名称：<b>${esc(result.brand.name)}</b>；尚未代入，请核对品牌输入框并确认。` : `当前品牌可在上方编辑。${result.brand.needs_confirmation ? '候选品牌已由你确认。' : ''}`}</p>
    ${pending ? '<div class="ru-warning" role="status">仅根据有限网页信息推断品牌，需要你确认。<button type="button" id="confirm-inspected-brand" onclick="researchConfirmInspectedBrand()">确认输入框品牌 / 使用候选品牌</button></div>' : ''}
    <div class="ru-inspection-checks">${(diagnosis.checks || []).map(c => `<article class="ru-inspection-check" data-check-status="${esc(c.status)}"><div><b>${esc(c.label)}</b><span>${({pass: '通过', fail: '未满足', unknown: '未知'})[c.status] || '未知'}</span></div><p>${esc(c.evidence || '未提供检查依据')}</p>${c.action ? `<p>建议：${esc(c.action)}</p>` : ''}</article>`).join('')}</div>
    ${(result.warnings || []).map(w => `<p class="ru-warning">${esc(w)}</p>`).join('')}
    <details class="ru-optional"><summary>查看检查方法与抓取记录</summary><p>${esc(typeof diagnosis.methodology === 'string' ? diagnosis.methodology : JSON.stringify(diagnosis.methodology))}</p><p class="mono">${esc(result.website.url)}<br>抓取时间：${esc(result.website.captured_at)}<br>内容 SHA256：${esc(result.website.content_sha256)} · ${esc(result.website.bytes)} bytes</p></details></section>`;
}
