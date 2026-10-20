"""Load Expressions regression in a separate factory-startup Blender process.

The fixture and proprietary install/map are external inputs. Never run against a
user's interactive scene. This exercises the actual roster operator and samples
authored expressions through the normal host binding.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import bpy
import numpy as np


def main():
    assert bpy.app.background, 'Use a separate background Blender process.'
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('backend', 'deps', 'fixture', 'game-root', 'cabmap', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--addon-source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--decoder', required=True)
    parser.add_argument('--character', required=True)
    parser.add_argument('--scope', help='Exercise a user-pasted expression scope before the operator.')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    args.output.mkdir(parents=True, exist_ok=True)
    source = args.addon_source.resolve()
    os.environ['RURI_RIPPERHOOK_BIN'] = str(args.backend.resolve())
    os.environ['RURI_RIPPER_WORKSPACE'] = str(args.output / 'workspace')
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.deps.resolve()))
    spec = importlib.util.spec_from_file_location('RuriRipperImporter', source / '__init__.py',
                                                submodule_search_locations=[str(source)])
    addon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = addon
    spec.loader.exec_module(addon)
    addon.register()
    bpy.ops.wm.open_mainfile(filepath=str(args.fixture.resolve()))
    from RuriRipperImporter.Kernel.bridge import cabmap_state, pythonnet_bridge
    from RuriRipperImporter.Game.Endfield import face, morph_state, roster, skeletal_morph
    from RuriRipperImporter.Host import Blender
    from RuriRipperImporter.Host.Blender import animation_builder
    from RuriRipperImporter.Kernel.app import browser
    pythonnet_bridge.set_bin_dir(str(args.backend))
    bridge = pythonnet_bridge.RipperBridge(args.decoder, str(args.game_root))
    cabmap_state.BRIDGE = bridge
    config = browser._ensure_active_config(browser.state_of(bpy.context))
    bridge.load_cab_map(str(args.cabmap), key=config.key)
    cabmap_state.activate(config.key, game='Endfield')
    cabmap_state.load_rows()
    rig = next(o for o in bpy.data.objects if o.type == 'ARMATURE' and args.character in o.name)
    bpy.ops.object.select_all(action='DESELECT')
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    if args.scope:
        state = face.state_of(bpy.context)
        state.armature_name = rig.name
        state.character_token = args.scope
    if rig.animation_data:
        rig.animation_data.action = None
        for track in rig.animation_data.nla_tracks:
            track.mute = True
    assert bpy.ops.ruri.roster_refresh() == {'FINISHED'}
    roster_state = roster.state_of(bpy.context)
    roster_state.active_index = next(i for i in range(len(roster.BOUND.view))
                                    if roster.BOUND.view.key(i) == args.character)
    assert bpy.ops.ruri.roster_load_expressions() == {'FINISHED'}
    state = face.state_of(bpy.context)
    host = Blender.HOST
    assert state.library_ready, state.status
    if args.scope:
        assert state.character_token == face.identity.morph_scope(args.scope), state.character_token
    avatars = face.avatars_for(state)
    assert avatars, state.status
    table = face.table_of(state)
    bound = host.face_bindings(bpy.context, rig, table)
    assert any(how == 'via bones' and count > 0 for count, how in bound['via']), bound
    assert not bound['missing_bones'], bound['missing_bones']
    report = {'version': bpy.app.version_string, 'build_hash': bpy.app.build_hash.decode(),
              'backend_sha256': hashlib.sha256((args.backend / 'Ruri.RipperHook.dll').read_bytes()).hexdigest(),
              'rig': rig.name, 'token': state.character_token, 'status': state.status,
              'assets': len(morph_state.ASSETS), 'avatars': [a.name for a in avatars],
              'bound': len(bound['ctrls']), 'via': bound['via'], 'rest_error': bound['rest_error'],
              'missing_bones': bound['missing_bones'], 'static_checks': []}
    assert not bound['unresolved_targets'], bound['unresolved_targets']
    assert bpy.ops.ruri.character_clear() == {'FINISHED'}
    bpy.context.view_layer.update()
    def matrices():
        return np.array([list(row) for bone in rig.pose.bones for row in bone.matrix_basis])
    baseline = matrices()
    state.apply_on_click = False
    for kind in ('pose', 'emotion'):
        state.section = kind
        tested = 0
        for i, item in enumerate(state.items):
            if item.animated or not item.bound_count:
                continue
            state.items_active_index = i
            assert bpy.ops.ruri.character_apply() == {'FINISHED'}
            bpy.context.view_layer.update()
            delta = float(np.max(np.abs(matrices() - baseline)))
            assert np.isfinite(matrices()).all(), item.asset
            assert bpy.ops.ruri.character_clear() == {'FINISHED'}
            bpy.context.view_layer.update()
            reset = float(np.max(np.abs(matrices() - baseline)))
            assert reset < 1e-6, (item.asset, reset)
            if delta > 1e-6:
                report['static_checks'].append({'asset': item.asset, 'delta': delta, 'reset_error': reset})
                tested += 1
            if tested == 3:
                break
        assert tested, kind
    # Every loaded animation must yield finite weights; no discarded/clamped NaN samples.
    curves = 0
    for asset in morph_state.ASSETS.values():
        if not asset.is_animated():
            continue
        for driver in asset.drivers():
            if driver.curve is not None:
                samples = driver.curve.sample(np.linspace(0, max(asset.duration, driver.curve.last_time()), 13))
                assert np.isfinite(samples).all(), (asset.name, driver.ctrl)
                curves += 1
    report['sampled_curves'] = curves
    baked = []
    for kind in morph_state.kinds():
        state.section = kind
        candidates = [item for item in state.items if item.animated and item.bound_count and 0 < item.duration <= 5]
        if not candidates:
            continue
        item = min(candidates, key=lambda item: item.duration)
        item.selected = True
        before = set(bpy.data.actions)
        assert bpy.ops.ruri.character_build_actions() == {'FINISHED'}, state.status
        created = set(bpy.data.actions) - before
        assert created, (item.asset, state.status)
        for action in created:
            count = 0
            for fc in animation_builder.channels_of(action, action.slots[0]):
                values = np.empty(len(fc.keyframe_points) * 2, dtype=np.float32)
                fc.keyframe_points.foreach_get('co', values)
                assert np.isfinite(values).all(), (action.name, fc.data_path)
                count += len(fc.keyframe_points)
            baked.append({'action': action.name, 'keys': count})
        break
    assert baked, 'No facial animation was baked.'
    report['baked'] = baked
    if rig.animation_data:
        rig.animation_data.action = None
    assert bpy.ops.ruri.character_clear() == {'FINISHED'}
    old = (len(morph_state.ASSETS), len(state.drivers), len(table['deltas']))
    assert bpy.ops.ruri.roster_load_expressions() == {'FINISHED'}
    new = (len(morph_state.ASSETS), len(state.drivers), len(face.table_of(state)['deltas']))
    assert old == new, (old, new)
    report['repeat_load_counts'] = list(new)
    state.section = 'emotion'
    state.apply_on_click = True
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output / 'Expressions-tested.blend'))
    (args.output / 'regression.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('LOAD_EXPRESSIONS_BLENDER_PASS ' + json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
