"""Public CI checks for routing/removal, without Blender or game access."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WeaponUIContract(unittest.TestCase):
    def test_declared_tab_beside_character(self):
        module = ast.parse((ROOT / 'Game/Endfield/__init__.py').read_text(encoding='utf-8'))
        tabs = [node for node in ast.walk(module) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == 'GameTab']
        self.assertEqual([node.args[0].value for node in tabs], ['streamingscene', 'character', 'weapon'])
        weapon = tabs[-1]
        self.assertEqual(weapon.args[1].value, 'Weapon')
        self.assertFalse(next(k.value.value for k in weapon.keywords if k.arg == 'requires_index'))

    def test_no_independent_weapon_panels(self):
        for name, draw in [('weapons', 'draw_mount'), ('weapon_effects', 'draw_effects'), ('weapon_states', 'draw'),
                           ('weapon_glow', 'draw_glow')]:
            module = ast.parse((ROOT / f'Game/Endfield/Blender/{name}.py').read_text(encoding='utf-8'))
            self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == draw for n in module.body))
            self.assertFalse(any(isinstance(n, ast.ClassDef) and any(
                isinstance(base, ast.Attribute) and base.attr == 'Panel' for base in n.bases)
                for n in module.body))

    def test_compact_panes_and_host_seam(self):
        module = ast.parse((ROOT / 'Game/Endfield/weapon.py').read_text(encoding='utf-8'))
        panes = next(ast.literal_eval(node.value) for node in module.body if isinstance(node, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == 'PANES' for t in node.targets))
        self.assertEqual([one[0] for one in panes], ['catalog', 'states', 'mount', 'effects', 'glow'])
        self.assertEqual({one[0]: one[3] for one in panes},
                         dict(catalog=3, states=4, mount=0, effects=1, glow=2))
        self.assertFalse(any(isinstance(n, (ast.Import, ast.ImportFrom)) and
                             ('bpy' in ast.unparse(n)) for n in module.body))

    def test_retired_compatibility_is_not_packaged(self):
        self.assertFalse((ROOT / 'Game/Endfield/Blender/shader_compatibility.py').exists())
        self.assertFalse((ROOT / 'Game/Endfield/Blender/legacy52/runtime.py').exists())
        import package_addon
        self.assertFalse(any('/legacy52/' in path for path in package_addon.PUBLIC_SHADER_LIBRARIES))
        self.assertTrue(package_addon.included('docs/WEAPON-EQUIPMENT.md'))
        self.assertTrue((ROOT / 'Game/Endfield/shader/Blender/ruri_character_uber_endfield.blend').is_file())

    def test_compact_selection_icon_and_removed_mount_elements(self):
        module = ast.parse((ROOT / 'Game/Endfield/Blender/weapons.py').read_text(encoding='utf-8'))
        draw = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == 'draw_mount')
        calls = [n for n in ast.walk(draw) if isinstance(n, ast.Call)]
        select = next(n for n in calls if n.args and isinstance(n.args[0], ast.Constant)
                      and n.args[0].value == 'ruri.endfield_select_weapon_actor')
        self.assertEqual({k.arg: ast.literal_eval(k.value) for k in select.keywords},
                         dict(text='', icon='RESTRICT_SELECT_OFF'))
        text = ast.unparse(draw)
        for removed in ('catalog_search', '装备武器 · 由你选择', '隐藏槽位手动预览；技能切换与特效未接入'):
            self.assertNotIn(removed, text)
        self.assertIn('资源目录不推断专武归属或游戏装备限制', text)
        self.assertIn('仅唯一完整动作名匹配自动加载；其余留待选择', text)

    def test_retired_search_cannot_leave_an_invisible_catalog_filter(self):
        module = ast.parse((ROOT / 'Game/Endfield/Blender/weapons.py').read_text(encoding='utf-8'))
        self.assertNotIn('catalog_search', ast.unparse(module))
        ui = next(n for n in module.body if isinstance(n, ast.ClassDef)
                  and n.name == 'RURI_UL_equipment_resources')
        self.assertFalse(any(isinstance(n, ast.FunctionDef) and n.name == 'filter_items' for n in ui.body))


if __name__ == '__main__':
    unittest.main()
