"""Import notifications and Weapon selection, without Blender or a game reader."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


def functions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if len(nodes) != len(names):
        raise AssertionError('Missing functions: ' + str(set(names) - {n.name for n in nodes}))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, 'exec'), namespace)
    return NS(**{name: namespace[name] for name in names})


class ImportCompletionTests(unittest.TestCase):
    def setUp(self):
        self.built = NS(imported=1, rig=NS(type='ARMATURE', seed='opaque:actor'), warnings=[])
        self.host = NS(materialise=Mock(return_value=self.built))
        self.namespace = dict(_import_listeners=[], host_port=NS(current=lambda: self.host),
                              texturing=NS(record=Mock()))
        self.loading = functions('Kernel/app/loading.py',
            ['register_import_listener', 'unregister_import_listener', 'place'], self.namespace)
        self.stated = NS(materials={})

    def test_success_delivers_result_and_copies_options(self):
        callback = Mock()
        self.loading.register_import_listener(callback)
        options = dict(source_game='fixture', source_panel='cast')
        result = self.loading.place('context', self.stated, options)
        self.assertIs(result, self.built)
        callback.assert_called_once_with('context', self.built, options)
        self.assertIsNot(callback.call_args.args[2], options)

    def test_failed_materialise_does_not_notify(self):
        callback = Mock()
        self.loading.register_import_listener(callback)
        self.host.materialise.side_effect = ValueError('fixture failure')
        with self.assertRaises(ValueError):
            self.loading.place(None, self.stated)
        callback.assert_not_called()

    def test_empty_result_does_not_notify(self):
        callback = Mock()
        self.loading.register_import_listener(callback)
        self.built.imported = 0
        self.loading.place(None, self.stated)
        callback.assert_not_called()

    def test_observer_failure_isolated_from_import_and_other_observers(self):
        self.loading.register_import_listener(Mock(side_effect=ValueError('fixture observer')))
        callback = Mock()
        self.loading.register_import_listener(callback)
        self.assertIs(self.loading.place(None, self.stated), self.built)
        callback.assert_called_once()
        self.assertIn('fixture observer', self.built.warnings[0])

    def test_listener_lifecycle_is_idempotent(self):
        callback = Mock()
        for _ in range(2):
            self.loading.register_import_listener(callback)
        self.loading.place(None, self.stated)
        callback.assert_called_once()
        for _ in range(2):
            self.loading.unregister_import_listener(callback)
        self.loading.place(None, self.stated)
        callback.assert_called_once()


class ActorSelectionTests(unittest.TestCase):
    def setUp(self):
        self.state = NS(actor=None, seed='', rows=['old slot'], index=5,
                        candidates=['old action'], candidate_index=3,
                        candidate_slot=7, candidate_seed='old:weapon', auto_sync=False)
        self.context = NS(scene=NS(fixture=self.state))
        self.callback = functions('Game/Endfield/Blender/weapons.py', ['on_import'],
            dict(STATE='fixture', roster=NS(STATE='cast'),
                 rig_identity=NS(seed_of=lambda rig: rig.seed))).on_import
        self.options = dict(source_game='Endfield', source_panel='cast')

    def notify(self, actor, options=None, imported=1):
        self.callback(self.context, NS(rig=actor, imported=imported),
                      self.options if options is None else options)

    def test_last_successful_character_selected_even_with_auto_sync_disabled(self):
        for seed in ('opaque:first', 'opaque:last'):
            actor = NS(type='ARMATURE', seed=seed)
            self.notify(actor)
            self.assertIs(self.state.actor, actor)
        self.assertEqual(self.state.seed, 'opaque:last')
        self.assertEqual((self.state.rows, self.state.candidates), ([], []))
        self.assertEqual((self.state.index, self.state.candidate_index,
                          self.state.candidate_slot, self.state.candidate_seed), (0, 0, -1, ''))

    def test_weapon_attachment_other_game_and_other_panels_do_not_steal_actor(self):
        original = NS(type='ARMATURE', seed='opaque:character')
        self.notify(original)
        for options in (dict(source_game='Endfield'),
                        dict(source_game='Endfield', source_panel='other'),
                        dict(source_game='OtherGame', source_panel='cast')):
            self.notify(NS(type='ARMATURE', seed='opaque:weapon'), options)
            self.assertIs(self.state.actor, original)

    def test_empty_or_non_rig_import_preserves_existing_selection(self):
        original = NS(type='ARMATURE', seed='opaque:character')
        self.notify(original)
        for actor, imported in ((None, 1), (NS(type='MESH'), 1),
                                (NS(type='ARMATURE', seed='failed'), 0)):
            self.notify(actor, imported=imported)
            self.assertIs(self.state.actor, original)

    def test_browser_passes_origin_as_metadata_not_seed_parsing(self):
        tree = ast.parse((ROOT / 'Kernel/app/browser.py').read_text(encoding='utf-8'))
        load = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_load_steps')
        self.assertTrue(any(isinstance(n, ast.Assign) and ast.unparse(n) == "options['source_panel'] = panel"
                            for n in ast.walk(load)))


if __name__ == '__main__':
    unittest.main()
