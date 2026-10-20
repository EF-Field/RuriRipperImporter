"""Real Blender RNA + existing core view/search, synthetic rows, no game read.

Use the existing Blender build in factory-startup/background, with --deps,
--backend and --output. Does not install an addon or alter saved preferences.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--addon-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--deps', type=Path, required=True)
    parser.add_argument('--backend', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    args.output.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.deps))
    spec = importlib.util.spec_from_file_location('RuriRipperImporter', args.addon_root / '__init__.py',
                                                submodule_search_locations=[str(args.addon_root)])
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
    from RuriRipperImporter.Game.Endfield import roster, datasets
    from RuriRipperImporter.Game.Endfield.Blender import weapons
    from RuriRipperImporter.Kernel.bridge import cabmap_state, pythonnet_bridge
    # Core host-table operations need no Initialize/game root/map/decoder.
    pythonnet_bridge.set_bin_dir(str(args.backend))
    pythonnet_bridge._ensure_runtime()
    bridge = object.__new__(pythonnet_bridge.RipperBridge)
    bridge._bridge = pythonnet_bridge._bridge_type
    bridge._map = None
    cabmap_state.BRIDGE = bridge
    spec = importlib.util.spec_from_file_location('name_fixtures', Path(__file__).with_name('test_names_zh.py'))
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    checks = []
    state = roster.state_of(bpy.context)
    fixture = fixtures.FakeTable()
    table = bridge.open_host_table('fixture:backend-labels',
        [name + ('#' if name == 'shipped' else '') for name in fixture.names],
        fixture.rows, fixture.roles)
    with patch.object(datasets, 'language_for_locale', return_value='en'), \
         patch.object(datasets, 'cast', return_value=table), \
         patch.object(datasets, '_rows', side_effect=AssertionError('Unexpected game read')):
        result = roster._refresh(bpy.context, {})
        assert result is None, state.status
        checks.append('actual_refresh_uses_backend_table_directly')
        for facet, query, identity, label, payload in (
            ('Characters', '角色甲', 'fixture_actor_a', '角色甲', 'fixture:seed:1'),
            ('Characters', 'ACTOR_A', 'fixture_actor_a', '角色甲', 'fixture:seed:1'),
            ('Characters', 'fixture actor alpha', 'fixture_actor_a', '角色甲', 'fixture:seed:1'),
            ('UI Models', '角色乙', 'fixture_actor_b', '角色乙', 'fixture:seed:2'),
            ('UI Models', 'beta', 'fixture_actor_b', '角色乙', 'fixture:seed:2'),
            ('NPCs', 'npc original', 'fixture_npc', 'npc original', 'fixture:seed:3'),
        ):
            state.facet, state.search = facet, query
            roster.rebuild(state)
            assert roster.BOUND.keys() == [identity], (facet, query, roster.BOUND.keys())
            state.active_index = roster.BOUND.view.index_of_key(identity)
            entry = roster.BOUND.picked(state)
            assert entry.key == identity and entry.label == label
            assert roster.BOUND.payload(state) == payload
            checks.append('core_search:' + query)
        state.facet, state.search = 'Characters', 'Future'
        roster.rebuild(state)
        assert not roster.BOUND.keys(), 'unshipped row retained its numeric zero'
        checks.append('unknown_label_and_numeric_shipped_preserved')
    mount = getattr(bpy.context.scene, weapons.STATE)
    rows = [dict(asset='fixture_weapon', label='武器甲 · fixture_weapon', seed='fixture:exact-resource', family='sword', status='ready'),
            dict(asset='fixture_prop', seed='fixture:misc', family='misc', status='ready')]
    with patch.object(weapons, 'catalog_rows', return_value=rows):
        assert bpy.ops.ruri.endfield_scan_weapon_catalog() == {'FINISHED'}
    assert mount.resources[0].name == '武器甲 · fixture_weapon'
    assert mount.resources[0].seed == rows[0]['seed']
    assert mount.resources[1].name == rows[1]['asset']
    labels = []
    layout = SimpleNamespace(label=lambda **kw: labels.append(kw))
    weapons.RURI_UL_equipment_resources.draw_item(None, bpy.context, layout, mount,
                                                 mount.resources[0], 0, mount, 'resource_index')
    assert labels == [dict(text='武器甲 · fixture_weapon', icon='MESH_DATA')]
    assert 'catalog_search' not in mount.bl_rna.properties
    checks.append('weapon_label_preserved_without_separate_search')
    actor = bpy.data.objects.new('name fixture', bpy.data.armatures.new('name fixture'))
    bpy.context.scene.collection.objects.link(actor)
    source = dict(slot=7, mode=mount.mode, status='ready', visible=True, weapon='fixture_weapon', label='武器甲 · fixture_weapon',
                  bone='fixture_mount', resource_kind='equipment')
    with patch.object(weapons.rig_identity, 'seed_of', return_value='fixture:actor'):
        weapons.populate_slots(mount, actor, [source])
    assert mount.rows[0].name == '7 · 武器甲 · fixture_weapon'
    checks.append('weapon_slot_display_only')
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output / 'names-fixture.blend'), compress=True)
    bpy.ops.wm.open_mainfile(filepath=str(args.output / 'names-fixture.blend'), load_ui=False, use_scripts=False)
    mount = getattr(bpy.context.scene, weapons.STATE)
    assert mount.resources[0].name == '武器甲 · fixture_weapon'
    assert mount.resources[0].seed == rows[0]['seed']
    checks.append('weapon_labels_and_identity_survive_reopen')
    report = dict(build=bpy.app.build_hash.decode(), backend=str(args.backend), checks=checks,
                  game_reads=0, synthetic_data=True, visual_acceptance=False)
    cabmap_state.BRIDGE = None
    addon.unregister()
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('NAMES_ZH_BLENDER_PASS', json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
