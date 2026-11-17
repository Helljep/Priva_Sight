// dom_rules.js
// Layer 1: decisions that can be made from the DOM alone, without reading
// any values. A password box is sensitive because of its *type*, whatever
// is typed in it. On its own this layer only reaches ~6.5% recall (see the
// ablation results) - it is the foundation, not the whole defence.
//
// classifyField(el) -> null | { type, token }
//   el = { tag, type, name, id, label, placeholder, autocomplete }

const HINTS = [
  // [regex over name/id/label/placeholder/autocomplete, PII type]
  [/pass(word|wd)?|pwd|passcode|pin\b|cvv|cvc|otp/i, 'PASSWORD'],
  [/aadhaar|aadhar|uidai/i, 'AADHAAR'],
  [/\bpan\b|pan[_ -]?(no|number|card)/i, 'PAN'],
  [/card[_ -]?(no|number|num)|cc-number|credit/i, 'CARD'],
  [/e-?mail/i, 'EMAIL'],
  [/phone|mobile|tel\b|contact[_ -]?no/i, 'PHONE'],
  [/ifsc/i, 'IFSC'],
  [/account[_ -]?(no|number|num)|acct/i, 'ACCOUNT'],
  [/dob|birth/i, 'DOB'],
  [/address|street|pincode|postal|zip|city/i, 'ADDRESS'],
  [/full[_ -]?name|first[_ -]?name|last[_ -]?name|given-name|family-name|patient|\bname\b/i, 'NAME'],
];

export function classifyField(el) {
  if ((el.type || '').toLowerCase() === 'password') return { type: 'PASSWORD' };
  const t = (el.type || '').toLowerCase();
  if (t === 'email') return { type: 'EMAIL' };
  if (t === 'tel') return { type: 'PHONE' };
  const hay = [el.name, el.id, el.label, el.placeholder, el.autocomplete].filter(Boolean).join(' ');
  for (const [re, type] of HINTS) {
    if (re.test(hay)) return { type };
  }
  return null;
}

/** Is this a text field whose *value* the agent should never see? */
export function isSensitiveField(el) {
  return classifyField(el) !== null;
}
