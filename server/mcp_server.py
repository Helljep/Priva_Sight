"""
mcp_server.py - exposes PrivaSight to any MCP-capable AI agent (Claude Desktop, IDE agents, ...).

An agent that is given THESE tools instead of raw browser control can only ever
see the sanitised screen. It speaks the Model Context Protocol over stdio
(newline-delimited JSON-RPC 2.0), so no extra packages are needed.

Tools
  privasight_screen   Sanitised screenshot (image) + element list and page text (JSON, tokens only)
  privasight_act      click / type / select / scroll / navigate. Text may be a token,
                      e.g. "{PASSWORD}" or "[PHONE_1]"; the real value is typed locally.

Setup for an MCP client (example, claude_desktop_config.json):
  { "mcpServers": { "privasight": {
      "command": "python",
      "args": ["C:/path/to/PrivaSight/server/mcp_server.py"],
      "env": { "PRIVASIGHT_URL": "http://127.0.0.1:8787", "PRIVASIGHT_AGENT_TOKEN": "choose-a-secret" } } } }
"""
import json
import os
import sys

import httpx

BASE = os.environ.get('PRIVASIGHT_URL', 'http://127.0.0.1:8787').rstrip('/')
HEADERS = {'X-PrivaSight-Token': os.environ['PRIVASIGHT_AGENT_TOKEN']} if os.environ.get('PRIVASIGHT_AGENT_TOKEN') else {}

TOOLS = [
    {
        'name': 'privasight_screen',
        'description': ('Look at the current browser tab. Returns a sanitised screenshot (personal data is blacked out, '
                        'faces blurred) and the page as JSON: numbered elements and visible text where personal values are '
                        'replaced by tokens like [PHONE_1] or {PASSWORD}. Use element ids with privasight_act.'),
        'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    {
        'name': 'privasight_act',
        'description': ('Perform ONE action on the current tab. To enter personal data, type the TOKEN, never a guessed value: '
                        'the real value is filled in on the user\'s device.'),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'type': {'type': 'string', 'enum': ['click', 'type', 'select', 'scroll', 'navigate', 'wait']},
                'id': {'type': 'integer', 'description': 'element id from privasight_screen'},
                'text': {'type': 'string', 'description': 'text, option name or token to enter'},
                'direction': {'type': 'string', 'enum': ['up', 'down']},
                'url': {'type': 'string'},
                'submit': {'type': 'boolean'},
            },
            'required': ['type'],
        },
    },
]


def call_tool(name: str, args: dict) -> dict:
    with httpx.Client(timeout=60) as client:
        if name == 'privasight_screen':
            r = client.post(f'{BASE}/agent/screen', headers=HEADERS)
            if r.status_code != 200:
                return {'isError': True, 'content': [{'type': 'text', 'text': f'PrivaSight refused: {r.status_code} {r.text[:500]}'}]}
            data = r.json()
            image = data.pop('screenshot', '')
            content = [{'type': 'text', 'text': json.dumps(data, ensure_ascii=False)}]
            if image.startswith('data:'):
                mime, b64 = image[5:].split(';base64,', 1)
                content.append({'type': 'image', 'data': b64, 'mimeType': mime})
            return {'content': content}
        if name == 'privasight_act':
            r = client.post(f'{BASE}/agent/act', json=args, headers=HEADERS)
            if r.status_code != 200:
                return {'isError': True, 'content': [{'type': 'text', 'text': f'action failed: {r.status_code} {r.text[:300]}'}]}
            return {'content': [{'type': 'text', 'text': json.dumps(r.json())}]}
    return {'isError': True, 'content': [{'type': 'text', 'text': f'unknown tool {name}'}]}


def handle(msg: dict):
    """Return a JSON-RPC response dict, or None for notifications."""
    method, mid = msg.get('method'), msg.get('id')
    if method == 'initialize':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {
            'protocolVersion': msg.get('params', {}).get('protocolVersion', '2024-11-05'),
            'capabilities': {'tools': {}},
            'serverInfo': {'name': 'privasight', 'version': '1.0.0'}}}
    if method == 'tools/list':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {'tools': TOOLS}}
    if method == 'tools/call':
        p = msg.get('params', {})
        try:
            result = call_tool(p.get('name', ''), p.get('arguments') or {})
        except Exception as err:  # noqa: BLE001 - report any failure to the agent as a tool error
            result = {'isError': True, 'content': [{'type': 'text', 'text': f'gateway unreachable: {err}'}]}
        return {'jsonrpc': '2.0', 'id': mid, 'result': result}
    if method == 'ping':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {}}
    if mid is None:
        return None  # notification such as notifications/initialized
    return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': f'method not found: {method}'}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        resp = handle(json.loads(line))
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + '\n')
            sys.stdout.flush()


if __name__ == '__main__':
    main()
