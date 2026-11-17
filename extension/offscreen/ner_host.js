// ner_host.js - runs inside the offscreen document. Content scripts can't start
// the name model themselves (page origin, page CSP), so Shield mode asks this
// page, which owns the Web Worker that runs the BERT model.
import { initNER, scanNames } from '../src/pii/ner.js';

const ready = initNER();

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg.ps !== 'ner-run') return false;
  ready.then(async () => {
    const results = [];
    for (const t of msg.texts) results.push(await scanNames(t));
    reply({ results });
  });
  return true; // reply asynchronously
});
