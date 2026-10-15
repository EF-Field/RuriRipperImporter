"""Synthetic, host-free contract tests. Never opens a game, reader or Blender."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('weapon_contract', ROOT / 'Game/Endfield/weapon_contract.py')
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


def row(slot, **kw):
    return dict(dict(slot=slot, mode='fight', status='ready', seed='fixture:resource',
                     bone='mount', scale=1, visible=False, mount_kind='character'), **kw)


class EquipmentContractTests(unittest.TestCase):
    def test_no_implicit_equipment(self):
        self.assertEqual(contract.selections(), {})

    def test_selection_roundtrip_and_multiple_slots(self):
        choices = {'0': 'fixture:A', '42': 'fixture:B'}
        self.assertEqual(contract.selections(contract.selection_json(choices)), choices)

    def test_reject_invalid_selections(self):
        for text in ['[]', '{"0":"a","0":"b"}', '{"01":"a"}', '{"-1":"a"}',
                     '{"0":""}', '{"0":null}', '{"2147483648":"a"}', '{"٠":"a"}']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                contract.selections(text)

    def test_hidden_dependency_is_preserved_and_ordered(self):
        parent = row(18)
        child = row(5, bone='', mount_kind='weapon', target_slot=18, weapon_mount=100,
                    status='cross_weapon_mount', scale=.85)
        self.assertEqual(contract.attachment_order([child, parent], child), [parent, child])

    def test_context_required_never_becomes_a_default(self):
        equipment = row(7, seed='', status='equipment_required')
        with self.assertRaises(ValueError):
            contract.attachment_order([equipment], equipment)

    def test_cycle_missing_parent_duplicate_slot(self):
        a = row(3, mount_kind='weapon', target_slot=4, weapon_mount=1)
        b = row(4, mount_kind='weapon', target_slot=3, weapon_mount=1)
        for rows in ([a, b], [a], [a, a]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                contract.attachment_order(rows, a)

    def test_modes_are_independent(self):
        a = row(9)
        self.assertEqual(contract.attachment_order([row(9, mode='idle'), a], a), [a])

    def test_invalid_scale_and_slot(self):
        for scale in [0, -1, float('nan'), float('inf')]:
            with self.subTest(scale=scale), self.assertRaises(ValueError):
                contract.attachment_order([row(1, scale=scale)], row(1))
        for slot in [True, -1, 1.5, float('inf')]:
            with self.subTest(slot=slot), self.assertRaises(ValueError):
                contract.slot_number(slot)

    def test_mount_exact_path_and_component_ambiguity(self):
        identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        chain = [{'path': '', 'local': identity}, {'path': 'Root', 'local': identity},
                 {'path': 'Root/point', 'local': identity}]
        item = dict(key=2, path='Root/point', ancestry=json.dumps(chain), status='ready', basis='blender')
        self.assertEqual(contract.mount_ancestry([item], 2), chain)
        with self.assertRaises(ValueError):
            contract.mount_ancestry([item, item], 2)
        for change in [dict(path='wrong'), dict(basis='unity'), dict(status='unresolved_mount')]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                contract.mount_ancestry([dict(item, **change)], 2)


if __name__ == '__main__':
    unittest.main()
