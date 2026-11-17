// redactor.js
// Draws the redactions onto the screenshot. Everything happens on an
// OffscreenCanvas inside the side panel - the original screenshot is never
// stored or sent anywhere.
//
//   text PII      -> solid black box over the exact characters
//   input values  -> solid black box over the whole field
//   faces         -> pixelated + darkened (blurred beyond recognition)
//   video         -> solid black box (frames can contain anyone)
//   OCR hits      -> solid black box over the matching text line

import { looksLikeFace } from '../vision/faces.js';
import { MAX_IMAGES_PER_STEP } from '../vision/ocr.js';
import { scan as regexScan } from '../pii/regex_detector.js';
import { scanNames } from '../pii/ner.js';

const PAD = 2; // CSS px of padding around each box so anti-aliased edges are covered

async function toBitmap(dataUrl) {
  const blob = await (await fetch(dataUrl)).blob();
  return createImageBitmap(blob);
}

async function blobToDataUrl(blob) {
  const buf = new Uint8Array(await blob.arrayBuffer());
  let bin = '';
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return `data:${blob.type};base64,` + btoa(bin);
}

function blackBox(ctx, r, scale) {
  ctx.fillStyle = '#000';
  ctx.fillRect((r.x - PAD) * scale, (r.y - PAD) * scale, (r.w + 2 * PAD) * scale, (r.h + 2 * PAD) * scale);
}

function pixelate(ctx, x, y, w, h) {
  x = Math.max(0, Math.floor(x)); y = Math.max(0, Math.floor(y));
  w = Math.ceil(w); h = Math.ceil(h);
  if (w < 2 || h < 2) return;
  const small = new OffscreenCanvas(Math.max(1, Math.round(w / 14)), Math.max(1, Math.round(h / 14)));
  const sctx = small.getContext('2d');
  sctx.drawImage(ctx.canvas, x, y, w, h, 0, 0, small.width, small.height);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(small, 0, 0, small.width, small.height, x, y, w, h);
  ctx.imageSmoothingEnabled = true;
  ctx.fillStyle = 'rgba(0,0,0,0.55)';
  ctx.fillRect(x, y, w, h);
}

/**
 * @param screenshotDataUrl  PNG/JPEG from captureVisibleTab
 * @param viewport           {w,h} CSS px from the snapshot
 * @param charRects          [{rect}] exact rectangles for text matches (CSS px)
 * @param fieldBoxes         [{rect}] whole-field boxes (CSS px)
 * @param media              snapshot.media list
 * @param layers             enabled layers
 * @param tools              { faceDetector, ocr }
 * @returns {{ dataUrl, stats }}
 */
export async function redactScreenshot({ screenshotDataUrl, viewport, charRects, fieldBoxes, media, layers, tools }) {
  const bmp = await toBitmap(screenshotDataUrl);
  const scale = bmp.width / viewport.w;
  const canvas = new OffscreenCanvas(bmp.width, bmp.height);
  const ctx = canvas.getContext('2d');
  ctx.drawImage(bmp, 0, 0);
  const stats = { textBoxes: 0, fieldBoxes: 0, faces: 0, videos: 0, ocrBoxes: 0, imagesOcrd: 0 };

  // ---- media first, so later text boxes always end up on top ----
  let ocrBudget = MAX_IMAGES_PER_STEP;
  for (const m of media) {
    const px = { x: m.rect.x * scale, y: m.rect.y * scale, w: m.rect.w * scale, h: m.rect.h * scale };
    if (m.kind === 'video') {
      if (layers.faces) { blackBox(ctx, m.rect, scale); stats.videos++; }
      continue;
    }
    if (layers.faces) {
      let faces = [];
      if (tools.faceDetector && tools.faceDetector.mode === 'blazeface') {
        const crop = await createImageBitmap(bmp, Math.max(0, px.x), Math.max(0, px.y),
          Math.max(1, Math.min(px.w, bmp.width - px.x)), Math.max(1, Math.min(px.h, bmp.height - px.y)));
        faces = (await tools.faceDetector.detect(crop)).map((f) => ({ x: px.x + f.x, y: px.y + f.y, w: f.w, h: f.h }));
        crop.close();
      }
      // Detector found nothing but the DOM says "this is a person's photo": blur it all.
      if (!faces.length && looksLikeFace(m.hint)) faces = [px];
      for (const f of faces) { pixelate(ctx, f.x, f.y, f.w, f.h); stats.faces++; }
    }
    if (layers.ocr && tools.ocr && tools.ocr.available && ocrBudget > 0 && m.kind === 'image') {
      ocrBudget--;
      stats.imagesOcrd++;
      const crop = new OffscreenCanvas(Math.max(1, Math.round(px.w)), Math.max(1, Math.round(px.h)));
      crop.getContext('2d').drawImage(bmp, px.x, px.y, px.w, px.h, 0, 0, crop.width, crop.height);
      for (const line of await tools.ocr.read(await crop.convertToBlob())) {
        const hit = regexScan(line.text).length || (layers.ner && (await scanNames(line.text)).length);
        if (hit) {
          ctx.fillStyle = '#000';
          ctx.fillRect(px.x + line.bbox.x - 3, px.y + line.bbox.y - 3, line.bbox.w + 6, line.bbox.h + 6);
          stats.ocrBoxes++;
        }
      }
    }
  }

  // ---- text and field boxes ----
  for (const r of charRects) { blackBox(ctx, r, scale); stats.textBoxes++; }
  for (const b of fieldBoxes) { blackBox(ctx, b.rect, scale); stats.fieldBoxes++; }

  // JPEG keeps the payload small; black boxes survive compression.
  const blob = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.85 });
  bmp.close();
  return { dataUrl: await blobToDataUrl(blob), stats };
}
