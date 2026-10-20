/* Report presentation only. Scores and evidence remain computed by the existing rules. */
function reportValidSamples(r) {
  return (r.samples || []).filter(s => s.status === 'complete' && s.analysis?.eligible);
}

function reportGapGroups(r) {
  const valid = new Set(reportValidSamples(r).map(s => s.id)), groups = new Map();
  for (const gap of r.gaps || []) {
    if (!valid.has(gap.sample_id)) continue;
    if (!groups.has(gap.prompt)) groups.set(gap.prompt, {prompt: gap.prompt, competitors: new Set(), ids: new Set()});
    const group = groups.get(gap.prompt);
    group.ids.add(gap.sample_id);
    for (const name of gap.competitors) group.competitors.add(name);
  }
  return [...groups.values()].map(g => ({...g, competitors: [...g.competitors], ids: [...g.ids]}))
    .sort((a, b) => b.ids.length - a.ids.length);
}

function reportCitedSources(r) {
  const sources = new Map();
  for (const sample of reportValidSamples(r)) for (const citation of sample.analysis.citations || []) {
    if (citation.kind !== 'citation') continue;
    if (!sources.has(citation.domain)) sources.set(citation.domain, {...citation, urls: new Set(), ids: new Set()});
    const source = sources.get(citation.domain);
    source.urls.add(citation.url);
    source.ids.add(sample.id);
  }
  return [...sources.values()].map(s => ({...s, urls: [...s.urls], sample_ids: [...s.ids], answer_count: s.ids.size}))
    .sort((a, b) => b.answer_count - a.answer_count);
}

function reportEvidenceButtons(ids, label = '查看原始回答') {
  return ids.map((id, i) => `<button class="small" onclick="reportOpenEvidence(decodeURIComponent('${enc(id)}'))">${esc(label)}${ids.length > 1 ? ' ' + (i + 1) : ''} ↗</button>`).join('');
}

function reportOpenEvidence(id) {
  const sample = geoActive?.report?.samples?.find(s => s.id === id);
  if (!sample) return;
  drawer(reportEvidenceContent(sample));
}

function reportEvidenceContent(sample) {
  const kinds = {citation: 'AI 返回的引用', retrieved_source: '搜索找到的页面', answer_link: '回答里的普通链接'};
  return head('原始回答与引用') + `<p class="ru-evidence-meta">${esc(researchDisplayModel(sample.provider))}</p><h3>${esc(sample.prompt)}</h3><pre class="evidence">${esc(sample.answer || sample.error || '没有保存回答正文')}</pre><h3>这条回答的来源</h3>${(sample.analysis?.citations || []).map(c => `<p>${esc(kinds[c.kind] || '其他来源')} · ${safeURL(c.url) ? `<a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">${esc(c.url)} ↗</a>` : esc(c.url)}</p>`).join('') || '<p class="ru-help">这条回答没有提供可展示的来源信息。</p>'}<details class="ru-optional"><summary>查看记录详情</summary><pre class="evidence">${esc(JSON.stringify(sample, null, 2))}</pre></details>`;
}

function reportScrollTo(section) {
  document.getElementById('report-' + section)?.scrollIntoView({behavior: 'smooth', block: 'start'});
}

function reportCompetitors(m) {
  const rows = new Map();
  for (const model of m.ms) for (const brand of model.brands) {
    if (!rows.has(brand.name)) rows.set(brand.name, {name: brand.name, own: brand.own, hits: 0, total: 0});
    const row = rows.get(brand.name);
    row.hits += brand.mentions;
    row.total += brand.denominator;
  }
  return [...rows.values()].map(b => ({...b, rate: b.total ? 100 * b.hits / b.total : null}))
    .sort((a, b) => Number(b.own) - Number(a.own) || (b.rate ?? -1) - (a.rate ?? -1));
}

