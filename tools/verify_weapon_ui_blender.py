"""Background routing/lifecycle tests, with synthetic UI state and no game reader.

RecordingLayout validates Blender RNA/operator addresses through the real host
renderer. It is a draw-contract test, not a screenshot or manual GUI acceptance.
"""
import argparse
import ctypes
import importlib.util
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--addon-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--deps', type=Path, required=True)
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
    addon.register()
    import bpy
    bpy.context.preferences.filepaths.recent_files = 0
    from RuriRipperImporter import Game
    from RuriRipperImporter.Kernel.app import browser, layout
    from RuriRipperImporter.Host.Blender import render
    from RuriRipperImporter.Game.Endfield import weapon, datasets
    from RuriRipperImporter.Game.Endfield.Blender import weapons, weapon_effects, weapon_glow
    from RuriRipperImporter.Host.Blender import material_builder
    from RuriRipperImporter.Kernel.bridge import bootstrap

    def unexpected_reader(*args, **kwargs):
        raise AssertionError('Drawing attempted to read a game dataset')
    datasets._rows = unexpected_reader
    # Simulate the existing reader-ready UI gate; no CLR/backend is opened.
    bootstrap.is_ready = lambda: True
    browser._DECODERS = []  # UI-only fixture: skip querying backend decoder inventory.
    report = dict(blender=bpy.app.version_string, build_hash=bpy.app.build_hash.decode(),
                  loaded_module=addon.__file__, scripts=bpy.utils.user_resource('SCRIPTS'),
                  user_resource=bpy.utils.resource_path('USER'), config=bpy.utils.user_resource('CONFIG'),
                  panes=[], game_reads=0,
                  draw_contract_only=True, reader_ready_gate='fixture')
    length = ctypes.c_uint(0)
    report['process_package_query'] = ctypes.windll.kernel32.GetCurrentPackageFullName(
        ctypes.byref(length), None)
    tabs = Game.tabs_of('Endfield')
    assert [tab.id for tab in tabs] == ['streamingscene', 'character', 'weapon']
    assert tabs[1].requires_index and not tabs[2].requires_index
    assert not any(tab.id == 'weapon' for tab in Game.tabs_of('WutheringWaves'))
    assert weapon.SECTIONS.keys() == ('mount', 'effects', 'glow')
    for panel in ('RURI_PT_endfield_weapons', 'RURI_PT_endfield_effects',
                  'RURI_PT_endfield_weapon_glow', 'RURI_PT_endfield_shader_compat'):
        assert bpy.types.Panel.bl_rna_get_subclass_py(panel) is None
    assert not hasattr(bpy.types.Scene, 'ruri_endfield_shader_mode')
    assert not any('shader_compatibility' in getattr(provider, '__module__', '')
                   for provider in material_builder.GRAPH_PROVIDERS)
    assert any('Endfield.shader.Blender' in getattr(provider, '__module__', '')
               for provider in material_builder.GRAPH_PROVIDERS)

    # Saved feature state and filled lists exercise the old native bodies, not
    # only empty-page routing. All identities below are synthetic fixture data.
    actor = bpy.data.objects.new('UI fixture actor', bpy.data.armatures.new('UI fixture rig'))
    bpy.context.scene.collection.objects.link(actor)
    mount = getattr(bpy.context.scene, weapons.STATE)
    mount.actor = actor
    item = mount.rows.add()
    item.name, item.status, item.mode = 'fixture weapon', 'ready', mount.mode
    candidate = mount.candidates.add()
    candidate.name, candidate.seed = 'fixture action', 'fixture:action'
    effects = getattr(bpy.context.scene, weapon_effects.STATE)
    effects.actor = actor
    item = effects.rows.add()
    item.name = 'fixture effect'
    item.payload = json.dumps({'status': 'ready'})
    effects.placement, effects.anchor = 'ANCHOR', actor
    glow = getattr(bpy.context.scene, weapon_glow.STATE)
    region = glow.regions.add()
    region.material = bpy.data.materials.new('UI fixture emission')
    region.selected = True
    region.role = 'independent fixture'

    class RecordingLayout:
        def __init__(self, calls=None):
            self.calls = [] if calls is None else calls
            self.enabled = True
            self.active = True
        def container(self, *args, **kwargs):
            return RecordingLayout(self.calls)
        column = row = box = split = grid_flow = container
        def prop(self, data, key, **kwargs):
            assert key in data.bl_rna.properties, (data, key)
            self.calls.append(('prop', key))
        def prop_search(self, data, key, search, collection, **kwargs):
            assert key in data.bl_rna.properties and collection in search.bl_rna.properties
            self.calls.append(('search', key))
        def operator(self, name, **kwargs):
            namespace, verb = name.split('.')
            getattr(getattr(bpy.ops, namespace), verb).get_rna_type()
            self.calls.append(('operator', name, self.enabled))
            return type('Arguments', (), {})()
        def template_list(self, name, identifier, data, collection, active, index, **kwargs):
            assert collection in data.bl_rna.properties and index in active.bl_rna.properties
            assert bpy.types.UIList.bl_rna_get_subclass_py(name) is not None
            self.calls.append(('list', identifier))
        def label(self, **kwargs):
            self.calls.append(('label', kwargs.get('text', '')))
        def separator(self, **kwargs):
            pass
        def menu(self, *args, **kwargs):
            pass
        def popover(self, *args, **kwargs):
            pass
        def progress(self, **kwargs):
            pass

    state = browser.state_of(bpy.context)
    config = state.games.add()
    config.key, config.game_name = 'fixture-install', 'Endfield'
    state.current_tab = config.key
    state.active_tab = tabs[2].key
    assert not state.loaded
    nav = getattr(bpy.context.scene, weapon.STATE)
    expected = {'mount': 'ruri.endfield_read_weapons', 'effects': 'ruri.endfield_read_effects',
                'glow': 'ruri.endfield_weapon_glow_scan'}
    for pane, operator in expected.items():
        nav.pane = pane
        target = RecordingLayout()
        render.draw(layout.describe(browser.draw, bpy.context), target, bpy.context)
        operators = [call[1] for call in target.calls if call[0] == 'operator']
        assert operator in operators, (pane, target.calls, state.active_tab,
                                      browser.active_config(state), browser._tab_bar(state))
        assert not any(other in operators for key, other in expected.items() if key != pane)
        assert ('label', 'Build or load a cabmap to browse/import.') not in target.calls
        report['panes'].append(dict(pane=pane, operators=operators))
    state.active_tab = tabs[1].key
    target = RecordingLayout()
    render.draw(layout.describe(browser.draw, bpy.context), target, bpy.context)
    assert ('label', 'Build or load a cabmap to browse/import.') in target.calls
    state.active_tab = tabs[2].key
    config.game_name = 'WutheringWaves'
    assert browser._active_tab(state) is None
    config.game_name = 'Endfield'
    nav.pane = 'glow'
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output / 'ui-fixture.blend'), compress=True)
    bpy.ops.wm.open_mainfile(filepath=str(args.output / 'ui-fixture.blend'), load_ui=False, use_scripts=False)
    assert getattr(bpy.context.scene, weapon.STATE).pane == 'glow'
    assert getattr(bpy.context.scene, weapons.STATE).candidates[0].seed == 'fixture:action'
    assert getattr(bpy.context.scene, weapon_effects.STATE).rows[0].name == 'fixture effect'
    region = getattr(bpy.context.scene, weapon_glow.STATE).regions[0]
    assert region.selected and region.role == 'independent fixture'
    assert region.material.name == 'UI fixture emission'
    report.update(pane_save_reopen=True, old_feature_state_retained=True, standalone_panels_removed=True,
                  compatibility_removed=True, native_provider_retained=True, weapon_without_index=True)
    report.update(character_index_gate_retained=True, game_switch_drops_weapon_tab=True)
    addon.unregister()
    assert not hasattr(bpy.types.Scene, weapon.STATE)
    assert not weapon.SECTIONS.keys()
    addon.register()
    from RuriRipperImporter.Game.Endfield import weapon as reloaded_weapon
    assert reloaded_weapon.SECTIONS.keys() == ('mount', 'effects', 'glow')
    addon.unregister()
    report['register_unregister_register'] = True
    (args.output / 'ui-report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print('WEAPON_UI_PASS', json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
