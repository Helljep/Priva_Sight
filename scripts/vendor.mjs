// vendor.mjs - copies the optional on-device ML libraries and models into
// extension/vendor and extension/models.   Run:  npm install && npm run vendor
//
// Everything is OPTIONAL. Without it the extension still works (rule-based
// names, DOM-hint faces, no OCR); with it you get the full pipeline.
//
//   Layer        Library (npm)                Model file                              Approx. size
//   NER (names)  @huggingface/transformers    models/bert-ner-in/ (see below)         ~108 MB
//   Faces        @mediapipe/tasks-vision      models/blaze_face_short_range.tflite    ~0.2 MB
//   OCR          tesseract.js (+ core, lang)  vendor/tesseract/eng.traineddata.gz     ~11 MB
//
// The model files are NOT downloaded by this script automatically except where
// you pass --download, because they come from third-party hosts:
//   --download faces   BlazeFace from storage.googleapis.com (MediaPipe)
//   --download ocr     English traineddata from the tesseract.js-data CDN
//   NER model: either train your own (training/README) and copy it to
//   extension/models/bert-ner-in/, or use the public baseline
//   Xenova/bert-base-NER from huggingface.co (--download ner).
import { cpSync, existsSync, mkdirSync, writeFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const nm = join(root, 'node_modules');
const ext = join(root, 'extension');
const want = new Set(process.argv.filter((a, i) => process.argv[i - 1] === '--download').flatMap((a) => a.split(',')));

function copy(from, to) {
  if (!existsSync(from)) { console.log('  missing, skipped:', from); return false; }
  mkdirSync(dirname(to), { recursive: true });
  cpSync(from, to, { recursive: true });
  console.log('  copied', to.replace(root, '.'));
  return true;
}

async function download(url, to) {
  console.log('  downloading', url);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} -> HTTP ${res.status}`);
  mkdirSync(dirname(to), { recursive: true });
  writeFileSync(to, Buffer.from(await res.arrayBuffer()));
  console.log('  saved', to.replace(root, '.'));
}

console.log('Transformers.js (NER)');
const tf = join(nm, '@huggingface', 'transformers', 'dist');
copy(join(tf, 'transformers.min.js'), join(ext, 'vendor', 'transformers.min.js'));
if (existsSync(tf)) {
  for (const f of readdirSync(tf).filter((n) => /^ort-wasm.*\.(wasm|mjs)$/.test(n))) copy(join(tf, f), join(ext, 'vendor', f));
}

console.log('MediaPipe (faces)');
const mp = join(nm, '@mediapipe', 'tasks-vision');
copy(join(mp, 'vision_bundle.mjs'), join(ext, 'vendor', 'mediapipe', 'vision_bundle.mjs'));
copy(join(mp, 'wasm'), join(ext, 'vendor', 'mediapipe', 'wasm'));
if (want.has('faces')) {
  await download('https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite',
    join(ext, 'models', 'blaze_face_short_range.tflite'));
}

console.log('Tesseract.js (OCR)');
const tj = join(nm, 'tesseract.js', 'dist');
copy(join(tj, 'tesseract.min.js'), join(ext, 'vendor', 'tesseract', 'tesseract.min.js'));
copy(join(tj, 'worker.min.js'), join(ext, 'vendor', 'tesseract', 'worker.min.js'));
const core = join(nm, 'tesseract.js-core');
// Tesseract picks one of several core builds (simd / non-simd, lstm / relaxed) at run time: copy them all.
if (existsSync(core)) {
  for (const f of readdirSync(core).filter((n) => /^tesseract-core.*\.wasm(\.js)?$/.test(n))) {
    copy(join(core, f), join(ext, 'vendor', 'tesseract', f));
  }
}
if (want.has('ocr')) {
  await download('https://tessdata.projectnaptha.com/4.0.0_fast/eng.traineddata.gz', join(ext, 'vendor', 'tesseract', 'eng.traineddata.gz'));
}

if (want.has('ner')) {
  console.log('NER baseline model (Xenova/bert-base-NER, int8 ONNX)');
  const base = 'https://huggingface.co/Xenova/bert-base-NER/resolve/main/';
  const dest = join(ext, 'models', 'bert-ner-in');
  for (const f of ['config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', 'vocab.txt']) {
    await download(base + f, join(dest, f)).catch((e) => console.log('  skipped', f, e.message));
  }
  await download(base + 'onnx/model_quantized.onnx', join(dest, 'onnx', 'model_quantized.onnx'));
}
console.log('done');
