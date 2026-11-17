"""
run_ablation.py - layer ablation: how much does each detector layer add?

Runs the privacy evaluation four times with layers switched on cumulatively:
    dom  ->  dom+regex  ->  dom+regex+ner  ->  dom+regex+ner+faces+ocr
and prints a table of text-PII recall for each step.

    python eval/run_ablation.py            # full set (slow: 4 x 225 captures)
    python eval/run_ablation.py --quick
Output: eval/results/ablation.json
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
STEPS = [
    ('DOM rules only', 'dom'),
    ('+ Regex (Verhoeff, Luhn, PAN)', 'dom,regex'),
    ('+ NER (names)', 'dom,regex,ner'),
    ('+ Faces, video, OCR (full pipeline)', 'dom,regex,ner,faces,ocr'),
]

ap = argparse.ArgumentParser()
ap.add_argument('--quick', action='store_true')
args = ap.parse_args()

rows = []
for label, layers in STEPS:
    tag = 'abl_' + layers.replace(',', '_')
    cmd = [sys.executable, str(HERE / 'run_privacy_eval.py'), '--layers', layers, '--tag', tag] + (['--quick'] if args.quick else [])
    print('running:', label, flush=True)
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    r = json.loads((HERE / 'results' / f'privacy_{tag}.json').read_text())
    rows.append({'layers': label, 'text_pii_recall': r['text_pii_recall'], 'face_recall': r['face_recall'],
                 'captures_with_leak': r['captures_with_leak']})

(HERE / 'results' / 'ablation.json').write_text(json.dumps(rows, indent=2))
print(f"\n{'Layers active':42s} {'Text PII recall':>16s} {'Face recall':>12s} {'Leaky captures':>15s}")
for r in rows:
    print(f"{r['layers']:42s} {r['text_pii_recall']:>15.1f}% {r['face_recall']:>11.1f}% {r['captures_with_leak']:>15d}")
