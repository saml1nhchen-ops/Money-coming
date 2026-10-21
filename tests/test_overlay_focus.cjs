/* Browser regression of the actual shared overlay handler, without API/model calls.
 * Requires Python Playwright and /usr/bin/chromium, as the browser integration tests do.
 */
const {execFileSync} = require('node:child_process');
const result = execFileSync('python', ['-c', String.raw`
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

source = Path('dist/app.js').read_text().removesuffix('init();\n')
if source.rstrip().endswith('init();'):
    source = source.rstrip()[:-len('init();')]
checks = []
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    page = browser.new_page()
    page.route('http://overlay.test/**', lambda route: route.fulfill(body='<button id="trigger">Open overlay</button><a href="#background">Background</a><div id="overlay"></div><div id="toast"></div>', content_type='text/html'))
    page.goto('http://overlay.test/')
    page.add_script_tag(content=source)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    for mode in ['modal', 'drawer']:
        page.evaluate('''mode=>{
          document.querySelector('#trigger').onclick=()=>{
            const html=head('Focus regression')+'<button id="alpha">Alpha</button><details id="extra"><summary id="summary">Evidence</summary><a id="evidence-link" href="#source">Source</a><input id="evidence-input"></details><button id="hidden" hidden>Hidden</button><button id="css-hidden" style="display:none">Hidden CSS</button><button disabled>Disabled</button><fieldset disabled><input></fieldset><div inert><button>Inert</button></div><button tabindex="-1">Not tabbable</button><button id="omega">Omega</button>';
            if(mode==='modal')modal(html);else drawer(html);
            document.querySelector('#overlay .card-head button').id='close';
          };
        }''', mode)
        page.locator('#trigger').click()
        assert page.evaluate("document.activeElement.matches('[role=dialog]')")
        actual = page.evaluate("overlayTabStops(document.querySelector('[role=dialog]')).map(el=>el.id)")
        assert actual == ['close', 'alpha', 'summary', 'omega'], actual
        forward = []
        for _ in range(12):
            page.keyboard.press('Tab')
            assert page.evaluate("document.querySelector('[role=dialog]').contains(document.activeElement)")
            forward.append(page.evaluate('document.activeElement.id'))
        assert forward == ['close','alpha','summary','omega'] * 3, forward
        reverse = []
        page.locator('#close').focus()
        for _ in range(12):
            page.keyboard.press('Shift+Tab')
            assert page.evaluate("document.querySelector('[role=dialog]').contains(document.activeElement)")
            reverse.append(page.evaluate('document.activeElement.id'))
        assert reverse == ['omega','summary','alpha','close'] * 3, reverse
        page.locator('#summary').click()
        assert page.evaluate("overlayTabStops(document.querySelector('[role=dialog]')).map(el=>el.id)") == ['close','alpha','summary','evidence-link','evidence-input','omega']
        for _ in range(18):
            page.keyboard.press('Tab')
            assert page.evaluate("document.querySelector('[role=dialog]').contains(document.activeElement)")
        page.locator('#summary').click()
        page.locator('#close').focus()
        page.keyboard.press('Shift+Tab')
        assert page.evaluate("document.activeElement.id==='omega'")
        # Recover from an external focus move on the next Tab.
        page.locator('#trigger').evaluate('(el)=>el.focus()')
        page.keyboard.press('Tab')
        assert page.evaluate("document.activeElement.id==='close'")
        page.keyboard.press('Escape')
        assert page.locator('[role=dialog]').count() == 0
        assert page.locator('#trigger').evaluate('(el)=>el===document.activeElement')
        page.locator('#trigger').click()
        page.locator('#close').click()
        assert page.locator('#trigger').evaluate('(el)=>el===document.activeElement')
        checks.append({'mode':mode,'forward':forward,'reverse':reverse,'expanded_details':True,'escape_and_close_restore':True})
    page.evaluate("document.querySelector('#trigger').onclick=()=>modal('<p>No interactive controls</p>')")
    page.locator('#trigger').click()
    for key in ['Tab','Shift+Tab']:
        page.keyboard.press(key)
        assert page.evaluate("document.activeElement.matches('[role=dialog]')")
    page.keyboard.press('Escape')
    assert not errors, errors
    browser.close()
print(json.dumps({'shared_overlay_chromium':checks,'empty_dialog':True,'browser_errors':errors}))
`], {encoding: 'utf8'});
process.stdout.write(result);
