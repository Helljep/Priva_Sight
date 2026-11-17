// sidepanel.js - the UI. Wires the controls to the agent loop.
import { Vault } from '../src/redact/vault.js';
import { DEFAULT_LAYERS } from '../src/redact/sanitize.js';
import { initNER, status as nerStatus } from '../src/pii/ner.js';
import { createFaceDetector } from '../src/vision/faces.js';
import { createOCR } from '../src/vision/ocr.js';
import { perceive } from '../src/agent/pipeline.js';
import { runAgent } from '../src/agent/loop.js';
import { health } from '../src/agent/api.js';
import { startBridge } from '../src/agent/bridge.js';

const $ = (id) => document.getElementById(id);
const vault = new Vault();
const tools = { faceDetector: null, ocr: null };
let controller = null;

function layers() {
  return {
    dom: $('l-dom').checked, regex: $('l-regex').checked, ner: $('l-ner').checked,
    faces: $('l-faces').checked, ocr: $('l-ocr').checked,
  };
}

function syncSecrets() {
  const map = { '{USERNAME}': 'sec-username', '{PASSWORD}': 'sec-password', '{OTP}': 'sec-otp' };
  for (const [token, id] of Object.entries(map)) if ($(id).value) vault.setSecret(token, $(id).value);
}

function log(text, cls = '') {
  const li = document.createElement('li');
  li.textContent = text;
  if (cls) li.className = cls;
  $('log').appendChild(li);
  li.scrollIntoView({ block: 'end' });
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return tab;
}

async function loadSettings() {
  const s = await chrome.storage.local.get(['server', 'maxsteps', 'layers']);
  if (s.server) $('server').value = s.server;
  if (s.maxsteps) $('maxsteps').value = s.maxsteps;
  const l = { ...DEFAULT_LAYERS, ...(s.layers || {}) };
  for (const k of Object.keys(l)) $('l-' + k).checked = l[k];
}

function saveSettings() {
  // Secrets are deliberately NOT saved - they live in memory only.
  chrome.storage.local.set({ server: $('server').value, maxsteps: $('maxsteps').value, layers: layers() });
}

async function showStatus() {
  const ner = nerStatus();
  $('layer-status').textContent =
    `Names: ${ner.mode === 'model' ? 'BERT model' : 'rule-based fallback'}` +
    ` · Faces: ${tools.faceDetector.mode === 'blazeface' ? 'BlazeFace' : 'DOM hints only'}` +
    ` · OCR: ${tools.ocr.available ? 'Tesseract' : 'not installed'}`;
  try {
    const h = await health($('server').value);
    $('shield').textContent = `server: ${h.backend}`;
    $('shield').className = 'pill ok';
  } catch {
    $('shield').textContent = 'server offline';
    $('shield').className = 'pill bad';
  }
}

// ---- Shield mode: one switch for every tab, plus the secrets that agents may type as tokens ----
async function pushShield() {
  const secrets = { '{USERNAME}': $('sec-username').value, '{PASSWORD}': $('sec-password').value, '{OTP}': $('sec-otp').value };
  const stored = (await chrome.storage.session.get('shieldVault')).shieldVault;
  const shieldVault = Vault.fromJSON(stored);
  for (const [token, value] of Object.entries(secrets)) if (value) shieldVault.setSecret(token, value);
  await chrome.storage.session.set({
    shieldVault: shieldVault.toJSON(),
    shield: { enabled: $('shield').checked, strict: $('shield-strict').checked },
  });
}

// ---- Agent gateway: serve an external agent through the local server ----
let bridge = null;
function toggleGateway() {
  if (bridge) { bridge.stop(); bridge = null; $('gw-status').textContent = 'off'; }
  if (!$('gateway').checked) return;
  syncSecrets();
  bridge = startBridge({
    url: $('server').value, token: $('gw-token').value, vault, getLayers: layers, tools,
    onStatus: (s) => { $('gw-status').textContent = s; },
  });
}

async function init() {
  $('gateway').addEventListener('change', toggleGateway);
  await chrome.storage.session.setAccessLevel({ accessLevel: 'TRUSTED_AND_UNTRUSTED_CONTEXTS' }).catch(() => {});
  const st = (await chrome.storage.session.get('shield')).shield || {};
  $('shield').checked = !!st.enabled; $('shield-strict').checked = !!st.strict;
  for (const id of ['shield', 'shield-strict', 'sec-username', 'sec-password', 'sec-otp']) $(id).addEventListener('change', pushShield);
  await loadSettings();
  await initNER();
  tools.faceDetector = await createFaceDetector();
  tools.ocr = await createOCR();
  await showStatus();
  for (const id of ['server', 'maxsteps', 'l-dom', 'l-regex', 'l-ner', 'l-faces', 'l-ocr']) {
    $(id).addEventListener('change', () => { saveSettings(); if (id === 'server') showStatus(); });
  }
}

$('run').addEventListener('click', async () => {
  const goal = $('goal').value.trim();
  if (!goal) return;
  const tab = await activeTab();
  if (!tab || !/^https?:/.test(tab.url || '')) return log('Open a normal web page tab first.', 'error');
  syncSecrets();
  $('log').innerHTML = '';
  $('run').disabled = true; $('stop').disabled = false;
  controller = new AbortController();
  const result = await runAgent({
    goal, tabId: tab.id, windowId: tab.windowId, vault, layers: layers(), tools,
    serverUrl: $('server').value, maxSteps: Number($('maxsteps').value) || 15,
    signal: controller.signal,
    onEvent: (e) => {
      if (e.type === 'step') log(`Step ${e.step}: sanitised in ${e.timingMs} ms · hidden ${JSON.stringify(e.stats.pii)}`);
      else if (e.type === 'action') log(`→ ${e.action.type}${e.action.id !== undefined ? ' #' + e.action.id : ''}${e.action.text ? ' ' + JSON.stringify(e.action.text) : ''}${e.thought ? ' — ' + e.thought : ''}`);
      else if (e.type === 'blocked') log('BLOCKED by privacy gate: ' + JSON.stringify(e.reasons), 'blocked');
      else if (e.type === 'error') log('Error: ' + e.message, 'error');
      else if (e.type === 'done') log('Done: ' + (e.answer || ''), 'done');
    },
  });
  log(`Finished: ${result.status} after ${result.steps} step(s).`);
  $('run').disabled = false; $('stop').disabled = true;
});

$('stop').addEventListener('click', () => controller && controller.abort());

// "Preview what's sent": run perception only and show the sanitised result.
$('preview').addEventListener('click', async () => {
  const tab = await activeTab();
  if (!tab || !/^https?:/.test(tab.url || '')) return log('Open a normal web page tab first.', 'error');
  syncSecrets();
  const p = await perceive({ tabId: tab.id, windowId: tab.windowId, vault, layers: layers(), tools });
  $('preview-box').hidden = false;
  $('preview-img').src = p.screenshot;
  $('preview-json').textContent = JSON.stringify({ gate: p.gate, stats: p.stats, payload: p.payloadParts }, null, 2);
});

init();
