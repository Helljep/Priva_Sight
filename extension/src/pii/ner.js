// ner.js
// Layer 3: person-name detection.
//
// Preferred path: the fine-tuned BERT NER model (int8 ONNX) running in a Web
// Worker through Transformers.js. It is only used if its files exist under
// extension/models/bert-ner-in/ and the vendored library exists under
// extension/vendor/. Otherwise we fall back to name_heuristic.js so the
// extension never silently loses its name layer - it just gets weaker, and
// status() tells the UI which one is running.

import { scan as heuristicScan } from './name_heuristic.js';

let worker = null;
let nextId = 1;
const pending = new Map();
let mode = 'heuristic'; // 'model' once the worker reports ready
let loadError = null;

async function exists(path) {
  try {
    const r = await fetch(chrome.runtime.getURL(path), { method: 'HEAD' });
    return r.ok;
  } catch { return false; }
}

/** Try to start the model worker. Safe to call more than once. */
export async function initNER() {
  if (worker || typeof chrome === 'undefined' || !chrome.runtime) return status();
  const haveLib = await exists('vendor/transformers.min.js');
  const haveModel = await exists('models/bert-ner-in/config.json');
  if (!haveLib || !haveModel) {
    loadError = !haveLib ? 'vendor/transformers.min.js missing' : 'models/bert-ner-in missing';
    return status();
  }
  worker = new Worker(chrome.runtime.getURL('src/pii/ner.worker.js'), { type: 'module' });
  let markReady;
  const ready = new Promise((resolve) => { markReady = resolve; });
  worker.onmessage = (e) => {
    const { id, ready: isReady, error, entities } = e.data;
    if (isReady) { mode = 'model'; markReady(); return; }
    if (error && id === undefined) { loadError = error; mode = 'heuristic'; markReady(); return; }
    const p = pending.get(id);
    if (!p) return;
    pending.delete(id);
    error ? p.reject(new Error(error)) : p.resolve(entities);
  };
  worker.postMessage({ type: 'init', base: chrome.runtime.getURL('') });
  // Wait for the model to finish loading (or fail) so callers know which mode they got.
  await Promise.race([ready, new Promise((r) => setTimeout(r, 60000))]);
  return status();
}

export function status() {
  return { mode, loadError };
}

/** Detect names in text. Returns [{start,end,type:'NAME',value,source}]. */
export async function scanNames(text, context = '') {
  if (mode === 'model' && worker) {
    try {
      const id = nextId++;
      const entities = await new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        worker.postMessage({ type: 'ner', id, text });
      });
      // Union with the heuristic: the model might miss a short run, and an
      // extra black box is cheaper than a leaked name.
      return mergeNames(entities, heuristicScan(text, context));
    } catch { /* fall through to heuristic */ }
  }
  return heuristicScan(text, context);
}

function mergeNames(a, b) {
  const out = [...a];
  for (const m of b) if (!out.some((o) => m.start < o.end && o.start < m.end)) out.push(m);
  return out.sort((x, y) => x.start - y.start);
}
