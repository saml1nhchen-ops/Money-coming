"""Browser acceptance against tests/fixtures/serve_url_flow.py --partial.

Requires Python Playwright and Chromium. This tests controlled integration only;
no website snapshot or model answer is a real Cremo measurement.
"""
import argparse
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--complete', action='store_true', help='Use fixture server without --partial')
    parser.add_argument('--no-models', action='store_true', help='Use fixture server with --no-models')
    args = parser.parse_args()
    evidence = Path(os.environ.get('GEO_BROWSER_EVIDENCE', '/tmp/geo-url-flow-evidence'))
    evidence.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:8772/#/w/demo/research')
        page.get_by_role('button', name='美国', exact=True).click()
        page.locator('#geo-website').fill('https://cremocompany.com/')
        page.locator('#inspect-website-button').click()
        expect(page.locator('#website-readiness-score')).to_contain_text('100')
        expect(page.locator('#ru-brand')).to_have_value('Cremo')
        expect(page.locator('#website-inspection')).to_contain_text('不代表 AI 提及')
        page.get_by_role('button', name='下一步：选择 AI').click()
        if args.no_models:
            expect(page.locator('.ru-model')).to_have_count(0)
            expect(page.get_by_role('button', name='开始分析')).to_be_disabled()
            expect(page.locator('main')).to_contain_text('还没有可用的 AI 连接')
            assert not errors, errors
            print('PASS controlled browser: URL-only page inspection works with no model credentials; analysis stays disabled.')
            browser.close()
            return
        page.locator('.ru-model').filter(has_text='OpenAI').click()
        page.locator('.ru-model').filter(has_text='Google').click()
        page.get_by_role('button', name='开始分析').click()
        page.wait_for_function("typeof geoActive !== 'undefined' && ['finished','partial','failed'].includes(geoActive?.status)", timeout=60000)
        job = page.evaluate('geoActive')
        assert job['status'] == ('finished' if args.complete else 'partial'), job.get('error')
        assert len(job['prompts']) == 30
        assert len(job['samples']) == (60 if args.complete else 33)
        expect(page.locator('[data-question-index]')).to_have_count(30)
        page.locator('#question-card-0').click()
        dialog = page.get_by_role('dialog')
        expect(dialog).to_be_visible()
        expect(dialog.locator('.rq-model')).to_have_count(2)
        expect(dialog).to_contain_text('SYNTHETIC TEST ANSWER')
        expect(dialog).to_contain_text('原始回答')
        page.keyboard.press('Escape')
        expect(dialog).not_to_be_visible()
        expect(page.locator('#question-card-0')).to_be_focused()
        page.locator('#question-card-2').click()
        if not args.complete:
            expect(page.get_by_role('dialog')).to_contain_text('HTTP 429')
        assert page.evaluate('window.fixtureXSS') is None
        page.keyboard.press('Escape')
        page.locator('#question-card-3').click()
        expect(page.get_by_role('dialog').locator('.rq-model')).to_have_count(2)
        if not args.complete:
            expect(page.get_by_role('dialog')).to_contain_text('未运行')
        page.keyboard.press('Escape')
        # Explicitly mark every exported screenshot as controlled test evidence.
        page.evaluate("""() => {const banner=document.createElement('div');banner.textContent='SYNTHETIC FIXTURE · 非 Cremo 实测';banner.style='position:fixed;top:0;left:0;z-index:99999;background:#ffeb92;padding:5px;font-weight:bold';document.body.append(banner)}""")
        page.screenshot(path=str(evidence / 'desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile page overflows'
        page.locator('#question-card-0').click()
        expect(page.get_by_role('dialog')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile dialog overflows'
        page.screenshot(path=str(evidence / 'mobile-dialog.png'), full_page=True)
        page.keyboard.press('Escape')
        assert not errors, errors
        (evidence / 'summary.json').write_text(json.dumps({'synthetic': True, 'status': job['status'],
            'questions': len(job['prompts']), 'samples': len(job['samples']), 'browser_errors': errors}, indent=2))
        print(f'PASS controlled HTTP/browser workflow: 30 question cards, 2 models, {job["status"]}, desktop/mobile, Escape/focus/XSS. Evidence: {evidence}')
        browser.close()


if __name__ == '__main__':
    main()
