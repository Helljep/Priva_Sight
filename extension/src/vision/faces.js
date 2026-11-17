// faces.js
// Layer 4: find faces inside images so they can be blurred.
//
// Preferred: MediaPipe BlazeFace (WASM/WebGPU) if the vendored library and
// model exist. Fallback: a DOM-hint rule that treats any image whose
// class/alt/src suggests a person (avatar, profile, portrait ...) as a face.
// The fallback over-blurs but never under-blurs obvious profile photos.
//
//   const fd = await createFaceDetector();
//   await fd.detect(imageBitmap) -> [{x,y,w,h}]   (pixel coords in the bitmap)
//   fd.mode -> 'blazeface' | 'dom-hint'

const HINT = /(face|avatar|profile|portrait|person|people|selfie|headshot|photo|user|patient|employee|staff|doctor|candidate|participant|tile)/i;

export function looksLikeFace(hintText) {
  return HINT.test(hintText || '');
}

async function exists(path) {
  try { return (await fetch(chrome.runtime.getURL(path), { method: 'HEAD' })).ok; } catch { return false; }
}

export async function createFaceDetector() {
  const inExtension = typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.getURL;
  if (inExtension && await exists('vendor/mediapipe/vision_bundle.mjs') &&
      await exists('models/blaze_face_short_range.tflite')) {
    try {
      const vision = await import(chrome.runtime.getURL('vendor/mediapipe/vision_bundle.mjs'));
      const fileset = await vision.FilesetResolver.forVisionTasks(chrome.runtime.getURL('vendor/mediapipe/wasm'));
      const detector = await vision.FaceDetector.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: chrome.runtime.getURL('models/blaze_face_short_range.tflite') },
        runningMode: 'IMAGE',
        minDetectionConfidence: 0.4,
      });
      return {
        mode: 'blazeface',
        async detect(bitmap) {
          const res = detector.detect(bitmap);
          return res.detections.map((d) => {
            const b = d.boundingBox;
            // Grow the box 25% so hair/chin do not peek out around the blur.
            const gx = b.width * 0.25, gy = b.height * 0.25;
            return { x: b.originX - gx, y: b.originY - gy, w: b.width + 2 * gx, h: b.height + 2 * gy };
          });
        },
      };
    } catch (err) {
      console.warn('[PrivaSight] BlazeFace failed to load, using DOM-hint fallback:', err);
    }
  }
  return { mode: 'dom-hint', async detect() { return []; } };
}
