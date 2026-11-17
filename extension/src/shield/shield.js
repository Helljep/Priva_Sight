// shield.js - SHIELD MODE: redact the page itself, in place.
//
// Why this exists: an agent that takes its own screenshot or reads the DOM
// never asks PrivaSight for anything, so a "sanitise on request" design can't
// protect it. Shield mode instead edits what the page *shows*, so every reader
// (screenshot, DOM text, accessibility tree) gets the safe version:
//
//   text nodes      real value  -> token         "+91 98450 12345" -> "[PHONE_1]"
//   sensitive input value hidden with CSS        (the value stays, so forms still submit)
//   faces / video   blurred with CSS             (hint based; strict mode blurs every image)
//   typing          the agent types a token      "[PHONE_1]" -> real value, locally, as it is typed
//
// Real values live only in the vault (chrome.storage.session = memory only).
//
// Honest limits (also in docs/SHIELD.md):
//   * an agent that reads an <input>'s .value through JavaScript still gets the
//     real value - we hide it visually and in screenshots, not from page JS;
//   * names use the fast rule detector here, plus the BERT model through an
//     offscreen document when it is installed; pixels in <canvas>/CSS
//     backgrounds are not inspected.

import { scan as regexScan, resolveOverlaps } from '../pii/regex_detector.js';
import { scan as nameScan } from '../pii/name_heuristic.js';
import { classifyField } from '../pii/dom_rules.js';
import { Vault } from '../redact/vault.js';
import { looksLikeFace } from '../vision/faces.js';

const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'TEXTAREA']);
const TOKEN_RE = /\[[A-Z]+_\d+\]|\{[A-Z_]+\}/g;
const ATTRS = ['aria-label', 'title', 'alt', 'placeholder'];
const STYLE_ID = 'privasight-shield-style';

const SHIELD_CSS = `
  .ps-hide-value { color: transparent !important; text-shadow: none !important; background: #000 !important;
                   caret-color: transparent !important; -webkit-text-security: none; }
  .ps-blur { filter: blur(18px) brightness(.55) !important; }
`;

let vault = new Vault();
let strict = false;           // strict: blur every image, not just face-like ones
let running = false;
let observer = null;
let timer = null;
const originals = new WeakMap();     // Text node -> its real text, so Shield can be switched off
const doneText = new WeakMap();      // Text node -> the shielded text we last wrote
const nerCache = new Map();          // text -> detections from the name model
const attrOriginals = new WeakMap(); // Element -> {attr: real}

// ------------------------------------------------------------------ vault

async function loadVault() {
  try {
    const s = await chrome.storage.session.get('shieldVault');
    vault = Vault.fromJSON(s.shieldVault);
  } catch { vault = new Vault(); }
}
let saveQueued = false;
function saveVault() {
  if (saveQueued) return;
  saveQueued = true;
  setTimeout(() => {
    saveQueued = false;
    try { chrome.storage.session.set({ shieldVault: vault.toJSON() }); } catch { /* ignore */ }
  }, 150);
}

// ------------------------------------------------------------------ detection

function detect(text, context) {
  const found = [...vault.findKnown(text), ...regexScan(text, context), ...nameScan(text, context)];
  const cached = nerCache.get(text);
  if (cached) found.push(...cached);
  return resolveOverlaps(found);
}

function replaceRanges(text, dets) {
  let out = '', cursor = 0;
  for (const d of dets) {
    if (d.start < cursor) continue;
    out += text.slice(cursor, d.start) + (d.token || vault.tokenFor(d.type, d.value));
    cursor = d.end;
  }
  return out + text.slice(cursor);
}

/** Ask the name model (offscreen document) about texts we have not seen yet. */
async function askNameModel(texts) {
  const fresh = [...new Set(texts)].filter((t) => !nerCache.has(t) && /[A-Z][a-z]{2,}/.test(t) && t.length < 240);
  if (!fresh.length) return false;
  try {
    const res = await chrome.runtime.sendMessage({ ps: 'ner', texts: fresh });
    if (!res || !res.results) return false;
    fresh.forEach((t, i) => nerCache.set(t, res.results[i] || []));
    return true;
  } catch { fresh.forEach((t) => nerCache.set(t, [])); return false; }
}

// ------------------------------------------------------------------ text nodes

function textNodes(root) {
  const out = [];
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    const p = n.parentElement;
    if (!p || SKIP.has(p.tagName) || !n.nodeValue.trim()) continue;
    out.push(n);
  }
  return out;
}

/**
 * Rewrite text nodes so they show tokens instead of PII.
 * `force` re-derives nodes we already rewrote from their real text - used after
 * the name model reports, because it can find names the fast rules missed.
 */
function shieldTextNodes(nodes, force = false) {
  let changed = false, previous = '';
  for (const n of nodes) {
    const cur = n.nodeValue;
    const ours = originals.has(n) && doneText.get(n) === cur; // this text is our own output
    if (ours && !force) { previous = originals.get(n); continue; }
    const base = ours ? originals.get(n) : cur;              // the real text we should analyse
    const dets = detect(base, previous);
    previous = base;
    const safe = dets.length ? replaceRanges(base, dets) : base;
    if (safe !== cur) {
      originals.set(n, base);
      n.nodeValue = safe;
      doneText.set(n, safe);
      changed = true;
    }
  }
  if (changed) saveVault();
}

// ------------------------------------------------------------------ attributes, inputs, media

