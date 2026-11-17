"""
test_shield.py - does Shield mode protect a page from an agent that never asks PrivaSight for anything?

The "agent" here is plain Playwright: it reads the page text, takes its own screenshot, and types into
fields - exactly what a third-party agent does. Shield mode must make all of that safe:

  1. with Shield on, page text and attributes contain NONE of the persona's PII;
  2. sensitive inputs are visually blacked out, faces are blurred;
  3. the agent can still log in and edit a field by typing TOKENS ({USERNAME}, {PASSWORD}, {NEWPHONE});
     the real values reach the site, but were never visible to the agent;
  4. switching Shield off restores the page.

Run:  python eval/test_shield.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, browser_with_extension, free_port, static_server  # noqa: E402

PERSONAS = json.loads((ROOT / 'testbed/sites/data/personas.json').read_text(encoding='utf-8'))
ME = PERSONAS[0]
NEW_PHONE = '+91 98450 12345'
PII_FIELDS = ['name', 'aadhaar', 'pan', 'card', 'address', 'dob', 'email', 'phone', 'account', 'ifsc']

CHECKS = []


def check(name, ok, detail=''):
    CHECKS.append(ok)
    print(('PASS ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail else ''))


def norm(s):
    return ''.join(ch for ch in str(s) if ch.isalnum()).lower()


def page_surface(page):
    """Everything an agent can read WITHOUT running JS on an input: text + attributes."""
    return page.evaluate("""() => {
      const bits = [document.body.innerText, document.title];
      document.querySelectorAll('*').forEach(e => ['aria-label','title','alt','placeholder'].forEach(a => { const v = e.getAttribute(a); if (v) bits.push(v); }));
      return bits.join(' | ');
    }""")


def main():
    with static_server(free_port()) as base, browser_with_extension(headless=True) as (ctx, harness):
        ext = harness.url.split('/')[2]
        # The user's secrets live in the vault; agents only ever know the token names.
        harness.evaluate("""async ({u, p, n}) => {
          const { Vault } = await import(chrome.runtime.getURL('src/redact/vault.js'));
          const v = new Vault();
          v.setSecret('{USERNAME}', u); v.setSecret('{PASSWORD}', p); v.setSecret('{NEWPHONE}', n);
          await chrome.storage.session.setAccessLevel({ accessLevel: 'TRUSTED_AND_UNTRUSTED_CONTEXTS' });
          await chrome.storage.session.set({ shieldVault: v.toJSON(), shield: { enabled: true, strict: false } });
        }""", {'u': ME['username'], 'p': ME['password'], 'n': NEW_PHONE})

        page = ctx.new_page()
        page.bring_to_front()

        # ---- 3a. login by typing tokens ----
        page.goto(f'{base}/demobank/login.html?p=0&layout=1')
        page.wait_for_selector('html[data-privasight=ready]')
        page.click('#username'); page.keyboard.type('{USERNAME}')
        page.click('#password'); page.keyboard.type('{PASSWORD}')
        shown = page.evaluate("document.querySelector('#username').value")
        check('typed token was swapped for the real username inside the field', shown == ME['username'])
        page.click('button[type=submit]')
        page.wait_for_url('**/dashboard.html*')
        check('login with tokens succeeded', True)

        # ---- 1. profile page: nothing sensitive is readable ----
        page.goto(f'{base}/demobank/profile.html?p=0&layout=1')
        page.wait_for_selector('html[data-privasight=ready]', timeout=30000)
        surface = norm(page_surface(page))
        leaked = [f for f in PII_FIELDS if len(str(ME[f])) >= 4 and norm(ME[f]) in surface]
        check('page text + attributes contain no persona PII', not leaked, 'leaked: ' + ','.join(leaked) if leaked else '')
        text = page.inner_text('body')
        check('tokens are shown instead', '[AADHAAR_' in text and '[PAN_' in text and '[CARD_' in text)

        # ---- 2. visual hiding ----
        dark = page.evaluate("""() => [...document.querySelectorAll('input')].filter(i => i.value).map(i => getComputedStyle(i).backgroundColor)""")
        check('sensitive input fields are blacked out', dark and all(c == 'rgb(0, 0, 0)' for c in dark), str(dark))

        # ---- 3b. edit a field by typing a token ----
        page.fill('#phone', '')
        page.click('#phone'); page.keyboard.type('{NEWPHONE}')
        page.click('button:has-text("Save changes")')
        page.wait_for_selector('#result:has-text("Profile updated")')
        state = page.evaluate('window.__state()')
        saved = [a['data'].get('phone') for a in state.get('actions', []) if a['action'] == 'edit_profile']
        check('site received the REAL phone number typed via token', saved and saved[-1] == NEW_PHONE, str(saved))

        # ---- faces blurred ----
        page.goto(f'{base}/hr/login.html?p=0&layout=1')
        page.wait_for_selector('html[data-privasight=ready]')
        page.click('#username'); page.keyboard.type('{USERNAME}')
        page.click('#password'); page.keyboard.type('{PASSWORD}')
        page.click('button[type=submit]')
        page.wait_for_url('**/hr/profile.html*')
        page.wait_for_selector('html[data-privasight=ready]', timeout=30000)
        blur = page.evaluate("getComputedStyle(document.querySelector('img.avatar')).filter")
        check('profile photo is blurred', 'blur' in blur, blur)
        surface = norm(page_surface(page))
        leaked = [f for f in ['name', 'email', 'phone', 'address'] if norm(ME[f]) in surface]
        check('HR profile text has no persona PII', not leaked, ','.join(leaked))

        # ---- 4. switching off restores the page ----
        harness.evaluate("chrome.storage.session.set({ shield: { enabled: false } })")
        page.wait_for_function("!document.documentElement.dataset.privasight", timeout=10000)
        restored = norm(page_surface(page))
        check('Shield off restores the real page', norm(ME['email']) in restored)

    print(f"\n{sum(CHECKS)}/{len(CHECKS)} checks passed")
    sys.exit(0 if all(CHECKS) else 1)


if __name__ == '__main__':
    main()
