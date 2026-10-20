"""Neutral source declarations are consumed, not reinterpreted in public hosts."""
import ast
import contextlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.loads, self.builds = [], []
        self.mesh = type('MeshObject', (dict,), {})()
        def read(seeds, values):
            self.loads.append((seeds, values))
            return contextlib.nullcontext('source')
        def build(*args):
            self.builds.append(args)
            return self.mesh
        self.ns = dict(json=json, loading=SimpleNamespace(read=read),
            materialise=SimpleNamespace(materialise_mesh_asset=build), Matrix=SimpleNamespace(Identity=lambda n: 'identity'))
        source = ROOT/'Game/Endfield/Blender/weapon_effects.py'
        function = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef) and n.name == '_mesh_templates')
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), self.ns)
        self.template = dict(schema=1, state='ready', mesh='opaque:mesh', materials=['opaque:mat', 'opaque:mat'], seeds=['resource:A', 'resource:B'])
        self.item = dict(kind='opaque:not interpreted', path='root/anchor', name='fixture', parameters='{invalid raw JSON', mesh_template=json.dumps(self.template))
        self.anchor = object()
        self.nodes = [SimpleNamespace(index=9, path='root/anchor')]

    def run_template(self, item):
        return self.ns['_mesh_templates']('context', [item], self.nodes, {9: self.anchor}, {'host': True})

    def test_declared_resources_and_slot_order_are_used_exactly(self):
        self.assertEqual(self.run_template(self.item), 1)
        self.assertEqual(self.loads, [(['resource:A', 'resource:B'], {'host': True})])
        self.assertEqual(self.builds[0][2:4], ('opaque:mesh', ['opaque:mat', 'opaque:mat']))
        self.assertIs(self.mesh.parent, self.anchor)
        self.assertTrue(self.mesh['ruri_effect_source_template'])

    def test_unclaimed_source_row_is_skipped_without_raw_decoding(self):
        self.assertEqual(self.run_template(dict(self.item, mesh_template='')), 0)
        self.assertFalse(self.loads)

    def test_unknown_or_missing_declaration_fails_before_resource_acquisition(self):
        missing = dict(self.item);missing.pop('mesh_template')
        for item in (missing, dict(self.item, mesh_template=json.dumps(dict(self.template, state='UNKNOWN', reason='unresolved_source'))),
                     dict(self.item, mesh_template=json.dumps(dict(self.template, schema=2))),
                     dict(self.item, mesh_template=json.dumps(dict(self.template, seeds=[])))):
            with self.subTest(item=item), self.assertRaises(ValueError):
                self.run_template(item)
        self.assertFalse(self.loads)

    def test_missing_materialized_anchor_is_not_guessed(self):
        self.nodes = []
        with self.assertRaises(ValueError): self.run_template(self.item)
        self.assertFalse(self.loads)

    def test_public_executors_have_no_native_class_or_renderer_mode_rules(self):
        host = (ROOT/'Host/Blender/face_rig.py').read_text(encoding='utf-8')
        self.assertNotIn('SkMorphShaderParam', host)
        self.assertNotIn('blend_mode', host)
        effects = (ROOT/'Game/Endfield/Blender/weapon_effects.py').read_text(encoding='utf-8')
        for marker in ('render_mode', '_source_target', 'resource_seed'):
            self.assertNotIn(marker, effects)


if __name__ == '__main__':
    unittest.main()
