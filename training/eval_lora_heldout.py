"""
eval_lora_heldout.py - did the LoRA learn the task, or just memorise its training steps?

For every step of a HELD-OUT trajectory (page layouts and personas the adapter never saw during
training) we show the model the same redacted screenshot + prompt the planner would send, let it
answer greedily, and compare the answer with the action the scripted planner took:

    exact   the whole action matches (type + element id + text/key/url ...), 'thought' ignored
    type    only the action type matches (click / type / done ...)
    valid   the reply contained a parseable JSON object

The same steps are scored twice, with the adapter switched off (base model) and on (LoRA), so the
difference is the effect of training. Optionally the same is done on a sample of TRAINING steps; a
big gap between training and held-out accuracy means memorisation.

Runs on a Kaggle T4 (PyTorch is blocked on the development PC). See training/kaggle/run_heldout.sh.
"""
import argparse
import json
import random
import sys
from pathlib import Path

import torch
from peft import PeftModel
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig

BASE = 'Qwen/Qwen3-VL-2B-Instruct'
ROOT = Path(__file__).resolve().parents[1]


def system_prompt():
    ns = {}
    src = (ROOT / 'server' / 'prompts.py').read_text(encoding='utf-8').split('def element_line')[0]
    exec(src, ns)  # only the SYSTEM_PROMPT constant, same string the planner uses at inference time
    return ns['SYSTEM_PROMPT']


def first_json(text):
    """First JSON object in a reply (small models sometimes add text or several objects)."""
    start = text.find('{')
    if start < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
        return obj if isinstance(obj, dict) else None
    except ValueError:
        return None


def clean(action):
    a = {k: v for k, v in action.items() if k != 'thought' and v not in (None, False, '')}
    if 'id' in a:
        try:
            a['id'] = int(str(a['id']).lstrip('#'))
        except ValueError:
            pass
    return a


def load_rows(path):
    root = Path(path).parent
    return [(json.loads(l), root) for l in open(path, encoding='utf-8') if l.strip()]


@torch.no_grad()
def answer(model, processor, sys_prompt, row, root):
    image = Image.open(root / row['image']).convert('RGB')
    msgs = [{'role': 'system', 'content': [{'type': 'text', 'text': sys_prompt}]},
            {'role': 'user', 'content': [{'type': 'image'}, {'type': 'text', 'text': row['prompt']}]}]
    prompt = processor.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
    enc = processor(text=[prompt], images=[image], return_tensors='pt').to(model.device)
    out = model.generate(**enc, max_new_tokens=120, do_sample=False)
    return processor.batch_decode(out[:, enc['input_ids'].shape[1]:], skip_special_tokens=True)[0]


def score(model, processor, sys_prompt, rows, label, adapter_on, limit):
    ok_exact = ok_type = ok_valid = 0
    rows = rows[:limit]
    for i, (row, root) in enumerate(rows):
        if adapter_on:
            reply = answer(model, processor, sys_prompt, row, root)
        else:
            with model.disable_adapter():
                reply = answer(model, processor, sys_prompt, row, root)
        pred, gold = first_json(reply), clean(json.loads(row['answer']))
        if pred is not None:
            ok_valid += 1
            pred = clean(pred)
            ok_type += pred.get('type') == gold.get('type')
            ok_exact += pred == gold
        if i < 3:
            print(f'  [{label}] gold={gold}\n  [{label}] pred={pred}', flush=True)
    n = max(1, len(rows))
    res = {'steps': len(rows), 'exact_pct': round(100 * ok_exact / n, 1), 'type_pct': round(100 * ok_type / n, 1),
           'valid_json_pct': round(100 * ok_valid / n, 1)}
    print(label, res, flush=True)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--heldout', required=True, help='sft.jsonl of held-out steps')
    ap.add_argument('--train', default='', help='optional sft.jsonl of training steps (a sample is scored)')
    ap.add_argument('--adapter', required=True)
    ap.add_argument('--limit', type=int, default=300)
    ap.add_argument('--out', default='/kaggle/working/lora_heldout.json')
    args = ap.parse_args()

    processor = AutoProcessor.from_pretrained(BASE)
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4', bnb_4bit_compute_dtype=torch.float16,
                             bnb_4bit_use_double_quant=True)  # same quantisation the adapter was trained on
    model = AutoModelForImageTextToText.from_pretrained(BASE, quantization_config=bnb, device_map='auto')
    model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()
    sys_prompt = system_prompt()

    held = load_rows(args.heldout)
    random.Random(0).shuffle(held)
    results = {'held_out': {
        'base': score(model, processor, sys_prompt, held, 'held-out base', False, args.limit),
        'lora': score(model, processor, sys_prompt, held, 'held-out lora', True, args.limit)}}
    if args.train:
        train = load_rows(args.train)
        random.Random(0).shuffle(train)
        results['train_sample'] = {'lora': score(model, processor, sys_prompt, train, 'train lora', True, args.limit)}
    Path(args.out).write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    sys.exit(main())
