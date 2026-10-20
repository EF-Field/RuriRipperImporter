"""Reopen a migrated fixture, reconstruct shader data and prepare a visual-review copy."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

import bpy
from mathutils import Vector

if not bpy.app.background:
    raise RuntimeError('This diagnostic is background-only. Install the add-on manually and import in Blender.')

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--fixture', required=True, type=Path)
p.add_argument('--backend', required=True, type=Path)
p.add_argument('--addon-source', type=Path)
p.add_argument('--deps', required=True, type=Path)
p.add_argument('--output', required=True, type=Path)
p.add_argument('--render', action='store_true')
p.add_argument('--review', action='store_true')
args = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
args.output.mkdir(parents=True, exist_ok=True)
sys.dont_write_bytecode = True
sys.path.insert(0, str(args.deps.resolve()))
os.environ['RURI_RIPPERHOOK_BIN'] = str(args.backend.resolve())
os.environ['RURI_RIPPER_WORKSPACE'] = str(args.output / 'workspace')
source = (args.addon_source or Path(__file__).resolve().parents[1]).resolve()
spec = importlib.util.spec_from_file_location('RuriRipperImporter', source / '__init__.py',
                                            submodule_search_locations=[str(source)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
from RuriRipperImporter.Host.Blender import material_builder as host, derived_state
from RuriRipperImporter.Kernel.bridge import pythonnet_bridge
pythonnet_bridge.set_bin_dir(str(args.backend))
bpy.ops.wm.open_mainfile(filepath=str(args.fixture.resolve()))
scene = bpy.context.scene
rigs = [o for o in scene.objects if o.type == 'ARMATURE']
actor = next(o for o in rigs if len(o.data.bones) == 556)
weapon = next(o for o in rigs if o != actor)
assert actor.animation_data.action_slot is not None
assert weapon.animation_data.action_slot is not None
assert not weapon.pose.bones['slot_M_string_01_vfx'].constraints
identities = {o.name: (len(o.data.bones), o.animation_data.action.name,
                       o.animation_data.action_slot.identifier) for o in rigs}
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = scene.render.resolution_y = 900
scene.render.resolution_percentage = 100
scene.render.fps = 60
scene.frame_start, scene.frame_end = 0, 300
scene.frame_set(9)
if not scene.get('migration53_review_layout'):
    weapon.location.x += 1.2
    light = bpy.data.objects.new('Review Sun', bpy.data.lights.new('Review Sun', 'SUN'))
    scene.collection.objects.link(light)
    light.data.energy = 2.0
    light.rotation_euler = (math.radians(35), math.radians(-20), math.radians(-35))
    scene['migration53_review_layout'] = True
    scene['migration53_review_lighting'] = 'Neutral review light, not extracted game lighting. Weapon is separately displayed, not runtime-attached.'
if scene.camera is None:
    camera = bpy.data.objects.new('Review Camera', bpy.data.cameras.new('Review Camera'))
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = 3.4
    center = Vector((0.5, 0, 1.0))
    camera.location = center + Vector((3.0, -6.0, 2.0))
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
if scene.camera.name == 'Review Camera':
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    points = [o.matrix_world @ Vector(corner) for o in scene.objects
              if o.type == 'MESH' and not o.hide_render
              for corner in o.evaluated_get(depsgraph).bound_box]
    rotation = scene.camera.rotation_euler.to_matrix()
    projected = [rotation.transposed() @ point for point in points]
    lower = Vector(tuple(min(p[i] for p in projected) for i in range(3)))
    upper = Vector(tuple(max(p[i] for p in projected) for i in range(3)))
    center = rotation @ ((lower + upper) * 0.5)
    scene.camera.location = center + rotation @ Vector((0, 0, 6))
    scene.camera.data.ortho_scale = max(upper.x - lower.x, upper.y - lower.y) * 1.15
host.rebuild_plugin_data(True)
# Explicit fixture preparation, not an automatic load handler. The upstream
# native stack intentionally does not serialize/recreate vertex trees on load.
host.apply_vertex_stages(list(scene.objects))
host.push_camera_stages(camera=scene.camera)
host.apply_rig_stages(list(scene.objects))
host.apply_post_stages(scene)
derived_state.flush()
assert not derived_state.LAST_ERROR, derived_state.LAST_ERROR
native = [m for m in bpy.data.materials if m.get('ruri_uber_stack') == 'ruri_character_uber_endfield'
          and not m.get('ruri_plugin_data')]
assert len(native) >= 5
assert all(m.node_tree and all(n.node_tree is not None for n in m.node_tree.nodes if n.type == 'GROUP')
           for m in native)
assert identities == {o.name: (len(o.data.bones), o.animation_data.action.name,
                               o.animation_data.action_slot.identifier) for o in rigs}
for obj in scene.objects:
    obj.select_set(False)
actor.select_set(True)
bpy.context.view_layer.objects.active = actor
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            area.spaces.active.region_3d.view_perspective = 'CAMERA'
            area.spaces.active.shading.type = 'MATERIAL'
            area.spaces.active.shading.use_scene_lights = True
            area.spaces.active.shading.use_scene_world = True
            area.spaces.active.overlay.show_overlays = False
            area.spaces.active.show_region_ui = True
scene['migration53_visual_approval'] = 'PENDING USER REVIEW'
output = args.output / 'Typhoea-5.3-review.blend'
if not args.review:
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
report = {'build_hash': bpy.app.build_hash.decode(), 'native_character_materials': len(native),
          'rigs': identities, 'actions': len(bpy.data.actions),
          'backend_sha256': hashlib.sha256((args.backend/'Ruri.RipperHook.dll').read_bytes()).hexdigest(),
          'scene': str(output), 'vertex_reconstruction': 'explicit review-fixture preparation only',
          'visual_approval': 'pending user', 'derived_errors': derived_state.LAST_ERROR}
(args.output / 'scene-roundtrip.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
if args.render:
    scene.render.filepath = str(args.output / 'native-frame009.png')
    bpy.ops.render.render(write_still=True)
print('MIGRATION53_SCENE_REOPEN_PASS', json.dumps(report), flush=True)
