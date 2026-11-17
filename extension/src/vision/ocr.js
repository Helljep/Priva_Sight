// ocr.js
// Layer 5: read text that exists only as pixels (a photo of an ID card, a
// text-in-image banner) so it can be checked and blacked out.
//
// Uses Tesseract.js from extension/vendor/tesseract/ if present; otherwise
// this layer reports itself unavailable. Capped to MAX_IMAGES per step to
// keep the per-step latency bounded.
//
//   const ocr = await createOCR();
//   await ocr.read(canvasOrBitmap) -> [{ text, bbox:{x,y,w,h} }]  (lines)

export const MAX_IMAGES_PER_STEP = 3;

async function exists(path) {
  try { return (await fetch(chrome.runtime.getURL(path), { method: 'HEAD' })).ok; } catch { return false; }
}

export async function createOCR() {
  const ok = typeof chrome !== 'undefined' && chrome.runtime &&
    await exists('vendor/tesseract/tesseract.min.js') &&
    await exists('vendor/tesseract/worker.min.js') &&
    await exists('vendor/tesseract/eng.traineddata.gz');
  if (!ok) return { available: false, async read() { return []; } };

  try {
    // tesseract.min.js is a UMD bundle: load it as a classic script tag.
    await new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = chrome.runtime.getURL('vendor/tesseract/tesseract.min.js');
      s.onload = resolve; s.onerror = reject;
      document.head.appendChild(s);
    });
    const base = chrome.runtime.getURL('vendor/tesseract/');
    const worker = await globalThis.Tesseract.createWorker('eng', 1, {
      workerPath: base + 'worker.min.js',
      corePath: base,
      langPath: base,
      workerBlobURL: false,
      gzip: true,
    });
    return {
      available: true,
      async read(image) {
        const { data } = await worker.recognize(image);
        return (data.lines || []).map((l) => ({
          text: l.text.trim(),
          bbox: { x: l.bbox.x0, y: l.bbox.y0, w: l.bbox.x1 - l.bbox.x0, h: l.bbox.y1 - l.bbox.y0 },
        }));
      },
    };
  } catch (err) {
    console.warn('[PrivaSight] OCR failed to load:', err);
    return { available: false, async read() { return []; } };
  }
}
