#!/bin/bash
# One-line entry for the held-out LoRA check on Kaggle (GPU T4).
# Notebook cell:  !git clone -q https://github.com/Helljep/Priva_Sight.git && bash Priva_Sight/training/kaggle/run_heldout.sh
# Inputs to attach: the held-out dataset (privasight-heldout) and the output of the LoRA notebook
# (privasight-lora-run). Optional: the original bundle dataset, to also score training steps.
set -e
export CUDA_VISIBLE_DEVICES=0  # one GPU: splitting a 2B model over two T4s only adds transfer time
cd Priva_Sight
pip install -q -U "transformers>=4.57" peft bitsandbytes accelerate qwen-vl-utils

HELD=$(find /kaggle/input -name sft.jsonl -path '*heldout*' | head -1)
[ -z "$HELD" ] && HELD=$(find /kaggle/input -name sft.jsonl | head -1)
TRAIN=$(find /kaggle/input -name sft.jsonl -path '*training/data/sft*' | head -1)
ADAPTER_CFG=$(find /kaggle/input -name adapter_config.json | head -1)
if [ -z "$ADAPTER_CFG" ]; then
  ZIP=$(find /kaggle/input -name 'qwen3vl-privasight-lora.zip' | head -1)
  mkdir -p /kaggle/working/adapter && unzip -oq "$ZIP" -d /kaggle/working/adapter
  ADAPTER_CFG=$(find /kaggle/working/adapter -name adapter_config.json | head -1)
fi
ADAPTER=$(dirname "$ADAPTER_CFG")
echo "held-out: $HELD | train: $TRAIN | adapter: $ADAPTER"

python training/eval_lora_heldout.py --heldout "$HELD" --adapter "$ADAPTER" ${TRAIN:+--train "$TRAIN"} --limit 100
