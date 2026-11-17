// pipeline.js
// One "perception step": look at the tab, sanitise everything, return the
// payload that is allowed to leave the device.
//
//   page --snapshot--> detect --> tokenise --> redact screenshot --> gate
//
// Used by the agent loop (agent/loop.js) and by the evaluation harness
// (eval/harness.html) so both exercise exactly the same code.

import { sanitizeSnapshot, sanitizeString, DEFAULT_LAYERS } from '../redact/sanitize.js';
import { redactScreenshot } from '../redact/redactor.js';
import { checkPayload } from '../redact/gate.js';

export async function ensureContentScript(tabId) {
  try {
    await chrome.tabs.sendMessage(tabId, { ps: 'ping' });
  } catch {
    await chrome.scripting.executeScript({ target: { tabId }, files: ['content/content.js'] });
  }
}

export function sendToTab(tabId, msg) {
  return chrome.tabs.sendMessage(tabId, msg);
}

/**
 * @returns {{ payloadParts, screenshot, stats, gate, timingMs, raw }}
 *   raw is the unsanitised snapshot; it stays local and is returned only so the
 *   evaluation harness can compare against ground truth. Never send it.
 */
export async function perceive({ tabId, vault, layers = DEFAULT_LAYERS, tools, windowId }) {
  const t0 = performance.now();
  await ensureContentScript(tabId);

  const snapshot = await sendToTab(tabId, { ps: 'snapshot' });
  const clean = await sanitizeSnapshot(snapshot, vault, layers);

  // Exact rectangles for each detected character range.
  const rectLists = clean.boxRequests.length
    ? await sendToTab(tabId, { ps: 'rects', requests: clean.boxRequests })
    : [];
  const charRects = rectLists.flat();

  const shot = await chrome.tabs.captureVisibleTab(windowId, { format: 'png' });
  const redacted = await redactScreenshot({
    screenshotDataUrl: shot,
    viewport: snapshot.viewport,
    charRects,
    fieldBoxes: clean.fieldBoxes,
    media: snapshot.media,
    layers,
    tools,
  });

  const payloadParts = {
    url: stripQuery(snapshot.url),
    title: (await sanitizeString(String(snapshot.title || '').slice(0, 120), vault, layers)),
    elements: clean.elements,
    visibleText: clean.visibleText,
    scroll: snapshot.scroll,
  };
  const gate = checkPayload(payloadParts, vault);

  return {
    payloadParts,
    screenshot: redacted.dataUrl,
    stats: { pii: clean.stats, redaction: redacted.stats },
    boxes: { chars: charRects, fields: clean.fieldBoxes.map((b) => b.rect) }, // for precision scoring
    gate,
    timingMs: Math.round(performance.now() - t0),
    raw: snapshot,
  };
}

function stripQuery(u) {
  try { const x = new URL(u); return x.origin + x.pathname; } catch { return u; }
}

