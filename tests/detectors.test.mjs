// Node tests for the pure-logic parts of the extension (no browser needed).
// Run:  node --test tests/
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { verhoeff, luhn, isAadhaar, isPAN, isIndianMobile } from '../extension/src/pii/validators.js';
import { scan } from '../extension/src/pii/regex_detector.js';
import { scan as nameScan } from '../extension/src/pii/name_heuristic.js';
import { classifyField } from '../extension/src/pii/dom_rules.js';
import { Vault } from '../extension/src/redact/vault.js';
import { tokenise } from '../extension/src/redact/sanitize.js';
import { checkPayload } from '../extension/src/redact/gate.js';

const vectors = JSON.parse(readFileSync(new URL('./vectors.json', import.meta.url)));

test('shared vectors: regex detector finds exactly the expected types', () => {
  for (const v of vectors) {
    const got = scan(v.text).map((m) => m.type).sort();
    assert.deepEqual(got, [...v.types].sort(), `text: ${v.text}`);
  }
});

test('checksums', () => {
  assert.ok(verhoeff('2363'), 'known Verhoeff sample');
  assert.ok(isAadhaar('3417 0753 6454'));
  assert.ok(!isAadhaar('3417 0753 6455'));
  assert.ok(!isAadhaar('1234 5678 9012'), 'cannot start with 1');
  assert.ok(luhn('4111111111111111'));
  assert.ok(!luhn('4111111111111112'));
  assert.ok(isPAN('ABCPE1234F'));
  assert.ok(!isPAN('ABCZE1234F'));
  assert.ok(isIndianMobile('+91 98450 12345'));
  assert.ok(!isIndianMobile('5845012345'));
});

test('name heuristic: names, titles and labels', () => {
  assert.equal(nameScan('Welcome Rohan Sharma to your account')[0].value, 'Rohan Sharma');
  assert.equal(nameScan('Dr. Menon will see you')[0].value, 'Menon');
  assert.equal(nameScan('Patient: Zoya Khan')[0].value, 'Zoya Khan');
  assert.equal(nameScan('Transfer funds to your saved payee').length, 0);
});

test('dom rules', () => {
  assert.equal(classifyField({ type: 'password' }).type, 'PASSWORD');
  assert.equal(classifyField({ type: 'text', autocomplete: 'cc-number' }).type, 'CARD');
  assert.equal(classifyField({ type: 'text', label: 'Mobile number' }).type, 'PHONE');
  assert.equal(classifyField({ type: 'text', label: 'Amount (INR)' }), null);
});

test('vault: stable tokens and local resolution', () => {
  const v = new Vault();
  const a = v.tokenFor('PHONE', '+91 98450 12345');
  assert.equal(a, '[PHONE_1]');
  assert.equal(v.tokenFor('PHONE', '+91 98450 12345'), a, 'same value, same token');
  assert.equal(v.tokenFor('PHONE', '+91 97410 55555'), '[PHONE_2]');
  assert.equal(v.resolve('type [PHONE_1] now'), 'type +91 98450 12345 now');
  v.setSecret('{PASSWORD}', 'hunter2!');
  assert.equal(v.resolve('{PASSWORD}'), 'hunter2!');
});

test('tokenise replaces detected ranges', () => {
  const v = new Vault();
  const text = 'Mobile +91 98450 12345 mail a.b@example.test';
  assert.equal(tokenise(text, scan(text), v), 'Mobile [PHONE_1] mail [EMAIL_1]');
});

test('privacy gate blocks raw PII and passes tokenised payloads', () => {
  const v = new Vault();
  v.tokenFor('EMAIL', 'rohan@example.test');
  const bad = checkPayload({ visibleText: ['Contact rohan@example.test'] }, v);
  assert.equal(bad.ok, false);
  assert.ok(bad.reasons.every((r) => !JSON.stringify(r).includes('rohan@example.test')), 'reasons are masked');
  const good = checkPayload({ visibleText: ['Contact [EMAIL_1]', 'password {PASSWORD}'], goal: 'log in' }, v);
  assert.equal(good.ok, true);
  const leakedName = checkPayload({ visibleText: ['Hello Rohan Sharma'] }, v);
  assert.equal(leakedName.ok, false);
});

test('gate catches a vault value even when no pattern matches', () => {
  const v = new Vault();
  v.setSecret('{PASSWORD}', 'Ps!4821-sha');
  assert.equal(checkPayload({ visibleText: ['typed Ps!4821-sha here'] }, v).ok, false);
});

test('context from the previous text run satisfies label checks', () => {
  assert.deepEqual(scan('123456789012', 'Account no.').map((m) => m.type), ['ACCOUNT']);
  assert.deepEqual(scan('14/03/1990', 'Date of birth').map((m) => m.type), ['DOB']);
  assert.deepEqual(scan('123456789012', 'Order').map((m) => m.type), []);
  assert.deepEqual(scan('12, MG Road, Bengaluru, Karnataka 560001').map((m) => m.type), ['ADDRESS']);
});

test('name heuristic uses the previous run as context ("Hello" + "Ishaan")', () => {
  assert.equal(nameScan('Ishaan', 'Hello')[0].value, 'Ishaan');
  assert.equal(nameScan('Ishaan').length, 0, 'a lone first name without context is not flagged');
  assert.equal(nameScan('Rohan Sharma', 'Hello')[0].value, 'Rohan Sharma');
});

test('vault.findKnown hides a typed secret wherever it shows up', () => {
  const v = new Vault();
  v.setSecret('{USERNAME}', 'ishaan.sharma42');
  const text = 'user ishaan.sharma42 logged in';
  const hits = v.findKnown(text);
  assert.equal(hits.length, 1);
  assert.equal(tokenise(text, hits, v), 'user {USERNAME} logged in');
});

test('name heuristic does not treat "Amount" after a "Payee" label as a name', () => {
  assert.equal(nameScan('Amount (INR)', 'Payee').length, 0);
  assert.equal(nameScan('Amount: 500').length, 0);
});
