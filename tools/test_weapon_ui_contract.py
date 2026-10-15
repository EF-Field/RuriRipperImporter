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
        for name, draw in [('weapons', 'draw_mount'), ('weapon_effects', 'draw_effects'),
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
        self.assertEqual([one[0] for one in panes], ['mount', 'effects', 'glow'])
        self.assertFalse(any(isinstance(n, (ast.Import, ast.ImportFrom)) and
                             ('bpy' in ast.unparse(n)) for n in module.body))

    def test_retired_compatibility_is_not_packaged(self):
        self.assertFalse((ROOT / 'Game/Endfield/Blender/shader_compatibility.py').exists())
        self.assertFalse((ROOT / 'Game/Endfield/Blender/legacy52/runtime.py').exists())
        import package_addon
        self.assertFalse(any('/legacy52/' in path for path in package_addon.PUBLIC_SHADER_LIBRARIES))
        self.assertTrue(package_addon.included('docs/WEAPON-EQUIPMENT.md'))
        self.assertTrue((ROOT / 'Game/Endfield/shader/Blender/ruri_character_uber_endfield.blend').is_file())


if __name__ == '__main__':
    unittest.main()
