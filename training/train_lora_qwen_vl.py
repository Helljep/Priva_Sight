"""
train_lora_qwen_vl.py - QLoRA fine-tune of Qwen3-VL-2B-Instruct on REDACTED
screens, so the model learns to act on black boxes and placeholder tokens.

Meant for a Kaggle T4 (16 GB, free tier, ~2 h). It was NOT run on the
development laptop (4-8 GB GPU, PyTorch blocked) and has not been executed
end to end: treat it as a reviewed starting point, and expect to adjust the
model class / processor call if your transformers version differs.

Data comes from the project's own pipeline:
    python eval/run_task_eval.py --condition redacted --runs 15 --record-sft training/data/sft
which saves, for every agent step, the SANITISED screenshot (jpg) and a JSONL
row {image, prompt, answer}. No real personal data is involved at any point.

Kaggle setup:
    pip install -U "transformers>=4.57" peft trl bitsandbytes accelerate qwen-vl-utils
    python training/train_lora_qwen_vl.py --data training/data/sft/sft.jsonl

Afterwards merge + convert for Ollama (see docs/TRAINING.md).
"""
import argparse
import json
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from PIL import Image
from transformers import (AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig, Trainer,
                          TrainingArguments)

BASE = 'Qwen/Qwen3-VL-2B-Instruct'
SYSTEM = (Path(__file__).resolve().parents[1] / 'server' / 'prompts.py')


def system_prompt():
    # reuse the exact string used at inference time
    ns = {}
    exec(SYSTEM.read_text(encoding='utf-8').split('def element_line')[0], ns)  # only the SYSTEM_PROMPT constant
    return ns['SYSTEM_PROMPT']


class SFTData(torch.utils.data.Dataset):
    def __init__(self, path, processor, root):
        self.rows = [json.loads(l) for l in open(path, encoding='utf-8')]
        self.p, self.root, self.sys = processor, Path(root), system_prompt()

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        image = Image.open(self.root / r['image']).convert('RGB')
        msgs = [
            {'role': 'system', 'content': [{'type': 'text', 'text': self.sys}]},
            {'role': 'user', 'content': [{'type': 'image'}, {'type': 'text', 'text': r['prompt']}]},
        ]
        prompt = self.p.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
        full = prompt + r['answer'] + self.p.tokenizer.eos_token
        enc = self.p(text=[full], images=[image], return_tensors='pt')
        n_prompt = self.p(text=[prompt], images=[image], return_tensors='pt')['input_ids'].shape[1]
        labels = enc['input_ids'].clone()
        labels[:, :n_prompt] = -100              # learn only the action JSON, not the prompt
        enc['labels'] = labels
        return dict(enc)  # keeps the batch dim of 1; Qwen's pixel_values/grid already have their own layout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default='training/data/sft/sft.jsonl')
    ap.add_argument('--out', default='training/out/qwen3vl-privasight-lora')
    ap.add_argument('--epochs', type=int, default=2)
    args = ap.parse_args()

    processor = AutoProcessor.from_pretrained(BASE)
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4', bnb_4bit_compute_dtype=torch.float16,
                             bnb_4bit_use_double_quant=True)
    model = AutoModelForImageTextToText.from_pretrained(BASE, quantization_config=bnb, device_map='auto')
    model = prepare_model_for_kbit_training(model)
    model = get_peft_model(model, LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05, task_type='CAUSAL_LM',
        target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj']))
    model.print_trainable_parameters()

    data = SFTData(args.data, processor, Path(args.data).parent)
    targs = TrainingArguments(output_dir=args.out, num_train_epochs=args.epochs, per_device_train_batch_size=1,
                              gradient_accumulation_steps=8, learning_rate=2e-4, warmup_steps=10, lr_scheduler_type='cosine',
                              fp16=True, logging_steps=10, save_strategy='epoch', report_to=[], remove_unused_columns=False)
    Trainer(model=model, args=targs, train_dataset=data, data_collator=lambda batch: batch[0]).train()
    model.save_pretrained(args.out)
    print('adapter saved to', args.out)


if __name__ == '__main__':
    main()
