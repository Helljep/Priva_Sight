// bridge.js - lets an EXTERNAL agent use PrivaSight as its eyes and hands.
//
//   agent (MCP / HTTP) --> server/gateway.py --WebSocket--> this file --> the active tab
//
// The side panel connects out to the local gateway (never the other way round).
// Two commands are served:
//   perceive  -> run the full sanitising pipeline on the active tab and return the
//                SAFE result (redacted screenshot + tokenised elements/text).
//                If the privacy gate fails, an error is returned instead - never raw data.
//   act       -> carry out one action; tokens in `text` are swapped for real values
//                here, locally, so the agent never sees them.
//
// Only gate-approved data is ever returned to the agent.

import { perceive, ensureContentScript, sendToTab } from './pipeline.js';

export function startBridge({ url, token, vault, getLayers, tools, onStatus = () => {} }) {
  let ws = null;
  let stopped = false;

  async function activeTab() {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (!tab || !/^https?:/.test(tab.url || '')) throw new Error('no web page is active');
    return tab;
  }

  const handlers = {
    async perceive() {
      const tab = await activeTab();
      const p = await perceive({ tabId: tab.id, windowId: tab.windowId, vault, layers: getLayers(), tools });
      if (!p.gate.ok) return { error: 'blocked', reasons: p.gate.reasons };
      return { ...p.payloadParts, screenshot: p.screenshot, stats: p.stats };
    },

    async act(action) {
      const tab = await activeTab();
      const real = { ...action };
      if (action.type === 'navigate' && !/^https?:\/\//i.test(action.url || '')) {
        return { ok: false, error: 'only http(s) navigation is allowed' };
      }
      if (typeof real.text === 'string') real.text = vault.resolve(real.text); // tokens -> real values, locally
      await ensureContentScript(tab.id);
      return sendToTab(tab.id, { ps: 'act', action: real });
    },
  };

  function connect() {
    if (stopped) return;
    ws = new WebSocket(url.replace(/^http/, 'ws').replace(/\/$/, '') + '/bridge' + (token ? `?token=${encodeURIComponent(token)}` : ''));
    ws.onopen = () => onStatus('connected');
    ws.onclose = () => { onStatus('disconnected'); if (!stopped) setTimeout(connect, 2000); };
    ws.onmessage = async (ev) => {
      const msg = JSON.parse(ev.data);
      let result;
      try {
        if (!handlers[msg.cmd]) throw new Error('unknown command ' + msg.cmd);
        result = await handlers[msg.cmd](msg.params || {});
      } catch (err) {
        result = { error: String(err && err.message ? err.message : err) };
      }
      ws.send(JSON.stringify({ id: msg.id, result }));
    };
  }

  connect();
  return { stop() { stopped = true; if (ws) ws.close(); } };
}
