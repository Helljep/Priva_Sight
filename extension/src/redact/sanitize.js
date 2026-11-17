// sanitize.js
// The heart of PrivaSight: turn a raw page snapshot into something that is
// safe to send to a remote model.
//
//   snapshot (raw, local)  ->  { elements, text, redactionBoxes, stats }
//
// Layers, in order (each can be switched off for the ablation study):
//   dom    - field types / labels / attributes          (dom_rules.js)
//   regex  - Aadhaar (Verhoeff), cards (Luhn), PAN ...  (regex_detector.js)
//   ner    - person names                               (ner.js)
//   faces  - faces/images/video                         (done in redactor.js)
//   ocr    - text baked into images                     (done in redactor.js)
//
// This module only decides WHAT to hide and produces tokenised text. Drawing
// the black boxes on the screenshot is redactor.js.

import { scan as regexScan, resolveOverlaps } from '../pii/regex_detector.js';
import { classifyField } from '../pii/dom_rules.js';
import { scanNames } from '../pii/ner.js';

export const DEFAULT_LAYERS = { dom: true, regex: true, ner: true, faces: true, ocr: true };

/** Replace each detection in `text` by its vault token. */
export function tokenise(text, detections, vault) {
  let out = '';
  let cursor = 0;
  for (const d of [...detections].sort((a, b) => a.start - b.start)) {
    if (d.start < cursor) continue;
    out += text.slice(cursor, d.start) + (d.token || vault.tokenFor(d.type, d.value));
    cursor = d.end;
  }
  return out + text.slice(cursor);
}

async function detectText(text, layers, context = '', vault = null) {
  // Values already in the vault (typed secrets, earlier detections) are always hidden.
  let found = vault ? vault.findKnown(text) : [];
  if (layers.regex) found = found.concat(regexScan(text, context));
  if (layers.ner) found = found.concat(await scanNames(text, context));
  return resolveOverlaps(found);
}

/** Sanitise a free-standing string (page title, goal text, action history ...). */
export async function sanitizeString(text, vault, layers = DEFAULT_LAYERS) {
  return tokenise(text, await detectText(text, layers, '', vault), vault);
}

/**
 * @param snapshot  raw snapshot from content.js
 * @param vault     Vault instance
 * @param layers    which layers are enabled
 * @returns {
 *   elements: sanitised element list for the planner,
 *   visibleText: sanitised page text (array of strings),
 *   boxRequests: [{runId,start,end,type}]  character ranges to black out,
 *   fieldBoxes:  [{rect,type}]            whole-field boxes (password, input values),
 *   stats: counts per PII type
 * }
 */
export async function sanitizeSnapshot(snapshot, vault, layers = DEFAULT_LAYERS) {
  const stats = {};
  const count = (type) => { stats[type] = (stats[type] || 0) + 1; };
  const boxRequests = [];
  const fieldBoxes = [];

  // ---- 1. visible text runs ----
  const visibleText = [];
  let previous = ''; // text of the run before this one: usually its label ("Account no.")
  for (const run of snapshot.runs) {
    const dets = await detectText(run.text, layers, previous, vault);
    previous = run.text;
    for (const d of dets) {
      boxRequests.push({ runId: run.id, start: d.start, end: d.end, type: d.type });
      count(d.type);
    }
    const clean = tokenise(run.text, dets, vault).trim();
    if (clean) visibleText.push(clean);
  }

  // ---- 2. form fields / buttons / links ----
  const elements = [];
  for (const f of snapshot.fields) {
    const out = {
      id: f.id, tag: f.tag, type: f.type || undefined, role: f.role || undefined,
      label: f.label || undefined, placeholder: f.placeholder || undefined,
      rect: roundRect(f.rect),
    };

    // Visible text on buttons/links gets the same text detection.
    if (f.text) {
      const dets = await detectText(f.text, layers, '', vault);
      out.text = tokenise(f.text, dets, vault);
    }
    // Labels and placeholders can also hold PII (e.g. "Hi Rohan") - clean them.
    if (out.label) out.label = tokenise(out.label, await detectText(out.label, layers, '', vault), vault);
    if (out.placeholder) out.placeholder = tokenise(out.placeholder, await detectText(out.placeholder, layers, '', vault), vault);
    if (f.href) out.href = hrefPath(f.href); // path only; query strings can carry IDs/emails
    if (f.checked !== undefined) out.checked = f.checked;

    // Input values: never forwarded as text. Either a typed token or a flag.
    if (f.value !== undefined && f.valueRun) {
      const fieldKind = layers.dom ? classifyField(f) : null;
      let valueDets = await detectText(f.value, layers, '', vault);
      if (fieldKind) {
        // The field type itself says the value is sensitive even if no regex fires.
        const type = fieldKind.type;
        out.value = type === 'PASSWORD' ? '{PASSWORD}' : vault.tokenFor(type, f.value);
        fieldBoxes.push({ rect: f.rect, type });
        count(type);
      } else if (valueDets.length) {
        out.value = tokenise(f.value, valueDets, vault);
        fieldBoxes.push({ rect: f.rect, type: valueDets[0].type });
        for (const d of valueDets) count(d.type);
      } else {
        out.value = f.value.slice(0, 80);
      }
    } else if (layers.dom && f.type === 'password') {
      out.value = '';
    }
    if (layers.dom) {
      const kind = classifyField(f);
      if (kind) out.sensitive = kind.type; // tells the planner "use a token here"
    }
    elements.push(out);
  }

  return { elements, visibleText, boxRequests, fieldBoxes, stats };
}

function roundRect(r) {
  return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.w), h: Math.round(r.h) };
}

function hrefPath(href) {
  try {
    const u = new URL(href, 'http://x');
    return u.pathname + (u.hash || '');
  } catch { return href.split('?')[0]; }
}
