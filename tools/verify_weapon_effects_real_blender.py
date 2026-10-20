"""Opt-in actual-resource regression; all game-specific selections are external.

No installed addon, preferences or user scene is changed. Source mesh templates
are static previews, never claimed as particles or gameplay-timed playback.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    for name in ('backend', 'deps', 'game-root', 'cabmap', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('character', 'actor-clip', 'projectile'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--native-shaders', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    args.output.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.deps))
    os.environ['RURI_RIPPERHOOK_BIN'] = str(args.backend)
    os.environ['RURI_RIPPER_WORKSPACE'] = str(args.output / 'workspace')
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('RuriRipperImporter', root / '__init__.py',
                                                submodule_search_locations=[str(root)])
    addon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = addon
    spec.loader.exec_module(addon)
    addon.register()
    import bpy
    from RuriRipperImporter.Kernel.bridge import pythonnet_bridge as pn, cabmap_state
    from RuriRipperImporter.Kernel.app import loading, browser
    from RuriRipperImporter.Game.Endfield.Blender import weapons, weapon_sync, weapon_effects as effects
    bridge = pn.RipperBridge('Endfield_1.5.3', str(args.game_root))
    bridge.load_cab_map(str(args.cabmap))
    cabmap_state.BRIDGE = bridge
    table = bridge.game_data('endfield.roster.cast', language='en')
    try:
        seeds = [table.cell(i, 'seed') for i in range(len(table))
                 if table.cell(i, 'key') == args.character and table.cell(i, 'kind') == 'Characters']
    finally:
        table.close()
    assert len(seeds) == 1, seeds
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    options = dict(source_game='Endfield', game_shaders=False, import_animations=False)
    actor = loading.load(bpy.context, seeds, options).rig
    assert actor
    state = getattr(bpy.context.scene, weapons.STATE)
    state.actor = actor
    count, warnings = loading.perform(bpy.context, [args.actor_clip], actor, options, activate=True)
    assert count == 1 and not actor.get(weapon_sync.NOTE), warnings
    sockets = weapon_sync.owned_sockets(actor)
    assert len(sockets) == 1
    weapon = next(obj for obj in sockets[0].children_recursive if obj.type == 'ARMATURE')
    actor_action, weapon_action = actor.animation_data.action, weapon.animation_data.action
    weapons.select_actor(bpy.context, actor)
    bpy.context.scene.frame_set(31, subframe=.25)
    context_before = (list(bpy.context.selected_objects), bpy.context.view_layer.objects.active,
                      bpy.context.scene.frame_current, bpy.context.scene.frame_subframe,
                      bpy.context.scene.frame_start, bpy.context.scene.frame_end,
                      bpy.context.scene.render.fps, bpy.context.scene.render.fps_base)
    effect_state = getattr(bpy.context.scene, effects.STATE)
    effect_state.actor = actor
    assert bpy.ops.ruri.endfield_read_effects() == {'FINISHED'}
    rows = effects.rows_for(actor)
    choices = [row for row in rows if row['template'] == args.projectile and row['phase'] in ('mainEffects', 'hitEffects')]
    assert len(choices) == 2, choices
    report = dict(blender=bpy.app.version_string, build_hash=bpy.app.build_hash.decode(),
                  candidate_rows=len(rows), native_shaders=args.native_shaders, effects=[],
                  particle_playback='pending', event_timing='UNKNOWN', visual_acceptance='pending')
    for row in choices:
        components = effects.datasets._rows('endfield.effect.components', seed=row['seed'])
        assert not [item for item in components if item['kind'] == 'unsupported_component'], components
        import_options = dict(options, game_shaders=args.native_shaders)
        # Both source-only and exact mesh-mode template routes are covered.
        # Exercise the same entry point as the panel, including unmocked options.
        effect_state.index = next(index for index, item in enumerate(effect_state.rows)
                                  if json.loads(item.payload)['identity'] == row['identity'])
        effect_state.placement = 'CURSOR'
        effect_state.preview_source_meshes = False
        browser.state_of(bpy.context).game_shaders = args.native_shaders
        before = set(bpy.data.objects)
        assert bpy.ops.ruri.endfield_import_effect() == {'FINISHED'}, effect_state.note
        first_root = effect_state.instance
        assert first_root is not None and first_root in set(bpy.data.objects) - before
        first = effects.Imported(first_root, True, int(first_root['ruri_effect_meshes']),
                                 int(first_root['ruri_effect_particles']))
        assert effects.import_effect(bpy.context, actor, row, import_options).root == first.root
        assert effects.import_effect(bpy.context, actor, row, import_options).created is False
        effects.remove_effect(bpy.context, first.root)
        preview = effects.import_effect(bpy.context, actor, row, import_options, preview_source_meshes=True)
        assert preview.created
        preview.root.name = 'Renamed effect · ' + row['phase']
        manifest = json.loads(preview.root[effects.MANIFEST].as_string())
        assert manifest['source']['identity'] == row['identity']
        assert manifest['event_timing'] == 'UNKNOWN' and manifest['particle_playback'] == 'pending'
        meshes = [obj for obj in preview.root.children_recursive if obj.type == 'MESH']
        assert all(len(obj.data.vertices) > 0 for obj in meshes)
        templates = [obj for obj in meshes if obj.get('ruri_effect_source_template')]
        report['effects'].append(dict(name=row['name'], phase=row['phase'], ordinary_meshes=preview.meshes,
            particle_parameters=preview.particles, static_templates=len(templates),
            vertices=sum(len(obj.data.vertices) for obj in meshes),
            materials=[dict(name=mat.name, nodes=len(mat.node_tree.nodes) if mat.node_tree else 0,
                            stack=mat.get('ruri_uber_stack', ''))
                       for obj in meshes for mat in obj.data.materials if mat is not None],
            warnings=manifest['warnings']))
        assert actor.animation_data.action == actor_action and weapon.animation_data.action == weapon_action
        context_after = (list(bpy.context.selected_objects), bpy.context.view_layer.objects.active,
                         bpy.context.scene.frame_current, bpy.context.scene.frame_subframe,
                         bpy.context.scene.frame_start, bpy.context.scene.frame_end,
                         bpy.context.scene.render.fps, bpy.context.scene.render.fps_base)
        assert context_before == context_after
    report['character_action_preserved'] = report['weapon_action_preserved'] = True
    report['selection_frame_range_rate_preserved'] = True
    report['sources_readable'] = True
    report['ui_import_operator_unmocked_options'] = True
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output / 'effects.blend'))
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('WEAPON_EFFECTS_REAL_PASS', json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
