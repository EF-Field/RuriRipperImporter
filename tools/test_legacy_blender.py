"""Isolated real-Blender integration test, never edits installed add-ons."""
import importlib.util
import os
import sys
from pathlib import Path
import bpy
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--fixture', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--deps', type=Path)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
source = Path(__file__).resolve().parents[1]
args.output.mkdir(parents=True, exist_ok=True)
os.environ['RURI_RIPPER_WORKSPACE'] = str(args.output / 'workspace')
if args.deps:
    sys.path.insert(0, str(args.deps))
spec = importlib.util.spec_from_file_location('RuriRipperImporter', source / '__init__.py',
                                            submodule_search_locations=[str(source)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
from RuriRipperImporter.Game.Endfield.Blender import shader_compatibility as c
from RuriRipperImporter.Host.Blender import material_builder as host
bpy.ops.wm.open_mainfile(filepath=str(args.fixture.resolve()))
host.rebuild_plugin_data(True)
scene = bpy.context.scene
rig = next(o for o in scene.objects if o.type == 'ARMATURE')
before = (len(rig.data.bones), len(bpy.data.actions), rig.animation_data.action)
scene.ruri_endfield_shader_mode = 'LEGACY52'
count = len({slot.material for obj in scene.objects if obj.type == 'MESH'
             for slot in obj.material_slots if slot.material
             and slot.material.get('ruri_uber_stack') == c.NATIVE_KEY})
assert bpy.ops.ruri.endfield_shader_compat() == {'FINISHED'}
assert count > 0
assert c.apply_scene(scene, 'LEGACY52') == 0
legacy = [m for m in bpy.data.materials if m.get('ruri_uber_stack') == c.LEGACY_KEY
          and not m.get(c.stack().TEMPLATE_KEY)]
assert legacy and all(m.node_tree for m in legacy)
assert all(not any(n.bl_idname.startswith('ShaderNodeLight') for n in m.node_tree.nodes) for m in legacy)
for m in legacy:
    for n in m.node_tree.nodes:
        if n.bl_idname == 'ShaderNodeVectorTransform':
            assert n.inputs['Vector'].is_linked, (m.name, n.name)
            assert not any(s.is_linked for s in n.inputs if s.identifier == 'LightIndex'), (m.name, n.name)
assert before == (len(rig.data.bones), len(bpy.data.actions), rig.animation_data.action)
print('LEGACY53_CONVERSION_PASS', count, flush=True)
lamp = bpy.data.objects.new('Legacy light regression', bpy.data.lights.new('Legacy light regression', 'SUN'))
scene.collection.objects.link(lamp)
lamp.data.energy = 3
c.update_lights()
table = bpy.data.images.get(c.legacy.LIGHT_TABLE)
pixels = tuple(table.pixels)
lamp.data.energy = 5
c.update_lights()
assert tuple(table.pixels) != pixels
bpy.data.batch_remove([lamp, lamp.data])
c.update_lights()
print('LEGACY53_LIGHT_EDIT_PASS', flush=True)
bpy.ops.wm.save_as_mainfile(filepath=str(args.output / 'legacy-test.blend'), copy=True)
bpy.ops.wm.open_mainfile(filepath=str(args.output / 'legacy-test.blend'))
host.rebuild_plugin_data(True)
host.push_camera_stages()
host.apply_rig_stages()
assert bpy.context.scene.ruri_endfield_shader_mode == 'LEGACY52'
legacy = [m for m in bpy.data.materials if m.get('ruri_uber_stack') == c.LEGACY_KEY
          and not m.get(c.stack().TEMPLATE_KEY)]
assert len(legacy) == count
assert all(all(n.node_tree is not None for n in m.node_tree.nodes if n.type == 'GROUP') for m in legacy)
print('LEGACY53_RELOAD_PASS', flush=True)
# The normal MaterialBuilder route, not just the scene conversion operator.
builder, props = c.source_adapter(legacy[0])
real = host.MaterialBuilder(None, {'game_shaders': True})
real._load_image = builder._load_image
fresh = real._build(props)
assert fresh.get('ruri_uber_stack') == c.LEGACY_KEY
bpy.data.materials.remove(fresh)
print('LEGACY53_IMPORT_DISPATCH_PASS', flush=True)
bpy.context.scene.ruri_endfield_shader_mode = 'NATIVE'
assert c.apply_scene(bpy.context.scene, 'NATIVE') == count
print('LEGACY53_SWITCH_BACK_PASS', flush=True)
addon.unregister()
assert c.provide not in host.GRAPH_PROVIDERS
assert c.update_lights not in bpy.app.handlers.depsgraph_update_post
assert not hasattr(bpy.types.Scene, c.MODE)
print('LEGACY53_UNREGISTER_PASS', flush=True)
