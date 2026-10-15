"""Frontend-only names, provenance, and actual roster/weapon UI call contracts."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('names_zh', ROOT / 'Game/Endfield/names_zh.py')
names = importlib.util.module_from_spec(spec)
spec.loader.exec_module(names)


def functions(path, wanted, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / path), 'exec'), namespace)
    return namespace


class NameTests(unittest.TestCase):
    def test_snapshot_has_only_display_names_and_provenance(self):
        data = names._names()
        self.assertEqual(len(data['characters']), 35)
        self.assertEqual(len(data['weapons']), 84)
        self.assertEqual(len(data['source']['commit']), 40)
        for mapping in (data['characters'], data['weapons']):
            self.assertTrue(all(isinstance(v, str) and v and '\ufffd' not in v for v in mapping.values()))
        self.assertTrue(all(k.startswith('chr_') for k in data['characters']))
        self.assertTrue(all(k.startswith('wpn_') and not k.startswith('wpn_misc_') for k in data['weapons']))

    def test_user_named_characters_and_exact_tokens(self):
        for key in ('wulfa', 'chr_0028_wulfa', 'CHR_0028_WULFA_POSTMODEL.prefab',
                    'assets/chr_0028_wulfa_uimodel.prefab'):
            self.assertEqual(names.character_label(key, 'original'), '洛茜')
        self.assertEqual(names.character_label('typhoea'), '提弗洛斯')
        self.assertEqual(names.character_label('chr_0034_typhoea'), '提弗洛斯')

    def test_unknown_and_neighbouring_resources_keep_originals(self):
        for key in ('chr_9999_wulfa', 'npc_chr_0028_wulfa', 'prefix_wulfa', 'wulfa.001', ''):
            self.assertEqual(names.character_label(key, 'original'), 'original')
        for asset in ('wpn_misc_0051_01', 'wpn_sword_9999', 'wpn_sword_0003_extra', ''):
            self.assertEqual(names.weapon_label(asset), asset)

    def test_weapon_labels_include_technical_identity(self):
        self.assertEqual(names.weapon_label('wpn_sword_0003'), '塔尔11 · wpn_sword_0003')
        self.assertEqual(names.weapon_label('Gameplay\\Prefabs\\Weapons\\WPN_SWORD_0003.prefab'),
                         '塔尔11 · wpn_sword_0003')

    def test_model_paths_not_item_ids(self):
        self.assertEqual(names.weapon_label('wpn_funnel_0008'), '骑士精神 · wpn_funnel_0008')
        self.assertEqual(names.weapon_label('wpn_funnel_0010'), '爆破单元 · wpn_funnel_0010')


class FakeTable:
    names = ['key', 'label', 'detail', 'group', 'kind', 'seed', 'shipped']
    titles = list(names)
    roles = [2, 1, 4, 8, 16, 128, 64]

    def __init__(self):
        self.rows = [
            ['chr_0028_wulfa', 'chr 0028 wulfa', 'fixture:path:1', 'Playable', 'Characters', 'fixture:seed:1', 1],
            ['chr_0034_typhoea', 'chr 0034 typhoea', 'fixture:path:2', 'Playable', 'UI Models', 'fixture:seed:2', 1],
            ['chr_0028_wulfa', 'npc original', 'fixture:path:3', 'NPC', 'NPCs', 'fixture:seed:3', 1],
            ['chr_9999_future', 'Future', 'fixture:path:4', 'Playable', 'Characters', 'fixture:seed:4', 0],
        ]

    def __len__(self):
        return len(self.rows)

    def row(self, index):
        return dict(zip(self.names, self.rows[index]))

    def first_named(self, role):
        return next((name for name, carried in zip(self.names, self.roles) if carried & role), '')

    def kind(self, name):
        return 'real' if name == 'shipped' else 'text'


class RosterTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def publish(*args):
            self.calls.append(args)
            return args[0]
        self.namespace = functions('Game/Endfield/roster.py', {'_localized_table', '_refresh'}, dict(
            names_zh=names, app_view=SimpleNamespace(KEY=2, LABEL=1),
            CHARACTERS='Characters', UI_MODELS='UI Models', SPEC_KEY='Endfield:character',
            cabmap_state=SimpleNamespace(BRIDGE=SimpleNamespace(open_host_table=publish))))

    def test_projection_preserves_all_identity_columns_roles_and_source(self):
        table = FakeTable()
        before = copy.deepcopy(table.rows)
        self.assertEqual(self.namespace['_localized_table'](table), 'Endfield:character:zh-cn')
        handle, columns, rows, roles = self.calls[0]
        self.assertEqual(columns[-2:], ['shipped#|shipped', 'frontend_original_label|原始名称'])
        self.assertEqual(roles, table.roles + [0])
        self.assertEqual([r[1] for r in rows], ['洛茜', '提弗洛斯', 'npc original', 'Future'])
        for original, projected in zip(before, rows):
            self.assertEqual(projected[-1], original[1])
            for index in (0, 2, 3, 4, 5, 6):
                self.assertEqual(projected[index], original[index])
        self.assertEqual(table.rows, before)

    def test_missing_label_role_keeps_table(self):
        table = FakeTable()
        table.roles = [0] * len(table.names)
        self.assertIs(self.namespace['_localized_table'](table), table)
        self.assertFalse(self.calls)

    def test_refresh_caches_localized_handle_and_rebuilds(self):
        state = SimpleNamespace(language='', status='')
        refreshed = []
        cache = {}
        self.namespace.update(state_of=lambda _: state, language=lambda _: 'en',
                              datasets=SimpleNamespace(cast=lambda _: FakeTable()), _ROWS=cache,
                              rebuild=lambda s: refreshed.append(s), BOUND=object(),
                              cast_panel=SimpleNamespace(opened=lambda *_: None))
        self.assertIsNone(self.namespace['_refresh'](None, None))
        self.assertEqual(cache['en'], 'Endfield:character:zh-cn')
        self.assertEqual(refreshed, [state])


class WeaponTests(unittest.TestCase):
    def test_actual_catalog_scan_changes_label_only(self):
        path = ROOT / 'Game/Endfield/Blender/weapons.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'RURI_OT_scan_weapon_catalog')
        execute = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'execute')
        namespace = dict(names_zh=names, STATE='fixture', catalog_rows=lambda: [dict(
            asset='wpn_sword_0003', seed='fixture:exact-path', family='sword', status='ready')])
        exec(compile(ast.Module(body=[execute], type_ignores=[]), str(path), 'exec'), namespace)
        class Resources(list):
            def add(self):
                item = SimpleNamespace()
                self.append(item)
                return item
        state = SimpleNamespace(resources=Resources(), resource_index=7)
        operator = SimpleNamespace(report=lambda *_: None)
        self.assertEqual(namespace['execute'](operator, SimpleNamespace(scene=SimpleNamespace(fixture=state))), {'FINISHED'})
        item = state.resources[0]
        self.assertEqual(item.name, '塔尔11 · wpn_sword_0003')
        self.assertEqual((item.seed, item.family, item.status), ('fixture:exact-path', 'sword', 'ready'))
        self.assertEqual(state.resource_index, -1)

    def test_actual_ui_displays_chinese_and_internal_name(self):
        tree = ast.parse((ROOT / 'Game/Endfield/Blender/weapons.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'RURI_UL_equipment_resources')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'draw_item')
        namespace = {}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<weapon draw>', 'exec'), namespace)
        labels = []
        item = SimpleNamespace(name=names.weapon_label('wpn_sword_0003'), status='ready')
        layout = SimpleNamespace(label=lambda **kw: labels.append(kw))
        namespace['draw_item'](None, None, layout, None, item, 0, None, '')
        self.assertEqual(labels, [dict(text='塔尔11 · wpn_sword_0003', icon='MESH_DATA')])


if __name__ == '__main__':
    unittest.main()
