"""Public host consumes private plans; stale UI rows never replace source rules."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def functions(*wanted, **namespace):
    path = ROOT / 'Game/Endfield/Blender/weapons.py'
    nodes = [n for n in ast.parse(path.read_text(encoding='utf-8')).body
             if isinstance(n, ast.FunctionDef) and n.name in wanted]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.actor = {'choice': '{"7":"old","7":"duplicate"}'}
        self.plan = [dict(slot=7, mode='fight', seed='backend:authoritative', equipment='{"7":"backend:choice"}')]
        def read(dataset, **args):
            self.calls.append((dataset, args))
            return self.plan
        self.ns = functions('_request', 'rows_for', 'assembly_for',
            SELECTIONS='choice', rig_identity=SimpleNamespace(seed_of=lambda actor: 'source:actor'),
            cabmap_state=SimpleNamespace(BRIDGE=object()),
            weapon_contract=SimpleNamespace(slot_number=int),
            datasets=SimpleNamespace(WEAPONS='slots', WEAPON_ASSEMBLY='plan', _rows=read))

    def test_opaque_saved_choices_forwarded_without_json_reparse(self):
        result = self.ns['assembly_for'](self.actor, dict(slot=7, mode='fight', seed='stale:UI'), 'selected:explicit')
        self.assertIs(result, self.plan)
        self.assertEqual(self.calls, [('plan', dict(seed='source:actor', equipment=self.actor['choice'],
            slot=7, mode='fight', selection='selected:explicit'))])
        self.assertEqual(result[-1]['seed'], 'backend:authoritative')

    def test_plan_protocol_guard(self):
        for plan in ([], [dict(slot=8, mode='fight')], [dict(slot=7, mode='idle')]):
            self.plan = plan
            with self.assertRaises(ValueError):
                self.ns['assembly_for'](self.actor, dict(slot=7, mode='fight'))

    def test_equipment_commits_only_after_successful_host_execution(self):
        state = SimpleNamespace(mode='fight', candidates=[], candidate_seed='old', rows=[SimpleNamespace(slot=7)])
        actor = type('Actor', (dict,), {'is_editable': True})(choice='old')
        actor['unrelated'] = 'preserved'
        rows = [dict(slot=7, mode='fight')]
        ns = functions('equip_selected', STATE='fixture', SELECTIONS='choice',
            assembly_for=lambda *a: self.plan, rows_for=lambda *a: rows,
            populate_slots=lambda *a: None)
        context = SimpleNamespace(scene=SimpleNamespace(fixture=state))
        def fail(*a, **kw):
            raise ValueError('host import failed')
        ns['attach'] = fail
        with self.assertRaises(ValueError):
            ns['equip_selected'](context, actor, 7, 'new')
        self.assertEqual(actor['choice'], 'old')
        ns['attach'] = lambda *a, **kw: ('socket', True)
        self.assertEqual(ns['equip_selected'](context, actor, 7, 'new'), ('socket', True))
        self.assertEqual(actor['choice'], '{"7":"backend:choice"}')
        self.assertEqual(actor['unrelated'], 'preserved')


if __name__ == '__main__':
    unittest.main()
