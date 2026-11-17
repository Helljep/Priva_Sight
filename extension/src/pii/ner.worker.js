// ner.worker.js - runs the BERT NER model off the main thread.
// Loaded as a module worker by ner.js. Everything stays local: remote model
// downloads are switched off, so the model must be bundled in the extension.

let classifier = null;

self.onmessage = async (e) => {
  const msg = e.data;
  try {
    if (msg.type === 'init') {
      const lib = await import(msg.base + 'vendor/transformers.min.js');
      lib.env.allowRemoteModels = false;
      lib.env.allowLocalModels = true;
      lib.env.useBrowserCache = false; // the Cache API rejects chrome-extension:// URLs
      lib.env.localModelPath = msg.base + 'models/';
      lib.env.backends.onnx.wasm.wasmPaths = msg.base + 'vendor/';
      lib.env.backends.onnx.wasm.numThreads = 1; // extension pages are not cross-origin isolated
      classifier = await lib.pipeline('token-classification', 'bert-ner-in', { dtype: 'q8' });
      self.postMessage({ ready: true });
    } else if (msg.type === 'ner') {
      // Transformers.js returns one record per word-piece:
      //   {entity:'B-PER'|'I-PER'|..., score, index, word:'An'|'##sar'|...}
      // We merge adjacent PER pieces into one entity, then snap it outwards to
      // whole words in the original text (the model only gives pieces, not offsets).
      const raw = await classifier(msg.text);
      const per = raw.filter((r) => /PER/i.test(String(r.entity || r.entity_group)) && r.score >= 0.5);
      const groups = [];
      for (const r of per) {
        const last = groups[groups.length - 1];
        const adjacent = last && r.index === last[last.length - 1].index + 1;
        if (adjacent && !/^B-/i.test(r.entity) || (adjacent && r.word.startsWith('##'))) last.push(r);
        else groups.push([r]);
      }
      const text = msg.text;
      const entities = [];
      let cursor = 0;
      for (const g of groups) {
        let pos = cursor, start = -1;
        for (const piece of g) {
          const w = piece.word.replace(/^##/, '');
          const at = text.indexOf(w, pos);
          if (at < 0) { start = -2; break; }
          if (start === -1) start = at;
          pos = at + w.length;
        }
        if (start < 0) continue;
        let end = pos;
        while (start > 0 && /\p{L}/u.test(text[start - 1])) start--;   // snap to word start
        while (end < text.length && /\p{L}/u.test(text[end])) end++;   // snap to word end
        cursor = end;
        entities.push({ start, end, type: 'NAME', value: text.slice(start, end), source: 'ner-model' });
      }
      self.postMessage({ id: msg.id, entities });
    }
  } catch (err) {
    self.postMessage({ id: msg.id, error: String(err && err.message ? err.message : err) });
  }
};
