/* Homepage: language switch shared with the workspace ('signal-ui'), market tabs, and the
   website hand-off that opens the workspace diagnosis form prefilled. */
(() => {
  'use strict';
  const EN = {
    navLabel: 'Main', nav1: 'How it works', nav2: 'Features', nav3: 'Models', nav4: 'FAQ', signin: 'Sign in', cta: 'Diagnose for free',
    pill: 'AI search visibility for brands & agencies', h1a: 'Get your brand', h1b: 'recommended by AI',
    lead: 'Diagnose how your site shows up across DeepSeek, Qwen, ChatGPT, Gemini and more. Every score traces back to raw evidence. Every issue maps to a concrete fix.',
    urlLabel: 'Website', placeholder: 'Enter your website, e.g. brand.com', go: 'Diagnose', hint: 'No model calls or credits · report in about 1–2 minutes',
    invalid: 'Enter a valid website, e.g. brand.com',
    sampleLabel: 'Product preview', sample: 'Sample', own: 'Owned', cSources: 'Citation sources', cScore: 'GEO readiness', cRetest: 'Retest', cChecks: 'Rule checks',
    aiChip: 'DeepSeek · China', aiQ: 'Which home water purifier should I buy?', aiIntro: 'Weighing filter life and service, I’d pick:', ai1: '1. Your Brand RO-500 — 4-stage', ai2: '2. Competitor A 800G', ai3: '3. Competitor B Home', aiTag1: 'Mentioned · #1', aiTag2: '2 citations',
    scoreSub: '100% evidence coverage · 27 rules', d1: 'Access', d2: 'Entity & facts', d3: 'Questions', d4: 'Trust', d5: 'Structure', d6: 'Maintenance',
    retestTitle: 'Mention rate on unbranded questions', r1: 'Baseline', r2: 'Week 4', r3: 'Week 8', retestFoot: 'Same questions · models · entry',
    ch1: 'AI crawlers allowed', ch2: 'Organization schema', ch3: 'No FAQ content', ch4: 'No product spec table', ch5: 'AI citations · needs evidence',
    howA: 'From diagnosis to retest,', howB: 'evidence at every step', howSub: 'Not a black-box score. See how AI answers, find what your site is missing, then prove the fix with the same questions.',
    s1n: '01 · Diagnose', s1t: 'Site audit and AI answer sampling', s1b: 'Fetch representative pages and score 27 rules across six dimensions, while asking several models 30 real buyer questions to record mentions, ranks and citations.',
    s2n: '02 · Act', s2t: 'A prioritised fix list', s2b: 'Each issue names its evidence, target page, recommended change, owner and effort. Content changes are reviewed before they ship.',
    s3n: '03 · Retest', s3t: 'Like-for-like comparison', s3b: 'Freeze questions, models and entry points, then resample. Mismatched conditions are flagged, never dressed up as lift.',
    featTitle: 'Built for everyday GEO agency delivery', evA: 'Every conclusion', evB: 'opens to its source', snapshot: 'Page snapshot',
    evBody: 'Behind each score sit page snapshots, robots.txt, raw model answers and hashes. Every judgement holds up when a client asks why.',
    f1t: 'China and global, one workspace', f1b: 'Configure question sets and models per market. Metrics are computed separately, never blended.',
    f2t: 'Shared by the team, exported anytime', f2b: 'The team shares model connections and report history. Export HTML, PDF or Markdown for clients in one click.',
    modelsTitle: 'One question set, every major model', modelsSub: 'Pick from the models your team account can reach, one fixed version per vendor', market: 'Market', mktCN: 'China', mktUS: 'Global',
    faqTitle: 'FAQ',
    q1: 'How is GEO different from SEO?', a1: 'SEO is about rankings in search results. GEO is about whether AI answers mention, recommend and cite your brand. Related, but measured differently.',
    q2: 'Does the site diagnosis cost anything?', a2: 'It makes no model calls and uses no credits. Only AI answer sampling is billed, by the models you choose.',
    q3: 'Where does the score come from?', a3: '27 fixed rules across six dimensions, each with its reasoning and evidence. Rules without enough evidence are not scored, so you see a range instead.',
    q4: 'Can you test answers inside consumer apps?', a4: 'Sampling currently runs through model APIs, which can differ from in-app answers. Reports label the entry point clearly.',
    ctaA: 'See how AI describes', ctaB: 'your brand today', ctaSub: 'Enter your website and get your first diagnosis in minutes.', sampleReport: 'View sample report',
    title: 'Signal GEO · Get your brand recommended by AI'
  };
  const MODELS = { CN: ['DeepSeek', '通义千问 Qwen', '豆包 Doubao', 'Kimi', '腾讯混元', '智谱 GLM', 'MiniMax'], US: ['ChatGPT', 'Gemini', 'Claude', 'Perplexity', 'Llama', 'Grok'] };
  const $$ = s => [...document.querySelectorAll(s)];
  // Chinese strings live in the markup; capture them once so switching back restores them.
  const ZH = { invalid: '请输入有效的官网地址，例如 brand.com', title: document.title };
  for (const el of $$('[data-i18n]')) ZH[el.dataset.i18n] ??= el.textContent;
  for (const el of $$('[data-i18n-ph]')) ZH[el.dataset.i18nPh] ??= el.placeholder;
  for (const el of $$('[data-i18n-aria]')) ZH[el.dataset.i18nAria] ??= el.getAttribute('aria-label');
  let lang = 'zh', market = 'CN';
  try { if (localStorage.getItem('signal-ui') === 'en') lang = 'en'; } catch {}
  const text = key => (lang === 'en' ? EN : ZH)[key] ?? ZH[key] ?? '';

  function applyLang() {
    document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
    document.title = text('title');
    for (const el of $$('[data-i18n]')) el.textContent = text(el.dataset.i18n);
    for (const el of $$('[data-i18n-ph]')) el.placeholder = text(el.dataset.i18nPh);
    for (const el of $$('[data-i18n-aria]')) el.setAttribute('aria-label', text(el.dataset.i18nAria));
    for (const b of $$('[data-lang]')) b.setAttribute('aria-pressed', String(b.dataset.lang === lang));
    if (error.textContent) error.textContent = text('invalid');
  }
  function renderModels() {
    for (const b of $$('[data-market]')) b.setAttribute('aria-selected', String(b.dataset.market === market));
    const list = document.getElementById('models-list');
    list.setAttribute('aria-labelledby', market === 'CN' ? 'tab-cn' : 'tab-us');
    list.replaceChildren(...MODELS[market].map(name => Object.assign(document.createElement('li'), { textContent: name })));
  }

  const form = document.getElementById('start'), input = document.getElementById('site'), error = document.getElementById('site-error');
  form.addEventListener('submit', event => {
    event.preventDefault();
    const value = input.value.trim();
    // Accept bare domains; the backend normalises and re-validates the address.
    if (value.length > 2048 || !/^(https?:\/\/)?[^\s/.]+(\.[^\s/.]+)+(\/\S*)?$/i.test(value)) {
      form.classList.add('invalid'); error.textContent = text('invalid'); input.focus(); return;
    }
    try { sessionStorage.setItem('signal-diagnose-website', /^https?:\/\//i.test(value) ? value : 'https://' + value); } catch {}
    location.href = 'dist/team.html#/w/demo/diagnostic';
  });
  input.addEventListener('input', () => { form.classList.remove('invalid'); error.textContent = ''; });
  for (const a of $$('[data-focus-start]')) a.addEventListener('click', () => setTimeout(() => input.focus({ preventScroll: true }), 350));
  for (const b of $$('[data-lang]')) b.addEventListener('click', () => {
    lang = b.dataset.lang;
    try { localStorage.setItem('signal-ui', lang); } catch {}
    applyLang();
  });
  for (const b of $$('[data-market]')) b.addEventListener('click', () => { market = b.dataset.market; renderModels(); });
  renderModels();
  applyLang();
})();
