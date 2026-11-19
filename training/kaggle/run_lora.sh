#!/bin/bash
# One-line Kaggle entry point for the Qwen3-VL LoRA (GPU T4 + the privasight-bundle dataset attached).
#   !git clone -q https://github.com/Helljep/Priva_Sight.git && bash Priva_Sight/training/kaggle/run_lora.sh
set -e
SFT=$(find /kaggle/input -name sft.jsonl | head -1)
echo "training data: $SFT ($(wc -l < "$SFT") steps)"
cd Priva_Sight
pip install -q -U "transformers>=4.57" peft trl bitsandbytes accelerate qwen-vl-utils
python training/train_lora_qwen_vl.py --data "$SFT" --epochs 2
cd training/out && zip -qr /kaggle/working/qwen3vl-privasight-lora.zip qwen3vl-privasight-lora && ls -la /kaggle/working
