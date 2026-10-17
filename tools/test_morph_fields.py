"""Host-free contract-2 import: preserve metadata without inventing targets."""
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'morph_fields_test'
for name, path in ((PACKAGE, ROOT), (PACKAGE + '.Game.Endfield', ROOT / 'Game/Endfield')):
    package = ModuleType(name)
    package.__path__ = [str(path)]
    sys.modules[name] = package
host = importlib.import_module(PACKAGE + '.Kernel.host')
with patch.object(host, 'current', return_value=SimpleNamespace(capabilities=frozenset())):
    face = importlib.import_module(PACKAGE + '.Game.Endfield.face')
    morph = importlib.import_module(PACKAGE + '.Game.Endfield.morph_state')
    datasets = importlib.import_module(PACKAGE + '.Game.Endfield.datasets')


class MorphFields(unittest.TestCase):
    def setUp(self):
        morph.reset()

    def test_settings_keep_primitive_type_and_exact_integers(self):
        rows = [{'asset': 'emotion', 'field': '_blinkInterval', 'type': 'Single', 'value': '3'},
                {'asset': 'emotion', 'field': '_enabled', 'type': 'Bool', 'value': 'false'},
                {'asset': 'emotion', 'field': '_tag.tagId', 'type': 'ULong', 'value': '18446744073709551615'}]
        with patch.object(datasets, '_rows', return_value=rows):
            parsed = datasets.morph_settings(['cab'])
        self.assertEqual([r['value'] for r in parsed], [3.0, False, 18446744073709551615])
        self.assertEqual([r['type'] for r in parsed], ['Single', 'Bool', 'ULong'])

    def test_invalid_setting_is_not_silently_coerced(self):
        for kind, value in [('Single', 'nan'), ('Bool', '1'), ('Complex', '0')]:
            with patch.object(datasets, '_rows', return_value=[{'asset': 'a', 'field': 'f', 'type': kind, 'value': value}]):
                with self.assertRaises(ValueError):
                    datasets.morph_settings(['cab'])

    def test_old_runtime_reports_the_paired_contract_requirement(self):
        with patch.object(datasets, '_rows', return_value=[{'name': 'avatar', 'tagId': 1}]):
            with self.assertRaisesRegex(ValueError, 'contract 2'):
                datasets.morph_avatars(['cab'])

    def test_asset_settings_are_imported_not_discarded(self):
        rows = [{'asset': 'emotion', 'field': '_blinkInterval', 'type': 'Single', 'value': 3.0},
                {'asset': 'emotion', 'field': '_phonemePoseLipsType', 'type': 'Int', 'value': 2}]
        with patch.multiple(datasets, morph_settings=lambda _: rows, morph_drivers=lambda _: [],
                            morph_flags=lambda _: [], morph_references=lambda _: [], morph_lipsync=lambda _: [],
                            morph_assets=lambda _: [{'name': 'emotion', 'kind': 'emotion', 'cab': 'cab', 'duration': 0}]):
            self.assertEqual(morph.load_assets(['cab']), 1)
            a = morph.ASSETS['emotion']
            self.assertEqual(a.settings, {'_blinkInterval': 3.0, '_phonemePoseLipsType': 2})
            self.assertEqual(a.setting_types['_phonemePoseLipsType'], 'Int')
            self.assertEqual(morph.load_assets(['cab']), 0)
            self.assertIs(morph.ASSETS['emotion'], a)

    def test_avatar_metadata_shape_map_and_shader_declarations_survive_repeat(self):
        avatar = {'name': 'data_facemorph_avatar_fixture', 'tag_id': 7, 'contract': 2,
                  'avatar': 'fixtureAvatar', 'avatar_file_id': 2, 'avatar_path_id': -9007199254740997,
                  'data_type': 0, 'disable_blink': True, 'use_special_params': True,
                  'bone_names': ['face', 'brow']}
        control = {'avatar': avatar['name'], 'ctrl': 'fixture_ctrl', 'bones': 0, 'id': 3,
                   'name_hash': 4294967295, 'tag_hash': 2147483648, 'part_type': 32,
                   'type': 'SkeletalMorphShaderPropMappingData', 'rid': -9007199254740999}
        shape = {'avatar': avatar['name'], 'ctrl': 'shape_ctrl', 'name_hash': 123, 'index': 1}
        shader = {'avatar': avatar['name'], 'ctrl': 'fixture_ctrl', 'param': '_Vector', 'default': .25,
                  'type': 'SkMorphShaderParamVector4', 'vector_index': 2, 'renderer_mask': 0xffffffff,
                  'blend_mode': 0, 'defaults': (0., 0., .25, 1.), 'declaration': 'FixtureShader__Vector', 'rid': 42}
        definition = dict(shader, name='FixtureShader__Vector', index=0)
        with patch.multiple(datasets, morph_avatars=lambda _: [avatar], morph_ctrls=lambda _: [control],
                            morph_bones=lambda _: [], morph_shader_params=lambda _: [shader],
                            morph_blend_shapes=lambda _: [shape], morph_shader_definitions=lambda _: [definition]):
            self.assertEqual(morph.load_avatars(['cab']), 1)
            a = morph.AVATARS[avatar['name']]
            self.assertEqual(a.avatar_path_id, avatar['avatar_path_id'])
            self.assertEqual(a.bone_names, ['face', 'brow'])
            self.assertTrue(a.disable_blink and a.use_special_params)
            self.assertEqual(a.control_metadata['fixture_ctrl']['rid'], control['rid'])
            self.assertEqual(a.blend_shapes['shape_ctrl']['index'], 1)
            self.assertEqual(a.shader_params['fixture_ctrl']['defaults'], shader['defaults'])
            self.assertEqual(len(a.shader_definitions), 1)
            self.assertEqual(morph.load_avatars(['cab']), 0)
            self.assertIs(morph.AVATARS[avatar['name']], a)
            self.assertEqual(len(a.shader_definitions), 1)

    def test_face_table_carries_non_bone_targets(self):
        skeletal = importlib.import_module(PACKAGE + '.Game.Endfield.skeletal_morph')
        avatar = skeletal.MorphAvatar('a', 'a', 7)
        avatar.blend_shapes['shape_ctrl'] = {'index': 0, 'name_hash': 123, 'mesh_pattern': '^fixture_role$', 'mesh_basis': 'fixture_declared'}
        avatar.shader_params['shader_ctrl'] = {'param': '_Value', 'default': .25, 'defaults': (.25, 0, 0, 0),
                                             'declaration': 'OpaqueSourceDeclaration', 'shader': 'FixtureShader',
                                             'value_kind': 'scalar', 'component_count': 1, 'component': 0,
                                             'renderer_mask': 0xffffffff, 'round_value': False, 'binding_state': 'ready'}
        with patch.object(face, 'avatars_for', return_value=[avatar]):
            table = face.face_table(object())
        self.assertEqual(table['shape_index_mappings'][0]['ctrl'], 'shape_ctrl')
        self.assertEqual(table['shape_index_mappings'][0]['mesh_pattern'], '^fixture_role$')
        self.assertEqual(table['shader_mappings'][0]['shader'], 'FixtureShader')
        self.assertEqual(table['shader_mappings'][0]['renderer_mask'], 0xffffffff)
        self.assertNotIn('attack_ctrl', table['deltas'])

    def test_old_target_projection_requires_matching_backend(self):
        for method in (datasets.morph_shader_params, datasets.morph_blend_shapes):
            with patch.object(datasets, '_rows', return_value=[{'avatar': 'fixture'}]):
                with self.assertRaisesRegex(ValueError, 'matching private backend'):
                    method(['cab'])


if __name__ == '__main__':
    unittest.main()
