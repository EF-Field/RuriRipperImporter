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
    def test_host_numeric_guard(self):
        for slot in [True, -1, 1.5, float('inf')]:
            with self.subTest(slot=slot), self.assertRaises(ValueError):
                contract.slot_number(slot)

    def test_domain_plan_and_selection_rules_live_in_backend(self):
        self.assertFalse(hasattr(contract, 'selections'))
        self.assertFalse(hasattr(contract, 'attachment_order'))

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
