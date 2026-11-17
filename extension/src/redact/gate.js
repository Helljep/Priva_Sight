// gate.js - the Privacy Gate.
//
// Last line of defence before a request leaves the machine. It does NOT trust
// the earlier layers: it re-scans the exact payload that is about to be sent
// and blocks the request if anything that looks like raw PII is left.
//
//   checkPayload(payload, vault) -> { ok, reasons: [...] }
//
// The payload is {goal, url, elements, visibleText, history, screenshot}.
// Text fields are scanned with the structured detectors (regex + checksums)
// and compared with every real value the vault knows. The screenshot is
// checked by the caller with OCR in strict mode (see agent/loop.js).

import { scan as regexScan } from '../pii/regex_detector.js';
import { scan as nameScan } from '../pii/name_heuristic.js';

// Tokens look like [PHONE_1] or {PASSWORD}; strip them first so they are not flagged.
const TOKEN_RE = /\[[A-Z]+_\d+\]|\{[A-Z_]+\}|\[FACE\]/g;

function collectStrings(value, out = []) {
  if (typeof value === 'string') out.push(value);
  else if (Array.isArray(value)) value.forEach((v) => collectStrings(v, out));
  else if (value && typeof value === 'object') Object.values(value).forEach((v) => collectStrings(v, out));
  return out;
}

export function checkPayload(payload, vault, { checkNames = true } = {}) {
  const { screenshot, ...textPart } = payload;
  const strings = collectStrings(textPart);
  const reasons = [];
  const real = vault.realValues();

  for (const s of strings) {
    const stripped = s.replace(TOKEN_RE, ' ');
    // 1. exact leak of a value the vault is protecting
    for (const v of real) {
      if (stripped.includes(v)) reasons.push({ kind: 'vault-value', sample: mask(v) });
    }
    // 2. anything that still looks like structured PII
    for (const m of regexScan(stripped)) reasons.push({ kind: 'pattern', type: m.type, sample: mask(m.value) });
    // 3. names (gazetteer rule; cheap, conservative)
    if (checkNames) {
      for (const m of nameScan(stripped)) reasons.push({ kind: 'name', type: 'NAME', sample: mask(m.value) });
    }
  }
  if (screenshot && typeof screenshot !== 'string') reasons.push({ kind: 'bad-screenshot' });
  return { ok: reasons.length === 0, reasons };
}

/** Never put the real value into logs - show only its shape. */
function mask(v) {
  const s = String(v);
  return s.length <= 4 ? '****' : s.slice(0, 2) + '*'.repeat(Math.min(s.length - 3, 8)) + s.slice(-1);
}