function reportOverview(r, j, m, gaps, sources) {
  const provisional = j.status !== 'finished';
  const complete = (r.samples || []).filter(s => s.status === 'complete').length;
  const scope = `${m.hits} / ${m.total}`;
  return `<section class="rr-overview" id="report-overview" aria-labelledby="report-overview-title">
    <div class="rr-score"><span class="ru-kicker">${provisional ? '阶段结果 · 本次分析' : '本次分析'}</span><h3>品牌提及得分</h3><div class="rr-score-number">${m.score === null ? '—' : m.score}<span>/ 100</span></div><p>${m.total ? `${scope} 条有效回答提到你的品牌` : '有效回答不足，暂时无法评分'}</p><span class="rr-score-caption">按本次回答中的品牌提及比例换算</span></div>
    <div class="rr-conclusions"><span class="ru-kicker">先看结论</span><h2 id="report-overview-title">${m.total ? `本次有效回答中，${m.score}% 提到了你` : '先补齐回答，再判断品牌表现'}</h2>
      <ul><li>${m.total ? `本次有 ${m.total} 条完整回答可用于品牌发现分析，来自 ${m.ms.filter(v => v.eligible > 0).length} 个 AI 模型。` : '当前没有可用于品牌发现分析的完整回答；失败或不适用的回答不会算成零分。'}</li>
      <li>${!j.config.competitors?.length ? '本次未设置竞品，暂时不能判断竞品差距。' : gaps.length ? `有 ${gaps.length} 个问题出现了竞品，但你的品牌没有被提及或引用，值得优先核对。` : m.total ? '当前有效回答中，暂未发现“竞品出现而你未出现”的问题；这不代表所有问题都已覆盖。' : '竞品差距也需要有效回答，当前不作判断。'}</li>
      <li>${sources.length ? `找到 ${sources.length} 个被 AI 引用的来源域名，可展开核对原文。` : '暂没有可展示的 AI 引用证据，不能据此判断官网是否具备被引用的条件。'}</li></ul>
      <p class="ru-help">完整回答 ${complete} / ${(r.samples || []).length} 条已返回记录。得分只统计题目没有点名品牌、竞品或产品的完整回答，仅描述本次提及表现，不代表推荐程度或网站准备度；不同 AI 的结果可在下方分别查看。${provisional ? '分析尚未全部完成，结果可能继续变化。' : ''}${m.total > 0 && m.total < 10 ? '有效回答较少，建议先作为试测结果。' : ''}</p>
    </div></section>`;
}

function reportGapSection(r, j, m, gaps) {
  const competitors = reportCompetitors(m), own = competitors.find(b => b.own);
  const rows = competitors.map(b => {
    const diff = b.rate !== null && own?.rate != null ? Math.round((b.rate - own.rate) * 10) / 10 : null;
    return `<tr><td><strong>${esc(b.name)}</strong>${b.own ? '<span class="rr-own">你的品牌</span>' : ''}</td><td>${b.hits} / ${b.total}</td><td>${b.rate === null ? '—' : Number(b.rate.toFixed(1)) + '%'}</td><td>${b.own ? '—' : diff === null ? '待补回答' : diff === 0 ? '相同' : `${diff > 0 ? '多' : '少'} ${Math.abs(diff)} 个百分点`}</td></tr>`;
  }).join('');
  return `<section class="rr-section" id="report-gaps" aria-labelledby="report-gaps-title"><div class="rr-section-heading"><div><span class="ru-kicker">01 / 竞品差距</span><h2 id="report-gaps-title">哪些问题里，用户看到了竞品？</h2><p>先看差距，再展开回答确认具体语境。</p></div><span class="rr-count">${j.config.competitors?.length && m.total ? gaps.length : '—'} 个问题待核对</span></div>
    ${j.config.competitors?.length ? `<div class="rr-table">${table(['品牌', '提及回答 / 有效回答', '提及比例', '与本品牌相比'], rows)}</div><p class="ru-help">上表只比较名称提及，不把提及当作推荐。不同 AI 的回答按条数合计；逐家结果保留在报告明细中。</p>` : '<p class="rr-empty">本次没有设置竞品。补充竞品后，可以用已有回答重新分析，不必重新调用模型。</p>'}
    ${gaps.length ? `<div class="rr-gap-list">${gaps.slice(0, 3).map(g => `<details class="rr-gap"><summary><span>${esc(g.prompt)}<small>出现的竞品：${esc(g.competitors.join('、'))}</small></span><span class="rr-pill">${g.ids.length} 条回答</span></summary><p class="ru-help">这些完整回答中，竞品被提及或引用，而你的品牌均未出现。原因尚未验证，请先查看回答和来源。</p><div class="actions">${reportEvidenceButtons(g.ids)}</div></details>`).join('')}</div>${gaps.length > 3 ? `<details class="ru-optional"><summary>其余 ${gaps.length - 3} 个问题</summary>${gaps.slice(3).map(g => `<div class="rr-extra-gap"><h3>${esc(g.prompt)}</h3><p>${esc(g.competitors.join('、'))}</p><div class="actions">${reportEvidenceButtons(g.ids)}</div></div>`).join('')}</details>` : ''}` : `<p class="rr-empty">${m.total ? j.config.competitors?.length ? '当前样本未发现符合条件的问题，仍可到回答明细查看具体表现。' : '设置竞品前，不生成竞品差距结论。' : '还没有有效回答，暂不判断是否存在竞品差距。'}</p>`}</section>`;
}

