"""Host-free checks for the generated JSON/runtime/library package contract."""
import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ShaderManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifests = sorted((ROOT / 'Game').glob('*/shader/Blender/RuriManifest.json'))
        self.assertTrue(self.manifests)

    def test_every_blender_runtime_has_external_manifest(self):
        runtimes = set((ROOT / 'Game').glob('*/shader/Blender/__init__.py'))
        self.assertEqual(runtimes, {p.with_name('__init__.py') for p in self.manifests})
        for path in self.manifests:
            with self.subTest(path=path):
                source = path.with_name('__init__.py').read_text(encoding='utf-8')
                ast.parse(source)
                self.assertIn("json.load(manifest_stream)['stacks']", source)
                self.assertNotIn("MANIFESTS = json.loads(", source)

    def test_library_paths_and_stack_identities(self):
        identities = set()
        for path in self.manifests:
            data = json.loads(path.read_text(encoding='utf-8'))
            self.assertIsInstance(data['pipeline'], dict)
            self.assertTrue(data['stacks'])
            for stack in data['stacks']:
                with self.subTest(path=path, stack=stack['names']['panel_key']):
                    key = stack['names']['panel_key']
                    self.assertNotIn(key, identities)
                    identities.add(key)
                    library = stack['blend']
                    self.assertEqual(Path(library).name, library)
                    self.assertTrue(path.with_name(library).is_file())
                    self.assertEqual(stack['kernel'], 'rvg1')
                    self.assertTrue(stack['group_names'])
                    self.assertEqual(len(stack['group_names']), len(set(stack['group_names'])))

    def test_runtime_and_stacks_share_stamp(self):
        for path in self.manifests:
            source = path.with_name('__init__.py').read_text(encoding='utf-8')
            stacks = json.loads(path.read_text(encoding='utf-8'))['stacks']
            stamps = {stack['stamp'] for stack in stacks}
            self.assertEqual(len(stamps), 1, str(path))
            self.assertIn('stamp(' + stamps.pop() + ')', ast.get_docstring(ast.parse(source)))

    def test_vertex_capabilities_have_host_builders(self):
        for path in self.manifests:
            module = ast.parse(path.with_name('__init__.py').read_text(encoding='utf-8'))
            builders = next(node.value for node in module.body if isinstance(node, ast.Assign)
                            and any(isinstance(t, ast.Name) and t.id == 'CAP_VERTEX_BUILDERS'
                                    for t in node.targets))
            capabilities = {ast.literal_eval(key) for key in builders.keys}
            for stack in json.loads(path.read_text(encoding='utf-8'))['stacks']:
                for part, answers in stack.get('vertex_host_answers', {}).items():
                    self.assertIn(part, stack['vertex_parts'])
                    for answer in answers:
                        self.assertIn(answer['cap'], capabilities)
                        self.assertTrue(answer['sock'])
                        self.assertTrue(answer['results'])


if __name__ == '__main__':
    unittest.main()
