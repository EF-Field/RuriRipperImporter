"""Host integration regression: source-preserving native weapon controls.

Factory-startup only. Fixtures use the real generated stack and its registered
material panel writer, never a second shader implementation.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import sys
from unittest.mock import patch

p = argparse.ArgumentParser()
p.add_argument('--deps', type=Path, required=True)
p.add_argument('--backend', type=Path)
p.add_argument('--output', type=Path)
p.add_argument('--reopen', type=Path)
args = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
sys.dont_write_bytecode = True
sys.path.insert(0, str(args.deps))
if args.backend:
    os.environ['RURI_RIPPERHOOK_BIN'] = str(args.backend)
fixture_path = args.output or args.reopen
if fixture_path:
    os.environ['RURI_RIPPER_WORKSPACE'] = str(fixture_path.parent / 'fixture-workspace')
root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('RuriRipperImporter', root / '__init__.py', submodule_search_locations=[str(root)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon._DRIVER.reload_modules()
from RuriRipperImporter.Kernel import bootstrap
with patch.object(bootstrap, 'configure'):
    addon._DRIVER.register()
import bpy
assert bpy.app.background and bpy.app.build_hash == b'73cfbda0a06d'
bpy.context.preferences.filepaths.recent_files = 0
from RuriRipperImporter.Game.Endfield.Blender import weapon_glow as glow
from RuriRipperImporter.Game.Endfield.shader.Blender import STACKS
from RuriRipperImporter.Host.Blender import material_builder, material_panel
from RuriRipperImporter.Kernel.bridge import cabmap_state, pythonnet_bridge as pn

# The synthetic owner graph uses the real private declaration dataset, not a
# Python copy of its rules. Reopen without --backend proves cached offline edits.
if args.backend:
    pn.set_bin_dir(str(args.backend))
    pn._ensure_runtime()
    from Ruri.RipperHook.AssetRipperGameHook.Endfield import EndfieldMaterialChannels
    EndfieldMaterialChannels.Register()
    bridge = object.__new__(pn.RipperBridge)
    bridge._bridge, bridge._map = pn._bridge_type, None
    cabmap_state.BRIDGE = bridge

if args.reopen:
    assert args.backend is None, 'Offline reopen test must not load a reader'
    assert cabmap_state.BRIDGE is None and pn._bridge_type is None
    bpy.ops.wm.open_mainfile(filepath=str(args.reopen), load_ui=False, use_scripts=False)
    material_builder.rebuild_plugin_data(purge=True)
    target = bpy.data.objects['QA weapon root']
    state = getattr(bpy.context.scene, glow.STATE)
    state.target = target
    glow.scan(bpy.context)
    owned = glow.owned_materials(target)
    native, = [mat for mat in owned if mat.get(glow.NATIVE)]
    assert native['ruri_uber_floats']['_EmissionBrightness'] == 11.5
    assert native['ruri_uber_floats']['_UseEmission'] == 1
    assert not any(n.get(glow.TAG) for n in native.node_tree.nodes)
    assert any(c.kind == 'PARALLAX' for c in state.channels)
    for preview in (mat for mat in owned if mat.get(glow.PREVIEW)):
        obj = preview[glow.PREVIEW]
        assert not obj.hide_viewport and not obj.hide_render
        getattr(preview, glow.SETTINGS).enabled = False
        assert obj.hide_viewport and obj.hide_render
    glow.restore(bpy.context)
    assert not glow.owned_materials(target)
    assert cabmap_state.BRIDGE is None and pn._bridge_type is None
    print('NATIVE_CHANNEL_REOPEN_PASS', flush=True)
    addon.unregister()
    raise SystemExit(0)

stack = next(s for s in STACKS if s.PANEL_KEY == 'ruri_character_uber_endfield')
# A real generated template, populated through its instance parameter writer.
material, _ = stack.instantiate('QA native source', 'Standard')
material.name = 'QA native source'
material['ruri_uber_images'] = {'_EmissionMap': bpy.data.images.new('QA native E', 2, 2),
                                '_ParallaxTex': bpy.data.images.new('QA native P', 2, 2)}
material['ruri_uber_floats'] = {'_UseEmission': 0., '_UseParallax': 1., '_EmissionBrightness': 6.86}
material['ruri_uber_colors'] = {}
material['ruri_uber_st'] = {}
material['ruri_uber_disabled_passes'] = []
material['ruri_uber_shader_passes'] = []
material['ruri_uber_shader_guid'] = ''
material['ruri_uber_shader'] = 'HGRP/CharacterNPR'
stack.apply_params(material)
target = bpy.data.objects.new('QA weapon root', None)
bpy.context.scene.collection.objects.link(target)
mesh = bpy.data.meshes.new('QA weapon mesh')
mesh.from_pydata([(0,0,0),(1,0,0),(0,1,0)], [], [(0,1,2)])
mesh.materials.append(material)
obj = bpy.data.objects.new('QA weapon body', mesh)
obj.parent = target
bpy.context.scene.collection.objects.link(obj)
state = getattr(bpy.context.scene, glow.STATE)
state.target = target
glow.scan(bpy.context)
assert {c.kind for c in state.channels} >= {'EMISSION', 'PARALLAX'}
assert len(state.regions) == 0, 'Native effects must not also receive automatic additive glow'
assert material['ruri_uber_floats']['_UseEmission'] == 0
print('NATIVE_CHANNEL_DISCOVERY_PASS', flush=True)

# The primary UI is an action, not a preparation checkbox: first click creates
# a local copy AND switches the native channel on; second click switches off.
assert bpy.ops.ruri.endfield_weapon_channel_toggle(material_name=material.name, kind='EMISSION') == {'FINISHED'}
quick, = glow.owned_materials(target)
assert quick['ruri_uber_floats']['_UseEmission'] == 1
assert material['ruri_uber_floats']['_UseEmission'] == 0
assert bpy.ops.ruri.endfield_weapon_channel_toggle(material_name=material.name, kind='EMISSION') == {'FINISHED'}
assert quick['ruri_uber_floats']['_UseEmission'] == 0
glow.restore(bpy.context)
glow.scan(bpy.context)
print('NATIVE_SINGLE_CLICK_TOGGLE_PASS', flush=True)

# Shared meshes/materials outside this weapon retain source identity and graph.
outside = bpy.data.objects.new('QA outside shared mesh', mesh)
bpy.context.scene.collection.objects.link(outside)
source_graph = (len(material.node_tree.nodes), len(material.node_tree.links))
assert bpy.ops.ruri.endfield_weapon_glow_apply() == {'FINISHED'}
owned, = glow.owned_materials(target)
assert owned != material and owned.get(glow.NATIVE)
assert obj.material_slots[0].link == 'OBJECT'
assert outside.active_material == material
assert stack.panel_read(owned)['values']['_UseParallax'] is True
assert abs(stack.panel_read(owned)['values']['_EmissionBrightness'] - 6.86) < 1e-5
assert not any(n.get(glow.TAG) for n in owned.node_tree.nodes)
from RuriRipperImporter.Host.Blender import material_panel
assert material_panel.sync(owned)
entry = material_panel.stack_of(owned)
mirror = getattr(owned, entry['property'])
mirror.p_UseEmission = True
mirror.p_EmissionBrightness = 11.5
mirror.p_ParallaxColor = (4., 2., .2, 1.)
assert owned['ruri_uber_floats']['_UseEmission'] == 1
assert owned['ruri_uber_floats']['_EmissionBrightness'] == 11.5
assert owned['ruri_uber_colors']['_ParallaxColor'][0] == 4
assert material['ruri_uber_floats']['_UseEmission'] == 0

class ProbeLayout:
    """Validate real RNA/operator names, not pixels or a visual acceptance."""
    def __init__(self): self.props, self.operators = [], []
    def container(self, *args, **kwargs): return self
    box = row = column = split = container
    def prop(self, data, key, **kwargs):
        assert key in data.bl_rna.properties, key
        self.props.append(key)
    def template_ID(self, data, key, **kwargs): self.prop(data, key)
    def label(self, **kwargs): pass
    def operator(self, name, **kwargs):
        module, operator = name.split('.')
        getattr(getattr(bpy.ops, module), operator).get_rna_type()
        self.operators.append(name)
        return type('Arguments', (), {})()

for channel in state.channels: channel.expanded = True
probe = ProbeLayout()
glow.draw_glow(probe, bpy.context)
assert 'p_UseEmission' in probe.props and 'p_UseParallax' in probe.props
assert 'ruri.endfield_weapon_channel_toggle' in probe.operators
assert 'ruri.endfield_weapon_glow_apply' not in probe.operators
assert 'selected' not in probe.props
print('NATIVE_CHANNEL_UI_RNA_PASS', flush=True)
glow.scan(bpy.context)
glow.apply(bpy.context)
assert glow.owned_materials(target) == [owned]
assert owned['ruri_uber_floats']['_EmissionBrightness'] == 11.5
assert not any(n.get(glow.TAG) for n in owned.node_tree.nodes)
state.material = material
glow.add_region(bpy.context)
try:
    glow.apply(bpy.context)
    raise AssertionError('A manual overlay must not be silently ignored on a native copy')
except ValueError:
    pass
state.regions.clear()
glow.restore(bpy.context)
assert obj.active_material == material and obj.material_slots[0].link == 'DATA'
assert (len(material.node_tree.nodes), len(material.node_tree.links)) == source_graph
print('NATIVE_COPY_WRITE_REPEAT_RESTORE_PASS', flush=True)

# A pointer to an object left in bpy.data but unlinked from the scene is not a
# valid weapon. A failed scan clears the old actionable channel/overlay list.
glow.scan(bpy.context)
bpy.context.scene.collection.objects.unlink(target)
try:
    glow.scan(bpy.context)
    raise AssertionError('Expected invalid scene target')
except ValueError:
    pass
assert not state.channels and not state.regions
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.context.scene.collection.objects.link(target)
assert bpy.ops.ruri.endfield_weapon_glow_target() == {'FINISHED'}
assert state.target == target and state.scanned_target == target

# Parameter declarations without a bound input are not promoted to emission.
emission_image = material['ruri_uber_images']['_EmissionMap']
material['ruri_uber_images'] = {'_ParallaxTex': material['ruri_uber_images']['_ParallaxTex']}
glow.scan(bpy.context)
assert not any(c.kind == 'EMISSION' for c in state.channels)
material['ruri_uber_images'] = dict(material['ruri_uber_images'], _EmissionMap=emission_image)

# Effect identity comes from the actual owning stack, not MainTex or a name.
effect_stack = next(s for s in STACKS if s.PANEL_KEY == 'ruri_effect_uber_endfield')
effect, _ = effect_stack.instantiate('QA no-main effect', 'VFXBaseV2')
effect['ruri_uber_images'] = {}
effect_channels = glow.weapon_channels.discover(effect)
assert [c['kind'] for c in effect_channels] == ['VFX']
assert not effect_channels[0]['enabled']
bpy.data.materials.remove(effect)
print('NATIVE_EFFECT_WITHOUT_MAINTEX_PASS', flush=True)

# A hidden, untextured/default-like material remains an unknown candidate.
unknown = bpy.data.materials.new('QA unproven material')
unknown.use_nodes = True
hidden_mesh = mesh.copy()
hidden_mesh.materials.clear()
hidden_mesh.materials.append(unknown)
hidden = bpy.data.objects.new('QA arbitrary hidden geometry', hidden_mesh)
hidden.parent = target
hidden.hide_viewport = hidden.hide_render = True
bpy.context.scene.collection.objects.link(hidden)
glow.scan(bpy.context)
assert any(c.kind == 'UNKNOWN' and c.material == unknown for c in state.channels)
assert all(not c.selected for c in state.channels if c.material == unknown)
glow.apply(bpy.context)
assert hidden.active_material == unknown and hidden.hide_viewport and hidden.hide_render
glow.restore(bpy.context)

# Unknown geometry has an explicit, reversible artist preview; it is not
# mislabeled as a recovered game material and never affects a shared mesh user.
outside_hidden = bpy.data.objects.new('QA unknown shared outside', hidden_mesh)
bpy.context.scene.collection.objects.link(outside_hidden)
original_nodes = len(unknown.node_tree.nodes)
assert bpy.ops.ruri.endfield_weapon_manual_preview(object_name=hidden.name, material_name=unknown.name) == {'FINISHED'}
preview = hidden.active_material
assert preview != unknown and preview.get(glow.PREVIEW) == hidden
assert getattr(preview, glow.SETTINGS).enabled
assert not hidden.hide_viewport and not hidden.hide_render
assert outside_hidden.active_material == unknown
assert len(unknown.node_tree.nodes) == original_nodes
assert sum(n.bl_idname == 'ShaderNodeEmission' and bool(n.get(glow.TAG)) for n in preview.node_tree.nodes) == 1
preview_count = len(bpy.data.materials)
assert bpy.ops.ruri.endfield_weapon_manual_preview(object_name=hidden.name, material_name=unknown.name) == {'FINISHED'}
assert hidden.hide_viewport and hidden.hide_render
assert not getattr(preview, glow.SETTINGS).enabled
assert len(bpy.data.materials) == preview_count
getattr(preview, glow.SETTINGS).enabled = True
assert not hidden.hide_viewport and not hidden.hide_render
glow.restore(bpy.context)
assert hidden.active_material == unknown and hidden.material_slots[0].link == 'DATA'
assert hidden.hide_viewport and hidden.hide_render and glow.VISIBILITY not in hidden
assert outside_hidden.active_material == unknown
print('EXPLICIT_MANUAL_PREVIEW_TOGGLE_RESTORE_PASS', flush=True)
print('NATIVE_TARGET_AND_UNKNOWN_PASS', flush=True)
replacement = bpy.data.objects.new('QA replacement root', None)
bpy.context.scene.collection.objects.link(replacement)
state.target = replacement
assert not state.channels and not state.regions and state.scanned_target is None
state.target = target
if args.output:
    glow.scan(bpy.context)
    glow.apply(bpy.context)
    native, = glow.owned_materials(target)
    assert material_panel.sync(native)
    mirror = getattr(native, material_panel.stack_of(native)['property'])
    mirror.p_UseEmission = True
    mirror.p_EmissionBrightness = 11.5
    glow.toggle_preview(bpy.context, hidden, unknown)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output))
    print('NATIVE_CHANNEL_SAVE_PASS', flush=True)
addon.unregister()
