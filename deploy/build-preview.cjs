/* Build a static-only preview from public frontend assets, never runtime data. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '..');
const source = path.join(root, 'dist');
const output = path.join(root, 'preview-dist');
const allowed = new Set(['.html', '.js', '.css', '.json', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.ico', '.woff', '.woff2', '.ttf']);

function copy(directory, destination) {
  fs.mkdirSync(destination, { recursive: true });
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    assert(!entry.isSymbolicLink(), 'Symlinks are not permitted in preview assets');
    assert(!entry.name.startsWith('.'), 'Hidden files are not permitted in preview assets');
    const from = path.join(directory, entry.name), to = path.join(destination, entry.name);
    if (entry.isDirectory()) copy(from, to);
    else {
      assert(allowed.has(path.extname(entry.name).toLowerCase()), `Unexpected frontend file: ${entry.name}`);
      fs.copyFileSync(from, to);
    }
  }
}

fs.rmSync(output, { recursive: true, force: true });
copy(source, output);
const index = path.join(output, 'index.html');
let html = fs.readFileSync(index, 'utf8');
assert(html.includes('<head>') && html.includes('<body>'), 'Expected HTML entry point');
html = html.replace('<head>', '<head><meta name="robots" content="noindex,nofollow,noarchive"><link rel="stylesheet" href="preview-notice.css">');
html = html.replace('<body>', '<body><div class="signal-preview-notice" role="note">界面预览 · 此地址不连接正式后台或共享结果。自动 AI 分析仍需后台服务。</div>');
fs.writeFileSync(index, html);
fs.writeFileSync(path.join(output, 'preview-notice.css'), ':root{--preview-notice-height:42px}body{padding-top:var(--preview-notice-height)}.signal-preview-notice{position:fixed;top:0;left:0;right:0;z-index:10000;min-height:var(--preview-notice-height);padding:10px 16px;background:#fff4ce;color:#513c06;border-bottom:1px solid #e3ce86;text-align:center;font:13px/1.6 system-ui,sans-serif}.layout>aside{top:var(--preview-notice-height);height:calc(100vh - var(--preview-notice-height))}@media(max-width:600px){:root{--preview-notice-height:64px}}\n');
fs.writeFileSync(path.join(output, 'robots.txt'), 'User-agent: *\nDisallow: /\n');
console.log('Static frontend preview built in preview-dist; no backend or credentials included.');
