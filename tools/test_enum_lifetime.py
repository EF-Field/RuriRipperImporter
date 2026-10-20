"""Host-free regression of the actual RNA callback's borrowed-string lifetime."""
import ast
import gc
from pathlib import Path
from types import SimpleNamespace
import unittest
import weakref

SOURCE = Path(__file__).resolve().parents[1] / 'Host/Blender/rna.py'


def implementation():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    names = {'_enum_items', '_enum_history', '_cache_enum_items', '_enum_callback'}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names
             or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in n.targets)]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace


class EnumLifetime(unittest.TestCase):
    def setUp(self):
        self.module = implementation()

    def callback(self, handler):
        return self.module['_enum_callback'](SimpleNamespace(name='Character'), SimpleNamespace(key='section'), handler)

    def test_identical_refreshes_reuse_the_exact_returned_list_and_strings(self):
        def fresh(_state, _context):
            return [('dialogue', ''.join(('Dia', 'logue')), ''.join(('The cabmap ', 'description')))]
        callback = self.callback(fresh)
        first = callback(None, None)
        for _ in range(1000):
            current = callback(None, None)
            self.assertIs(current, first)
            self.assertIs(current[0][1], first[0][1])

    def test_outgoing_catalog_strings_stay_alive_after_catalog_changes(self):
        class Text(str):
            pass
        rows = [('dialogue', Text('Dialogue'), Text('Description'))]
        callback = self.callback(lambda _s, _c: rows)
        result = callback(None, None)
        label = weakref.ref(result[0][1])
        rows = [('pose', 'Poses', 'Other description')]
        callback(None, None)
        del result
        gc.collect()
        self.assertIsNotNone(label())

    def test_returning_to_a_catalog_reuses_its_original_storage(self):
        rows = [('emotion', 'Emotions', '')]
        callback = self.callback(lambda _s, _c: rows)
        first = callback(None, None)
        rows = [('emotion', 'Emotions', ''), ('pose', 'Poses', '')]
        callback(None, None)
        rows = [('emotion', 'Emotions', '')]
        self.assertIs(callback(None, None), first)

    def test_explicit_item_numbers_and_empty_catalog_are_preserved(self):
        callback = self.callback(lambda _s, _c: [('emotion', 'Emotions', 'Help', 'NONE', 7)])
        self.assertEqual(callback(None, None), [('emotion', 'Emotions', 'Help', 'NONE', 7)])
        empty = self.callback(lambda _s, _c: [])
        self.assertEqual(empty(None, None), [('', '', '')])


if __name__ == '__main__':
    unittest.main()
