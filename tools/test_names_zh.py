"""Backend-owned labels pass through existing UI without public game-name data."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def functions(path, wanted, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / path), 'exec'), namespace)
    return namespace


class FakeTable:
    names = ['key', 'label', 'detail', 'group', 'kind', 'seed', 'shipped', 'original_label']
    titles = list(names)
    roles = [2, 1, 4, 8, 16, 128, 64, 0]

    def __init__(self):
        self.rows = [
            ['fixture_actor_a', '角色甲', 'fixture:path:1', 'Playable', 'Characters', 'fixture:seed:1', 1, 'fixture actor alpha'],
            ['fixture_actor_b', '角色乙', 'fixture:path:2', 'Playable', 'UI Models', 'fixture:seed:2', 1, 'fixture actor beta'],
            ['fixture_npc', 'npc original', 'fixture:path:3', 'NPC', 'NPCs', 'fixture:seed:3', 1, 'npc original'],
            ['fixture_future', 'Future', 'fixture:path:4', 'Playable', 'Characters', 'fixture:seed:4', 0, 'Future'],
        ]


class LabelTests(unittest.TestCase):
    def test_refresh_keeps_backend_table_without_reprojection(self):
        table = FakeTable()
        state, cache, calls = SimpleNamespace(language='', status=''), {}, []
        ns = functions('Game/Endfield/roster.py', {'_refresh'}, dict(
            state_of=lambda _: state, language=lambda _: 'en', _ROWS=cache,
            datasets=SimpleNamespace(cast=lambda lang: table), rebuild=lambda s: calls.append(s),
            BOUND=object(), cast_panel=SimpleNamespace(opened=lambda *_: None)))
        self.assertIsNone(ns['_refresh'](None, None))
        self.assertIs(cache['en'], table)
        self.assertEqual(calls, [state])

    def test_scan_displays_backend_label_without_changing_identity(self):
        path = ROOT / 'Game/Endfield/Blender/weapons.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'RURI_OT_scan_weapon_catalog')
        execute = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'execute')
        ns = dict(STATE='fixture', catalog_rows=lambda: [dict(
            asset='fixture_weapon', label='武器甲 · fixture_weapon', seed='fixture:exact-path', family='fixture', status='ready')])
        exec(compile(ast.Module(body=[execute], type_ignores=[]), str(path), 'exec'), ns)
        class Resources(list):
            def add(self):
                item = SimpleNamespace()
                self.append(item)
                return item
        state = SimpleNamespace(resources=Resources(), resource_index=7)
        operator = SimpleNamespace(report=lambda *_: None)
        self.assertEqual(ns['execute'](operator, SimpleNamespace(scene=SimpleNamespace(fixture=state))), {'FINISHED'})
        item = state.resources[0]
        self.assertEqual(item.name, '武器甲 · fixture_weapon')
        self.assertEqual((item.seed, item.family, item.status), ('fixture:exact-path', 'fixture', 'ready'))
        self.assertEqual(state.resource_index, -1)

    def test_public_source_has_no_name_snapshot_or_rule_module(self):
        self.assertFalse((ROOT / 'Game/Endfield/names_zh.py').exists())
        self.assertFalse((ROOT / 'Game/Endfield/names_zh.json').exists())
        for path in (ROOT / 'Game/Endfield').rglob('*.py'):
            self.assertNotIn('names_zh', path.read_text(encoding='utf-8'), str(path))


if __name__ == '__main__':
    unittest.main()
