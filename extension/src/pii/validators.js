// validators.js
// Checksum / format validators for Indian and global PII.
// Pure functions, no browser APIs, so the same file runs in the extension,
// in Node tests, and is mirrored by server/pii.py (keep the two in sync).

// ---- Verhoeff (used by Aadhaar) -------------------------------------------
const D = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
  [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
  [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
  [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
  [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
];
const P = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
  [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
  [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
  [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
];

export function digitsOnly(s) {
  return String(s).replace(/\D/g, '');
}

/** True if the digit string passes the Verhoeff checksum. */
export function verhoeff(numStr) {
  const digits = digitsOnly(numStr);
  if (!digits) return false;
  let c = 0;
  const rev = digits.split('').reverse();
  for (let i = 0; i < rev.length; i++) c = D[c][P[i % 8][Number(rev[i])]];
  return c === 0;
}

/** Aadhaar: 12 digits, first digit 2-9, valid Verhoeff checksum. */
export function isAadhaar(s) {
  const d = digitsOnly(s);
  return d.length === 12 && /^[2-9]/.test(d) && verhoeff(d);
}

// ---- Luhn (payment cards) -------------------------------------------------
export function luhn(numStr) {
  const d = digitsOnly(numStr);
  if (d.length < 13 || d.length > 19) return false;
  let sum = 0;
  let dbl = false;
  for (let i = d.length - 1; i >= 0; i--) {
    let n = Number(d[i]);
    if (dbl) { n *= 2; if (n > 9) n -= 9; }
    sum += n;
    dbl = !dbl;
  }
  return sum % 10 === 0;
}

// ---- Other Indian formats -------------------------------------------------
/** PAN: AAAAA9999A. 4th letter = holder type (P person, C company, ...). */
export function isPAN(s) {
  return /^[A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z]$/.test(String(s).toUpperCase());
}

/** IFSC: 4 letters, a literal 0, then 6 alphanumerics. */
export function isIFSC(s) {
  return /^[A-Z]{4}0[A-Z0-9]{6}$/.test(String(s).toUpperCase());
}

/** Indian mobile: optional +91 / 0 prefix, then 10 digits starting 6-9. */
export function isIndianMobile(s) {
  const d = digitsOnly(s);
  const core = d.length === 12 && d.startsWith('91') ? d.slice(2)
    : d.length === 11 && d.startsWith('0') ? d.slice(1) : d;
  return /^[6-9]\d{9}$/.test(core);
}

export function isEmail(s) {
  return /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(s);
}

/** Indian PIN code: 6 digits, first digit 1-9. */
export function isPincode(s) {
  return /^[1-9]\d{5}$/.test(String(s));
}
