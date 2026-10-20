"""Isolated native Blender target regression; never run in an interactive scene."""
import importlib
from pathlib import Path
import sys
from types import ModuleType

import bpy

assert bpy.app.background
ROOT = Path(__file__).resolve().parents[1]
NAME = 'morph_targets_test'
for name, path in ((NAME, ROOT), (NAME + '.Host.Blender', ROOT / 'Host/Blender')):
    package = ModuleType(name)
    package.__path__ = [str(path)]
    sys.modules[name] = package
face = importlib.import_module(NAME + '.Host.Blender.face_rig')
animation = importlib.import_module(NAME + '.Host.Blender.animation_builder')

rig = bpy.data.objects.new('fixture_rig', bpy.data.armatures.new('fixture_rig'))
bpy.context.collection.objects.link(rig)
mesh = bpy.data.meshes.new('fixture_brow')
mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
obj = bpy.data.objects.new('fixture_brow', mesh)
bpy.context.collection.objects.link(obj)
obj.parent = rig
obj.shape_key_add(name='Basis')
right = obj.shape_key_add(name='fixture_R_close')
left = obj.shape_key_add(name='fixture_L_close')
legacy = obj.shape_key_add(name='legacy_ctrl_tx_max')
node_group = bpy.data.node_groups.new('fixture_uniforms', 'ShaderNodeTree')
node_group.interface.new_socket(name='_Value', in_out='INPUT', socket_type='NodeSocketFloat')
node_group.interface.new_socket(name='_Vector', in_out='INPUT', socket_type='NodeSocketColor')
material = bpy.data.materials.new('fixture_material')
material.use_nodes = True
material['ruri_uber_shader'] = 'Fixture/FixtureShader'
obj.data.materials.append(material)
node = material.node_tree.nodes.new('ShaderNodeGroup')
node.node_tree = node_group
node.inputs['_Value'].default_value = .9
node.inputs['_Vector'].default_value = (.1, .2, .3, .4)

def shader(ctrl, param='_Value', kind='scalar', component=0, mask=0xffffffff, round_value=False):
    return {'ctrl': ctrl, 'shader': 'FixtureShader', 'shader_match': 'leaf', 'param': param,
            'component': component, 'renderer_mask': mask, 'round_value': round_value,
            'binding_state': 'ready', 'binding_reason': '', 'value_kind': kind, 'component_count': 1 if kind == 'scalar' else 4,
            'defaults': (.2, 0, 0, 0) if kind == 'scalar' else (.1, .2, .3, .4)}

table = {'base': {}, 'deltas': {}, 'shape_rule': {'suffix': r'_(?:[trs][xyz])_(max|min)$', 'signs': {'max': 1, 'min': -1}},
         'shape_index_mappings': [{'ctrl': 'a', 'index': 0}, {'ctrl': 'b', 'index': 0}, {'ctrl': 'c', 'index': 1}],
         'shape_mesh_pattern': r'_brow$', 'shader_identity_property': 'ruri_uber_shader',
         'renderer_mask_property': 'ruri_renderer_mask',
         'shader_mappings': [shader('value'), shader('vector', '_Vector', 'vector', 2),
                             shader('masked', mask=4)]}

before = (right.value, left.value, legacy.value, node.inputs['_Value'].default_value,
          tuple(node.inputs['_Vector'].default_value), len(bpy.data.actions))
report = face.bindings(bpy.context, rig, table)
assert (right.value, left.value, legacy.value, node.inputs['_Value'].default_value,
        tuple(node.inputs['_Vector'].default_value), len(bpy.data.actions)) == before
assert len(report['ctrls']) == 6 and 'masked' not in report['ctrls'], report
assert report['unresolved_targets'], 'Missing renderer-role metadata was treated as All'

face.drive(bpy.context, rig, table, {'a': .7, 'b': .6, 'c': .4, 'value': .55, 'vector': .5})
assert right.value == 1 and abs(left.value - .4) < 1e-6
assert abs(node.inputs['_Value'].default_value - .75) < 1e-6
assert abs(node.inputs['_Vector'].default_value[2] - .8) < 1e-6
assert abs(node.inputs['_Vector'].default_value[0] - .1) < 1e-6
face.drive(bpy.context, rig, table, {})
assert right.value == left.value == 0
assert abs(node.inputs['_Value'].default_value - .2) < 1e-6
assert abs(node.inputs['_Vector'].default_value[2] - .3) < 1e-6

frames = [{'a': 0, 'b': 0, 'c': 0, 'value': 0, 'vector': 0, 'legacy_ctrl': 0},
          {'a': .8, 'b': .7, 'c': .4, 'value': .6, 'vector': .5, 'legacy_ctrl': .3},
          {'a': 0, 'b': 0, 'c': 0, 'value': 0, 'vector': 0, 'legacy_ctrl': 0}]
keys = [(0, 0, 0, 0), (1 / 30, .3, 0, 0), (2 / 30, 0, 0, 0)]
tracks = {ctrl: keys for ctrl in frames[0]}
assert face.bake(bpy.context, rig, table, tracks, frames, 30, 'fixture_expression')
shape_owner = mesh.shape_keys
shape_action = shape_owner.animation_data.action
shape_curves = list(animation.channels_of(shape_action, shape_action.slots[0]))
assert len(shape_curves) == 3, [(c.data_path, c.array_index) for c in shape_curves]
assert len({(c.data_path, c.array_index) for c in shape_curves}) == 3
assert any(abs(c.evaluate(1) - 1) < 1e-6 for c in shape_curves)
shader_owner = material.node_tree
shader_action = shader_owner.animation_data.action
shader_curves = list(animation.channels_of(shader_action, shader_action.slots[0]))
assert len(shader_curves) == 2
assert len({(c.data_path, c.array_index) for c in shader_curves}) == 2
assert abs(next(c for c in shader_curves if c.array_index == 2).evaluate(1) - .8) < 1e-6

# Explicit mask metadata unlocks only that renderer; no fallback name guessing.
obj['ruri_renderer_mask'] = 4
masked_table = dict(table, shader_mappings=[shader('masked', mask=4, round_value=True)])
assert 'masked' in face.bindings(bpy.context, rig, masked_table)['ctrls']
face.drive(bpy.context, rig, masked_table, {'masked': .65})
assert node.inputs['_Value'].default_value == 1

# Raw source metadata never participates in neutral host binding.
neutral = dict(shader('neutral'), type='OpaqueSourceType', blend_mode=99, vector_index=99)
assert 'neutral' in face.bindings(bpy.context, rig, dict(table, shader_mappings=[neutral]))['ctrls']
unresolved = dict(neutral, ctrl='unresolved', binding_state='UNKNOWN', binding_reason='unsupported_source_semantics')
unknown_report = face.bindings(bpy.context, rig, dict(table, shader_mappings=[unresolved]))
assert 'unresolved' not in unknown_report['ctrls'] and any('unsupported_source_semantics' in s for s in unknown_report['unresolved_targets'])

# Two role meshes are ambiguous: never animate whichever happens to come first.
other = bpy.data.objects.new('other_brow', mesh.copy())
bpy.context.collection.objects.link(other)
other.parent = rig
ambiguous = face.bindings(bpy.context, rig, dict(table))
assert 'a' not in ambiguous['ctrls'] and any('2 meshes' in s for s in ambiguous['unresolved_targets'])
print('MORPH_TARGETS_BLENDER_PASS static_reset=True shared_curve_uniqueness=True vector_mask=True readonly_binding=True')
