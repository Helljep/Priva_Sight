"""
planner.py - turns a sanitised page description into ONE next action.

Two backends behind the same interface:

* OllamaPlanner    - the real thing: a vision-language model (Qwen3-VL-2B,
                     optionally with the PrivaSight LoRA adapter) served by
                     Ollama. It sees the sanitised screenshot + element list.
* ScriptedPlanner  - a deterministic, no-GPU planner that follows a small
                     controlled-language goal ('log in then click "Transfer"').
                     It exists so the whole pipeline (extension, gate, server,
                     test sites) can be tested in CI and on machines without a
                     model. It is NOT an AI agent and is never presented as one.
"""
import json
import re
from typing import Optional

import httpx

from prompts import SYSTEM_PROMPT, build_user_prompt
from schemas import Action, PlanRequest, PlanResponse


# --------------------------------------------------------------------------- #
# Scripted planner
# --------------------------------------------------------------------------- #
_STEP_RE = re.compile(r'^(?P<verb>log in|click|type|select|expect|go to)\s*(?P<rest>.*)$', re.I)
_QUOTED = re.compile(r'"([^"]*)"')


def parse_goal(goal: str) -> list[dict]:
    """'log in then click "Transfer" then expect "Success"' -> list of atoms."""
    atoms: list[dict] = []
    for raw in re.split(r'\s+then\s+|;', goal):
        raw = raw.strip().rstrip('.')
        m = _STEP_RE.match(raw)
        if not m:
            continue
        verb, q = m.group('verb').lower(), _QUOTED.findall(m.group('rest'))
        if verb == 'log in':
            atoms += [{'op': 'type', 'value': '{USERNAME}', 'field': r'user|email|login|id'},
                      {'op': 'type', 'value': '{PASSWORD}', 'field': r'pass'},
                      {'op': 'click', 'target': r'log ?in|sign ?in|submit'}]
        elif verb in ('click', 'go to') and q:
            atoms.append({'op': 'click', 'target': re.escape(q[0])})
        elif verb == 'type' and len(q) >= 2:
            atoms.append({'op': 'type', 'value': q[0], 'field': re.escape(q[1])})
        elif verb == 'select' and len(q) >= 2:
            atoms.append({'op': 'select', 'value': q[0], 'field': re.escape(q[1])})
        elif verb == 'expect' and q:
            atoms.append({'op': 'expect', 'text': q[0]})
    return atoms


def _haystack(e: dict, keys) -> str:
    return ' '.join(str(e.get(k, '')) for k in keys).lower()


def _find(elements: list[dict], pattern: str, keys, tags=None) -> Optional[dict]:
    rx = re.compile(pattern, re.I)
    candidates = [e for e in elements if (tags is None or e.get('tag') in tags) and rx.search(_haystack(e, keys))]
    # prefer the shortest visible text (most specific match)
    candidates.sort(key=lambda e: len(_haystack(e, keys)))
    return candidates[0] if candidates else None


class ScriptedPlanner:
    name = 'scripted'

    def plan(self, req: PlanRequest) -> PlanResponse:
        atoms = parse_goal(req.goal)
        done_count = sum(1 for h in req.history if h.endswith(' ok'))
        # A scroll we inserted ourselves does not advance the script.
        done_count -= sum(1 for h in req.history if h.startswith('scroll') and h.endswith(' ok'))
        if done_count >= len(atoms):
            return self._resp(Action(type='done', answer='script complete'), 'all steps executed')
        atom = atoms[done_count]

        if atom['op'] == 'expect':
            page = ' '.join(req.visibleText) + ' ' + req.title
            if atom['text'].lower() in page.lower():
                return self._resp(Action(type='done', answer=f'found "{atom["text"]}"'), 'expected text is visible')
            return self._resp(Action(type='fail', reason=f'"{atom["text"]}" not visible'), 'expected text missing')

        if atom['op'] == 'click':
            el = _find(req.elements, atom['target'], ('text', 'label', 'value', 'placeholder'))
        else:
            el = _find(req.elements, atom['field'], ('label', 'placeholder', 'type'), tags=('input', 'textarea', 'select')) \
                or _find(req.elements, atom['field'], ('label', 'placeholder'))
            if el is None and atom['op'] == 'type':
                # fall back to the field's name-ish hints stored in 'label'/'type'
                el = _find(req.elements, atom['field'], ('label', 'placeholder', 'type', 'sensitive'))

        if el is None:
            last = req.history[-1] if req.history else ''
            if not last.startswith('scroll'):
                return self._resp(Action(type='scroll', direction='down'), 'target not on screen, scrolling')
            return self._resp(Action(type='fail', reason=f'could not find target for step {done_count + 1}'), 'not found')

        if atom['op'] == 'click':
            return self._resp(Action(type='click', id=el['id']), f'click #{el["id"]}')
        if atom['op'] == 'select':
            return self._resp(Action(type='select', id=el['id'], text=atom['value']), f'select in #{el["id"]}')
        return self._resp(Action(type='type', id=el['id'], text=atom['value']), f'type into #{el["id"]}')

    def _resp(self, action: Action, thought: str) -> PlanResponse:
        return PlanResponse(action=action, thought=thought, backend=self.name)


