"""Blender-only regression on an already exported blend; no reader/game access.

Run with factory startup and disable-autoexec. All outputs go to --output;
the source blend and installed add-on/preferences are never saved or modified.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--blend', type=Path)
    parser.add_argument('--deps', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reopen', action='store_true')
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--fixtures-only', action='store_true')
    parser.add_argument('--addon-root', type=Path)
    parser.add_argument('--engine', choices=('CYCLES', 'BLENDER_EEVEE'), default='CYCLES')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    args.output.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.deps))
    root = args.addon_root or Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('RuriRipperImporter', root / '__init__.py',
                                                submodule_search_locations=[str(root)])
    addon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = addon
    spec.loader.exec_module(addon)
    addon.register()
    import bpy
    from RuriRipperImporter.Game.Endfield.Blender import weapon_glow as glow, weapons
    from RuriRipperImporter.Host.Blender import material_builder
    if args.fixtures_only:
        report = fixtures(bpy, glow)
        (args.output / 'fixture-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print('WEAPON_GLOW_FIXTURES_PASS', report, flush=True)
        addon.unregister()
        return
    assert args.blend, '--blend is required for exported-scene tests'
    bpy.ops.wm.open_mainfile(filepath=str(args.blend), load_ui=False, use_scripts=False)
    targets = [obj for obj in bpy.context.scene.objects if obj.get(weapons.OWNER)
               and any('wpn_misc_0051' in mesh.name for mesh in glow.meshes_of(obj))]
    assert len(targets) == 1, [obj.name for obj in targets]
    target = targets[0]
    state = getattr(bpy.context.scene, glow.STATE)
    state.target = target
    meshes = glow.meshes_of(target)
    source_slots = [(obj, index, slot.link, slot.material.get(glow.BASE, slot.material).name)
                    for obj in meshes for index, slot in enumerate(obj.material_slots) if slot.material]
    colorspaces = {image.name: image.colorspace_settings.name for image in bpy.data.images}
    transforms = {obj.name: [list(row) for row in obj.matrix_world] for obj in bpy.context.scene.objects}
    actions = {obj.name: obj.animation_data.action if obj.animation_data else None
               for obj in bpy.context.scene.objects}
    if args.reopen:
        materials = glow.owned_materials(target)
        assert len(materials) == 2
        material_builder.rebuild_plugin_data(purge=True)
        materials = glow.owned_materials(target)
        assert all(bool(any(n.get(glow.TAG) for n in mat.node_tree.nodes)) ==
                   (getattr(mat, glow.SETTINGS).role == '光弦') for mat in materials)
        assert all(getattr(mat, glow.SETTINGS).enabled ==
                   (getattr(mat, glow.SETTINGS).role == '光弦') for mat in materials)
        assert all(not mat.get(glow.ERROR) for mat in materials)
        assert bpy.ops.ruri.endfield_weapon_glow_restore() == {'FINISHED'}
        assert all(obj.material_slots[i].material.name == name for obj, i, link, name in source_slots)
        report = dict(reopen=True, rebuilt=True, restored=True, blender=bpy.app.version_string)
    else:
        assert bpy.ops.ruri.endfield_weapon_glow_scan() == {'FINISHED'}
        sources = [state.string_material, state.pattern_material]
        source_graphs = {mat.name: (len(mat.node_tree.nodes), len(mat.node_tree.links)) for mat in sources}
        outside = meshes[0].copy()
        outside.name = 'QA shared mesh outside weapon'
        outside.parent = None
        bpy.context.scene.collection.objects.link(outside)
        outside_materials = [slot.material for slot in outside.material_slots]
        assert bpy.ops.ruri.endfield_weapon_glow_apply() == {'FINISHED'}
        materials = glow.owned_materials(target)
        assert len(materials) == 2
        assert all(not mat.get(glow.ERROR) for mat in materials)
        assert all(getattr(mat, glow.SETTINGS).enabled ==
                   (getattr(mat, glow.SETTINGS).role == '光弦') for mat in materials)
        assert all(slot.material == mat for slot, mat in zip(outside.material_slots, outside_materials))
        assert all(obj.data.materials[i].name == name for obj, i, link, name in source_slots if link == 'DATA')
        counts = {mat.name: len(mat.node_tree.nodes) for mat in materials}
        assert bpy.ops.ruri.endfield_weapon_glow_apply() == {'FINISHED'}
        assert len(glow.owned_materials(target)) == 2
        assert counts == {mat.name: len(mat.node_tree.nodes) for mat in materials}
        for mat in materials:
            settings = getattr(mat, glow.SETTINGS)
            settings.enabled = False
            assert not any(n.get(glow.TAG) for n in mat.node_tree.nodes)
            settings.enabled = True
            settings.strength = 12
            settings.color = (.02, .4, 1, 1)
            assert not mat.get(glow.ERROR), mat.get(glow.ERROR)
        # Rebuild through the real host seam, not a direct call to the overlay.
        material_builder.rebuild_plugin_data(purge=True)
        materials = glow.owned_materials(target)
        assert all(any(n.get(glow.TAG) for n in mat.node_tree.nodes) for mat in materials)
        assert all(not mat.get(glow.ERROR) for mat in materials)
        assert all(getattr(mat, glow.SETTINGS).strength == 12 for mat in materials)
        assert all(abs(getattr(mat, glow.SETTINGS).color[1] - .4) < 1e-6 for mat in materials)
        assert bpy.ops.ruri.endfield_weapon_glow_normal() == {'FINISHED'}
        assert all(getattr(mat, glow.SETTINGS).enabled ==
                   (getattr(mat, glow.SETTINGS).role == '光弦') for mat in materials)
        assert all(max(abs(a-b) for a, b in zip(getattr(mat, glow.SETTINGS).color, glow.NORMAL_COLOR)) < 1e-6
                   for mat in materials)
        material_builder.rebuild_plugin_data(purge=True)
        materials = glow.owned_materials(target)
        assert all(getattr(mat, glow.SETTINGS).enabled ==
                   (getattr(mat, glow.SETTINGS).role == '光弦') for mat in materials)
        assert colorspaces == {image.name: image.colorspace_settings.name for image in bpy.data.images
                               if image.name in colorspaces}
        assert all([list(row) for row in bpy.data.objects[name].matrix_world] == value
                   for name, value in transforms.items())
        assert all((bpy.data.objects[name].animation_data.action
                    if bpy.data.objects[name].animation_data else None) == action for name, action in actions.items())
        bpy.data.objects.remove(outside, do_unlink=True)
        if args.render:
            render(bpy, glow, target, args.output, args.engine)
        bpy.ops.wm.save_as_mainfile(filepath=str(args.output / 'glow-test.blend'), compress=True)
        assert bpy.ops.ruri.endfield_weapon_glow_restore() == {'FINISHED'}
        assert all(obj.material_slots[i].material.name == name and obj.material_slots[i].link == link
                   for obj, i, link, name in source_slots)
        report = dict(blender=bpy.app.version_string, build_hash=bpy.app.build_hash.decode(),
                      source=str(args.blend), target=target.name, sources=list(source_graphs),
                      independent_materials=True, source_slots_preserved=True, shared_mesh_preserved=True,
                      repeated_apply=True, toggle_and_controls=True, host_recompile=True,
                      normal_preset=True, default_pattern_disabled=True, reference_blue_violet=True,
                      colorspaces_preserved=True, transforms_and_actions_preserved=True, restore=True,
                      original_graph_counts=source_graphs, render=args.render, engine=args.engine)
    (args.output / ('reopen-report.json' if args.reopen else 'report.json')).write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print('WEAPON_GLOW_PASS', json.dumps(report, ensure_ascii=False), flush=True)
    addon.unregister()


def fixtures(bpy, glow):
    scene = bpy.context.scene
    state = getattr(scene, glow.STATE)
    target = bpy.data.objects.new('QA standalone weapon', None)
    scene.collection.objects.link(target)
    image = bpy.data.images.new('QA mask', width=2, height=2)
    image.generated_color = (1, 1, 1, 1)
    sources, objects = [], []
    for role in ('objectline', 'pattern'):
        mat = bpy.data.materials.new('QA ' + role)
        mat.use_nodes = True
        mat['ruri_uber_images'] = {'_MainTex' if role == 'objectline' else '_EmissionMap': image}
        mesh = bpy.data.meshes.new('QA ' + role)
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        mesh.materials.append(mat)
        obj = bpy.data.objects.new('QA ' + role, mesh)
        scene.collection.objects.link(obj)
        obj.parent = target
        sources.append(mat)
        objects.append(obj)
    objects[1].material_slots[0].link = 'OBJECT'
    objects[1].material_slots[0].material = sources[1]
    state.target = target
    glow.scan(bpy.context)
    baseline_materials = set(bpy.data.materials)
    output = glow._output(sources[1])
    old = output.inputs['Surface'].links[0].from_socket
    sources[1].node_tree.links.remove(output.inputs['Surface'].links[0])
    # Second source failure must roll back the first source's binding and copy.
    try:
        glow.apply(bpy.context)
        raise AssertionError('Expected output validation failure')
    except ValueError:
        pass
    assert set(bpy.data.materials) == baseline_materials
    assert objects[0].material_slots[0].link == 'DATA'
    assert all(obj.material_slots[0].material == mat for obj, mat in zip(objects, sources))
    sources[1].node_tree.links.new(old, output.inputs['Surface'])
    glow.apply(bpy.context)
    materials = glow.owned_materials(target)
    assert len(materials) == 2
    assert all(not mat.get(glow.ERROR) for mat in materials)
    before = [obj.material_slots[0].material for obj in objects]
    # An externally changed DATA binding should reject restore before any mutation.
    objects[0].data.materials[0] = sources[1]
    try:
        glow.restore(bpy.context)
        raise AssertionError('Expected changed-slot validation failure')
    except ValueError:
        pass
    assert before == [obj.material_slots[0].material for obj in objects]
    objects[0].data.materials[0] = sources[0]
    shared = bpy.data.objects.new('QA external user', objects[0].data.copy())
    scene.collection.objects.link(shared)
    shared.data.materials[0] = before[0]
    glow.restore(bpy.context)
    assert all(obj.material_slots[0].material == mat for obj, mat in zip(objects, sources))
    assert objects[0].material_slots[0].link == 'DATA'
    assert objects[1].material_slots[0].link == 'OBJECT'
    assert shared.active_material == before[0]
    assert set(bpy.data.materials) == baseline_materials | {before[0]}
    return dict(rollback=True, data_and_object_slots=True, changed_slot_guard=True,
                external_shared_copy_retained=True, unused_copy_removed=True, standalone_target=True)


def render(bpy, glow, target, output, engine):
    from mathutils import Vector
    scene = bpy.context.scene
    meshes = glow.meshes_of(target)
    for obj in scene.objects:
        obj.hide_render = obj.type == 'MESH' and obj not in meshes
    scene.frame_set(1)
    bpy.context.view_layer.update()
    points = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    low = Vector([min(p[i] for p in points) for i in range(3)])
    high = Vector([max(p[i] for p in points) for i in range(3)])
    center = (low + high) / 2
    span = max(high - low)
    camera_data = bpy.data.cameras.new('QA weapon camera')
    camera = bpy.data.objects.new('QA weapon camera', camera_data)
    scene.collection.objects.link(camera)
    # Looking obliquely across the bow preserves its depth and thin light string.
    camera.location = center + Vector((1, -2.5, .6)).normalized() * span * 3
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera_data.type = 'ORTHO'
    camera_data.ortho_scale = span * 1.25
    scene.camera = camera
    world = bpy.data.worlds.new('QA dark world')
    world.use_nodes = True
    world.node_tree.nodes.get('Background').inputs['Color'].default_value = (.012, .018, .03, 1)
    world.node_tree.nodes.get('Background').inputs['Strength'].default_value = .5
    scene.world = world
    light_data = bpy.data.lights.new('QA key', 'AREA')
    light_data.energy = 800
    light_data.shape = 'DISK'
    light_data.size = span * 2
    light = bpy.data.objects.new('QA key', light_data)
    scene.collection.objects.link(light)
    light.location = center + Vector((2, -3, 3)) * span
    light.rotation_euler = (center - light.location).to_track_quat('-Z', 'Y').to_euler()
    scene.render.engine = engine
    scene.cycles.samples = 12
    scene.cycles.device = 'CPU'
    scene.render.resolution_x = 800
    scene.render.resolution_y = 800
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.view_settings.view_transform = 'AgX'
    # The product deliberately leaves the user's compositor unchanged.
    scene.render.use_compositing = False
    materials = glow.owned_materials(target)
    for enabled, filename in ((False, 'bow-before.png'), (True, 'bow-glow.png')):
        if enabled:
            glow.normal(bpy.context)
        else:
            for mat in materials:
                getattr(mat, glow.SETTINGS).enabled = False
        scene.render.filepath = str(output / filename)
        bpy.ops.render.render(write_still=True)


if __name__ == '__main__':
    main()
