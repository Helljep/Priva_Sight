"""Server tests. Run from the PrivaSight folder:  python server/tests/test_server.py"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'server'))

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from pii import find_pii, is_aadhaar, scan_payload  # noqa: E402
from planner import ScriptedPlanner, parse_goal, parse_model_json  # noqa: E402
from schemas import PlanRequest  # noqa: E402

client = TestClient(app)
VECTORS = json.loads((ROOT / 'tests' / 'vectors.json').read_text(encoding='utf-8'))
STRUCTURED = {'AADHAAR', 'CARD', 'PAN', 'EMAIL', 'PHONE', 'IFSC'}


class PiiTests(unittest.TestCase):
    def test_shared_vectors_match_javascript(self):
        # Server only does the structured types (no labelled/context types, no names).
        for v in VECTORS:
            expected = sorted(t for t in v['types'] if t in STRUCTURED)
            got = sorted(h['type'] for h in find_pii(v['text']))
            self.assertEqual(got, expected, v['text'])

    def test_aadhaar(self):
        self.assertTrue(is_aadhaar('3417 0753 6454'))
        self.assertFalse(is_aadhaar('3417 0753 6455'))

    def test_tokens_are_not_flagged(self):
        self.assertEqual(find_pii('type [PHONE_1] and {PASSWORD} for [EMAIL_1]'), [])

    def test_screenshot_is_not_scanned_as_text(self):
        self.assertEqual(scan_payload({'screenshot': 'data:image/jpeg;base64,' + '4111111111111111' * 5}), [])


class PlannerTests(unittest.TestCase):
    def test_parse_goal_expands_login(self):
        atoms = parse_goal('log in then click "Transfer" then expect "Fund"')
        self.assertEqual([a['op'] for a in atoms], ['type', 'type', 'click', 'click', 'expect'])

    def test_scripted_logs_in_with_tokens_only(self):
        els = [{'id': 0, 'tag': 'input', 'label': 'Username'},
               {'id': 1, 'tag': 'input', 'type': 'password', 'label': 'Password'},
               {'id': 2, 'tag': 'button', 'text': 'Log in'}]
        p = ScriptedPlanner()
        a = p.plan(PlanRequest(goal='log in', elements=els)).action
        self.assertEqual((a.type, a.id, a.text), ('type', 0, '{USERNAME}'))
        a = p.plan(PlanRequest(goal='log in', elements=els, history=['type #0 "{USERNAME}" ok'])).action
        self.assertEqual((a.type, a.id, a.text), ('type', 1, '{PASSWORD}'))
        a = p.plan(PlanRequest(goal='log in', elements=els, history=['type #0 ok', 'type #1 ok'])).action
        self.assertEqual((a.type, a.id), ('click', 2))
        a = p.plan(PlanRequest(goal='log in', elements=els, history=['type #0 ok', 'type #1 ok', 'click #2 ok'])).action
        self.assertEqual(a.type, 'done')

    def test_model_json_parsing(self):
        self.assertEqual(parse_model_json('```json\n{"type":"wait"}\n```'), {'type': 'wait'})
        with self.assertRaises(ValueError):
            parse_model_json('no json here')


class ApiTests(unittest.TestCase):
    def test_health(self):
        self.assertTrue(client.get('/health').json()['ok'])

    def test_clean_payload_is_planned(self):
        body = {'goal': 'click "Go"', 'elements': [{'id': 3, 'tag': 'button', 'text': 'Go'}],
                'visibleText': ['Welcome [NAME_1]', 'Mobile [PHONE_1]']}
        r = client.post('/plan', json=body)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['action']['type'], 'click')

    def test_raw_pii_is_rejected_with_masked_findings(self):
        body = {'goal': 'x', 'visibleText': ['call +91 98450 12345 or mail a.b@example.test']}
        r = client.post('/plan', json=body)
        self.assertEqual(r.status_code, 422)
        text = r.text
        self.assertNotIn('98450 12345', text)
        self.assertNotIn('a.b@example.test', text)
        self.assertEqual({f['type'] for f in r.json()['detail']['findings']}, {'PHONE', 'EMAIL'})

    def test_pii_hidden_in_element_value_is_rejected(self):
        body = {'goal': 'x', 'elements': [{'id': 1, 'tag': 'input', 'value': '3417 0753 6454'}]}
        self.assertEqual(client.post('/plan', json=body).status_code, 422)


if __name__ == '__main__':
    unittest.main()
