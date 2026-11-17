# Training the two models

Neither training run was executed on the development PC (Windows Smart App Control blocks PyTorch there,
and the laptop GPU is small). Both are designed for Kaggle / Colab. The scripts have been syntax-checked but
not run end to end, so expect to adjust versions on first use.

## 1. Indian-name NER (BERT, CPU, ~70 min)

```bash
pip install "transformers>=4.44" datasets seqeval "optimum[onnxruntime]" accelerate
python training/gen_ner_data.py --n 24000 --out training/data/ner_train.jsonl            # 24k synthetic UI snippets
python training/gen_ner_data.py --n 2000 --holdout --out training/data/ner_test.jsonl    # names never seen in training
python training/train_ner.py
```

`train_ner.py` prints entity-level P/R/F1 on the **held-out** names for the base model *before* tuning and for the tuned
model *after*, writes both to `training/out/ner_metrics.json`, then exports an int8 ONNX model.
Copy `training/out/bert-ner-in/` to `extension/models/bert-ner-in/` and reload the extension; the side panel will show
"Names: BERT model".

Until you do this, the extension uses the public baseline `Xenova/bert-base-NER` (fetched by
`scripts/vendor.mjs --download ner`), which is the "original model" the project compares against.

## 2. QLoRA for Qwen3-VL-2B on redacted screens (Kaggle T4, ~2 h)

1. Record expert trajectories from the project's own pipeline (sanitised screenshots only):
   ```bash
   python eval/run_task_eval.py --condition redacted --runs 15 --record-sft training/data/sft
   ```
   This writes `training/data/sft/sft.jsonl` + `images/`. With `--runs 15` over 32 tasks you get several hundred steps.
   The recorded actions come from the scripted planner, so the adapter learns the action format and
   how to act on black boxes and tokens. Add real human/other-model trajectories if you want more variety.
2. On Kaggle: `python training/train_lora_qwen_vl.py --data training/data/sft/sft.jsonl`
3. Serve it. Either merge the adapter and convert to GGUF for Ollama
   (`ollama create privasight-qwen3vl -f Modelfile`), or serve with `transformers`/vLLM behind the same
   `/plan` contract. Then:
   ```bash
   PRIVASIGHT_BACKEND=ollama OLLAMA_MODEL=privasight-qwen3vl python -m uvicorn app:app --port 8787
   python eval/run_task_eval.py --backend ollama --model privasight-qwen3vl
   ```
4. For a fair comparison also run the **base** model on redacted screens and (for the leak comparison only)
   `--condition unsafe`.

## Control experiment

To show the gain comes from redaction-aware training and not from extra data, also train on the *clean* (un-redacted)
screens (`--condition unsafe` with `--record-sft`, but note those images contain synthetic PII) and evaluate both
adapters live on redacted screens.
