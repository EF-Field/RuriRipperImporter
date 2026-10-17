"""Host-free weapon resource projection, invalidation and shared-import contracts."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'Game/Endfield/weapon_catalog.py'
TREE = ast.parse(SOURCE.read_text(encoding='utf-8'))


def functions(*names, **namespace):
    body = [n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=body, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return SimpleNamespace(**namespace)


class CatalogContract(unittest.TestCase):
    def test_projection_keeps_source_identity_and_blocks_ambiguous_load(self):
        f = functions('project', FAMILIES={'misc': '道具'})
        rows = [dict(seed='exact:' + status, asset='wpn_misc_1', label='后端名称 · wpn_misc_1', family='misc',
                     status=status, routes=routes, basis='exact_prefab_container_route')
                for status, routes in [('ready', 1), ('ambiguous_prefab', 2)]]
        result = f.project(rows)
        self.assertEqual(result[0][:5], ['exact:ready', '后端名称 · wpn_misc_1', 'wpn_misc_1', '道具', 'misc'])
        self.assertEqual(result[0][6], 'exact:ready')
        self.assertEqual(result[1][0], 'exact:ambiguous_prefab')
        self.assertEqual(result[1][6], '')
        self.assertEqual(result[1][8], 2)
        rows[0]['family'] = 'unknown'
        self.assertEqual(f.project(rows)[0][3], 'unknown')

    def test_source_identity_includes_map_and_install(self):
        bridge = SimpleNamespace(_map='map:1')
        state = SimpleNamespace(current_tab='install:A', loaded=True)
        f = functions('source_of', cabmap_state=SimpleNamespace(BRIDGE=bridge),
                      browser=SimpleNamespace(state_of=lambda ctx: state))
        original = f.source_of(None)
        bridge._map = 'map:2'
        self.assertNotEqual(original, f.source_of(None))
        bridge._map = 'map:1'
        state.current_tab = 'install:B'
        self.assertNotEqual(original, f.source_of(None))

    def test_catalog_requires_loaded_matching_source(self):
        state = SimpleNamespace(loaded=True)
        source = ['original']
        ns = dict(_TABLE=object(), _SOURCE='original', source_of=lambda ctx: source[0],
                  browser=SimpleNamespace(state_of=lambda ctx: state))
        f = functions('current', **ns)
        self.assertTrue(f.current(None))
        source[0] = 'different'
        self.assertFalse(f.current(None))
        source[0] = 'original'
        state.loaded = False
        self.assertFalse(f.current(None))

    def test_plain_shared_load_no_character_or_mount_dependency(self):
        draw = ast.unparse(next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'draw'))
        for call in ('app_view.draw_head', 'app_view.draw_list', 'browser.draw_import_options',
                     'cast_panel.draw_row_verbs'):
            self.assertIn(call, draw)
        self.assertNotIn('actor', draw)
        self.assertNotIn('attach(', draw)
        self.assertFalse(any('bpy' in ast.unparse(n) for n in TREE.body
                             if isinstance(n, (ast.Import, ast.ImportFrom))))
        self.assertIn("if not current(context):", draw)


if __name__ == '__main__':
    unittest.main()
