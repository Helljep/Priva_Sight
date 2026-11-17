"""
run_privacy_eval.py - how well does the on-device pipeline hide PII?

For every (page x layout x persona) capture it:
  1. opens the page in Chromium with the extension loaded,
  2. runs the REAL perceive() pipeline through the harness,
  3. scores against ground truth taken from the page's own markup
     ([data-bind] and [data-pii] elements are the known sensitive items).

Metrics (same categories as the project's results table):
  text recall  - fraction of ground-truth text items whose real value is absent
                 from the payload AND whose on-screen box is blacked out
  face recall  - fraction of face photos / video tiles that are blurred/blacked
  leaks        - captures where ANY real persona value appears in the payload
  precision    - fraction of drawn text boxes that overlap a ground-truth item
  latency      - median perceive() time

Usage:
  python eval/run_privacy_eval.py                 # full: 15 pages x 5 layouts x 3 personas
  python eval/run_privacy_eval.py --quick         # 4 pages x 2 layouts x 1 persona
  python eval/run_privacy_eval.py --layers dom    # ablation: only the listed layers on
Output: eval/results/privacy_<tag>.json
"""
import argparse
import base64
import io
import json
import re
import statistics
import sys
from pathlib import Path

from PIL import Image  # pip install pillow

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, browser_with_extension, free_port, static_server  # noqa: E402

CATEGORY = {
    'aadhaar': 'Aadhaar / PAN / Card', 'pan': 'Aadhaar / PAN / Card', 'card': 'Aadhaar / PAN / Card',
    'phone': 'Phone / Email', 'email': 'Phone / Email',
    'name': 'Names', 'first': 'Names', 'NAME': 'Names',
    'address': 'Addresses / DOB / IFSC', 'dob': 'Addresses / DOB / IFSC', 'ifsc': 'Addresses / DOB / IFSC',
    'account': 'Addresses / DOB / IFSC', 'pincode': 'Addresses / DOB / IFSC',
}
ALL_LAYERS = ['dom', 'regex', 'ner', 'faces', 'ocr']

# 15 pages used by the full run (login pages carry no PII, so they are skipped).
PAGES = ['demobank/dashboard', 'demobank/profile', 'demobank/statements', 'hr/profile', 'hr/directory', 'hr/payroll',
         'hospital/record', 'shopmart/checkout', 'mailbox/inbox', 'mailbox/message', 'videomeet/lobby', 'videomeet/room',
         'demobank/transfer', 'hospital/appointments', 'hr/profile']
LOGIN_SITES = {'demobank', 'hr', 'hospital', 'mailbox', 'videomeet'}

GROUND_TRUTH_JS = """
() => {
  const items = [];
  const rect = (el) => { const r = el.getBoundingClientRect(); return {x:r.left,y:r.top,w:r.width,h:r.height}; };
  // A wrapped value spans several lines; score every line box, not the block.
  const lines = (el) => { const rg = document.createRange(); rg.selectNodeContents(el);
    return [...rg.getClientRects()].filter((r) => r.width > 1 && r.height > 1)
      .map((r) => ({x:r.left,y:r.top,w:r.width,h:r.height})); };
  const vis = (r) => r.w > 1 && r.h > 1 && r.y < innerHeight && r.x < innerWidth && r.y + r.h > 0;
  document.querySelectorAll('[data-bind]').forEach((el) => {
    const r = rect(el); if (vis(r)) items.push({kind:'text', field: el.dataset.bind, value: el.textContent.trim(), rect: r, lines: lines(el)});
  });
  document.querySelectorAll('[data-pii]').forEach((el) => {
    const r = rect(el); if (vis(r)) items.push({kind:'text', field: el.dataset.pii, value: el.textContent.trim(), rect: r, lines: lines(el)});
  });
  document.querySelectorAll('input[data-bind-value]').forEach((el) => {
    const r = rect(el); if (vis(r) && el.value) items.push({kind:'text', field: el.dataset.bindValue, value: el.value, rect: r});
  });
  document.querySelectorAll('img[data-face], video[data-face]').forEach((el) => {
    const r = rect(el); if (vis(r)) items.push({kind:'face', field:'face', value:'', rect: r});
  });
  return items;
}
"""


