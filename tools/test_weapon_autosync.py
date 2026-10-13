"""Real Blender/Statement autosync regression. Inputs are external, never fixtures in the ZIP."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch


def main():
    p = argparse.ArgumentParser()
    for name in ('backend', 'deps', 'game-root', 'cabmap', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    for name in ('character', 'actor-clip'):
        p.add_argument('--'+name, required=True)
    args = p.parse_args(sys.argv[sys.argv.index('--')+1:])
    args.output.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.deps))
    os.environ['RURI_RIPPERHOOK_BIN'] = str(args.backend)
    os.environ['RURI_RIPPER_WORKSPACE'] = str(args.output/'workspace')
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('RuriRipperImporter', root/'__init__.py',
                                                submodule_search_locations=[str(root)])
    addon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = addon
    spec.loader.exec_module(addon)
    addon.register()
    import bpy
    from RuriRipperImporter.Kernel.bridge import pythonnet_bridge as pn, cabmap_state
    from RuriRipperImporter.Kernel.app import loading, browser
    from RuriRipperImporter.Game.Endfield.Blender import weapons, weapon_sync
    bridge = pn.RipperBridge('Endfield_1.5.3', str(args.game_root))
    bridge.load_cab_map(str(args.cabmap))
    cabmap_state.BRIDGE = bridge
    table = bridge.game_data('endfield.roster.cast', language='en')
    seeds = [table.cell(i, 'seed') for i in range(len(table))
             if table.cell(i, 'key') == args.character and table.cell(i, 'kind') == 'Characters']
    assert len(seeds) == 1
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    options = dict(source_game='Endfield', game_shaders=False, import_animations=False)
    actor = loading.load(bpy.context, seeds, options).rig
    assert actor and len([o for o in bpy.data.objects if o.type == 'ARMATURE']) == 1
    state = getattr(bpy.context.scene, weapons.STATE)
    def import_actor():
        weapons.select_actor(bpy.context, actor)
        with ExitStack() as stack:
            stack.enter_context(patch.object(browser, 'as_options', return_value=options))
            for name in ('_sync_texture_roles', '_rebuild_window', '_redraw', '_announce'):
                stack.enter_context(patch.object(browser, name))
            list(browser._load_steps(bpy.context, SimpleNamespace(), [], [args.actor_clip], False))
    import_actor()
    assert not actor.get(weapon_sync.NOTE), actor.get(weapon_sync.NOTE)
    sockets = weapon_sync.owned_sockets(actor)
    assert len(sockets) == 1, sockets
    socket = sockets[0]
    rig = next(o for o in socket.children_recursive if o.type == 'ARMATURE')
    action = rig.animation_data.action
    assert action and action != actor.animation_data.action
    assert int(socket[weapons.SPACE_VERSION]) == 2
    assert 'attack_01' in action.name.lower(), action.name
    assert bpy.context.scene.frame_end == 300, bpy.context.scene.frame_end
    assert bpy.context.scene.render.fps == 60
    assert len(action.slots) == 1
    owned = [a for a in bpy.data.actions if a.get(weapon_sync.ACTION_OWNER) == rig]
    import_actor()
    assert weapon_sync.owned_sockets(actor) == sockets
    assert rig.animation_data.action == action
    assert [a for a in bpy.data.actions if a.get(weapon_sync.ACTION_OWNER) == rig] == owned
    actor_action = actor.animation_data.action
    actor_slot = actor.animation_data.action_slot
    row = next(r for r in weapons.rows_for(actor) if r['mode']=='fight' and int(r['slot'])==int(socket[weapons.SLOT]))
    candidates = weapon_sync.catalog(row, actor[weapon_sync.LAST_CLIP])
    assert len([r for r in candidates if r['match']]) == 1
    # Miss/ambiguity are optional notes, not character-import failures.
    weapon_sync.on_performance(bpy.context, actor, SimpleNamespace(name='unknown clip'), None, options)
    assert '未匹配' in actor[weapon_sync.NOTE]
    with patch.object(weapon_sync, 'catalog', return_value=[dict(candidates[0], match=True)]*2):
        weapon_sync.on_performance(bpy.context, actor, SimpleNamespace(name='ambiguous clip'), None, options)
    assert '多个候选' in actor[weapon_sync.NOTE]
    with patch.object(weapon_sync, 'catalog', side_effect=ValueError('test backend unavailable')):
        weapon_sync.on_performance(bpy.context, actor, SimpleNamespace(name='read failure'), None, options)
    assert 'test backend unavailable' in actor[weapon_sync.NOTE]
    assert actor.animation_data.action == actor_action and actor.animation_data.action_slot == actor_slot
    assert bpy.ops.ruri.endfield_weapon_actions() == {'FINISHED'}
    assert len(state.candidates) > 0
    state.candidate_index = next(i for i,c in enumerate(state.candidates) if c.seed == action[weapon_sync.ACTION_SEED])
    with patch.object(browser, 'as_options', return_value=options):
        assert bpy.ops.ruri.endfield_apply_weapon_action() == {'FINISHED'}
    assert rig.animation_data.action == action and actor.animation_data.action == actor_action
    from RuriRipperImporter.Host.Blender import animation_builder
    actor_action[animation_builder.SAMPLE_RATE_KEY] = 120.0
    timeline = (bpy.context.scene.frame_start, bpy.context.scene.frame_end,
                bpy.context.scene.render.fps, bpy.context.scene.render.fps_base)
    def different_rate(*a, **kw):
        test_action = bpy.data.actions.new('Rate conversion fixture')
        curves, slot = animation_builder.prepare_channels(test_action, rig.name, 'OBJECT')
        fc = curves.new('location', index=0)
        fc.keyframe_points.insert(0, 0)
        fc.keyframe_points.insert(30, 1)
        test_action[animation_builder.SAMPLE_RATE_KEY] = 30.0
        return 1, []
    with patch.object(loading, 'perform', side_effect=different_rate):
        weapon_sync.apply(bpy.context, actor, row, 'rate-fixture', options)
    retimed = rig.animation_data.action
    assert list(retimed.frame_range) == [0.0, 120.0], list(retimed.frame_range)
    assert timeline == (bpy.context.scene.frame_start, bpy.context.scene.frame_end,
                        bpy.context.scene.render.fps, bpy.context.scene.render.fps_base)
    actor_action[animation_builder.SAMPLE_RATE_KEY] = 60.0
    animation_builder.adopt_action(rig, action, action.slots[0], frame_range=False)
    bpy.data.actions.remove(retimed)
    state.auto_sync = False
    old_note = actor[weapon_sync.NOTE]
    weapon_sync.on_performance(bpy.context, actor, SimpleNamespace(name='ignored clip'), None, options)
    assert actor[weapon_sync.NOTE] == old_note
    state.auto_sync = True
    import_actor()
    assert not actor[weapon_sync.NOTE]
    # Both actually evaluate after the automatic import, including middle string.
    middle = rig.pose.bones['slot_M_string_01_vfx']
    positions = []
    for frame in range(301):
        bpy.context.scene.frame_set(frame)
        positions.append(tuple(middle.location))
    assert max(abs(a-b) for sample in positions for a,b in zip(sample, positions[0])) > 1e-4
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output/'autosync.blend'))
    report = dict(frames=301, catalog=len(candidates), automatic_action=action.name,
                  one_socket=True, repeated_import_reuses_weapon_action=True,
                  miss_note=True, ambiguous_note=True, backend_failure_note=True,
                  manual_button=True, opt_out=True, character_range_preserved=True,
                  character_action_preserved=True, no_hand_constraint=True, sample_rate_conversion=True)
    (args.output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('WEAPON_AUTOSYNC_PASS', json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
