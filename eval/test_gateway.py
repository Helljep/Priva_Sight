"""
test_gateway.py - an external "agent" drives the browser ONLY through the MCP tools.

The fake agent below stands in for Claude Desktop / any MCP client. It speaks real MCP
(JSON-RPC over stdio) to server/mcp_server.py, which calls the gateway, which asks the
extension. We then check what the agent was able to learn:

  * it can log in and navigate using tokens ({USERNAME}, {PASSWORD}) - the task works;
  * nothing it received (text, JSON, tool results) contains the persona's real PII;
  * the screenshot it received is an image;
  * a wrong agent token is rejected.

Run:  python eval/test_gateway.py
"""
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, browser_with_extension, free_port, planner_server, static_server  # noqa: E402

PERSONAS = json.loads((ROOT / 'testbed/sites/data/personas.json').read_text(encoding='utf-8'))
ME = PERSONAS[0]
AGENT_TOKEN = 'test-secret-123'
CHECKS = []


def check(name, ok, detail=''):
    CHECKS.append(ok)
    print(('PASS ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail else ''))


def norm(s):
    return ''.join(ch for ch in str(s) if ch.isalnum()).lower()


class McpClient:
    """Minimal MCP client over stdio (what an agent framework does for you)."""

    def __init__(self, env):
        self.p = subprocess.Popen([sys.executable, str(ROOT / 'server' / 'mcp_server.py')], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, env={**os.environ, **env})
        self.n = 0

    def rpc(self, method, params=None, notify=False):
        msg = {'jsonrpc': '2.0', 'method': method, 'params': params or {}}
        if not notify:
            self.n += 1
            msg['id'] = self.n
        self.p.stdin.write(json.dumps(msg) + '\n')
        self.p.stdin.flush()
        return None if notify else json.loads(self.p.stdout.readline())

    def tool(self, name, **args):
        return self.rpc('tools/call', {'name': name, 'arguments': args})['result']

    def close(self):
        self.p.terminate()


def screen(mcp):
    res = mcp.tool('privasight_screen')
    if res.get('isError'):
        return None, None, res
    page = json.loads(res['content'][0]['text'])
    image = next((c for c in res['content'] if c['type'] == 'image'), None)
    return page, image, res


def find(page, tag=None, text=None, label=None, type_=None):
    for e in page['elements']:
        if tag and e['tag'] != tag:
            continue
        if text and text.lower() not in (e.get('text') or '').lower():
            continue
        if label and label.lower() not in (e.get('label') or '').lower():
            continue
        if type_ and e.get('type') != type_:
            continue
        return e['id']
    raise AssertionError(f'element not found: {tag} {text} {label}')


def main():
    seen = []  # everything the agent ever received, to scan for PII at the end
    env_srv = {'PRIVASIGHT_AGENT_TOKEN': AGENT_TOKEN}
    with static_server(free_port()) as base, planner_server(free_port(), extra_env=env_srv) as srv, \
            browser_with_extension(headless=True) as (ctx, harness):
        ext = harness.url.split('/')[2]

        # the user's side: open the side panel, put secrets in the vault, switch the gateway on
        panel = ctx.new_page()
        panel.goto(f'chrome-extension://{ext}/sidepanel/sidepanel.html')
        panel.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
        panel.fill('#server', srv); panel.dispatch_event('#server', 'change')
        panel.fill('#sec-username', ME['username']); panel.fill('#sec-password', ME['password'])
        panel.fill('#gw-token', AGENT_TOKEN)
        panel.check('#gateway')
        panel.wait_for_function("document.getElementById('gw-status').textContent === 'connected'", timeout=15000)
        check('extension connected to the gateway', True)

        page = ctx.new_page()
        page.goto(f'{base}/demobank/login.html?p=0&layout=1')
        page.wait_for_selector('body[data-ready]')
        page.bring_to_front()

        r = httpx.post(f'{srv}/agent/screen', headers={'X-PrivaSight-Token': 'wrong'})
        check('wrong agent token is rejected', r.status_code == 401, str(r.status_code))

        mcp = McpClient({'PRIVASIGHT_URL': srv, 'PRIVASIGHT_AGENT_TOKEN': AGENT_TOKEN})
        init = mcp.rpc('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 'fake-agent', 'version': '0'}})
        mcp.rpc('notifications/initialized', notify=True)
        tools = [t['name'] for t in mcp.rpc('tools/list')['result']['tools']]
        check('MCP handshake and tool list', init['result']['serverInfo']['name'] == 'privasight' and tools == ['privasight_screen', 'privasight_act'], str(tools))

        # ---- the agent logs in using tokens only ----
        pg, img, raw = screen(mcp)
        seen.append(json.dumps(raw['content'][0]['text']))
        check('agent received a screenshot image', img is not None and len(base64.b64decode(img['data'])) > 1000)
        u, p, b = find(pg, tag='input', label='Username'), find(pg, tag='input', label='Password'), find(pg, tag='button', text='Log in')
        for res in (mcp.tool('privasight_act', type='type', id=u, text='{USERNAME}'),
                    mcp.tool('privasight_act', type='type', id=p, text='{PASSWORD}'),
                    mcp.tool('privasight_act', type='click', id=b)):
            seen.append(json.dumps(res))
        page.wait_for_url('**/dashboard.html*', timeout=15000)
        check('agent logged in without ever seeing the credentials', True)

        # ---- navigate to the profile and read it ----
        pg, img, raw = screen(mcp)
        seen.append(raw['content'][0]['text'])
        mcp.tool('privasight_act', type='click', id=find(pg, tag='a', text='Profile'))
        page.wait_for_url('**/profile.html*', timeout=15000)
        pg, img, raw = screen(mcp)
        text = raw['content'][0]['text']
        seen.append(text)
        check('profile screen shows tokens', '[AADHAAR_' in text and '[PAN_' in text, '')

        # ---- the key check: nothing the agent received holds real PII ----
        blob = norm(' '.join(seen))
        leaked = [f for f in ['name', 'aadhaar', 'pan', 'card', 'address', 'dob', 'email', 'phone', 'account', 'ifsc', 'password', 'username']
                  if len(str(ME[f])) >= 4 and norm(ME[f]) in blob]
        check('nothing the agent received contains real PII', not leaked, ','.join(leaked))

        # ---- the agent edits a field with a token it was shown, never the real value ----
        phone_input = find(pg, tag='input', label='Mobile')
        mcp.tool('privasight_act', type='type', id=phone_input, text='{USERNAME}')  # any known token; proves token->real swap
        typed = page.evaluate("document.querySelector('#phone').value")
        check('token typed by the agent became the real value in the page', typed == ME['username'], '')
        mcp.close()

    print(f"\n{sum(CHECKS)}/{len(CHECKS)} checks passed")
    sys.exit(0 if all(CHECKS) else 1)


if __name__ == '__main__':
    main()