def login(page, base, site, persona_idx, layout):
    """Log in through the real form so protected pages can be captured."""
    people = json.loads((ROOT / 'testbed/sites/data/personas.json').read_text(encoding='utf-8'))
    me = people[persona_idx % len(people)]
    page.goto(f'{base}/{site}/login.html?p={persona_idx}&layout={layout}')
    page.wait_for_selector('body[data-ready]')
    page.fill('[name=username]', me['username'])
    page.fill('[name=password]', me['password'])
    page.click('button[type=submit]')
    page.wait_for_load_state()


def luminance_dark_fraction(img, box, thresh=40):
    crop = img.crop(box).convert('L')
    px = list(crop.get_flattened_data())
    return sum(1 for v in px if v < thresh) / max(1, len(px))


def region_changed(raw, red, box):
    a, b = raw.crop(box).convert('L'), red.crop(box).convert('L')
    pa, pb = list(a.get_flattened_data()), list(b.get_flattened_data())
    return sum(abs(x - y) for x, y in zip(pa, pb)) / max(1, len(pa))


def overlaps(a, b):
    return a['x'] < b['x'] + b['w'] and b['x'] < a['x'] + a['w'] and a['y'] < b['y'] + b['h'] and b['y'] < a['y'] + a['h']


def normalise(s):
    return re.sub(r'[\s\-+]', '', s).lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--layers', default=','.join(ALL_LAYERS), help='comma list of layers that are ON')
    ap.add_argument('--tag', default='full')
    ap.add_argument('--headed', action='store_true')
    args = ap.parse_args()

    on = set(x for x in args.layers.split(',') if x)
    layers = {k: (k in on) for k in ALL_LAYERS}
    pages = PAGES[:4] if args.quick else PAGES
    layouts = ['1', '2'] if args.quick else ['1', '2', '3', '4', '5']
    personas = [0] if args.quick else [0, 17, 34]

    per_cat = {}
    leaked_fields = {}
    persona_values = {normalise(v) for p in json.loads((ROOT / 'testbed/sites/data/personas.json').read_text(encoding='utf-8')) for k, v in p.items() if k in ('aadhaar','pan','card','phone','email','address','dob','account','ifsc','name','first','last','password','username') and len(str(v)) >= 4}
    vault_leaks = {}
    by_field = {}
    unscored = {}
    leaks, captures, latencies, box_total, box_good = 0, 0, [], 0, 0
    out_dir = Path(__file__).parent / 'results'
    out_dir.mkdir(exist_ok=True)

    with static_server(free_port()) as base, browser_with_extension(headless=not args.headed) as (ctx, harness):
        print('tools:', harness.evaluate('window.toolStatus()'))
        for pidx in personas:
            for layout in layouts:
                logged_in = set()
                for path in pages:
                    site, name = path.split('/')
                    page = ctx.new_page()
                    page.bring_to_front()
                    if site in LOGIN_SITES and (site, pidx, layout) not in logged_in:
                        login(page, base, site, pidx, layout)
                        logged_in.add((site, pidx, layout))
                    url = f'{base}/{path.split("/")[0]}/{name}.html?p={pidx}&layout={layout}'
                    page.goto(url)
                    page.wait_for_selector('body[data-ready]')
                    gt = page.evaluate(GROUND_TRUTH_JS)
                    inner_w = page.evaluate('innerWidth')
                    raw_png = page.screenshot()
                    cap = harness.evaluate('(a) => window.runCapture(a)', {'urlPrefix': url, 'layers': layers})
                    page.close()

                    payload = json.dumps(cap['payloadParts'], ensure_ascii=False)
                    norm_payload = normalise(payload)
                    # A vault value only counts as a leak if it is really one of the persona's secrets;
                    # the vault also holds detector false positives such as the label "Aadhaar".
                    vault_hits = [v for v in cap['realValues'] if len(v) >= 4 and normalise(v) in norm_payload
                                  and normalise(v) in persona_values]
                    for v in vault_hits:
                        vault_leaks[v] = vault_leaks.get(v, 0) + 1
                    this_leak = bool(vault_hits)
                    # independent leak check against the page's own ground-truth values
                    # (not only the vault), limited to the approved PII categories
                    for it in gt:
                        if it['kind'] == 'text' and it['field'] in CATEGORY and len(it['value']) >= 4                                 and normalise(it['value']) in norm_payload:
                            this_leak = True
                            leaked_fields[it['field']] = leaked_fields.get(it['field'], 0) + 1
                    leaks += this_leak
                    captures += 1
                    latencies.append(cap['timingMs'])

                    red = Image.open(io.BytesIO(base64.b64decode(cap['screenshot'].split(',', 1)[1]))).convert('RGB')
                    raw = Image.open(io.BytesIO(raw_png)).convert('RGB')
                    scale = red.width / inner_w

                    def to_box(r):
                        return (max(0, int(r['x'] * scale)), max(0, int(r['y'] * scale)),
                                min(red.width, int((r['x'] + r['w']) * scale)), min(red.height, int((r['y'] + r['h']) * scale)))

                    for it in gt:
                        if it['kind'] == 'text' and it['field'] not in CATEGORY:
                            # balance, department, medical condition ... are sensitive-ish but outside the
                            # approved PII categories: reported, never counted in recall.
                            unscored[it['field']] = unscored.get(it['field'], 0) + 1
                            continue
                        rects = it.get('lines') or [it['rect']]
                        boxes = [b for b in (to_box(r) for r in rects) if b[2] - b[0] >= 2 and b[3] - b[1] >= 2]
                        if not boxes:
                            continue
                        if it['kind'] == 'face':
                            cat = 'Faces'
                            hidden = all(region_changed(raw, red, b) > 25 for b in boxes)
                        else:
                            cat = CATEGORY[it['field']]
                            # hidden = real text absent from payload AND every line of it blacked out
                            hidden = normalise(it['value']) not in norm_payload and                                 all(luminance_dark_fraction(red, b) > 0.6 for b in boxes)
                        f = by_field.setdefault(it['field'], {'items': 0, 'hidden': 0})
                        f['items'] += 1
                        f['hidden'] += hidden
                        c = per_cat.setdefault(cat, {'items': 0, 'hidden': 0, 'leaked': 0})
                        c['items'] += 1
                        c['hidden'] += hidden
                        c['leaked'] += (not hidden)

                    # precision: do the drawn text boxes sit on ground-truth items?
                    gt_rects = [r for g in gt for r in (g.get('lines') or [g['rect']])]
                    for b in cap['boxes']['chars'] + cap['boxes']['fields']:
                        box_total += 1
                        box_good += any(overlaps(b, g) for g in gt_rects)

    text_items = sum(v['items'] for k, v in per_cat.items() if k != 'Faces')
    text_hidden = sum(v['hidden'] for k, v in per_cat.items() if k != 'Faces')
    result = {
        'layers_on': sorted(on), 'captures': captures,
        'per_category': {k: {**v, 'recall': round(100 * v['hidden'] / max(1, v['items']), 1)} for k, v in per_cat.items()},
        'text_pii_recall': round(100 * text_hidden / max(1, text_items), 1),
        'face_recall': round(100 * per_cat.get('Faces', {}).get('hidden', 0) / max(1, per_cat.get('Faces', {}).get('items', 0)), 1),
        'captures_with_leak': leaks,
        'leaking_fields': leaked_fields,
        'leaking_vault_values': vault_leaks,
        'by_field': by_field,
        'not_scored_fields': unscored,
        'precision': round(100 * box_good / max(1, box_total), 1),
        'median_latency_ms': statistics.median(latencies) if latencies else None,
    }
    (out_dir / f'privacy_{args.tag}.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