function reportSourceSection(r, sources) {
  const other = (r.sources || []).filter(s => s.kind !== 'citation');
  return `<section class="rr-section" id="report-sources" aria-labelledby="report-sources-title"><div class="rr-section-heading"><div><span class="ru-kicker">02 / 引用证据</span><h2 id="report-sources-title">AI 的回答依据来自哪里？</h2><p>这里仅展示有效品牌发现回答中，AI 返回的引用。</p></div></div>
    ${sources.length ? `<div class="rr-source-grid">${sources.map(s => `<article class="rr-source"><span class="rr-pill">AI 返回的引用</span><h3>${esc(s.domain)}</h3><p>${esc(s.owner)} · 出现在 ${s.answer_count} 条回答中</p><details><summary>展开页面与回答</summary><div class="rr-source-links">${s.urls.map(url => safeURL(url) ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(url)} ↗</a>` : `<span>${esc(url)}</span>`).join('')}</div><div class="actions">${reportEvidenceButtons(s.sample_ids)}</div></details></article>`).join('')}</div>` : '<p class="rr-empty">暂无可展示的引用证据。模型没有提供引用信息时，不将缺失信息记成“官网引用率为零”。</p>'}
    ${other.length ? `<details class="ru-optional"><summary>其他链接与搜索来源 <span>这些记录不计入上方引用证据</span></summary><p class="ru-help">搜索找到的页面、回答中的普通链接，以及其他题型和未完成回答的记录，可在“全部引用与链接”中查看。</p><button onclick="researchResultTab='sources';render();reportScrollTo('details')">查看全部引用与链接 →</button></details>` : ''}</section>`;
}

function reportActionSection(r, j, m, gaps, sources) {
  const incomplete = (r.samples || []).filter(s => s.status !== 'complete').length;
  const actions = [];
  if (incomplete || !m.total) actions.push({title: '先补齐可用的回答', text: incomplete ? `${incomplete} 条回答尚未完成。先查看失败原因，确认连接或额度后，再决定是否继续调用。` : '确认模型连接和题目设置，获取完整回答后再判断表现。', owner: '分析负责人', ids: (r.samples || []).filter(s => s.status !== 'complete').slice(0, 2).map(s => s.id)});
  if (gaps.length) actions.push({title: '先核对竞品出现的重点问题', text: `从“${gaps[0].prompt}”开始，检查官网是否回答了同一需求；只有确认缺少信息后，再补充有事实依据的内容。`, owner: '官网内容负责人', ids: gaps[0].ids});
  if (sources.length) actions.push({title: '对照引用页面检查信息差异', text: '查看这些页面回答了什么、用了哪些依据，再与自己的相关页面对照。被引用不代表已经证明了排名原因。', owner: '内容与产品负责人', ids: sources[0].sample_ids});
  if (m.total) actions.push({title: '记录修改，再用同一组问题复测', text: '保存本次题目和证据。实施修改后，尽量保持模型、市场与问题不变，再比较结果；目前还没有可比的提升结论。', owner: '分析负责人', ids: []});
  return `<section class="rr-section" id="report-actions" aria-labelledby="report-actions-title"><div class="rr-section-heading"><div><span class="ru-kicker">03 / 下一步行动</span><h2 id="report-actions-title">接下来，先做这几件事</h2><p>这是待执行清单，尚未修改或发布你的网站。</p></div></div><ol class="rr-actions">${actions.map((a, i) => `<li><span class="rr-action-number">${i + 1}</span><div><h3>${esc(a.title)}</h3><p>${esc(a.text)}</p><span class="rr-action-owner">建议负责：${esc(a.owner)}</span><div class="actions">${reportEvidenceButtons(a.ids, '核对依据')}</div></div></li>`).join('')}</ol><button onclick="geoExport()">↓ 保存本次分析与证据</button></section>`;
}

function researchReport(r, j) {
  const m = researchMetrics(r), gaps = reportGapGroups(r), sources = reportCitedSources(r);
  return `<nav class="rr-nav" aria-label="报告章节">${[['overview','总分与结论'],['gaps','竞品差距'],['sources','引用证据'],['actions','下一步行动']].map(([key, title]) => `<button onclick="reportScrollTo('${key}')">${title}</button>`).join('')}</nav>
    ${reportOverview(r, j, m, gaps, sources)}${reportGapSection(r, j, m, gaps)}${reportSourceSection(r, sources)}${reportActionSection(r, j, m, gaps, sources)}
    <section class="rr-section" id="report-details"><div class="rr-section-heading"><div><span class="ru-kicker">继续查看</span><h2>报告明细</h2><p>保留各家 AI、产品和每条原始回答，方便进一步核对。</p></div></div><div class="ru-result-tabs">${[['overview','各家 AI 表现'],['products','产品表现'],['gaps','全部差距回答'],['sources','全部引用与链接'],['answers','回答明细']].map(([k, v]) => `<button class="${researchResultTab === k ? 'active' : ''}" aria-pressed="${researchResultTab === k}" onclick="researchResultTab='${k}';render();reportScrollTo('details')">${v}</button>`).join('')}</div>${researchResultBody(r, j, m)}</section>`;
}

if (page === 'research' && geoActive?.report) render();