function shieldAttributes(root) {
  for (const el of root.querySelectorAll(ATTRS.map((a) => `[${a}]`).join(','))) {
    for (const a of ATTRS) {
      const v = el.getAttribute(a);
      if (!v) continue;
      const dets = detect(v, '');
      if (!dets.length) continue;
      const o = attrOriginals.get(el) || {};
      o[a] = o[a] || v;
      attrOriginals.set(el, o);
      el.setAttribute(a, replaceRanges(v, dets));
      saveVault();
    }
  }
}

function fieldInfo(el) {
  const label = el.id ? (document.querySelector(`label[for="${CSS.escape(el.id)}"]`) || {}).textContent : '';
  return { type: el.type, name: el.name, id: el.id, label: (label || '').trim(), placeholder: el.placeholder, autocomplete: el.autocomplete };
}

function shieldInputs(root) {
  for (const el of root.querySelectorAll('input, textarea')) {
    if (['checkbox', 'radio', 'submit', 'button', 'hidden', 'file', 'range', 'color'].includes(el.type)) continue;
    const kind = classifyField(fieldInfo(el));
    const hasValue = !!el.value;
    const hit = hasValue && (kind || detect(el.value, '').length > 0);
    if (hit) {
      // Register the value so the vault knows it (and `findKnown` hides it elsewhere on the page).
      if (kind && kind.type !== 'PASSWORD') vault.tokenFor(kind.type, el.value);
      el.classList.add('ps-hide-value');
      saveVault();
    } else {
      el.classList.remove('ps-hide-value');
    }
  }
}

function shieldMedia(root) {
  for (const el of root.querySelectorAll('img, video, canvas, picture')) {
    const r = el.getBoundingClientRect();
    if (r.width < 24 || r.height < 24) continue;
    const hint = [el.className && el.className.baseVal === undefined ? el.className : '', el.getAttribute('alt') || '', el.getAttribute('src') || '', el.getAttribute('poster') || ''].join(' ');
    const isVideo = el.tagName === 'VIDEO';
    el.classList.toggle('ps-blur', isVideo || strict || looksLikeFace(hint));
  }
}

// ------------------------------------------------------------------ typing: token -> real value

function onInput(e) {
  const el = e.target;
  if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) return;
  const v = el.value;
  if (!v || !TOKEN_RE.test(v)) { TOKEN_RE.lastIndex = 0; return; }
  TOKEN_RE.lastIndex = 0;
  const real = vault.resolve(v);
  if (real === v) return;
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, real); // bypasses framework value trackers
  el.classList.add('ps-hide-value');
}

// ------------------------------------------------------------------ main loop

let scanning = false, again = false, settleTimer = null;
async function fullScan() {
  if (!running) return;
  if (scanning) { again = true; return; }
  scanning = true;
  document.documentElement.dataset.privasight = 'scanning';
  try {
    do {
      again = false;
      const nodes = textNodes(document.body);
      shieldTextNodes(nodes);                       // fast rules first
      shieldAttributes(document.body); shieldInputs(document.body); shieldMedia(document.body);
      // then the name model: results go into the cache and a second pass applies them
      const texts = nodes.map((n) => originals.get(n) || n.nodeValue);
      if (await askNameModel(texts)) { shieldTextNodes(textNodes(document.body), true); }
    } while (again);
  } finally {
    scanning = false;
    // "ready" is only announced after the page has been quiet for a moment, because
    // sites fill in names, values and photos after the first paint. Agents (and the
    // PrivaSight gateway) should wait for data-privasight="ready" before reading.
    clearTimeout(settleTimer);
    settleTimer = setTimeout(() => {
      if (running && !scanning) {
        shieldInputs(document.body); shieldMedia(document.body);
        document.documentElement.dataset.privasight = 'ready';
      }
    }, 300);
  }
}

export async function startShield(opts = {}) {
  if (running) return;
  strict = !!opts.strict;
  await loadVault();
  running = true;
  if (!document.getElementById(STYLE_ID)) {
    const s = document.createElement('style');
    s.id = STYLE_ID; s.textContent = SHIELD_CSS;
    (document.head || document.documentElement).appendChild(s);
  }
  document.addEventListener('input', onInput, true);
  document.addEventListener('input', () => { shieldInputs(document.body); }, false);
  observer = new MutationObserver(() => {
    clearTimeout(settleTimer);
    document.documentElement.dataset.privasight = 'scanning';
    clearTimeout(timer);
    timer = setTimeout(fullScan, 60);
  });
  observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  setInterval(() => running && shieldInputs(document.body), 100); // input values change without DOM mutations
  await fullScan();
}

export function stopShield() {
  running = false;
  if (observer) observer.disconnect();
  document.removeEventListener('input', onInput, true);
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) if (originals.has(n)) { n.nodeValue = originals.get(n); originals.delete(n); }
  document.querySelectorAll('.ps-hide-value').forEach((e) => e.classList.remove('ps-hide-value'));
  document.querySelectorAll('.ps-blur').forEach((e) => e.classList.remove('ps-blur'));
  const st = document.getElementById(STYLE_ID); if (st) st.remove();
  delete document.documentElement.dataset.privasight;
}

/** Set a user secret that agents can type as a token, e.g. setSecret('{PASSWORD}', 'x'). */
export async function setSecret(token, value) {
  await loadVault();
  vault.setSecret(token, value);
  saveVault();
}
