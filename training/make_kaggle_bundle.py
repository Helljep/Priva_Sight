"""
make_kaggle_bundle.py - packs everything the two Kaggle notebooks need into ONE zip and
writes the notebooks next to it.

    python training/make_kaggle_bundle.py

Produces (in training/kaggle/):
    privasight_bundle.zip      training scripts, NER data, recorded SFT trajectories, server/prompts.py
    1_train_ner.ipynb          fine-tunes the name detector (CPU is enough, ~70 min)
    2_train_lora_qwen_vl.ipynb QLoRA on Qwen3-VL-2B-Instruct (needs a T4 GPU, ~2 h)

On Kaggle: New Dataset -> upload privasight_bundle.zip -> New Notebook -> add that dataset ->
File > Import notebook -> pick one of the .ipynb files -> Run all (notebook 2: set Accelerator to GPU T4).
The notebooks never touch real personal data: every sample is synthetic.
"""
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'training' / 'kaggle'

FILES = [
    'training/gen_ner_data.py', 'training/train_ner.py', 'training/train_lora_qwen_vl.py',
    'server/prompts.py', 'server/schemas.py',
]
FOLDERS = ['training/data']  # ner_train/test.jsonl + sft/ (images + sft.jsonl)


def md(text):
    return {'cell_type': 'markdown', 'metadata': {}, 'source': text.strip('\n').splitlines(keepends=True)}


def code(text):
    return {'cell_type': 'code', 'metadata': {}, 'execution_count': None, 'outputs': [],
            'source': text.strip('\n').splitlines(keepends=True)}


def notebook(cells):
    return {'cells': cells, 'metadata': {'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'}},
            'nbformat': 4, 'nbformat_minor': 5}


UNZIP = '''
import glob, os, shutil, subprocess
# Kaggle usually extracts an uploaded zip for you; handle both cases.
zips = glob.glob('/kaggle/input/**/privasight_bundle.zip', recursive=True)
if zips:
    os.makedirs('/kaggle/working/PrivaSight', exist_ok=True)
    subprocess.run(['unzip', '-oq', zips[0], '-d', '/kaggle/working/PrivaSight'], check=True)
else:
    src = os.path.dirname(os.path.dirname(glob.glob('/kaggle/input/**/training/train_ner.py', recursive=True)[0]))
    shutil.copytree(src, '/kaggle/working/PrivaSight', dirs_exist_ok=True)
os.chdir('/kaggle/working/PrivaSight')
print(os.listdir('.'))
'''

CLONE = '''
# Scripts come straight from the public repo, so the name detector needs no dataset upload.
import os
!git clone -q https://github.com/Helljep/Priva_Sight.git /kaggle/working/PrivaSight
os.chdir('/kaggle/working/PrivaSight')
print(os.listdir('.'))
'''

NER = notebook([
    md('# PrivaSight - fine-tune the name detector (BERT NER)\nCPU is enough (~70-90 min). Trains on our synthetic names PLUS public data '
       '(WikiANN English, Naamapadam Hindi). Prints the BASE vs FINE-TUNED score on held-out names, then exports int8 ONNX.'),
    code('!pip install -q "transformers>=4.44" datasets seqeval onnx onnxruntime accelerate'),
    code(CLONE),
    code('!python training/gen_ner_data.py --n 24000 --out training/data/ner_train.jsonl\n'
         '!python training/gen_ner_data.py --n 2000 --holdout --out training/data/ner_test.jsonl'),
    code('!python training/train_ner.py --extra'),
    md('Download `training/out/bert-ner-in/` and `training/out/ner_metrics.json` (right panel > Output), '
       'then copy the folder to `extension/models/bert-ner-in/` on your laptop.'),
    code("!cd training/out && zip -qr /kaggle/working/bert-ner-in.zip bert-ner-in ner_metrics.json && ls -la /kaggle/working"),
])

LORA = notebook([
    md('# PrivaSight - QLoRA on Qwen3-VL-2B-Instruct\nSettings > Accelerator > **GPU T4**. Trains on redacted screenshots recorded from the scripted planner, '
       'so the model learns to act on black boxes and tokens like `[PHONE_1]`.'),
    code('!pip install -q -U "transformers>=4.57" peft trl bitsandbytes accelerate qwen-vl-utils'),
    code(UNZIP),
    code("import json; n = sum(1 for _ in open('training/data/sft/sft.jsonl')); print(n, 'training steps recorded')"),
    code('!python training/train_lora_qwen_vl.py --data training/data/sft/sft.jsonl --epochs 2'),
    md('Download the adapter (`training/out/qwen3vl-privasight-lora`). See docs/TRAINING.md for merging and loading into Ollama.'),
    code('!cd training/out && zip -qr /kaggle/working/qwen3vl-privasight-lora.zip qwen3vl-privasight-lora && ls -la /kaggle/working'),
])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    zpath = OUT / 'privasight_bundle.zip'
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in FILES:
            z.write(ROOT / f, f)
        for folder in FOLDERS:
            for p in sorted((ROOT / folder).rglob('*')):
                if p.is_file():
                    z.write(p, p.relative_to(ROOT).as_posix())
    (OUT / '1_train_ner.ipynb').write_text(json.dumps(NER, indent=1), encoding='utf-8')
    (OUT / '2_train_lora_qwen_vl.ipynb').write_text(json.dumps(LORA, indent=1), encoding='utf-8')
    print('wrote', zpath, f'({zpath.stat().st_size / 1e6:.1f} MB) and 2 notebooks in', OUT)


if __name__ == '__main__':
    main()
