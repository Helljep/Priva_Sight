// regex_detector.js
// Layer 2 of the pipeline: structured PII found by pattern + checksum.
// Each pattern finds *candidates*; a validator then confirms them, which is
// what keeps precision high (a random 12-digit number is not an Aadhaar
// unless the Verhoeff check digit matches).
//
// scan(text) -> [{ start, end, type, value, source: 'regex' }]

import {
  isAadhaar, luhn, isPAN, isIFSC, isIndianMobile, isEmail, isPincode, digitsOnly,
} from './validators.js';

// How far back (in characters) we look for a label like "DOB:" or "A/c no".
const LABEL_WINDOW = 28;

const RULES = [
  {
    type: 'AADHAAR',
    re: /(?<!\d)[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}(?!\d)/g,
    ok: (m) => isAadhaar(m),
  },
  {
    type: 'CARD',
    re: /(?<!\d)(?:\d[ -]?){13,19}(?!\d)/g,
    ok: (m) => luhn(m),
  },
  {
    type: 'PAN',
    re: /\b[A-Za-z]{5}\d{4}[A-Za-z]\b/g,
    ok: (m) => isPAN(m),
  },
  {
    type: 'EMAIL',
    re: /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g,
    ok: (m) => isEmail(m),
  },
  {
    type: 'PHONE',
    re: /(?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)/g,
    ok: (m) => isIndianMobile(m),
  },
  {
    type: 'IFSC',
    re: /\b[A-Za-z]{4}0[A-Za-z0-9]{6}\b/g,
    ok: (m) => isIFSC(m),
  },
  {
    // Bank account numbers have no checksum, so we only trust them when a
    // label such as "account" or "a/c" sits just before the digits.
    type: 'ACCOUNT',
    re: /(?<!\d)\d{9,18}(?!\d)/g,
    ok: (m) => digitsOnly(m).length >= 9,
    needsLabel: /(account|a\/c|acct|acc\.? ?no)/i,
  },
  {
    // Date of birth: only when labelled, so transaction dates survive.
    type: 'DOB',
    re: /\b(?:0?[1-9]|[12]\d|3[01])[\/.-](?:0?[1-9]|1[0-2])[\/.-](?:19|20)\d{2}\b|\b(?:19|20)\d{2}-\d{2}-\d{2}\b/g,
    ok: () => true,
    needsLabel: /(dob|d\.o\.b|birth|born)/i,
  },
  {
    // Whole postal address: "12, MG Road, Bengaluru, Karnataka 560001".
    // A comma-separated run of 2-5 chunks that ends in a PIN code. Matching the
    // full span (not just the PIN) is what actually hides the street.
    type: 'ADDRESS',
    re: /(?<![\w])(?:\d{1,4}[A-Za-z]?,?\s+)?(?:[A-Za-z0-9.'\- ]{2,40},\s*){1,4}[A-Za-z .]{2,30}\s[1-9]\d{5}(?!\d)/g,
    ok: () => true,
  },
  {
    // PIN code: only when it looks like part of an address.
    type: 'ADDRESS',
    re: /(?<!\d)[1-9]\d{5}(?!\d)/g,
    ok: (m) => isPincode(m),
    needsLabel: /(pin|pincode|zip|postal|bengaluru|bangalore|mumbai|delhi|chennai|hyderabad|kolkata|pune|nagar|road|street|layout|cross|main)/i,
  },
];

// Priority when two matches overlap: validated hard IDs beat softer guesses.
const PRIORITY = ['KNOWN', 'AADHAAR', 'CARD', 'PAN', 'EMAIL', 'PHONE', 'IFSC', 'ACCOUNT', 'DOB', 'ADDRESS', 'NAME'];

/**
 * @param text     the string to scan
 * @param context  optional text that sat just BEFORE `text` on the page, e.g.
 *                 the label "Account no." in a <span> next to the value's own
 *                 <span>. It is only used to satisfy label checks; matches
 *                 inside `context` itself are not reported.
 */
export function scan(text, context = '') {
  const ctx = context ? context.slice(-LABEL_WINDOW) + ' ' : '';
  const found = [];
  for (const rule of RULES) {
    // Rules without a label requirement scan the text alone, so a pattern can
    // never start inside the context. Label rules scan context + text.
    const useCtx = Boolean(rule.needsLabel) && ctx.length > 0;
    const full = useCtx ? ctx + text : text;
    const shift = useCtx ? ctx.length : 0;
    rule.re.lastIndex = 0;
    let m;
    while ((m = rule.re.exec(full)) !== null) {
      const value = m[0];
      if (m.index < shift) continue; // belongs to the context, not to this text
      if (!rule.ok(value)) continue;
      if (rule.needsLabel) {
        const before = full.slice(Math.max(0, m.index - LABEL_WINDOW), m.index);
        if (!rule.needsLabel.test(before)) continue;
      }
      const start = m.index - shift;
      found.push({ start, end: start + value.length, type: rule.type, value, source: 'regex' });
    }
  }
  return resolveOverlaps(found);
}

/** Keep the highest-priority (then longest) match when ranges overlap. */
export function resolveOverlaps(matches) {
  const sorted = [...matches].sort((a, b) => {
    const pa = PRIORITY.indexOf(a.type), pb = PRIORITY.indexOf(b.type);
    if (pa !== pb) return pa - pb;
    return (b.end - b.start) - (a.end - a.start);
  });
  const kept = [];
  for (const m of sorted) {
    if (!kept.some((k) => m.start < k.end && k.start < m.end)) kept.push(m);
  }
  return kept.sort((a, b) => a.start - b.start);
}
