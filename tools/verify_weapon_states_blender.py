"""Real-bpy synthetic contract: six combinations, native binding, mounts, rollback, reopen.

Uses ordinary fixture statements and fake reader calls; contains no game assets.
Run with Blender --background --factory-startup --python this_file -- --output DIR.
"""
import argparse
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import patch

p = argparse.ArgumentParser()
p.add_argument('--output', type=Path, required=True)
args = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
args.output.mkdir(parents=True, exist_ok=True)
sys.dont_write_bytecode = True
source = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('RuriRipperImporter', source / '__init__.py', submodule_search_locations=[str(source)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon._DRIVER.reload_modules()
from RuriRipperImporter.Kernel import bootstrap
with patch.object(bootstrap, 'configure'):
    addon._DRIVER.register()
import bpy
from mathutils import Matrix
from RuriRipperImporter.Game.Endfield.Blender import weapon_states as states
from RuriRipperImporter.Game.Endfield import weapon
assert any(p[0] == 'states' and p[3] == 4 for p in weapon.PANES)

def mesh(name):
    data = bpy.data.meshes.new(name)
    data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    return obj

def plan(seed, appearance, deco, deco_key=''):
    return dict(weapon='fixture', seed='fixture:'+appearance, refined=appearance == 'refined',
      requested_appearance=appearance, deco=deco, warnings=[], slot_policy='replace_entire_array',
      renderer_name_contains='_vfx_', materials=[] if deco == 'none' else [dict(name=deco, seed='fixture:material', source_key='exact:mat')],
      effects=[] if deco == 'none' else [dict(name='effect', seed='fixture:effect', mount_point='Mesh_all', offset=[.2, .3, .4])])

nodes = [NS(index=0, parent=-1, name='Mesh_all', path='', mesh=''),
         NS(index=1, parent=0, name='Source_vfx_fixture', path='vfx', mesh='vfx'),
         NS(index=2, parent=0, name='Source_body_fixture', path='body', mesh='body')]
@contextmanager
def read(seeds, options):
    yield NS(nodes=nodes, materials={'exact:mat':NS()}, seeds=seeds)

def indexed(context, stated, options):
    root = bpy.data.objects.new('Renamed source root', None)
    context.collection.objects.link(root)
    vfx, body = mesh('Renamed glow target'), mesh('Renamed body')
    for o in (vfx, body):
        o.parent = root
        o.data.materials.append(bpy.data.materials.new('source material'))
    vfx.hide_viewport = vfx.hide_render = True
    return NS(missing=[], warnings=[]), {0:root, 1:vfx, 2:body}

def effect(context, stated, options):
    mesh('Effect child')
    return NS(missing=[], warnings=[])

class Builder:
    def __init__(self, source, options): pass
    def build(self, key):
        mat = bpy.data.materials.new('native effect')
        mat['fixture_native'] = True
        return mat

original = mesh('Existing user weapon')
original.data.materials.append(bpy.data.materials.new('User material'))
# Providers that use source names must never clear an existing same-named proxy.
proxy = bpy.data.materials.new('Fixture proxy')
proxy['user_value'] = 41
with states._fresh_materials(NS(materials={'proxy': NS(name='Fixture proxy')})):
    assert bpy.data.materials.get('Fixture proxy') is None
    incoming = bpy.data.materials.new('Fixture proxy')
assert proxy.name == 'Fixture proxy' and proxy['user_value'] == 41
assert incoming != proxy and incoming.name != proxy.name
# Only manifest-declared time globals, and only unlinked sockets, get drivers.
clock = bpy.data.materials.new('Fixture clock')
clock.use_nodes = True
group = bpy.data.node_groups.new('Fixture time', 'ShaderNodeTree')
group.interface.new_socket(name='_Time', in_out='INPUT', socket_type='NodeSocketVector')
group.interface.new_socket(name='_Time_w', in_out='INPUT', socket_type='NodeSocketFloat')
group.interface.new_socket(name='Time', in_out='OUTPUT', socket_type='NodeSocketVector')
gi=group.nodes.new('NodeGroupInput'); go=group.nodes.new('NodeGroupOutput')
group.links.new(gi.outputs['_Time'],go.inputs['Time'])
node = clock.node_tree.nodes.new('ShaderNodeGroup'); node.node_tree = group
clock.node_tree.links.new(node.outputs['Time'],clock.node_tree.nodes.get('Principled BSDF').inputs['Base Color'])
clock_obj=mesh('Clock fixture'); clock_obj.data.materials.append(clock)
clock[states.CLOCK] = bpy.context.scene
entry = {'stack': NS(GLOBALS={'_Time': {'role':'time', 'type':'VECTOR4'}})}
with patch.object(states.material_panel, 'stack_of', return_value=entry):
    states.finalize(clock)
    states.finalize(clock)
    assert len(clock.node_tree.animation_data.drivers) == 4
bpy.context.scene.render.fps = 24
bpy.context.scene.frame_set(24)
assert all(abs(a-b)<1e-5 for a,b in zip(node.inputs['_Time'].default_value,(.05,1,2)))
assert abs(node.inputs['_Time_w'].default_value-3)<1e-5
original.select_set(True)
bpy.context.view_layer.objects.active = original
bpy.context.scene.frame_set(17, subframe=.25)
prior = (original.data, original.material_slots[0].material, original.hide_viewport, original.hide_render)
roots = []
with patch.object(states, 'plan_for', plan), patch.object(states.loading, 'read', read), \
     patch.object(states.materialise, 'materialise_indexed', indexed), patch.object(states.materialise, 'materialise', effect), \
     patch.object(states.material_builder, 'MaterialBuilder', Builder), patch.object(states.datasets, '_rows', return_value=[]), \
     patch.object(states.weapons, 'attachment_basis', return_value=Matrix.Identity(4)):
    for appearance in ('base', 'refined'):
        for deco in ('none', 'gemDeco', 'gemMaxDeco'):
            root = states.import_state(bpy.context, 'fixture', appearance, deco)
            roots.append(root)
            targets = [o for o in root.children_recursive if '_vfx_' in o.get(states.SOURCE_NAME, '')]
            assert len(targets) == 1
            target = targets[0]
            assert target.hide_render == (deco == 'none')
            assert len(target.material_slots) == int(deco != 'none')
            if deco != 'none':
                assert target.material_slots[0].material.get('fixture_native')
                anchor = next(o for o in root.children_recursive if o.name.startswith('Decoration ·'))
                assert (anchor.location - __import__('mathutils').Vector((.2,.3,.4))).length < 1e-6
                child = next(o for o in anchor.children if o.type == 'MESH')
                assert child.parent == anchor
            assert bpy.context.object == original
            assert bpy.context.scene.frame_current == 17 and abs(bpy.context.scene.frame_subframe-.25) < 1e-6
    assert prior == (original.data, original.material_slots[0].material, original.hide_viewport, original.hide_render)
    before = states._snapshot()
    with patch.object(Builder, 'build', side_effect=ValueError('fixture failure')):
        try: states.import_state(bpy.context, 'fixture', 'base', 'gemDeco')
        except ValueError: pass
        else: raise AssertionError('failure not raised')
    assert states._snapshot() == before, 'failed import leaked data'
    # Owned objects moved outside the tree must block deletion.
    root = roots[-1]
    child = next(iter(root.children))
    parent = child.parent
    child.parent = None
    try: states.remove_state(bpy.context, root)
    except ValueError: pass
    else: raise AssertionError('modified hierarchy accepted')
    child.parent = parent
    # Shared meshes are isolated by binding.
    a, b = mesh('shared A'), mesh('shared B')
    old = b.data
    b.data = a.data
    mat = bpy.data.materials.new('shared fixture')
    states.bind_materials([a], [mat], True)
    assert a.data != b.data and len(b.material_slots) == 0
    states.bind_materials([a], [], True)
    assert a.hide_render and not a.material_slots

path = args.output / 'six-states.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
saved = [o for o in bpy.data.objects if states.MANIFEST in o]
assert len(saved) == 6
for root in saved:
    assert root[states.MANIFEST].as_string()
    assert set(root.children_recursive) == set(root['ruri_weapon_state_members'])
    states.remove_state(bpy.context, root)
assert not [o for o in bpy.data.objects if states.MANIFEST in o]
report = dict(status='WEAPON_STATES_FIXTURES_PASS', combinations=6, rollback=True,
              source_preserved=True, renamed_source_targets=True, shared_mesh_isolation=True,
              reopen=True, removal=True, visual_acceptance=False)
(args.output/'fixture-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('WEAPON_STATES_FIXTURES_PASS',json.dumps(report),flush=True)
