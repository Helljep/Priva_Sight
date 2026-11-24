"""
run_task_eval.py - can the agent still DO things on redacted screens, and does
anything leak while it does?

For each task YAML (32) x runs (default 3) it:
  1. starts a fresh browser tab at the task's start page for one persona,
  2. runs the real agent loop (extension) against the planner server,
  3. checks the site's own state to decide success,
  4. checks every request body sent to the planner for the persona's real values.

Conditions (choose with --condition):
  redacted  PrivaSight on (all layers + privacy gate)               <- the product
  unsafe    no redaction, gate bypassed (what a naive agent would do) <- baseline

Backends (choose with --backend):
  scripted  deterministic planner, no GPU: tests the PIPELINE (default)
  ollama    a real VLM via Ollama, e.g. --model qwen3-vl:2b

Usage:
  python eval/run_task_eval.py --condition redacted
  python eval/run_task_eval.py --condition unsafe --runs 1
  python eval/run_task_eval.py --backend ollama --model qwen3-vl:2b --limit 8
Output: eval/results/tasks_<backend>_<condition>.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, browser_with_extension, free_port, planner_server, static_server  # noqa: E402

PERSONAS = json.loads((ROOT / 'testbed/sites/data/personas.json').read_text(encoding='utf-8'))
LAYOUT = 1  # page layout (1-5); training data was recorded on layout 1 only
PII_FIELDS = ['aadhaar', 'pan', 'card', 'phone', 'email', 'address', 'dob', 'account', 'ifsc', 'name', 'password']
NEEDS_LOGIN = {'demobank', 'hr', 'hospital', 'mailbox', 'videomeet'}


def norm(s):
    return re.sub(r'[\s\-+]', '', str(s)).lower()


def do_login(page, base, site, pidx):
    me = PERSONAS[pidx]
    page.goto(f'{base}/{site}/login.html?p={pidx}&layout={LAYOUT}')
    page.wait_for_selector('body[data-ready]')
    page.fill('[name=username]', me['username'])
    page.fill('[name=password]', me['password'])
    page.click('button[type=submit]')
    page.wait_for_load_state()


def check_success(page, task, site):
    spec = task['success']
    state = page.evaluate('window.__state ? window.__state() : {}')
    if 'loggedIn' in spec:
        return bool((state.get('loggedIn') or {}).get(site))
    if 'page_text' in spec:
        return spec['page_text'].lower() in page.inner_text('body').lower()
    want = spec.get('data', {})
    for a in state.get('actions', []):
        if a['action'] == spec['action'] and all(str(a['data'].get(k)) == str(v) for k, v in want.items()):
            return True
    return False


def run_one(ctx, harness, base, server_url, task, pidx, condition, max_steps, sft_dir=None):
    site, start = task['site'], task['start']
    page = ctx.new_page()
    page.bring_to_front()
    page.goto(f'{base}/{site}/login.html?p={pidx}&layout={LAYOUT}')
    page.evaluate('window.__reset && window.__reset()')
    if start != 'login' and site in NEEDS_LOGIN:
        do_login(page, base, site, pidx)
    page.goto(f'{base}/{site}/{start}.html?p={pidx}&layout={LAYOUT}')
    page.wait_for_selector('body[data-ready]')
    me = PERSONAS[pidx]
    secrets = {'{USERNAME}': me['username'], '{PASSWORD}': me['password']}
    unsafe = condition == 'unsafe'
    run = harness.evaluate('(a) => window.runTask(a)', {
        'urlPrefix': f'{base}/{site}/{start}.html', 'goal': task['goal'], 'secrets': secrets,
        'layers': {k: False for k in ['dom', 'regex', 'ner', 'faces', 'ocr']} if unsafe else {},
        'serverUrl': server_url, 'maxSteps': max_steps, 'unsafeBaseline': unsafe,
    })
    page.wait_for_timeout(300)
    ok = check_success(page, task, site)
    bodies = norm(' '.join(run['sentBodies']))
    # In the unsafe condition the screenshot is also unredacted, so the text leak count is a lower bound.
    leaked = sorted({f for f in PII_FIELDS if len(str(me[f])) >= 4 and norm(me[f]) in bodies})
    page.close()
    if sft_dir and ok:
        record_sft(sft_dir, task, pidx, run)
    return {'task': task['id'], 'persona': pidx, 'success': ok, 'status': run['result']['status'],
            'steps': run['result']['steps'], 'leak': bool(leaked), 'leaked_fields': leaked,
            'blocked': run['result']['status'] == 'blocked', 'reason': run['result'].get('reason', '')}


def record_sft(folder, task, pidx, run):
    """Save each step of a SUCCESSFUL redacted run as a training sample:
    the sanitised screenshot + the exact prompt the model saw -> the action taken."""
    import base64
    sys.path.insert(0, str(ROOT / 'server'))
    from prompts import build_user_prompt
    from schemas import PlanRequest
    out = Path(folder)
    (out / 'images').mkdir(parents=True, exist_ok=True)
    actions = [e for e in run['events'] if e['type'] == 'action']
    with (out / 'sft.jsonl').open('a', encoding='utf-8') as f:
        for i, (body, ev) in enumerate(zip(run['sentBodies'], actions)):
            req = json.loads(body)
            img = f"images/{task['id']}_l{LAYOUT}_p{pidx}_{i}.jpg"  # layout in the name so layouts never overwrite each other
            (out / img).write_bytes(base64.b64decode(req['screenshot'].split(',', 1)[1]))
            action = {k: v for k, v in ev['action'].items() if v is not None and v is not False}
            answer = json.dumps({**action, 'thought': ev.get('thought', '')}, ensure_ascii=False)
            f.write(json.dumps({'image': img, 'prompt': build_user_prompt(PlanRequest(**req)), 'answer': answer}, ensure_ascii=False) + '\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--condition', choices=['redacted', 'unsafe'], default='redacted')
    ap.add_argument('--backend', choices=['scripted', 'ollama'], default='scripted')
    ap.add_argument('--model', default='qwen3-vl:2b')
    ap.add_argument('--runs', type=int, default=3)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--max-steps', type=int, default=12)
    ap.add_argument('--headed', action='store_true')
    ap.add_argument('--layout', type=int, default=1, help='page layout 1-5 (use 2-5 to record held-out data)')
    ap.add_argument('--persona-offset', type=int, default=0, help='shift persona choice (held-out personas)')
    ap.add_argument('--record-sft', default='', help='folder to write SFT training samples from successful runs')
    args = ap.parse_args()
    global LAYOUT
    LAYOUT = args.layout

    tasks = [yaml.safe_load(p.read_text(encoding='utf-8')) for p in sorted((ROOT / 'testbed/tasks').glob('*.yaml'))]
    if args.limit:
        tasks = tasks[:args.limit]
    results = []
    env = {'OLLAMA_MODEL': args.model} if args.backend == 'ollama' else {}
    if args.condition == 'unsafe':
        env['PRIVASIGHT_UNSAFE_NO_PII_CHECK'] = '1'  # a naive server would not check either
    with static_server(free_port()) as base, planner_server(free_port(), args.backend, env) as server_url, \
            browser_with_extension(headless=not args.headed) as (ctx, harness):
        for task in tasks:
            for r in range(args.runs):
                pidx = (r * 17 + 3 + args.persona_offset) % len(PERSONAS)
                res = run_one(ctx, harness, base, server_url, task, pidx, args.condition, args.max_steps, args.record_sft or None)
                results.append(res)
                print(f"{task['id']:28s} p{pidx:<2d} {'OK  ' if res['success'] else 'FAIL'} {res['status']:9s} leak={res['leak']}", flush=True)

    n = len(results)
    summary = {
        'backend': args.backend, 'model': args.model if args.backend == 'ollama' else None, 'condition': args.condition,
        'runs': n,
        'task_success_pct': round(100 * sum(r['success'] for r in results) / max(1, n), 1),
        'runs_with_leak': sum(r['leak'] for r in results),
        'runs_blocked_by_gate': sum(r['blocked'] for r in results),
        'results': results,
    }
    out = Path(__file__).parent / 'results'
    out.mkdir(exist_ok=True)
    (out / f'tasks_{args.backend}_{args.condition}.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'results'}, indent=2))


if __name__ == '__main__':
    main()
