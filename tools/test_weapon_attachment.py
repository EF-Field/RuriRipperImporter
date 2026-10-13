"""Background-only 5.3 integration regression; all game inputs stay external.

Pass --backend --deps --game-root --cabmap --character --slot --actor-clip
--weapon-clip --output after Blender's -- separator. No installed addon is used.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser()
    for name in ('backend', 'deps', 'game-root', 'cabmap', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('character', 'actor-clip', 'weapon-clip'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--slot', type=int, required=True)
    parser.add_argument('--decoder', default='Endfield_1.5.3')
    parser.add_argument('--native', action='store_true')
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
    import numpy as np
    from RuriRipperImporter.Kernel.bridge import pythonnet_bridge as pn, cabmap_state
    from RuriRipperImporter.Kernel.app import loading
    from RuriRipperImporter.Game.Endfield.Blender import weapons
    from RuriRipperImporter.Host.Blender import rig_identity
    bridge = pn.RipperBridge(args.decoder, str(args.game_root))
    bridge.load_cab_map(str(args.cabmap))
    cabmap_state.BRIDGE = bridge
    roster = bridge.game_data('endfield.roster.cast', language='en')
    seeds = [roster.cell(i, 'seed') for i in range(len(roster))
             if roster.cell(i, 'key') == args.character and roster.cell(i, 'kind') == 'Characters']
    assert len(seeds) == 1, seeds
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    options = {'game_shaders': args.native, 'import_animations': False, 'source_game': 'Endfield'}
    actor = loading.load(bpy.context, seeds, options).rig
    assert actor
    count, _ = loading.perform(bpy.context, [args.actor_clip], actor, {}, activate=True)
    assert count == 1
    action = actor.animation_data.action
    nla = tuple(actor.animation_data.nla_tracks)
    frames = range(int(action.frame_range[0]), int(action.frame_range[1]) + 1)
    def poses():
        result = []
        for frame in frames:
            bpy.context.scene.frame_set(frame)
            result.append(np.asarray([list(b.matrix) for b in actor.pose.bones]))
        return np.asarray(result)
    before = poses()
    state = getattr(bpy.context.scene, weapons.STATE)
    state.actor = actor
    assert bpy.ops.ruri.endfield_read_weapons() == {'FINISHED'}
    rows = weapons.rows_for(actor)
    row = next(r for r in rows if int(r['slot']) == args.slot and r['mode'] == 'fight')
    state.index = next(i for i, r in enumerate(state.rows) if r.slot == args.slot)
    # Test the actual button, using the same options as ordinary imports.
    with patch.object(weapons.browser, 'as_options', return_value=options):
        assert bpy.ops.ruri.endfield_add_weapon() == {'FINISHED'}
    sockets = [o for o in bpy.data.objects if o.get(weapons.OWNER) == actor]
    assert len(sockets) == 1
    socket = sockets[0]
    weapon = next(o for o in socket.children_recursive if o.type == 'ARMATURE')
    print('WEAPON_RIGS', [(o.name, len(o.data.bones), list(rig_identity.of(o).bone_to_path.items())[:6])
                         for o in socket.children_recursive if o.type == 'ARMATURE'], flush=True)
    assert actor.animation_data.action == action and tuple(actor.animation_data.nla_tracks) == nla
    assert np.array_equal(before, poses())
    count, _ = loading.perform(bpy.context, [args.weapon_clip], weapon, {}, activate=True)
    assert count == 1 and weapon.animation_data.action != action
    print('WEAPON_CHANNELS', [(fc.data_path, fc.array_index, len(fc.keyframe_points))
          for layer in weapon.animation_data.action.layers for strip in layer.strips
          for bag in strip.channelbags for fc in bag.fcurves][:8], flush=True)
    assert actor.animation_data.action == action
    assert all(not b.constraints for b in weapon.pose.bones)
    objects = set(bpy.data.objects)
    assert weapons.attach(bpy.context, actor, row, options) == (socket, False)
    assert set(bpy.data.objects) == objects
    bone = socket.constraints[0].subtarget
    actor.data.bones[bone].name = 'User renamed mount'
    actor.name = 'User renamed character'
    assert socket.constraints[0].subtarget == 'User renamed mount'
    maximum = 0.0
    moving = []
    for frame in frames:
        bpy.context.scene.frame_set(frame)
        expected = actor.matrix_world @ actor.pose.bones['User renamed mount'].matrix
        maximum = max(maximum, max(abs(socket.matrix_world[i][j] - expected[i][j])
                                   for i in range(4) for j in range(4)))
        moving.append(np.asarray([list(b.matrix_basis) for b in weapon.pose.bones]).copy())
    assert maximum < 1e-5, maximum
    movement = float(np.max(np.abs(np.asarray(moving) - np.asarray(moving[0]))))
    print('WEAPON_MOVEMENT', movement, weapon.animation_data.action.name,
          list(weapon.animation_data.action.frame_range), flush=True)
    assert movement > 1e-5, movement
    # Missing mount and malformed import both leave pre-existing objects intact.
    try:
        weapons.attach(bpy.context, actor, dict(row, slot=999, bone='missing'), options)
        raise AssertionError('missing mount accepted')
    except ValueError:
        pass
    def fail(*a, **kw):
        mesh = bpy.data.meshes.new('temporary failed import')
        obj = bpy.data.objects.new('temporary failed import', mesh)
        bpy.context.collection.objects.link(obj)
        raise ValueError('injected partial import failure')
    with patch.object(weapons.loading, 'load', side_effect=fail):
        try:
            weapons.attach(bpy.context, actor, dict(row, slot=999), options)
            raise AssertionError('partial failure accepted')
        except ValueError:
            pass
    assert set(bpy.data.objects) == objects
    assert bpy.data.meshes.get('temporary failed import') is None
    assert np.array_equal(before, poses())
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output / 'attached.blend'))
    report = {'blender': bpy.app.version_string, 'build': bpy.app.build_hash.decode(),
              'frames': len(frames), 'max_socket_error': maximum, 'actor_poses_unchanged': True,
              'independent_weapon_action': True, 'rename': True, 'duplicate': True, 'rollback': True,
              'native_materials': args.native,
              'rows': rows, 'boundary': 'Background structural/numerical regression, not visual or skill timing acceptance.'}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('WEAPON_ATTACHMENT_REGRESSION_PASS', flush=True)


if __name__ == '__main__':
    main()
