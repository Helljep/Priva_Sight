# Architecture

## Trust boundary

Everything left of the dashed line runs in the user's browser. The server and model are **untrusted**:
they get only what the privacy gate lets through.

```
 TRUSTED (user's laptop)                                         │  UNTRUSTED
                                                                 │
  Active page ──► content.js ──snapshot──► side panel            │
   (raw DOM,        (text runs,            │                     │
    raw pixels)      fields, media,        ├─ sanitize.js ──► tokens + hidden ranges
                     rectangles)           ├─ redactor.js ──► sanitised screenshot
                                           ├─ vault.js    ──► token <-> real value (memory only)
                                           └─ gate.js     ──► approve / BLOCK  ── approved ──► server /plan
                                                                 │                              │
  Action executor ◄── tokens resolved locally from the vault ◄───┼───── {"type":"type","text":"{PASSWORD}"}
```

## One agent step (`extension/src/agent/loop.js`)

1. `perceive()` (`pipeline.js`): ask the content script for a **snapshot**, sanitise it, fetch exact rectangles for every
   detected character range, capture the tab, draw the redactions, run the **gate** on the outgoing text.
2. Gate failed -> stop the run (`blocked`). It never retries with weaker redaction.
3. `planStep()` (`api.js`) refuses to send unless the gate said ok, then POSTs `{goal, history, url, title, elements, visibleText, scroll, screenshot}`.
4. The server rejects raw PII (HTTP 422), builds the redaction-aware prompt, asks the planner (Ollama VLM or the scripted planner)
   and returns one action.
5. The loop replaces tokens in the action text with real values from the vault and sends it to the content script, which performs it.
   History keeps the **token** form, never the real value.

## Detection layers

| # | Layer | File | Finds | Notes |
|---|---|---|---|---|
| 1 | DOM rules | `pii/dom_rules.js` | password/OTP/CVV, email/tel types, name/id/label/autocomplete hints | works from field *type*, never reads a value to decide |
| 2 | Regex + checksums | `pii/validators.js`, `pii/regex_detector.js` | Aadhaar (Verhoeff), cards (Luhn), PAN, IFSC, mobiles, e-mails, labelled account numbers / DOB, whole addresses | validators confirm candidates -> high precision; label context may come from the previous text run on the page |
| 3 | Names | `pii/ner.js` (+ `ner.worker.js`, `name_heuristic.js`) | person names | BERT int8 ONNX in a Web Worker if `models/bert-ner-in/` exists, **unioned** with the rule detector; rules only otherwise |
| 4 | Faces / video | `vision/faces.js`, `redact/redactor.js` | faces in images | MediaPipe BlazeFace if installed, else DOM hints (avatar/profile/photo ...); every `<video>` is blacked out |
| 5 | OCR | `vision/ocr.js` | text that exists only as pixels | Tesseract.js, capped at 3 images per step; hits go through layers 2-3 |
| - | Vault scrub | `redact/vault.js` `findKnown` | any value the vault already holds | e.g. the username the agent just typed |

Overlapping matches are resolved by priority (known vault value > Aadhaar > card > PAN > e-mail > phone > IFSC > account > DOB > address > name), then length.

## Redaction (`redact/redactor.js`)

| Thing | Treatment |
|---|---|
| text PII | solid black box over the exact characters (rectangles from `Range.getClientRects`) |
| input value | solid black box over the whole field |
| face | pixelated + darkened |
| `<video>` | solid black box |
| OCR hit | solid black box over the text line |

Page labels and structure stay visible on purpose - the model needs them to act.

## Server (`server/`)

* `pii.py` - structured-PII scanner (mirror of the JS validators; shared test vectors in `tests/vectors.json`).
* `prompts.py` - system prompt explaining sanitised screens and tokens; also used to build LoRA training data.
* `planner.py` - `OllamaPlanner` (VLM) and `ScriptedPlanner` (deterministic, no GPU).
* `app.py` - `/plan`, `/health`.

## Test world (`testbed/`)

Six synthetic apps (DemoBank, HR Portal, City Hospital, ShopMart, MailBox, VideoMeet), 21 static pages filled at run time from
one of 50 synthetic personas (`?p=N`) in one of 5 visual layouts (`?layout=1..5`). Forms record `{action, data}` into
`localStorage`, exposed as `window.__state()`, which is how tasks are judged. Pages mark their own ground truth
(`data-bind`, `data-pii`), so privacy scoring needs no hand labelling.
