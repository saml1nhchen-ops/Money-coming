/* One card per frozen question, one dialog column per selected model. */
function questionSamples(job, index, provider) {
  const matches = s => s.question_index !== null && s.question_index !== undefined && Number(s.question_index) === index && s.provider === provider;
  const rows = new Map();
  // Report analysis is authoritative; retain raw samples that have not been analyzed yet.
  for (const s of [...(job.samples || []), ...(job.report?.samples || [])].filter(matches)) {
    const key = s.id || [s.provider, s.question_index, s.repeat ?? 1].join(':');
    rows.set(key, {...rows.get(key), ...s});
  }
  return [...rows.values()].sort((a, b) => (a.repeat ?? 1) - (b.repeat ?? 1));
}
function questionFamily(job, index) {
  const prompt = job.prompts[index], family = prompt?.family || (job.report?.samples || []).find(s => Number(s.question_index) === index)?.analysis?.family;
  return ['discovery', 'brand', 'comparison'].includes(family) ? family : 'unknown';
}
function questionFamilyLabel(family) {
  return ({discovery: '自然发现题', brand: '品牌认知题 · 不计自然发现分母', comparison: '品牌比较题 · 不计自然发现分母', unknown: '题型未记录 · 计分资格待核对'})[family];
}
function questionSampleState(sample, job) {
  if (!sample) return ['queued', 'running'].includes(job.status) ? '等待中' : '未运行';
  if (sample.truncated || sample.status === 'truncated') return '回答截断 · 不完整';
  return ({complete: '完整', failed: '失败', error: '失败', queued: '等待中', pending: '等待中', running: '等待中', stopped: '已停止', interrupted: '已中断'})[sample.status] || '状态未记录';
}
function questionModelName(job, provider) {
  const frozen = job.config?.configuration?.[provider];
  return frozen?.model || frozen?.name || provider;
}
function questionCards(job) {
  const prompts = job.prompts || [], providers = job.config?.providers || [];
  return `<section class="rr-section" id="question-cards" aria-labelledby="question-cards-title"><div class="rr-section-heading"><div><span class="ru-kicker">逐题核对</span><h2 id="question-cards-title">每道问题，各家 AI 怎么回答？</h2><p>点击问题查看全部 ${providers.length} 个已选模型。提及不等于推荐；未回答和失败不会算成零分。</p></div><span class="rr-count">${prompts.length} 道已生成问题</span></div>
    ${prompts.length ? `<div class="rq-grid">${prompts.map((p, index) => {
      const rows = providers.flatMap(provider => questionSamples(job, index, provider)), returned = providers.filter(provider => questionSamples(job, index, provider).length).length;
      const complete = rows.filter(s => s.status === 'complete' && !s.truncated).length;
      const failed = rows.filter(s => ['failed', 'error'].includes(s.status)).length;
      return `<button type="button" class="rq-card" id="question-card-${index}" data-question-index="${index}" aria-haspopup="dialog" onclick="questionOpen(${index})"><span class="rq-card-top"><span>问题 ${index + 1}</span><span>${returned} / ${providers.length} 个模型已返回</span></span><strong>${esc(typeof p === 'string' ? p : p.text || '题目文本未记录')}</strong><span class="rq-family">${questionFamilyLabel(questionFamily(job, index))}</span><span class="rq-status">${complete ? `${complete} 条完整回答` : '暂无完整回答'}${failed ? ` · ${failed} 条失败` : ''}${returned < providers.length ? ` · ${['queued', 'running'].includes(job.status) ? '其余等待中' : '其余未运行'}` : ''}<span aria-hidden="true">查看回答 →</span></span></button>`;
    }).join('')}</div>` : `<p class="rr-empty">${['queued', 'running'].includes(job.status) ? '题目正在生成，已生成的题目会陆续出现在这里。' : '当前尚未生成题目。'}</p>`}</section>`;
}
function questionSampleContent(sample, job) {
  const state = questionSampleState(sample, job);
  if (!sample) return `<p class="rq-state">${state}</p><p class="ru-help">尚无这道问题的回答记录，不记为零分。</p>`;
  const analysis = sample.analysis, measured = sample.status === 'complete' && !sample.truncated && analysis;
  const own = analysis?.entities?.find(e => e.own), competitors = analysis?.entities?.filter(e => !e.own && e.alias) || [];
  const citations = analysis?.citations;
  const mention = measured && own && Object.hasOwn(own, 'alias') ? own.alias ? '已提及' : '未提及' : '未知';
  const competitor = measured && Array.isArray(analysis.entities) ? competitors.length ? competitors.map(e => e.name).join('、') : '未提及已跟踪竞品' : '未知';
  const native = measured && Array.isArray(citations) ? citations.filter(c => c.kind === 'citation' && c.own) : null;
  const position = measured && own?.rank?.position != null ? `第 ${own.rank.position} 位` : measured ? '未给出明确列表位置' : '未知';
  return `<div class="rq-sample"><p class="rq-state">${esc(state)}${sample.repeat != null ? ` · 第 ${esc(sample.repeat)} 次采样` : ''}</p>
    <dl class="rq-metrics"><div><dt>品牌提及</dt><dd>${mention}</dd></div><div><dt>竞品提及</dt><dd>${esc(competitor)}</dd></div><div><dt>官网原生引用</dt><dd>${native === null ? '未知' : native.length ? `${native.length} 条 AI 返回的引用` : '未返回官网引用'}</dd></div><div><dt>明确列表位置</dt><dd>${esc(position)}</dd></div></dl>
    ${measured && own?.rank?.evidence ? `<p class="ru-help">位置依据：${esc(own.rank.evidence)}</p>` : ''}
    <p class="ru-help">${!measured ? '回答不完整或分析未提供，提及与引用指标保持未知。' : analysis.eligible === true ? '此条纳入自然发现分母。' : analysis.eligible === false ? '此条不纳入自然发现分母（题面已点名跟踪对象或不适用）。' : '计分资格未记录。'}</p>
    ${sample.error ? `<p class="ru-warning">失败原因：${esc(sample.error)}</p>` : ''}
    <h4>原始回答</h4><pre class="evidence">${esc(sample.answer || '没有保存回答正文')}</pre>
    <p class="mono">请求模型：${esc(sample.model_requested || '未记录')}<br>返回模型：${esc(sample.model_returned || '未记录')}</p>
    <details class="ru-optional"><summary>查看引用、链接与原始记录</summary>${Array.isArray(citations) ? citations.map(c => `<p class="rq-citation"><b>${esc(({citation: 'AI 返回的引用', retrieved_source: '检索来源', answer_link: '回答中的普通链接'})[c.kind] || '类型未记录')}</b> · ${esc(c.owner || '归属未记录')}<br>${safeURL(c.url) ? `<a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">${esc(c.url)} ↗</a>` : esc(c.url || 'URL 未记录')}</p>`).join('') || '<p class="ru-help">未返回引用信息；不据此推断官网不可引用。</p>' : '<p class="ru-help">分析与引用信息未知。</p>'}<pre class="evidence">${esc(JSON.stringify(sample, null, 2))}</pre></details></div>`;
}
function questionDialogContent(job, index) {
  const prompt = job.prompts[index], providers = job.config?.providers || [];
  return head(`问题 ${index + 1} · 各模型回答`) + `<div class="rq-dialog-intro"><h3>${esc(typeof prompt === 'string' ? prompt : prompt.text || '题目文本未记录')}</h3><p class="rq-family">${questionFamilyLabel(questionFamily(job, index))}</p><p class="ru-help">展示本题所有已选模型；仅采用已保存分析，不根据原文推测分数。</p></div><div class="rq-models">${providers.map(provider => {
    const samples = questionSamples(job, index, provider), blocked = job.blocked_models?.[provider];
    return `<article class="rq-model" data-provider="${esc(provider)}"><h3>${esc(questionModelName(job, provider))}</h3><p class="mono">模型 ID：${esc(provider)}</p>${blocked ? `<p class="ru-warning">${esc(typeof blocked === 'string' ? blocked : JSON.stringify(blocked))}</p>` : ''}${samples.length ? samples.map(s => questionSampleContent(s, job)).join('') : questionSampleContent(null, job)}</article>`;
  }).join('') || '<p class="rr-empty">此任务未记录所选模型。</p>'}</div>`;
}
function questionOpen(index) {
  if (!geoActive || !Number.isInteger(index) || !geoActive.prompts?.[index]) return;
  modal(questionDialogContent(geoActive, index), 'question');
  document.querySelector('#overlay').dataset.questionIndex = String(index);
  const dialog = document.querySelector('#overlay [role="dialog"]');
  dialog?.setAttribute('aria-label', `问题 ${index + 1} · 所有已选模型的回答`);
  dialog?.classList.add('rq-dialog');
  dialog?.querySelector('.card-head button')?.setAttribute('aria-label', '关闭问题回答');
}
const questionBaseCloseOverlay = closeOverlay;
closeOverlay = function(updateURL = true) {
  const host = document.querySelector('#overlay'), index = host?.dataset.kind === 'question' ? host.dataset.questionIndex : null;
  questionBaseCloseOverlay(updateURL);
  // Polling may recreate the trigger while the dialog is open.
  if (index !== null) document.getElementById('question-card-' + index)?.focus();
};
if (page === 'research') render();
