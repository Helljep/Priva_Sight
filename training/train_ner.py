"""
train_ner.py - fine-tune a BERT NER model on the synthetic Indian-name data and
export it as an int8 ONNX model the extension can load.

NOT run on the development PC: PyTorch is blocked there by Windows Smart App
Control. Run it on Kaggle / Colab (CPU is enough: ~70 minutes) or any machine
with PyTorch:

    pip install "transformers>=4.44" datasets seqeval "optimum[onnxruntime]" accelerate
    python training/gen_ner_data.py --n 24000 --out training/data/ner_train.jsonl
    python training/gen_ner_data.py --n 2000 --holdout --out training/data/ner_test.jsonl
    python training/train_ner.py

Result: training/out/bert-ner-in/  ->  copy the folder to extension/models/bert-ner-in/
(the folder must contain config.json, tokenizer files and onnx/model_quantized.onnx).

Reported numbers are measured on the HELD-OUT test file (names never seen in
training), together with the same measurement for the un-tuned base model so the
improvement is real rather than assumed.
"""
import json
from pathlib import Path

import numpy as np
from datasets import Dataset
from seqeval.metrics import f1_score, precision_score, recall_score
from transformers import (AutoModelForTokenClassification, AutoTokenizer, DataCollatorForTokenClassification,
                          Trainer, TrainingArguments)

BASE = 'dslim/bert-base-NER'     # the public model Xenova/bert-base-NER is converted from
LABELS = ['O', 'B-PER', 'I-PER']
L2I = {l: i for i, l in enumerate(LABELS)}
ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'out' / 'bert-ner-in'


def load(path):
    rows = [json.loads(line) for line in open(path, encoding='utf-8')]
    return Dataset.from_list(rows)


def encode(tok):
    def fn(batch):
        enc = tok(batch['tokens'], is_split_into_words=True, truncation=True, max_length=64)
        all_labels = []
        for i, labels in enumerate(batch['labels']):
            word_ids, prev, out = enc.word_ids(i), None, []
            for w in word_ids:
                out.append(-100 if w is None or w == prev else L2I[labels[w]])
                prev = w
            all_labels.append(out)
        enc['labels'] = all_labels
        return enc
    return fn


def evaluate(model, tok, test_rows):
    """Entity-level P/R/F1 on the held-out names."""
    model.eval()
    preds, golds = [], []
    import torch
    for row in test_rows:
        enc = tok(row['tokens'], is_split_into_words=True, return_tensors='pt', truncation=True, max_length=64)
        with torch.no_grad():
            logits = model(**enc).logits[0]
        ids, prev, p = enc.word_ids(0), None, []
        for pos, w in enumerate(ids):
            if w is not None and w != prev:
                p.append(model.config.id2label[int(logits[pos].argmax())])
            prev = w
        # map the base model's CoNLL labels (B-PER/I-PER/B-ORG...) to PER-or-O
        p = [x if x in ('B-PER', 'I-PER') else 'O' for x in p]
        preds.append(p)
        golds.append(row['labels'][:len(p)])
    return {'precision': precision_score(golds, preds), 'recall': recall_score(golds, preds), 'f1': f1_score(golds, preds)}


def main():
    tok = AutoTokenizer.from_pretrained(BASE)
    test_rows = [json.loads(line) for line in open(ROOT / 'data' / 'ner_test.jsonl', encoding='utf-8')]

    base_model = AutoModelForTokenClassification.from_pretrained(BASE)
    before = evaluate(base_model, tok, test_rows)
    print('BASE model on held-out Indian names:', before)

    model = AutoModelForTokenClassification.from_pretrained(
        BASE, num_labels=len(LABELS), id2label=dict(enumerate(LABELS)), label2id=L2I, ignore_mismatched_sizes=True)
    ds = load(ROOT / 'data' / 'ner_train.jsonl').map(encode(tok), batched=True, remove_columns=['tokens', 'labels'])
    args = TrainingArguments(output_dir=str(OUT / 'ckpt'), num_train_epochs=2, per_device_train_batch_size=32,
                             learning_rate=3e-5, weight_decay=0.01, logging_steps=100, save_strategy='no', report_to=[])
    Trainer(model=model, args=args, train_dataset=ds, data_collator=DataCollatorForTokenClassification(tok)).train()

    after = evaluate(model, tok, test_rows)
    print('FINE-TUNED model on held-out Indian names:', after)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT.parent / 'ner_metrics.json').write_text(json.dumps({'base': before, 'fine_tuned': after}, indent=2))

    model.save_pretrained(OUT)
    tok.save_pretrained(OUT)

    # ---- export to ONNX + int8 quantisation (what the browser loads) ----
    from optimum.onnxruntime import ORTModelForTokenClassification, ORTQuantizer
    from optimum.onnxruntime.configuration import AutoQuantizationConfig
    ort = ORTModelForTokenClassification.from_pretrained(OUT, export=True)
    ort.save_pretrained(OUT / 'onnx')
    quantizer = ORTQuantizer.from_pretrained(OUT / 'onnx')
    quantizer.quantize(save_dir=OUT / 'onnx', quantization_config=AutoQuantizationConfig.avx2(is_static=False, per_channel=False))
    print('exported ->', OUT / 'onnx', '(model_quantized.onnx). Copy', OUT, 'to extension/models/bert-ner-in/')


if __name__ == '__main__':
    main()
