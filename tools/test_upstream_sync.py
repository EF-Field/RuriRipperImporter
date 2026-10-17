"""Merged upstream retarget flow and the fork's optional companions coexist."""
import ast
from contextlib import nullcontext
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from test_import_completion import functions

ROOT = Path(__file__).resolve().parents[1]


class MergeTests(unittest.TestCase):
    def setUp(self):
        package = ModuleType('MergeFixture')
        package.__path__ = []
        package.Game = NS(face_retarget_of=Mock(return_value=None))
        self.modules = patch.dict(sys.modules, {'MergeFixture': package})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.own = NS(key='own', bindings=['root/joint'])
        self.foreign = NS(key='foreign', bindings=['other/joint'])
        self.host = NS(rig_paths=Mock(return_value=['root/joint']),
                       rig_avatar=Mock(return_value='avatar'),
                       play=Mock(return_value=({'own': 'own-action'}, [])))
        self.ns = dict(__package__='MergeFixture.Kernel.app', FOREIGN_SHARE=.05,
                       host_port=NS(current=lambda: self.host),
                       statement=Mock(return_value=nullcontext(NS(clips=Mock(return_value=[self.own, self.foreign])))),
                       _carry=Mock(return_value=({'foreign': 'carried-action'}, [])),
                       _performance_listeners=[])
        self.api = functions('Kernel/app/loading.py', ['_split_by_binding', 'perform'], self.ns)

    def test_binding_boundary_and_empty_bindings_follow_upstream(self):
        boundary = NS(bindings=['root/joint'] + ['other/'+str(i) for i in range(19)])
        empty = NS(bindings=[])
        own, foreign = self.api._split_by_binding([self.own, self.foreign, boundary, empty], {'root/joint'})
        self.assertEqual(own, [self.own, boundary, empty])
        self.assertEqual(foreign, [self.foreign])

    def test_own_and_foreign_actions_keep_optional_companion_notification(self):
        callback = Mock()
        self.ns['_performance_listeners'].append(callback)
        count, notes = self.api.perform('context', ['opaque:clip'], 'target', activate=True)
        self.assertEqual((count, notes), (2, []))
        self.assertEqual(self.host.play.call_args.args[2], [self.own])
        self.assertFalse(self.ns['_carry'].call_args.args[-1])
        callback.assert_called_once_with('context', 'target', self.own, 'own-action', {})

    def test_foreign_only_activation_and_companion_opt_out(self):
        self.ns['statement'].return_value = nullcontext(NS(clips=lambda **kw: [self.foreign]))
        callback = Mock()
        self.ns['_performance_listeners'].append(callback)
        count, _ = self.api.perform(None, ['opaque:clip'], 'target', {'skip_companions': True}, activate=True)
        self.assertEqual(count, 1)
        self.host.play.assert_not_called()
        self.assertTrue(self.ns['_carry'].call_args.args[-1])
        callback.assert_not_called()

    def test_companion_error_keeps_successful_upstream_result(self):
        self.ns['_performance_listeners'].append(Mock(side_effect=ValueError('fixture companion')))
        count, notes = self.api.perform(None, ['opaque:clip'], 'target', activate=True)
        self.assertEqual(count, 2)
        self.assertEqual(notes, ['Companion note: fixture companion'])

    def test_upstream_stand_in_is_discarded_on_retarget_failure(self):
        class Retarget:
            pass
        host = Retarget()
        host.stand_in_rig = Mock(return_value='stand-in')
        host.rig_paths = Mock(return_value=['other/joint'])
        host.rig_avatar = Mock(return_value='source-avatar')
        host.play = Mock(return_value=({'foreign': 'source-action'}, []))
        host.retarget = Mock(side_effect=ValueError('fixture retarget'))
        host.discard_rig = Mock()
        ns = dict(host_port=NS(current=lambda: host, Retarget=Retarget),
                  kernel_statement=NS(source_host=Mock(return_value='opaque:source')),
                  statement=Mock(return_value=nullcontext(NS(skeletons={'source-rig': None}))))
        carry = functions('Kernel/app/loading.py', ['_carry'], ns)._carry
        self.foreign.archive = 'opaque:archive'
        stated = NS(clips=Mock(return_value=[self.foreign]))
        with self.assertRaisesRegex(ValueError, 'fixture retarget'):
            carry(None, stated, 'target', [self.foreign], {}, True)
        host.discard_rig.assert_called_once_with(None, 'stand-in')

    def test_materialisation_conflict_preserves_both_sides(self):
        tree = ast.parse((ROOT/'Host/Blender/materialise.py').read_text(encoding='utf-8'))
        names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
        for name in ('materialise_indexed', 'materialise_mesh_asset', 'build_rig'):
            self.assertEqual(names.count(name), 1)


if __name__ == '__main__':
    unittest.main()