# --------------------------------------------------------------------------- #
# Ollama VLM planner
# --------------------------------------------------------------------------- #
class OllamaPlanner:
    name = 'ollama'

    def __init__(self, base_url='http://127.0.0.1:11434', model='qwen3-vl:2b', timeout=120.0):
        self.base_url, self.model, self.timeout = base_url.rstrip('/'), model, timeout

    def plan(self, req: PlanRequest) -> PlanResponse:
        user = {'role': 'user', 'content': build_user_prompt(req)}
        if req.screenshot:
            # Ollama wants raw base64 without the 'data:image/...;base64,' prefix.
            user['images'] = [req.screenshot.split(',', 1)[-1]]
        body = {
            'model': self.model,
            'messages': [{'role': 'system', 'content': SYSTEM_PROMPT}, user],
            'stream': False,
            # No 'format': 'json' here: the qwen3-vl "thinking" build reasons first and
            # returns empty content if it runs out of tokens, so we give it room (num_predict)
            # and pull the JSON object out of the reply ourselves (parse_model_json).
            'options': {'temperature': 0.0, 'num_predict': 2048},
        }
        last_err = ''
        for _ in range(2):  # one retry on malformed output
            r = httpx.post(f'{self.base_url}/api/chat', json=body, timeout=self.timeout)
            r.raise_for_status()
            content = r.json()['message']['content']
            try:
                data = parse_model_json(content)
                thought = str(data.pop('thought', ''))
                return PlanResponse(action=Action(**data), thought=thought, backend=f'ollama:{self.model}')
            except Exception as err:  # noqa: BLE001 - any parse/validation problem -> retry
                last_err = f'{err} | raw: {content[:160]!r}'
        return PlanResponse(action=Action(type='fail', reason=f'model gave invalid action: {last_err[:120]}'),
                            backend=f'ollama:{self.model}')


def parse_model_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (tolerates ```json fences)."""
    text = re.sub(r'^```(?:json)?|```$', '', text.strip(), flags=re.M).strip()
    start = text.find('{')
    if start < 0:
        raise ValueError('no JSON object in model output')
    # Small models often list several actions, one JSON object per line. We want ONE action
    # per step (the loop asks again after each), so decode only the first object.
    # Small models sometimes forget the quotes around a token: "text": {PASSWORD}  ->  "text": "{PASSWORD}"
    text = re.sub(r':\s*#(\d+)', r': \1', text)  # "id":#4 -> "id":4
    text = re.sub(r':\s*([{\[][A-Z_]+(?:_\d+)?[}\]])', r': "\1"', text)
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    # Small models write the element id as "3", "#3" or "[3]"; accept those as the number 3.
    if isinstance(obj.get('id'), str):
        digits = re.search(r'\d+', obj['id'])
        obj['id'] = int(digits.group()) if digits else None
    return obj


def make_planner(kind: str, **kw):
    if kind == 'ollama':
        return OllamaPlanner(**kw)
    return ScriptedPlanner()
