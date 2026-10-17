"""Host-free contract checks; eligibility stays in the reader, not this host."""
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]

class Material(dict):
    name='Fixture material'

class CoverageContract(unittest.TestCase):
    def setUp(self):
        prefix='_coverage_fixture'
        modules={}
        for suffix in ('','Host','Host.Blender','Kernel','Kernel.bridge'):
            name=prefix+('.'+suffix if suffix else '')
            mod=ModuleType(name);mod.__path__=[];modules[name]=mod
        self.bridge=Mock()
        self.bridge.game_data_blob.return_value=b'{"schema":1,"state":"none","reason":"off"}'
        state=ModuleType(prefix+'.Kernel.bridge.cabmap_state');state.BRIDGE=self.bridge
        modules[state.__name__]=state
        self.finalizers=set()
        builder=ModuleType(prefix+'.Host.Blender.material_builder');builder.MATERIAL_FINALIZERS=self.finalizers
        modules[builder.__name__]=builder
        self.spec={'finals':{},'params':[]}
        stack=SimpleNamespace(m={'parts':{'Fixture':self.spec}})
        panel=ModuleType(prefix+'.Host.Blender.material_panel');panel.stack_of=lambda mat: {'stack':stack}
        modules[panel.__name__]=panel
        self.scope=patch.dict(sys.modules,modules);self.scope.start();self.addCleanup(self.scope.stop)
        spec=importlib.util.spec_from_file_location(prefix+'.Host.Blender.material_coverage',ROOT/'Host/Blender/material_coverage.py')
        self.mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.mod)
        self.mod.register_reader('FixtureGame','fixture.material.coverage')
        self.mat=Material(ruri_uber_part='Fixture')
        self.props=SimpleNamespace(shader_name='Fixture/Shader',keywords=['SOURCE_ON'],
            floats={'inspector_toggle':0},colors={},textures={},disabled_passes=[],shader_passes=[])

    def test_source_facts_cross_without_host_inference(self):
        self.mod.capture(self.mat,self.props,{'source_game':'FixtureGame'})
        call=self.bridge.game_data_blob.call_args
        self.assertEqual(call.args,('fixture.material.coverage',))
        payload=json.loads(call.kwargs['payload'])
        self.assertEqual(payload['material']['keywords'],['SOURCE_ON'])
        self.assertEqual(payload['material']['floats'],{'inspector_toggle':0})
        self.assertEqual(json.loads(self.mat[self.mod.RECORD])['keywords'],['SOURCE_ON'])

    def test_unknown_reader_preserves_import_and_marks_state(self):
        self.bridge.game_data_blob.side_effect=RuntimeError('optional dataset absent')
        self.mod.capture(self.mat,self.props,{'source_game':'FixtureGame'})
        self.assertNotIn(self.mod.RECORD,self.mat)
        self.assertTrue(self.mat[self.mod.STATUS].startswith('UNKNOWN:'))

    def test_unregistered_game_is_untouched(self):
        self.mod.capture(self.mat,self.props,{'source_game':'Other'})
        self.bridge.game_data_blob.assert_not_called()
        self.assertNotIn(self.mod.STATUS,self.mat)

    def test_projection_hash_changes_with_graph(self):
        first=self.mod.projection(self.mat)
        self.spec['finals']['__clip']=[0,0]
        second=self.mod.projection(self.mat)
        self.assertNotEqual(first['sha256'],second['sha256'])
        self.assertFalse(first['has_clip']);self.assertTrue(second['has_clip'])

    def test_lifecycle_is_idempotent(self):
        self.mod.register_reader('FixtureGame','fixture.material.coverage')
        self.assertEqual(len(self.finalizers),1)
        self.mod.unregister_reader('FixtureGame')
        self.assertEqual(len(self.finalizers),0)

    def test_unsupported_answer_is_not_saved(self):
        self.bridge.game_data_blob.return_value=b'{"schema":999,"state":"apply"}'
        self.mod.capture(self.mat,self.props,{'source_game':'FixtureGame'})
        self.assertNotIn(self.mod.RECORD,self.mat)
        self.assertIn('UNKNOWN:',self.mat[self.mod.STATUS])

    def test_declined_record_does_not_touch_graph(self):
        self.mat[self.mod.RECORD]=json.dumps({'answer':{'state':'none'}})
        self.mod.finalize(self.mat)
        self.assertNotIn(self.mod.STATUS,self.mat)

    def test_public_executor_has_no_title_shader_rules(self):
        source=(ROOT/'Host/Blender/material_coverage.py').read_text(encoding='utf-8')
        for name in ('CharacterNPR','_ALPHATEST_ON','_BaseMap','_BaseColor','_AlphaClipThreshold','wpn_'):
            self.assertNotIn(name,source)

if __name__=='__main__':unittest.main()
