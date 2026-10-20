"""Host-only declaration transport/cache tests, using neutral synthetic fields."""
import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.fields = ['switch_a', 'colour_a']
        self.values = {'switch_a': False}
        self.stack = SimpleNamespace(PART_META={'part': {'shader': 'fixture:shader'}},
            panel_rows=lambda mat: [dict(rows=[dict(name=name) for name in self.fields])],
            panel_read=lambda mat: dict(values=self.values))
        self.material = dict(ruri_uber_part='part', ruri_uber_images={'image_a': object()})
        self.answer = dict(schema=1, state='ready', channels=[dict(kind='fixture_channel', label='测试通道',
            gate='switch_a', image='image_a', controls=['switch_a', 'colour_a'], full_panel=False)], manual=[])
        self.calls, self.draws = [], []
        def blob(dataset, payload):
            self.calls.append((dataset, json.loads(payload)))
            return json.dumps(self.answer).encode()
        self.bridge = SimpleNamespace(game_data_blob=blob)
        self.port = SimpleNamespace(BRIDGE=self.bridge)
        self.ns = dict(json=json, cabmap_state=self.port,
            material_panel=SimpleNamespace(stack_of=lambda m: {'stack': self.stack},
                draw_subset=lambda *args: self.draws.append(args)))
        path = ROOT/'Game/Endfield/Blender/weapon_channels.py'
        nodes = [n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n, (ast.FunctionDef, ast.Assign))]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), self.ns)

    def test_only_host_facts_cross_reader_seam(self):
        channels = self.ns['discover'](self.material)
        self.assertEqual(len(channels), 1)
        self.assertEqual(self.calls, [('endfield.material.channels', dict(schema=1,
            shader='fixture:shader', fields=['colour_a', 'switch_a'], images=['image_a']))])
        self.assertFalse(channels[0]['enabled'])
        self.values['switch_a'] = True
        self.assertTrue(self.ns['discover'](self.material)[0]['enabled'])
        self.assertEqual(len(self.calls), 1, 'live values change without reader round-trips')

    def test_declared_controls_are_passed_to_existing_host_drawer(self):
        self.ns['draw']('layout', self.material, 'fixture_channel')
        self.assertEqual(self.draws, [('layout', self.material, ['switch_a', 'colour_a'])])

    def test_reopen_offline_uses_saved_declaration_not_new_rules(self):
        self.ns['discover'](self.material)
        reopened = dict(self.material)
        self.port.BRIDGE = None
        self.assertEqual(self.ns['discover'](reopened, refresh=True)[0]['kind'], 'fixture_channel')
        self.assertTrue(reopened[self.ns['STATUS']].startswith('CACHED:'))
        self.assertEqual(len(self.calls), 1)

    def test_offline_unrecognized_and_changed_bindings_remain_unknown(self):
        self.port.BRIDGE = None
        self.assertEqual(self.ns['discover'](self.material), [])
        self.assertEqual(json.loads(self.material[self.ns['RECORD']])['answer']['state'], 'UNKNOWN')
        self.port.BRIDGE = self.bridge
        self.ns['discover'](self.material, refresh=True)
        self.port.BRIDGE = None
        self.material['ruri_uber_images'] = {}
        self.assertEqual(self.ns['discover'](self.material), [])

    def test_schema_live_field_and_duplicate_guards(self):
        original = copy.deepcopy(self.answer)
        variants = [dict(original, schema=2), dict(original, state='UNKNOWN'),
            dict(original, channels=original['channels']*2)]
        for change in (dict(controls=['missing']), dict(gate='missing'), dict(image='missing'), dict(full_panel=1)):
            variants.append(dict(original, channels=[dict(original['channels'][0], **change)]))
        for invalid in variants:
            with self.subTest(invalid=invalid):
                self.answer = invalid
                self.material.pop(self.ns['RECORD'], None)
                self.assertEqual(self.ns['discover'](self.material, refresh=True), [])

    def test_no_public_shader_or_channel_profiles(self):
        source = (ROOT/'Game/Endfield/Blender/weapon_channels.py').read_text(encoding='utf-8')
        for marker in ('PROFILES', 'HGRP/', '_UseEmission', '_ParallaxTex', '_EnableEmissiveMap', '_EmissionMap'):
            self.assertNotIn(marker, source)


if __name__ == '__main__':
    unittest.main()
