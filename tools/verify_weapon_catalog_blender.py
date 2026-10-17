"""Actual-source standalone imports and material/texture/reopen checks.

Run only in isolated background Blender 5.3; never touches the installed addon,
preferences or a live scene. Game and runtime paths are supplied externally.
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch


class RecordingLayout:
    """Real host renderer/RNA validation; not a visual screenshot test."""
    def __init__(self, calls=None):
        self.calls = [] if calls is None else calls
        self.enabled = self.active = True

    def container(self, *args, **kwargs):
        return RecordingLayout(self.calls)
    column = row = box = split = grid_flow = container

    def prop(self, data, key, **kwargs):
        assert key in data.bl_rna.properties
        self.calls.append(('prop', key))

    def operator(self, name, **kwargs):
        import bpy
        namespace, verb = name.split('.')
        getattr(getattr(bpy.ops, namespace), verb).get_rna_type()
        self.calls.append(('operator', name, self.enabled))
        return type('Arguments', (), {})()

    def template_list(self, name, identifier, data, collection, active, index, **kwargs):
        import bpy
        assert collection in data.bl_rna.properties and index in active.bl_rna.properties
        assert bpy.types.UIList.bl_rna_get_subclass_py(name) is not None
        self.calls.append(('list', identifier))

    def label(self, **kwargs):
        self.calls.append(('label', kwargs.get('text', '')))

    def separator(self, *args, **kwargs):
        pass
    menu = popover = progress = separator


def main():
    p = argparse.ArgumentParser()
    for name in ('backend', 'deps', 'game-root', 'cabmap', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--addon-root', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--sample', action='append', default=[])
    args = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    args.output.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.deps))
    os.environ['RURI_RIPPERHOOK_BIN'] = str(args.backend)
    os.environ['RURI_RIPPER_WORKSPACE'] = str(args.output / 'workspace')
    spec = importlib.util.spec_from_file_location('RuriRipperImporter', args.addon_root / '__init__.py',
                                                submodule_search_locations=[str(args.addon_root)])
    addon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = addon
    spec.loader.exec_module(addon)
    addon._DRIVER.reload_modules()
    from RuriRipperImporter.Kernel import bootstrap as lifecycle
    with patch.object(lifecycle, 'configure'):
        addon._DRIVER.register()
    import bpy
    assert bpy.app.background and bpy.app.build_hash == b'73cfbda0a06d'
    bpy.context.preferences.filepaths.recent_files = 0
    from RuriRipperImporter.Kernel.bridge import pythonnet_bridge as pn, cabmap_state
    from RuriRipperImporter.Kernel.app import browser, command, loading, view, layout
    from RuriRipperImporter.Host.Blender import render, material_builder
    from RuriRipperImporter.Game.Endfield import weapon, weapon_catalog as catalog, datasets
    from RuriRipperImporter.Game.Endfield.Blender import weapons
    pn.set_bin_dir(str(args.backend))
    bridge = pn.RipperBridge('Endfield_1.6.0', str(args.game_root))
    bridge.load_cab_map(str(args.cabmap), key='standalone-test')
    cabmap_state.BRIDGE = bridge
    cabmap_state.activate('standalone-test', 'Endfield')
    cabmap_state.load_rows()
    state = browser.state_of(bpy.context)
    config = state.games.add()
    config.key, config.game_name = 'standalone-test', 'Endfield'
    config.game_root, config.decoder_id = str(args.game_root), 'Endfield_1.6.0'
    state.current_tab, state.active_tab = config.key, 'Endfield:weapon'
    assert state.loaded
    nav = getattr(bpy.context.scene, weapon.STATE)
    assert nav.pane == 'states'
    assert catalog.REFRESH.poll(bpy.context)
    assert catalog._refresh(bpy.context, {}) is None
    assert catalog.current(bpy.context)
    resources = datasets._rows(datasets.WEAPON_RESOURCES)
    assert any(r['family'] == 'misc' for r in resources)
    original_count = catalog.BOUND.count
    assert original_count > 0
    panel = catalog.state_of(bpy.context)
    # Exercise the same native filtering engine, not a Python list substitute.
    panel.search = 'wpn_sword_0006'
    catalog.rebuild(panel)
    assert catalog.BOUND.count > 0
    panel.search = 'no-such-fixture-weapon-standalone'
    catalog.rebuild(panel)
    assert catalog.BOUND.count == 0
    panel.search = ''
    catalog.rebuild(panel)
    assert catalog.BOUND.count == original_count
    mount = getattr(bpy.context.scene, weapons.STATE)
    assert mount.actor is None
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    samples = args.sample or (['wpn_sword_0006', 'wpn_misc_0051'] +
        [next(r['asset'] for r in resources if r['family'] == family and r['status'] == 'ready')
         for family in ('claym', 'funnel', 'lance', 'pistol')])
    report = dict(blender=bpy.app.version_string, build_hash=bpy.app.build_hash.decode(),
                  addon=str(args.addon_root), kernel=str(args.backend / 'Ruri.RipperHook.dll'),
                  kernel_sha256=hashlib.sha256((args.backend / 'Ruri.RipperHook.dll').read_bytes()).hexdigest(),
                  resources=len(resources), families=dict(Counter(r['family'] for r in resources)),
                  source_imports=[], synthetic_ui=False, visual_acceptance=False)
    actor = None
    for sample_index, sample in enumerate(samples):
        if sample_index == 1:
            actor = bpy.data.objects.new('Preserved character target', bpy.data.armatures.new('Preserved actor rig'))
            bpy.context.scene.collection.objects.link(actor)
            mount.actor = actor
        row, = [r for r in resources if r['asset'] == sample and r['status'] == 'ready']
        panel.active_index = catalog.BOUND.at(row['seed'])
        picked = catalog.BOUND.picked(panel)
        assert picked.payload == row['seed']
        panel.facet = catalog.FAMILIES.get(row['family'], row['family'])
        catalog.rebuild(panel)
        assert catalog.BOUND.count > 0
        assert all(entry['family'] == row['family'] for entry in catalog.BOUND.rows())
        panel.facet = view.EVERY
        catalog.rebuild(panel)
        panel.active_index = catalog.BOUND.at(row['seed'])
        picked = catalog.BOUND.picked(panel)
        before = set(bpy.data.objects)
        # Drive the exact shared Load command that the resource list draws.
        with patch.object(browser, '_sync_texture_roles'), patch.object(browser, '_rebuild_window'):
            steps = browser._load(bpy.context, browser.LOAD.filled(
                dict(seeds=picked.payload, reset_scene=False, panel=catalog.STATE)))
            reply = None
            while True:
                try:
                    step = steps.send(reply)
                except StopIteration:
                    break
                reply = step.fn() if isinstance(step, command.Read) else None
        made = set(bpy.data.objects) - before
        meshes = [obj for obj in made if obj.type == 'MESH']
        assert meshes and mount.actor == actor
        assert not any(obj.get(weapons.OWNER) for obj in made)
        mats = set(slot.material for obj in meshes for slot in obj.material_slots if slot.material)
        assert mats
        images = {node.image for mat in mats if mat.node_tree for node in mat.node_tree.nodes
                  if node.type == 'TEX_IMAGE' and node.image}
        images.update(image for mat in mats for image in mat.get('ruri_uber_images', {}).values()
                      if isinstance(image, bpy.types.Image))
        # Packed images can remain lazy in background mode. Query size first to
        # materialise them before testing resident pixels (has_data alone is not IO proof).
        image_state = [dict(name=image.name, size=list(image.size), has_data=image.has_data,
                            source=image.source, packed=bool(image.packed_file)) for image in images]
        print('WEAPON_IMAGE_DIAGNOSTIC', sample, json.dumps(image_state), flush=True)
        assert images and all(image.has_data and image.size[0] > 0 for image in images), image_state
        assert all(mat.get(material_builder.SOURCE_KEY_PROPERTY) for mat in mats)
        assert any(mat.get('ruri_uber_images') for mat in mats), 'native material texture bindings missing'
        # Verify the production importer packed source pixels itself; the test
        # must not repair an unpacked source image before its reopen check.
        assert all(image.source != 'FILE' or image.packed_file for image in images)
        report['source_imports'].append(dict(asset=sample, meshes=len(meshes), materials=len(mats),
            images=sorted(image.name for image in images),
            colorspaces={image.name: image.colorspace_settings.name for image in images},
            no_character_required=True, no_mount_created=True, panel_status=panel.status))
    report['existing_character_target_preserved'] = actor is not None and mount.actor == actor
    report['shared_filter_search'] = True
    report['category_filter'] = True
    # Draw is pure: prohibit all dataset reads after refresh/import.
    with patch.object(datasets, '_rows', side_effect=AssertionError('draw read game data')):
        description = layout.describe(weapon.draw_tab, bpy.context)
        target = RecordingLayout()
        render.draw(description, target, bpy.context)
    for operator in ('ruri.weapon_resources_refresh', 'ruri.load', 'ruri.reveal'):
        assert any(call[:2] == ('operator', operator) for call in target.calls)
    assert not any(call[:2] == ('operator', 'ruri.endfield_read_weapons') for call in target.calls)
    report['draw_without_reader'] = True
    report['filled_catalog_rna_render'] = True
    original_map = bridge._map
    bridge._map = None
    assert not catalog.current(bpy.context)
    bridge._map = original_map
    assert catalog.current(bpy.context)
    report['map_change_blocks_stale_catalog'] = True
    ambiguous = dict(asset='wpn_sword_fixture', family='sword', seed='fixture:ambiguous',
                     status='ambiguous_prefab', routes=2, basis='exact_prefab_container_route')
    with patch.object(datasets, '_rows', return_value=[ambiguous]):
        assert catalog._refresh(bpy.context, {}) is None
    picked = catalog.BOUND.picked(panel)
    assert picked is not None and picked.key == ambiguous['seed'] and not picked.payload
    target = RecordingLayout()
    render.draw(layout.describe(weapon.draw_tab, bpy.context), target, bpy.context)
    assert ('operator', 'ruri.load', False) in target.calls
    report['synthetic_ambiguous_route_blocks_load'] = True
    # A reader failure clears the previous table and blocks its old load payload.
    with patch.object(datasets, '_rows', side_effect=RuntimeError('fixture read failure')):
        assert catalog._refresh(bpy.context, {}) == {'CANCELLED'}
    assert not catalog.current(bpy.context) and not panel.rows
    assert mount.actor == actor
    report['failed_scan_invalidates_catalog'] = True
    path = args.output / 'standalone-weapons.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(path), compress=True)
    report['saved_blend'] = str(path)
    report['expected_images'] = [dict(name=image.name, size=list(image.size), packed=bool(image.packed_file))
                                 for image in bpy.data.images if image.has_data and image.packed_file]
    (args.output / 'catalog-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('WEAPON_CATALOG_SOURCE_PASS', json.dumps(report, ensure_ascii=False), flush=True)
    addon.unregister()


if __name__ == '__main__':
    main()
