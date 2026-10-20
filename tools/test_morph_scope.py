"""Regression for pasted rig/character ids and stale scope on rig switches."""
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'morph_scope_test'
for name, path in ((PACKAGE, ROOT), (PACKAGE + '.Game.Endfield', ROOT / 'Game/Endfield')):
    package = ModuleType(name)
    package.__path__ = [str(path)]
    sys.modules[name] = package
host = importlib.import_module(PACKAGE + '.Kernel.host')
with patch.object(host, 'current', return_value=SimpleNamespace(capabilities=frozenset())):
    face = importlib.import_module(PACKAGE + '.Game.Endfield.face')
    morph = importlib.import_module(PACKAGE + '.Game.Endfield.morph_state')
    identity = importlib.import_module(PACKAGE + '.Game.Endfield.identity')


class MorphScope(unittest.TestCase):
    def setUp(self):
        morph.reset()
        face._TABLE['state'] = None
        self.avatar = SimpleNamespace(name='data_facemorph_avatar_typhoea', tag_id=943923360)
        morph.AVATARS.update(typhoea=self.avatar, other=SimpleNamespace(name='data_facemorph_avatar_pelica', tag_id=1))
        self.rows = [{'cab': 'cab-own', 'name': 'dialogue_typhoea_1', 'path': 'dialogue/own.asset', 'kind': 'dialogue'}]
        self.rows += [{'cab': 'cab-other-' + str(i), 'name': 'dialogue_other_' + str(i),
                       'path': 'dialogue/other.asset', 'kind': 'dialogue'} for i in range(250)]

    def scan(self, token, previous_rig='chr_0034_typhoea_postmodel'):
        state = SimpleNamespace(character_token=token, armature_name=previous_rig, face_morph='',
                                status='', library_ready=True, items=[], drivers=[])
        current = SimpleNamespace(name='chr_0034_typhoea_postmodel')
        with patch.object(face, 'state_of', return_value=state), \
             patch.object(host, 'selected_rig', return_value=current), \
             patch.object(identity, 'declared_face_morph', return_value=''), \
             patch.object(identity, 'npc_template', return_value=''), \
             patch.object(morph.datasets, 'morph_library', return_value=self.rows), \
             patch.object(face, 'retable'), \
             patch.object(face, '_bindings', return_value={'ctrls': {}}):
            self.assertIsNone(face._scan(object(), {}))
        return state

    def test_scan_normalizes_user_pasted_full_rig_name(self):
        state = self.scan('chr_0034_typhoea_postmodel')
        self.assertEqual(state.character_token, 'typhoea')
        self.assertEqual(morph.CHARACTER_TOKEN, 'typhoea')
        entries, _ = morph.plan_load()
        self.assertEqual([e['cab'] for e in entries], ['cab-own'])

    def test_avatar_lookup_accepts_character_id_and_blender_suffix(self):
        for value in ('typhoea', 'chr_0034_typhoea', 'chr_0034_typhoea_postmodel.001'):
            self.assertEqual(morph.avatars_for(value), [self.avatar], value)

    def test_different_rig_does_not_inherit_previous_character_scope(self):
        state = self.scan('pelica', previous_rig='chr_0004_pelica_postmodel')
        self.assertEqual(state.character_token, 'typhoea')

    def test_unknown_scope_does_not_select_an_unrelated_single_avatar(self):
        morph.AVATARS.clear()
        morph.AVATARS['other'] = SimpleNamespace(name='data_facemorph_avatar_pelica')
        self.assertEqual(morph.avatars_for('missing_character'), [])

    def test_normalization_preserves_npc_templates_and_custom_tokens(self):
        normalize = identity.morph_scope
        self.assertEqual(normalize('npc_chr_0034_typhoea_01'), 'npc_chr_0034_typhoea_01')
        self.assertEqual(normalize('npc_spl_adaxier_01'), 'npc_spl_adaxier_01')
        self.assertEqual(normalize('custom_token'), 'custom_token')
        self.assertEqual(normalize('chr_0123_name_with_parts_uimodel.002'), 'name_with_parts')
        self.assertEqual(normalize('  TYPHOEA  '), 'typhoea')

    def test_loading_new_family_preserves_dynamic_enum_tab_identity(self):
        class State:
            def __init__(self):
                self.sections = ['cfg', 'emotion', 'pose']
                self.index = 1
                self.armature_name = 'rig'
                self.status = ''
                self.library_ready = True
            @property
            def section(self):
                return self.sections[self.index]
            @section.setter
            def section(self, value):
                self.index = self.sections.index(value)
        state = State()
        def load(_cabs):
            state.sections.insert(1, 'dialogue')
            return 1
        bindings = {'ctrls': {}, 'via': [], 'missing_bones': [], 'reason': ''}
        with patch.object(face, 'state_of', return_value=state), \
             patch.object(morph, 'plan_load', return_value=([{}], 0)), \
             patch.object(morph, 'cabs_for', return_value=['cab']), \
             patch.object(morph, 'load', side_effect=load), \
             patch.object(morph, 'all_ctrl_names', return_value=[]), \
             patch.object(face, 'retable'), \
             patch.object(face, 'avatars_for', return_value=[self.avatar]), \
             patch.object(face, '_bindings', return_value=bindings), \
             patch.object(face, '_section_items', side_effect=lambda _s, _c: [(k, k, '') for k in state.sections]), \
             patch.object(face, 'populate_items'), patch.object(face, 'populate_drivers'):
            sequence = face._load_library(object(), {})
            step = next(sequence)
            value = step.fn()
            self.assertEqual(state.section, 'dialogue')  # The actual index-shift repro.
            with self.assertRaises(StopIteration):
                sequence.send(value)
        self.assertEqual(state.section, 'emotion')


if __name__ == '__main__':
    unittest.main()
