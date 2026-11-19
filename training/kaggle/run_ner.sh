#!/bin/bash
# One-line Kaggle entry point for the name detector.
#   !git clone -q https://github.com/Helljep/Priva_Sight.git && bash Priva_Sight/training/kaggle/run_ner.sh
set -e
cd Priva_Sight
pip install -q "transformers>=4.44" datasets seqeval onnx onnxruntime accelerate
python training/gen_ner_data.py --n 24000 --out training/data/ner_train.jsonl
python training/gen_ner_data.py --n 2000 --holdout --out training/data/ner_test.jsonl
python training/train_ner.py --extra
cd training/out && zip -qr /kaggle/working/bert-ner-in.zip bert-ner-in ner_metrics.json && ls -la /kaggle/working
