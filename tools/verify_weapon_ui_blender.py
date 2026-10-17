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
from unittest.mock import patch


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
    def register_without_reader():
        addon._DRIVER.reload_modules()
        from RuriRipperImporter.Kernel import bootstrap as lifecycle_bootstrap
        with patch.object(lifecycle_bootstrap, 'configure'):
            addon._DRIVER.register()
    register_without_reader()
    import bpy
    bpy.context.preferences.filepaths.recent_files = 0
    from RuriRipperImporter import Game
    from RuriRipperImporter.Kernel.app import browser, layout, loading, command
    from RuriRipperImporter.Kernel import host as host_port, statement
    from RuriRipperImporter.Host.Blender import render, rig_identity
    from RuriRipperImporter.Game.Endfield import weapon, weapon_catalog, datasets, roster
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
    assert weapon.SECTIONS.keys() == ('mount', 'effects', 'glow', 'states')
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
    # Drive the actual stepped Character import path, replacing only the reader
    # and materialiser with synthetic results. No data is read from a game.
    host = host_port.current()
    class Stated:
        materials = {}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    def import_from(panel, game, result):
        with patch.object(browser, 'as_options', return_value=dict(source_game=game)), \
             patch.object(loading, 'read', return_value=Stated()), \
             patch.object(type(host), 'materialise', return_value=result), \
             patch.object(browser, '_sync_texture_roles'), \
             patch.object(browser, '_rebuild_window'), \
             patch.object(browser, '_redraw'), patch.object(browser, '_announce'):
            steps = browser._load_steps(bpy.context, browser.state_of(bpy.context),
                                        ['fixture:opaque'], (), False, panel)
            reply = None
            while True:
                try:
                    step = steps.send(reply)
                except StopIteration:
                    break
                reply = step.fn() if isinstance(step, command.Read) else None
    mount.auto_sync = False
    rig_identity.stamp_seed(actor, 'fixture:first')
    import_from(roster.STATE, 'Endfield', statement.Built(rig=actor, objects=[actor], imported=1))
    assert mount.actor == actor and mount.seed == 'fixture:first'
    later = bpy.data.objects.new('Last imported fixture', bpy.data.armatures.new('Later rig'))
    bpy.context.scene.collection.objects.link(later)
    rig_identity.stamp_seed(later, 'fixture:last')
    mount.rows.add().name = 'stale slot'
    mount.candidates.add().name = 'stale action'
    mount.candidate_slot, mount.candidate_seed = 7, 'fixture:old-weapon'
    import_from(roster.STATE, 'Endfield', statement.Built(rig=later, objects=[later], imported=1))
    assert mount.actor == later and mount.seed == 'fixture:last'
    assert not mount.rows and not mount.candidates
    assert mount.candidate_slot == -1 and not mount.candidate_seed
    for panel, game, result in (
            ('', 'Endfield', statement.Built(rig=actor, imported=1)),
            (browser.STATE, 'Endfield', statement.Built(rig=actor, imported=1)),
            (roster.STATE, 'WutheringWaves', statement.Built(rig=actor, imported=1)),
            (roster.STATE, 'Endfield', statement.Built(rig=actor, imported=0)),
            (roster.STATE, 'Endfield', statement.Built(imported=1))):
        import_from(panel, game, result)
        assert mount.actor == later
    # The icon still selects the target for subsequent character actions.
    mount.actor = later
    assert bpy.ops.ruri.endfield_select_weapon_actor() == {'FINISHED'}
    assert bpy.context.view_layer.objects.active == later and later.select_get()
    assert loading._import_listeners.count(weapons.on_import) == 1
    assert 'catalog_search' not in mount.bl_rna.properties
    report.update(last_successful_character=True, stale_actor_rows_cleared=True,
                  auto_sync_opt_out_selection=True, weapon_import_preserves_actor=True,
                  other_games_unchanged=True, selection_icon_operator=True)
    mount.actor = actor
    item = mount.rows.add()
    item.name, item.status, item.mode = 'fixture weapon', 'ready', mount.mode
    item.resource_kind = 'equipment'
    resource = mount.resources.add()
    resource.name, resource.seed, resource.family, resource.status = 'fixture resource', 'fixture:resource', 'fixture', 'ready'
    mount.resource_index = 0
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
            self.children = []
            self.local = []
            self.enabled = True
            self.active = True
        def container(self, *args, **kwargs):
            child = RecordingLayout(self.calls)
            self.children.append(child)
            return child
        column = row = box = split = grid_flow = container
        def prop(self, data, key, **kwargs):
            assert key in data.bl_rna.properties, (data, key)
            self.calls.append(('prop', key))
            self.local.append(('prop', key))
        def prop_search(self, data, key, search, collection, **kwargs):
            assert key in data.bl_rna.properties and collection in search.bl_rna.properties
            self.calls.append(('search', key))
        def operator(self, name, **kwargs):
            namespace, verb = name.split('.')
            getattr(getattr(bpy.ops, namespace), verb).get_rna_type()
            self.calls.append(('operator', name, self.enabled))
            self.local.append(('operator', name, kwargs))
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

    target = RecordingLayout()
    weapons.draw_mount(target, bpy.context)
    actor_row = next(child for child in target.children if ('prop', 'actor') in child.local)
    assert len(actor_row.children) == 1
    assert actor_row.children[0].local == [('operator', 'ruri.endfield_select_weapon_actor',
                                          dict(text='', icon='RESTRICT_SELECT_OFF'))]
    assert 'RESTRICT_SELECT_OFF' in bpy.types.UILayout.bl_rna.functions['operator'].parameters['icon'].enum_items
    assert not any(call in target.calls for call in (
        ('prop', 'catalog_search'), ('label', '装备武器 · 由你选择'),
        ('label', '隐藏槽位手动预览；技能切换与特效未接入')))
    for required in ('ruri.endfield_scan_weapon_catalog', 'ruri.endfield_equip_weapon',
                     'ruri.endfield_add_weapon', 'ruri.endfield_weapon_actions'):
        assert any(call[:2] == ('operator', required) for call in target.calls)
    assert ('label', '资源目录不推断专武归属或游戏装备限制') in target.calls
    assert ('label', '仅唯一完整动作名匹配自动加载；其余留待选择') in target.calls
    report.update(compact_actor_row=True, struck_elements_removed=True, retained_controls=True)

    state = browser.state_of(bpy.context)
    config = state.games.add()
    config.key, config.game_name = 'fixture-install', 'Endfield'
    state.current_tab = config.key
    state.active_tab = tabs[2].key
    assert not state.loaded
    nav = getattr(bpy.context.scene, weapon.STATE)
    assert nav.pane == 'catalog'
    for stored, pane in ((0, 'mount'), (1, 'effects'), (2, 'glow')):
        nav['pane'] = stored
        assert nav.pane == pane
    nav.property_unset('pane')
    assert nav.pane == 'catalog'
    report['legacy_pane_numbers_retained'] = True
    assert browser._active_filter_spec_key(bpy.context) == weapon_catalog.SPEC_KEY
    expected = {'catalog': 'ruri.weapon_resources_refresh',
                'states': 'ruri.endfield_import_weapon_state',
                'mount': 'ruri.endfield_read_weapons', 'effects': 'ruri.endfield_read_effects',
                'glow': 'ruri.endfield_weapon_glow_scan'}
    for pane, operator in expected.items():
        nav.pane = pane
        target = RecordingLayout()
        render.draw(layout.describe(browser.draw, bpy.context), target, bpy.context)
        operators = [call[1] for call in target.calls if call[0] == 'operator']
        assert operator in operators, (pane, target.calls, state.active_tab,
                                      browser.active_config(state), browser._tab_bar(state))
        allowed = {pane, 'catalog'} if pane == 'states' else {pane}
        assert not any(other in operators for key, other in expected.items() if key not in allowed)
        if pane == 'states':
            assert 'ruri.weapon_resources_refresh' in operators
            assert all(('prop', key) in target.calls for key in ('appearance', 'deco', 'deco_key'))
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
    assert getattr(bpy.context.scene, weapons.STATE).resources[0].seed == 'fixture:resource'
    assert getattr(bpy.context.scene, weapon_effects.STATE).rows[0].name == 'fixture effect'
    region = getattr(bpy.context.scene, weapon_glow.STATE).regions[0]
    assert region.selected and region.role == 'independent fixture'
    assert region.material.name == 'UI fixture emission'
    report.update(pane_save_reopen=True, old_feature_state_retained=True, standalone_panels_removed=True,
                  compatibility_removed=True, native_provider_retained=True, weapon_without_index=True)
    report.update(character_index_gate_retained=True, game_switch_drops_weapon_tab=True)
    addon.unregister()
    assert not loading._import_listeners
    assert not hasattr(bpy.types.Scene, weapon.STATE)
    assert not hasattr(bpy.types.Scene, weapon_catalog.STATE)
    assert not weapon.SECTIONS.keys()
    register_without_reader()
    from RuriRipperImporter.Game.Endfield import weapon as reloaded_weapon
    from RuriRipperImporter.Game.Endfield.Blender import weapons as reloaded_weapons
    from RuriRipperImporter.Kernel.app import loading as reloaded_loading
    assert reloaded_weapon.SECTIONS.keys() == ('mount', 'effects', 'glow', 'states')
    assert reloaded_loading._import_listeners.count(reloaded_weapons.on_import) == 1
    addon.unregister()
    report['register_unregister_register'] = True
    (args.output / 'ui-report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print('WEAPON_UI_PASS', json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
