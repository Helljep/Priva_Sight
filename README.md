# PrivaSight

**On-device visual perception for privacy-preserving lightweight browser agents.**

AI browser agents (WebVoyager, Agent-E, ...) send full screenshots and raw page text to a cloud
vision-language model. That exposes passwords, Aadhaar / PAN numbers, bank details, medical records
and faces. PrivaSight is a Chrome (Manifest V3) extension that detects and hides all of that **on
your laptop, before anything is sent**. The model only ever sees:

* a **sanitised screenshot** - black boxes over text PII and form values, faces pixelated, video blacked out
* **placeholder tokens** in the page description - `[PHONE_1]`, `[EMAIL_1]`, `[NAME_1]`, `{PASSWORD}` ...

When the model says `type(#4, "{PASSWORD}")`, the real value is substituted **locally** from an
in-memory vault at the moment of typing.

```
 Chrome extension (on your device)                              Server (open-weights VLM)
 ┌──────────────────────────────────────────────┐              ┌────────────────────────────┐
 │ page ─ snapshot ─► detection layers          │              │ FastAPI  /plan             │
 │        screenshot  1 DOM rules               │  sanitised   │  ├ PII rejection (422)     │
 │                    2 regex + checksums       │ ───────────► │  ├ redaction-aware prompt  │
 │                    3 name NER (BERT / rules) │ screenshot   │  └ planner:                │
 │                    4 faces / video          │ + tokens     │     Qwen3-VL via Ollama    │
 │                    5 image OCR              │              │     or scripted (no GPU)   │
 │ ► redaction engine ► token vault ► PRIVACY   │ ◄─────────── │                            │
 │   GATE (fail closed) ◄─ action executor      │  JSON action └────────────────────────────┘
 └──────────────────────────────────────────────┘
```

## Sitting between ANY agent and the browser

Two modes (see [docs/INTEGRATION.md](docs/INTEGRATION.md)):

* **Shield mode** - the page itself is redacted in place (tokens in text, blacked-out inputs, blurred faces), so any agent's
  screenshot or DOM read is already safe, and tokens the agent types are swapped for real values locally.
* **Agent gateway (MCP)** - an agent given only the `privasight_screen` / `privasight_act` tools can see and act on the
  browser through PrivaSight and nothing else.

Tested with `python eval/test_shield.py` and `python eval/test_gateway.py` (real Chromium, fake MCP agent).

## What is in this folder

| Folder | What it is |
| --- | --- |
| `extension/` | The Chrome MV3 extension (content script, detectors, redaction, vault, gate, agent loop, side-panel UI) |
| `server/` | FastAPI planner server: PII rejection, redaction-aware prompts, Ollama / scripted planners |
| `testbed/` | 6 synthetic web apps (21 pages), 50 synthetic Indian personas, 32 task YAMLs |
| `eval/` | Playwright harness: privacy evaluation, task evaluation, layer ablation |
| `training/` | Indian-name NER data generator + fine-tune/ONNX export, QLoRA script for Qwen3-VL-2B |
| `tests/`, `server/tests/` | Unit tests (Node and Python) sharing one set of test vectors |
| `docs/` | Architecture, evaluation results, training guide |

## Quick start

Requirements: Chrome/Chromium, Python 3.10+, Node 18+. (Ollama only if you want a real model.)

```bash
# 1. generate the synthetic test world (personas, 21 pages, 32 tasks)
python testbed/gen_personas.py && python testbed/build_sites.py && python testbed/gen_tasks.py

# 2. start the planner server (scripted planner: no GPU, deterministic)
cd server && pip install -r requirements.txt && python -m uvicorn app:app --port 8787

# 3. serve the demo sites
cd testbed/sites && python -m http.server 8000      # then open http://localhost:8000/demobank/login.html

# 4. load the extension: chrome://extensions -> Developer mode -> Load unpacked -> choose extension/
#    click the PrivaSight icon to open the side panel
```

In the side panel: enter your goal, put the login in the **Secrets vault** (`{USERNAME}`, `{PASSWORD}`),
press **Run agent**. Use **Preview what's sent** to see exactly the screenshot and JSON the server would receive.

With the scripted planner the goal uses a small controlled language, e.g.

```
log in then click "Transfer" then select "Priya Nair" in "Payee" then type "500" into "Amount" then click "Transfer now"
```

For a real model: `ollama pull qwen3-vl:2b`, then start the server with
`PRIVASIGHT_BACKEND=ollama` (and `OLLAMA_MODEL=<name>` for a LoRA-merged model). Goals can then be plain English.

### Optional: the full ML layers

Without these the extension still works - names use a rule-based detector, faces use DOM hints, there is no OCR.
`extension/models/bert-ner-in/` (names), `blaze_face_short_range.tflite` (faces) and Tesseract (OCR) switch on automatically when present.

```bash
npm install
npm run vendor                              # copies the libraries into extension/vendor
node scripts/vendor.mjs --download faces,ocr,ner   # fetches model files (BlazeFace ~0.2 MB, OCR ~11 MB, BERT NER ~108 MB)
```

The side panel's **Detection layers** section always shows which implementation of each layer is active.

## Tests and evaluation

```bash
npm test                                    # Node: validators, detectors, vault, gate
python server/tests/test_server.py          # Python: server, planner, PII rejection
python eval/run_privacy_eval.py --quick     # real Chromium + extension; add nothing for the full 225 captures
python eval/run_task_eval.py --condition redacted
python eval/run_task_eval.py --condition unsafe     # baseline: no redaction, no gate, server check off
python eval/run_ablation.py
```

See [docs/EVALUATION.md](docs/EVALUATION.md) for the measured numbers and, importantly, what they do and
do not show.

## Privacy design in one page

1. **Five detection layers** (`extension/src/pii/`, `vision/`): DOM rules (password / autocomplete / label hints),
   regex with checksums (Aadhaar-Verhoeff, Luhn cards, PAN structure, IFSC, Indian mobiles, labelled accounts / DOB, whole addresses),
   name NER, face detection, OCR of images.
2. **Redaction** (`redact/redactor.js`): black boxes over the exact characters, whole-field boxes over input values,
   pixelated faces, black video, OCR-hit boxes. Done on an `OffscreenCanvas`; the raw screenshot is never stored or sent.
3. **Token vault** (`redact/vault.js`): value <-> placeholder, in memory only. Anything the vault knows is hidden wherever it appears
   (for example the username the agent just typed).
4. **Privacy gate** (`redact/gate.js`): re-scans the final payload and compares it with every real value in the vault.
   If anything is left, the run **stops** - it never retries without redaction.
5. **Server PII rejection** (`server/pii.py`): a third check; raw PII gets HTTP 422 and is never logged or passed to the model.
6. **Hidden-text defence**: invisible / tiny text (the usual vehicle for injected instructions) is not read. URLs are sent without query strings.

## Honest limitations

* Names in free prose and non-Latin scripts are covered less well than structured PII. The rule-based fallback is weak;
  use the fine-tuned model for real use.
* Page labels and UI context stay visible by design - the model needs them to act.
* The scripted planner tests the pipeline; it is not an AI agent. Task-success numbers for a real VLM need Ollama (see docs).
* Chromium only (MV3 side panel). Firefox is future work.
