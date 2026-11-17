"""
gateway.py - the door an external AI agent uses to see and act on the browser.

    agent  --HTTP-->  /agent/screen, /agent/act   (or the MCP wrapper, mcp_server.py)
    gateway --WebSocket /bridge-->  the PrivaSight extension, which does the real work

The agent never talks to the browser directly. Whatever comes back from the
extension is the SANITISED view (redacted screenshot, tokenised text); this
module re-scans it for raw PII once more before handing it over, and refuses
if anything is found.

Security:
  * Bind to 127.0.0.1 only (the default in the README).
  * Set PRIVASIGHT_AGENT_TOKEN to require a shared secret on every /agent call
    and on the extension's WebSocket, so other local programs cannot use it.
"""
import asyncio
import itertools
import os

from fastapi import APIRouter, Header, HTTPException, WebSocket, WebSocketDisconnect

from pii import scan_payload

router = APIRouter()
TOKEN = os.environ.get('PRIVASIGHT_AGENT_TOKEN', '')


class Bridge:
    """Holds the one live connection to the extension and matches replies to requests."""

    def __init__(self):
        self.ws: WebSocket | None = None
        self.pending: dict[int, asyncio.Future] = {}
        self.ids = itertools.count(1)

    @property
    def connected(self) -> bool:
        return self.ws is not None

    async def call(self, cmd: str, params: dict | None = None, timeout: float = 40.0) -> dict:
        if not self.ws:
            raise HTTPException(503, 'PrivaSight extension is not connected. Open the side panel and switch on "Agent gateway".')
        rid = next(self.ids)
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        await self.ws.send_json({'id': rid, 'cmd': cmd, 'params': params or {}})
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            raise HTTPException(504, 'the extension did not answer in time')
        finally:
            self.pending.pop(rid, None)


bridge = Bridge()


def _auth(token: str | None):
    if TOKEN and token != TOKEN:
        raise HTTPException(401, 'bad or missing agent token')


@router.websocket('/bridge')
async def bridge_socket(ws: WebSocket, token: str = ''):
    if TOKEN and token != TOKEN:
        await ws.close(code=4401)
        return
    await ws.accept()
    bridge.ws = ws
    try:
        while True:
            msg = await ws.receive_json()
            fut = bridge.pending.get(msg.get('id'))
            if fut and not fut.done():
                fut.set_result(msg.get('result', {}))
    except WebSocketDisconnect:
        pass
    finally:
        if bridge.ws is ws:
            bridge.ws = None


@router.get('/agent/status')
async def status(x_privasight_token: str | None = Header(default=None)):
    _auth(x_privasight_token)
    return {'extension_connected': bridge.connected}


@router.post('/agent/screen')
async def screen(x_privasight_token: str | None = Header(default=None)):
    """Return the sanitised view of the active tab."""
    _auth(x_privasight_token)
    result = await bridge.call('perceive')
    if result.get('error') == 'blocked':
        raise HTTPException(409, {'error': 'privacy gate blocked this screen', 'reasons': result.get('reasons')})
    if result.get('error'):
        raise HTTPException(502, result['error'])
    # third and last check before the data reaches the agent
    hits = scan_payload(result)
    if hits:
        raise HTTPException(422, {'error': 'raw PII found in outgoing view', 'findings': hits[:10]})
    return result


@router.post('/agent/act')
async def act(action: dict, x_privasight_token: str | None = Header(default=None)):
    """Perform one action. Text may contain tokens such as {PASSWORD} or [PHONE_1]."""
    _auth(x_privasight_token)
    if action.get('type') not in {'click', 'type', 'select', 'scroll', 'navigate', 'wait'}:
        raise HTTPException(400, 'unsupported action type')
    result = await bridge.call('act', action)
    if isinstance(result, dict) and result.get('error'):
        raise HTTPException(502, result['error'])
    return result
