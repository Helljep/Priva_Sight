"""
test_ner_model.py - sanity-check the fine-tuned name detector INSIDE the extension.

The ONNX file was exported with tracing warnings, so besides "does it find names" we check that it
behaves the same on very short and very long inputs (a traced graph can silently bake in one length).

Run:  python eval/test_ner_model.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import browser_with_extension  # noqa: E402

FILLER = 'Please review the quarterly statement and confirm the transaction details before the deadline. '
CASES = [  # (text, names that MUST be found, strings that must NOT be flagged)
    ('Rohan Sharma', ['Rohan Sharma'], []),
    ('Welcome back Ananya Iyer', ['Ananya Iyer'], ['Welcome']),
    ('Payee: Vikram Singh Rathore', ['Vikram Singh Rathore'], ['Payee']),
    (FILLER * 4 + 'Account holder is Meera Krishnamurthy and the branch is Indiranagar.', ['Meera Krishnamurthy'], ['Indiranagar']),
    (FILLER * 12 + 'Contact Arjun Nair for help.', ['Arjun Nair'], []),
    ('Transfer 500 INR to savings account', [], ['Transfer', 'INR', 'savings']),
    ('Dashboard Profile Settings Logout', [], ['Dashboard', 'Profile', 'Settings', 'Logout']),
]


def main():
    ok_all = True
    with browser_with_extension(headless=True) as (ctx, harness):
        harness.evaluate("import(chrome.runtime.getURL('src/pii/ner.js')).then(async m => { window.__ner = m; await m.initNER(); })")
        harness.wait_for_function('window.__ner !== undefined', timeout=60000)
        for text, must, must_not in CASES:
            found = harness.evaluate("async (t) => (await window.__ner.scanNames(t)).map(e => e.value)", text)
            miss = [m for m in must if not any(m in f or f in m for f in found)]
            false = [x for x in must_not if any(x == f for f in found)]
            ok = not miss and not false
            ok_all &= ok
            print(('PASS ' if ok else 'FAIL ') + f'len={len(text.split()):3d} words  found={found}' + (f'  missed={miss}' if miss else '') + (f'  false={false}' if false else ''))
    sys.exit(0 if ok_all else 1)


if __name__ == '__main__':
    main()
