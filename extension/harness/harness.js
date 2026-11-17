// harness.js - lets the Playwright evaluation call the REAL pipeline.
//
//   await window.runCapture({ urlPrefix, layers })
//     -> { payload, screenshot, stats, gate, timingMs, raw }
//
// It finds the tab whose URL starts with `urlPrefix`, runs perceive() on it
// with a fresh vault, and returns the sanitised payload plus the raw snapshot
// (the raw snapshot is for scoring only - it is never sent anywhere).
import { Vault } from '../src/redact/vault.js';
import { DEFAULT_LAYERS } from '../src/redact/sanitize.js';
import { initNER, status as nerStatus } from '../src/pii/ner.js';
import { createFaceDetector } from '../src/vision/faces.js';
import { createOCR } from '../src/vision/ocr.js';
import { perceive } from '../src/agent/pipeline.js';
import { runAgent } from '../src/agent/loop.js';

const tools = { faceDetector: null, ocr: null };
const ready = (async () => {
  await initNER();
  tools.faceDetector = await createFaceDetector();
  tools.ocr = await createOCR();
})();

window.runCapture = async ({ urlPrefix, layers }) => {
  await ready;
  const tabs = await chrome.tabs.query({});
  const tab = tabs.find((t) => t.url && t.url.startsWith(urlPrefix));
  if (!tab) throw new Error('no tab matching ' + urlPrefix);
  await chrome.tabs.update(tab.id, { active: true });
  await chrome.windows.update(tab.windowId, { focused: true });
  const vault = new Vault();
  const p = await perceive({ tabId: tab.id, windowId: tab.windowId, vault, layers: { ...DEFAULT_LAYERS, ...(layers || {}) }, tools });
  return { ...p, realValues: vault.realValues() };
};

// Run a whole task through the real agent loop. Every request body that is
// sent to the planner server is recorded so the caller can check it for the
// persona's real values (an independent leak check, separate from the gate).
window.runTask = async ({ urlPrefix, goal, secrets, layers, serverUrl, maxSteps, unsafeBaseline }) => {
  await ready;
  const tabs = await chrome.tabs.query({});
  const tab = tabs.find((t) => t.url && t.url.startsWith(urlPrefix));
  if (!tab) throw new Error('no tab matching ' + urlPrefix);
  await chrome.tabs.update(tab.id, { active: true });
  await chrome.windows.update(tab.windowId, { focused: true });
  const vault = new Vault();
  for (const [token, value] of Object.entries(secrets || {})) vault.setSecret(token, value);

  const sentBodies = [];
  const realFetch = window.fetch;
  window.fetch = (url, init) => {
    if (init && typeof init.body === 'string' && String(url).includes('/plan')) sentBodies.push(init.body);
    return realFetch(url, init);
  };
  const events = [];
  try {
    const result = await runAgent({
      goal, tabId: tab.id, windowId: tab.windowId, vault, tools, serverUrl, maxSteps: maxSteps || 15,
      layers: { ...DEFAULT_LAYERS, ...(layers || {}) }, unsafeBaseline: !!unsafeBaseline,
      onEvent: (e) => events.push(e),
    });
    return { result, events, sentBodies, realValues: vault.realValues() };
  } finally {
    window.fetch = realFetch;
  }
};

window.toolStatus = async () => {
  await ready;
  return { ner: nerStatus(), faces: tools.faceDetector.mode, ocr: tools.ocr.available };
};
