"""Real Blender/Statement migration regression using external private fixtures.

Run in a fresh factory-startup process. No installed add-on or preferences are
modified. Numeric references are comparison inputs, never animation sources.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector


def arguments():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backend', required=True, type=Path)
    p.add_argument('--addon-source', type=Path)
    p.add_argument('--deps', required=True, type=Path)
    p.add_argument('--game-root', required=True, type=Path)
    p.add_argument('--cabmap', required=True, type=Path)
    p.add_argument('--decoder', required=True)
    p.add_argument('--character', required=True)
    p.add_argument('--attack-seed', required=True)
    p.add_argument('--reference', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--dense-fixtures', type=Path)
    p.add_argument('--native', action='store_true')
    return p.parse_args(sys.argv[sys.argv.index('--') + 1:])


def finite_actions(actions, animation_builder):
    result = []
    for action in sorted(actions, key=lambda a: a.name):
        curves = animation_builder.channels_of(action, action.slots[0])
        keys = 0
        for fc in curves:
            co = np.empty(len(fc.keyframe_points) * 2, dtype=np.float32)
            fc.keyframe_points.foreach_get('co', co)
            assert np.isfinite(co).all(), (action.name, fc.data_path)
            keys += len(fc.keyframe_points)
        result.append({'name': action.name, 'curves': len(curves), 'keys': keys,
                       'range': list(action.frame_range)})
    return result


def compare_attack(rig, reference, animation_builder, rig_identity, host):
    from Ruri.RipperHook.BlenderBridge.Statements import AvatarPathAliases
    from System import Array, String
    path_to_bone = {path: bone for bone, path in rig_identity.bone_paths(rig).items()}
    avatar = json.loads(host.rig_avatar(rig))
    aliases = {p.Key: p.Value for p in AvatarPathAliases.Resolve(
        Array[String](list(avatar['Tos'].values())), Array[String](list(path_to_bone)))}
    with gzip.open(reference, 'rt') as f:
        expected = json.load(f)
    curves = animation_builder.channels_of(rig.animation_data.action,
                                            rig.animation_data.action_slot)
    C = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    worst, missing = 0.0, []
    for path in expected['frames'][0]['rotations']:
        name = path_to_bone.get('' if path == 'Root' else aliases.get(path, path))
        if name is None:
            missing.append(path)
            continue
        bone = rig.data.bones[name]
        rest = (bone.parent.matrix_local.inverted() @ bone.matrix_local
                if bone.parent else bone.matrix_local.copy())
        prefix = f'pose.bones["{bpy.utils.escape_identifier(name)}"].'
        channels = {a: [curves.find(prefix + a, index=i) for i in range(n)]
                    for a, n in [('location', 3), ('rotation_quaternion', 4), ('scale', 3)]}
        for i, frame in enumerate(expected['frames']):
            def sample(attr, default):
                return [fc.evaluate(i) if fc else default[j]
                        for j, fc in enumerate(channels[attr])]
            actual = C @ rest @ Matrix.LocRotScale(
                Vector(sample('location', (0, 0, 0))),
                Quaternion(sample('rotation_quaternion', (1, 0, 0, 0))),
                Vector(sample('scale', (1, 1, 1)))) @ C
            x, y, z, w = frame['rotations'][path]
            target = Matrix.LocRotScale(Vector(frame['positions'][path]),
                                       Quaternion((w, x, y, z)), Vector((1, 1, 1)))
            worst = max(worst, max(abs(actual[r][c] - target[r][c])
                                   for r in range(4) for c in range(4)))
    assert not missing, missing
    assert worst < 0.00015, worst
    return {'reference_paths': len(expected['frames'][0]['rotations']),
            'reference_frames': len(expected['frames']), 'missing': missing,
            'max_local_matrix_component_error': worst}


def main():
    args = arguments()
    args.output.mkdir(parents=True, exist_ok=True)
    source = (args.addon_source or Path(__file__).resolve().parents[1]).resolve()
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
    from RuriRipperImporter.Host import Blender
    from RuriRipperImporter.Host.Blender import animation_builder, rig_identity
    from RuriRipperImporter.Kernel.app import loading
    from RuriRipperImporter.Kernel.bridge import cabmap_state, pythonnet_bridge
    pythonnet_bridge.set_bin_dir(str(args.backend))
    bridge = pythonnet_bridge.RipperBridge(args.decoder, str(args.game_root))
    bridge.load_cab_map(str(args.cabmap))
    cabmap_state.BRIDGE = bridge
    captures, observed, callback_errors = {}, {}, []
    handler = None
    if args.dense_fixtures:
        from System import Action, Array, String
        from Ruri.RipperHook.Core.TypeTree import TypeTreeOverrides, TypeTreeReadContext
        from AssetRipper.SourceGenerated import ClassIDType
        captures = {x['name']: x for x in json.loads(
            (args.dense_fixtures / 'dense_captures.json').read_text())}
        def observe(c):
            try:
                asset = c.Asset
                name = str(asset.GetType().GetProperty('Name').GetValue(asset))
                if name not in captures:
                    return
                muscle = asset.GetType().GetProperty('MuscleClip_C74').GetValue(asset)
                dense = muscle.Clip.Data.DenseClip
                expected = np.frombuffer((args.dense_fixtures / (name + '.dense.bin')).read_bytes(),
                                         dtype='<u2').reshape(dense.FrameCount, dense.CurveCount)
                expected = expected.astype(np.float32) / np.float32(65535) * np.float32(2) - np.float32(1)
                expected[:, :captures[name]['m_NPositionCurves']] *= np.float32(captures[name]['m_PositionFactor'])
                actual = np.asarray(list(dense.SampleArray), dtype=np.float32)
                assert actual.size == expected.size, (name, actual.size, expected.size)
                assert np.array_equal(actual, expected.ravel()), name
                observed[name] = {'samples': int(actual.size), 'max_error': 0.0}
            except Exception as exc:
                callback_errors.append(str(exc))
        handler = Action[TypeTreeReadContext](observe)
        TypeTreeOverrides.RegisterPostRead(ClassIDType.AnimationClip, handler, Array[String]([]))
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    roster = bridge.game_data('endfield.roster.cast', language='en')
    seeds = [roster.cell(i, 'seed') for i in range(len(roster))
             if roster.cell(i, 'key') == args.character and roster.cell(i, 'kind') == 'Characters']
    assert len(seeds) == 1, seeds
    options = {'detail_level': 0, 'game_shaders': args.native, 'import_animations': False}
    model = loading.load(bpy.context, seeds, options)
    if args.native:
        native = [m for m in bpy.data.materials
                  if m.get('ruri_uber_stack') == 'ruri_character_uber_endfield']
        assert len(native) >= 5, [m.name for m in native]
        assert all(m.node_tree is not None for m in native)
        print('MIGRATION53_NATIVE_MATERIALS', len(native), flush=True)
    rigs = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
    assert len(rigs) == 1, [o.name for o in rigs]
    actor = rigs[0]
    bpy.context.view_layer.update()
    head = actor.matrix_world @ actor.pose.bones['Bip001_Head'].matrix.translation
    foot = actor.matrix_world @ actor.pose.bones['Bip001_L_Foot'].matrix.translation
    assert head.z - foot.z > 0.9, (head, foot)
    bpy.context.scene.render.fps = 24
    count, lines = loading.perform(bpy.context, [args.attack_seed], actor, {}, activate=True)
    assert count == 1, lines
    assert bpy.context.scene.render.fps / bpy.context.scene.render.fps_base == 60
    attack = actor.animation_data.action
    assert list(attack.frame_range) == [0.0, 300.0], list(attack.frame_range)
    report = {'blender': bpy.app.version_string, 'build_hash': bpy.app.build_hash.decode(),
              'backend_sha256': hashlib.sha256((args.backend / 'Ruri.RipperHook.dll').read_bytes()).hexdigest(),
              'native_materials': args.native, 'bones': len(actor.data.bones),
              'model_warnings': model.warnings, 'attack_warnings': lines,
              'attack': compare_attack(actor, args.reference, animation_builder, rig_identity, Blender.HOST),
              'actor_actions': finite_actions([attack], animation_builder)}
    print('MIGRATION53_ATTACK_PASS', json.dumps(report['attack']), flush=True)
    if args.dense_fixtures:
        routes = json.loads((args.dense_fixtures / 'routes.json').read_text())['wpn_misc_0051']
        weapon_seed = next(r['cab'] for r in routes if r['name'] == 'wpn_misc_0051.prefab')
        weapon_model = loading.load(bpy.context, [weapon_seed], options)
        weapon = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE' and o != actor)
        before = set(bpy.data.actions)
        captured_names = {name.casefold() for name in captures}
        clip_seeds = [r['cab'] for r in routes if r['type_names'] == 'AnimationClip'
                      and r['name'].removesuffix('.fbx').casefold() in captured_names]
        assert len(clip_seeds) == 22, len(clip_seeds)
        count, warnings = loading.perform(bpy.context, clip_seeds, weapon, {}, activate=False)
        actions = set(bpy.data.actions) - before
        assert count == 22 and len(actions) == 22, (count, len(actions), warnings)
        assert not callback_errors, callback_errors
        assert set(observed) == set(captures), sorted(set(captures) - set(observed))
        actor_before = actor.animation_data.action
        count, attack_warnings = loading.perform(bpy.context,
            [next(r['cab'] for r in routes if r['name'] == 'a_wpn_misc_0051_01_battle_attack_01.fbx')],
            weapon, {}, activate=True)
        assert count == 1, (count, attack_warnings)
        assert actor.animation_data.action == actor_before
        assert not weapon.pose.bones['slot_M_string_01_vfx'].constraints
        report['weapon'] = {'bones': len(weapon.data.bones), 'actions': finite_actions(actions, animation_builder),
                            'warnings': warnings, 'model_warnings': weapon_model.warnings,
                            'dense_source_comparisons': observed}
        print('MIGRATION53_DENSE_PASS', len(actions), len(observed), flush=True)
    scene = bpy.context.scene
    scene.frame_set(9)
    scene['migration53_boundary'] = 'Technical regression only. Visual approval pending. Raw game clips, no synthetic curve injection.'
    scene['migration53_backend_sha256'] = report['backend_sha256']
    scene['migration53_cabmap_boundary'] = 'External isolated RCM7 map; inspect provenance separately.'
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output / 'model-actions.blend'))
    report['saved_scene'] = str(args.output / 'model-actions.blend')
    report['boundary'] = 'No installed addon/preferences changed; visual review and game-runtime blending are separate.'
    (args.output / 'regression.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('MIGRATION53_REGRESSION_PASS', flush=True)


if __name__ == '__main__':
    main()
