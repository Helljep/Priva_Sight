# Evaluation results (measured on this rebuild)

These numbers come from running the code in this repository in real Chromium with the extension loaded
(`eval/`, raw JSON in `eval/results/`). They are **not** the numbers from the original project deck, whose code was lost.
All data is synthetic (50 personas, 6 sites).

## Privacy: 225 captures (15 pages x 5 layouts x 3 personas), all five layers on

Names use the public baseline BERT model (`Xenova/bert-base-NER`, int8) unioned with the rule detector; faces use BlazeFace.

| Category | Recall |
|---|---|
| Aadhaar / PAN / Card | 100% |
| Phone / Email | 100% |
| Names | 100% |
| Addresses / DOB / IFSC / Account | 100% |
| **All text PII** | **100%** |
| Faces | 94.7% (142 of 150) |

* Captures where any real persona value appeared in the outgoing payload: **0 of 225**.
* Redaction precision (drawn boxes that sit on real PII): 90.5%. The BERT model sometimes boxes label words.
* Median perception time: ~1.4 s per step (BERT on single-thread WASM). With rule-based names only it was ~0.1 s.
* Not scored (outside the approved categories, so still visible): account balance, department, medical condition.

## Layer ablation (text-PII recall)

| Layers active | Text PII recall |
|---|---|
| DOM rules only | 12.7% |
| + Regex (Verhoeff, Luhn, PAN) | 65.5% |
| + NER (names) | 100% |
| + Faces, video, OCR (full) | 100% (faces 94.7%) |

Every layer adds coverage. (The "leaky captures" column in `ablation.json` was inflated by a scoring bug, fixed afterwards; use `privacy_final.json`.)

## Tasks: 32 tasks, scripted planner

| Condition | Task success | Runs that leaked PII to the server |
|---|---|---|
| Unsafe baseline (no redaction, no gate, server check off) | 100% | 26 of 32 |
| PrivaSight (redacted, gate on) | 100% | 0 of 32 |

Run with the rule-based name layer, one run per task. The scripted planner follows a controlled-language goal,
so this proves the **pipeline** (redaction does not break acting, nothing leaks), not that a VLM can use redacted screens.

## Tasks: 32 tasks, real model (Qwen3-VL-2B-Instruct via Ollama, base, no LoRA)

| Condition | Task success | Runs that leaked PII to the server |
|---|---|---|
| Unsafe baseline (no redaction, no gate, server check off) | 25% (8/32) | 2 of 32 |
| PrivaSight (redacted, gate on) | 25% (8/32) | 0 of 32 |

Per site, both conditions identical: shop 5/5, meet 2/4, mail 1/4, bank 0/10, hospital 0/4, HR 0/5.
One run per task, max 10 steps, 10 s/step budget not enforced.

**Reading:** redaction cost no task success here (same tasks pass and fail either way), so the 25% is limited by the
2B base model, not by masking. Most failures hit the step limit. This is the figure a LoRA should improve.
The unsafe run leaked in only 2 of 32 runs because the weak model rarely reaches pages that show PII; do not read that as a leak rate.
Note: the `qwen3-vl:2b` Ollama tag is a thinking build that returns empty answers within our token budget; `qwen3-vl:2b-instruct` was used.

## Name model: fine-tuned vs public baseline (name layer alone, 225 captures)

Fine-tuned on Kaggle: 24,000 synthetic sentences + 7,244 WikiANN-English sentences (Naamapadam failed to load, so no Hindi/Devanagari data).

| Model | Held-out synthetic names F1 | Name recall in the extension | Precision of redaction boxes |
|---|---|---|---|
| Public baseline (dslim/bert-base-NER) | 0.884 | 100% (315/315) | 78.8% |
| Fine-tuned v1 | 0.994 | 100% (315/315) | 50.7% |
| Fine-tuned v2 (hard negatives) | 0.993 | 100% (315/315) | 82.4% |

**Reading:** the 0.994 only shows the model learned our own templates. Inside the real pipeline it catches the same names
but wrongly flags many ordinary words as names (precision drops 28 points), so it would mask page text the agent needs.
v1 is kept in `extension/models/bert-ner-finetuned-v1/`.

**v2 fix:** 45% of the training sentences now contain no person (menu words, headers, status labels, "Label: value" lines) and 10% put a name among UI words.
Same recall, precision back up to 82.4% (baseline 78.8%), so v2 is the active model. The gain over the baseline is small (+3.6 points) and comes from one run on our synthetic pages.
One sentence still fails for both v2 and the baseline: "Meera Krishnamurthy" inside a 62-word line (`eval/test_ner_model.py`).

## What this does not show
* A real base VLM was run (above), but a LoRA-tuned model was not, so base-vs-LoRA improvement is unmeasured.
* NER fine-tuning and LoRA training scripts exist but were never run.
* Test personas are synthetic and pages are simple; real sites will be harder, especially names in free text.
* The 8 missed faces were not investigated.
