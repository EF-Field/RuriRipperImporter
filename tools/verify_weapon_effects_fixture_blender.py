"""Opt-in real-Blender regression; source fixtures are not gameplay/visual proof.

Invoke Blender with --background --factory-startup --disable-autoexec --python
this file -- --deps PATH --backend PATH --output PATH.json. All artifacts are
written beside the requested report. A second clean Blender process checks the
saved ID pointers with --mode reopen; no existing user scene is opened/changed.
"""
import argparse
from contextlib import nullcontext
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
from types import SimpleNamespace
from unittest.mock import patch


def bootstrap(args):
    sys.path.insert(0, str(Path(args.deps).resolve()))
    os.environ['RURI_RIPPERHOOK_BIN'] = str(Path(args.backend).resolve())
    os.environ['RURI_RIPPER_WORKSPACE'] = str(Path(args.output).resolve().parent / 'fixture-workspace')
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        'RuriRipperImporter', root / '__init__.py',
        submodule_search_locations=[str(root)])
    addon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = addon
    spec.loader.exec_module(addon)
    addon._DRIVER.reload_modules()
    from RuriRipperImporter.Kernel import bootstrap as runtime_bootstrap
    with patch.object(runtime_bootstrap, 'configure'):
        addon._DRIVER.register()
    from RuriRipperImporter.Game.Endfield.Blender import weapon_effects
    return weapon_effects


def snapshot(effects):
    import bpy
    return {name: set(getattr(bpy.data, name))
            for name in ('objects',) + effects.DATA_BLOCKS}


def matrix_error(actual, expected):
    return max(abs(actual[i][j] - expected[i][j]) for i in range(4) for j in range(4))


def assert_snapshot(effects, before):
    after = snapshot(effects)
    changes = {name: dict(added=[dict(name=block.name, users=block.users,
                                     fake_user=block.use_fake_user)
                                for block in after[name] - before[name]],
                         removed=[block.name for block in before[name] - after[name]])
               for name in before if before[name] != after[name]}
    assert not changes, changes


def require_error(call):
    try:
        call()
    except (ValueError, RuntimeError) as exc:
        return str(exc)
    raise AssertionError('Expected a validation/transaction error')


def run_case(report, name, call):
    try:
        details = call()
        report['cases'].append(dict(name=name, passed=True, details=details))
    except Exception:
        report['cases'].append(dict(name=name, passed=False, error=traceback.format_exc()))


def armature(name):
    import bpy
    rig = bpy.data.objects.new(name, bpy.data.armatures.new(name + ' data'))
    bpy.context.collection.objects.link(rig)
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    bone = rig.data.edit_bones.new('fixture_socket')
    bone.head = (0, 0, 0)
    bone.tail = (0, 0, 1)
    bpy.ops.object.mode_set(mode='OBJECT')
    rig.keyframe_insert('location', frame=1)
    rig.keyframe_insert('location', frame=21)
    rig.animation_data.action.name = name + ' untouched Action'
    return rig


def context_state():
    import bpy
    context = bpy.context
    return (set(context.selected_objects), context.view_layer.objects.active,
            context.scene.frame_current, context.scene.frame_subframe)


def fixture_cases(effects, report, output):
    import bpy
    from mathutils import Matrix
    context = bpy.context
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    actor, weapon = armature('Fixture actor'), armature('Fixture weapon')
    actions = (actor.animation_data.action, weapon.animation_data.action)
    action_ranges = tuple(tuple(action.frame_range) for action in actions)
    anchor = bpy.data.objects.new('Fixture manual anchor', None)
    context.collection.objects.link(anchor)
    anchor.location = (2, -3, 4)
    context.scene.cursor.location = (7, 8, 9)
    context.scene.frame_set(13, subframe=.375)
    actor.select_set(True)
    weapon.select_set(True)
    context.view_layer.objects.active = weapon
    row = dict(status='ready', seed='fixture-source', identity='fixture-effect',
               name='Authored fixture', phase='hit', template='fixture_archery_hit')
    components = [dict(kind='transform', path='root'),
                  dict(kind='mesh', path='root/geometry'),
                  dict(kind='particle', path='root/emitter', source_only=True)]
    made = []
    calls = []
    offset = Matrix.Translation((.125, -.25, .375))
    # Declared synthetic import frame; this fixture opens no game/session.
    source_basis = Matrix.Rotation(1.1, 4, 'X')
    class Basis:
        def tolist(self):
            return [list(row) for row in source_basis]

    def rows(dataset, **kwargs):
        assert dataset == 'endfield.effect.components'
        assert kwargs == {'seed': row['seed']}
        return components

    def load(context, seeds, options):
        assert seeds == [row['seed']]
        assert options['import_empties'] and options['import_inactive']
        assert not options['import_animations'] and options['source_game'] == 'Endfield'
        calls.append(dict(options))
        mesh = bpy.data.meshes.new('Fixture effect mesh')
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new('Fixture source root', mesh)
        context.collection.objects.link(obj)
        obj.matrix_world = source_basis @ offset
        child = bpy.data.objects.new('Fixture source child', None)
        context.collection.objects.link(child)
        child.parent = obj
        child.location = (.1, .2, .3)
        made.append((obj, child))
        # The loader deliberately disturbs transient context; public API restores it.
        for selected in context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        context.scene.frame_set(67, subframe=.5)
        return SimpleNamespace(objects=[obj, child], missing=[], warnings=['fixture warning'])

    def actions_unchanged():
        assert (actor.animation_data.action, weapon.animation_data.action) == actions
        assert tuple(tuple(action.frame_range) for action in actions) == action_ranges

    with patch.object(effects.weapons.statement, 'basis', return_value={'root': Basis()}), \
            patch.object(effects.datasets, '_rows', side_effect=rows), \
            patch.object(effects.loading, 'load', side_effect=load):
        def operator_options():
            # Exercise the actual UI operator and actual browser option conversion.
            # Only the resource import is replaced, keeping this repro deterministic.
            state = getattr(context.scene, effects.STATE)
            state.actor = actor
            state.rows.clear()
            state.rows.add().payload = json.dumps(row)
            browser_state = effects.browser.state_of(context)
            old_detail = browser_state.detail_level
            captured = []
            fake_root = bpy.data.objects.new('Operator fixture result', None)
            context.collection.objects.link(fake_root)
            fake_root['ruri_effect_note'] = 'Operator fixture imported'
            def receive(ctx, target, source, options, **kwargs):
                captured.append(options)
                assert target == actor and source['identity'] == row['identity']
                return SimpleNamespace(root=fake_root)
            try:
                browser_state.detail_level = 2
                with patch.object(effects, 'import_effect', side_effect=receive):
                    result = bpy.ops.ruri.endfield_import_effect()
                assert result == {'FINISHED'}, (result, state.note)
                assert len(captured) == 1 and captured[0]['detail_level'] == 2, captured
                assert state.instance == fake_root
                return dict(operator='ruri.endfield_import_effect', browser_options_unmocked=True,
                            detail_level=captured[0]['detail_level'])
            finally:
                state.instance = None
                browser_state.detail_level = old_detail
                state.rows.clear()
                bpy.data.objects.remove(fake_root, do_unlink=True)
        run_case(report, 'ui_operator_reads_browser_state_not_scene', operator_options)

        def invalid_inputs():
            before = snapshot(effects)
            errors = [require_error(lambda: effects.import_effect(
                context, actor, dict(row, status='missing_or_ambiguous_prefab'))),
                require_error(lambda: effects.import_effect(context, actor, row, bone='missing')),
                require_error(lambda: effects.import_effect(context, actor, row,
                                                            anchor=weapon, bone='missing'))]
            assert snapshot(effects) == before
            assert not calls
            return errors
        run_case(report, 'invalid_status_and_missing_anchor_bone', invalid_inputs)

        def basic_checked():
            state = context_state()
            result = effects.import_effect(context, actor, row)
            assert result.created and result.meshes == 1 and result.particles == 1
            assert context_state() == state
            assert matrix_error(result.root.matrix_world, Matrix.Translation((7, 8, 9))) < 1e-5
            assert matrix_error(made[-1][0].matrix_basis, source_basis @ offset) < 1e-5
            repeat = effects.import_effect(context, actor, row)
            assert not repeat.created and repeat.root == result.root and len(calls) == 1
            manifest = result.root[effects.MANIFEST]
            manifest_name = manifest.name
            payload = json.loads(manifest.as_string())
            assert payload['components'] == components
            assert payload['particle_playback'] == 'pending' and payload['event_timing'] == 'UNKNOWN'
            assert manifest.use_module is False
            actions_unchanged()
            member_names = [obj.name for obj in result.root[effects.MEMBERS]]
            effects.remove_effect(context, result.root)
            assert all(name not in bpy.data.objects for name in member_names)
            assert manifest_name not in bpy.data.texts, dict(
                retained_manifest=manifest_name, users=bpy.data.texts[manifest_name].users,
                fake_user=bpy.data.texts[manifest_name].use_fake_user)
            return dict(meshes=1, particle_declarations=1, load_calls=1)
        run_case(report, 'cursor_import_idempotence_manifest_remove_context', basic_checked)

        def rollback():
            before, state = snapshot(effects), context_state()
            def partial(*args):
                built = load(*args)
                bpy.data.texts.new('Fixture partial text')
                obj = built.objects[0]
                obj.animation_data_create()
                obj.animation_data.action = bpy.data.actions.new('Fixture partial Action')
                raise RuntimeError('Fixture partial load failure')
            with patch.object(effects.loading, 'load', side_effect=partial):
                error = require_error(lambda: effects.import_effect(context, actor, row))
            assert 'partial load failure' in error
            assert_snapshot(effects, before)
            assert context_state() == state
            actions_unchanged()
            return dict(rolled_back=list(before))
        run_case(report, 'partial_load_exception_rollback_objects_meshes_texts_actions', rollback)

        def incomplete():
            before, state = snapshot(effects), context_state()
            def missing(*args):
                built = load(*args)
                built.missing = ['fixture absent dependency']
                return built
            with patch.object(effects.loading, 'load', side_effect=missing):
                require_error(lambda: effects.import_effect(context, actor, row))
            assert snapshot(effects) == before and context_state() == state
            return 'Missing dependency transaction rolled back'
        run_case(report, 'partial_result_missing_dependency_rollback', incomplete)

        def unresolved_template():
            before, state = snapshot(effects), context_state()
            original = list(components)
            try:
                components[:] = [dict(item, name=item['path'], mesh_template=json.dumps(dict(schema=1, state='UNKNOWN', reason='fixture_unresolved_source'))
                    if i == 2 else '') for i, item in enumerate(original)]
                ordinary = effects.import_effect(context, actor, row)
                assert ordinary.created, 'unresolved preview must not block ordinary source import'
                effects.remove_effect(context, ordinary.root)
                # Normal removal deliberately retains potentially shared source
                # datablocks. Measure rollback from the next transaction's start.
                before = snapshot(effects)
                def indexed(ctx, source, values):
                    return load(ctx, [row['seed']], values), {}
                with patch.object(effects.loading, 'read', return_value=nullcontext(SimpleNamespace(nodes=[]))), \
                     patch.object(effects.materialise, 'materialise_indexed', side_effect=indexed):
                    error = require_error(lambda: effects.import_effect(context, actor, row, preview_source_meshes=True))
                assert 'fixture_unresolved_source' in error
                assert_snapshot(effects, before)
                assert context_state() == state
                actions_unchanged()
                return 'Ordinary import succeeds; explicit unresolved preview rolls back imported host data'
            finally:
                components[:] = original
        run_case(report, 'private_unknown_template_is_preview_only_and_rolls_back', unresolved_template)

        def altered_hierarchy():
            result = effects.import_effect(context, actor, row)
            user_child = bpy.data.objects.new('User-added child', None)
            context.collection.objects.link(user_child)
            user_child.parent = result.root
            before = snapshot(effects)
            require_error(lambda: effects.remove_effect(context, result.root))
            require_error(lambda: effects.import_effect(context, actor, row))
            assert snapshot(effects) == before and user_child.parent == result.root
            user_child.parent = None
            effects.remove_effect(context, result.root)
            assert user_child.name in bpy.data.objects
            bpy.data.objects.remove(user_child, do_unlink=True)
            return 'Both public routes reject the changed hierarchy without deletion/import'
        run_case(report, 'modified_hierarchy_preserves_user_objects', altered_hierarchy)

        def anchored():
            state = context_state()
            result = effects.import_effect(context, actor, row, anchor=anchor)
            obj, child = made[-1]
            assert context_state() == state
            assert matrix_error(obj.matrix_basis, offset) < 1e-5
            assert matrix_error(result.root.matrix_world, anchor.matrix_world) < 1e-5
            assert matrix_error(obj.matrix_world, anchor.matrix_world @ offset) < 1e-5
            assert tuple(round(v, 5) for v in child.location) == (.1, .2, .3)
            anchor.location.x += 1
            context.view_layer.update()
            assert matrix_error(result.root.matrix_world, anchor.matrix_world) < 1e-5
            require_error(lambda: effects.import_effect(context, actor, row, anchor=weapon))
            effects.remove_effect(context, result.root)
            return 'Authored local offset survives exactly one root-basis removal'
        run_case(report, 'manual_anchor_copy_transforms_source_root_basis', anchored)

        def shared_manifest():
            result = effects.import_effect(context, actor, row)
            manifest = result.root[effects.MANIFEST]
            manifest_name = manifest.name
            holder = bpy.data.objects.new('User manifest reference', None)
            context.collection.objects.link(holder)
            holder['user_source_reference'] = manifest
            effects.remove_effect(context, result.root)
            assert holder['user_source_reference'] == bpy.data.texts[manifest_name]
            bpy.data.objects.remove(holder, do_unlink=True)
            bpy.data.texts.remove(manifest)
            return 'Externally referenced manifest retained; fixture-only holder cleaned explicitly'
        run_case(report, 'remove_preserves_externally_shared_manifest', shared_manifest)

        def rename_and_save():
            result = effects.import_effect(context, actor, row, anchor=weapon, bone='fixture_socket')
            actor.name = 'Renamed fixture actor'
            weapon.name = 'Renamed fixture weapon'
            result.root.name = 'Renamed fixture effect'
            for index, obj in enumerate(result.root[effects.MEMBERS]):
                obj.name = 'Renamed fixture member %d' % index
            result.root[effects.MANIFEST].name = 'Renamed fixture manifest.json'
            repeat = effects.import_effect(context, actor, row, anchor=weapon, bone='fixture_socket')
            assert repeat.root == result.root and not repeat.created
            assert result.root[effects.OWNER] == actor
            assert result.root['ruri_effect_anchor'] == weapon
            assert set(result.root.children_recursive) == set(result.root[effects.MEMBERS])
            expected = weapon.matrix_world @ weapon.pose.bones['fixture_socket'].matrix
            context.view_layer.update()
            assert matrix_error(result.root.matrix_world, expected) < 1e-5
            actions_unchanged()
            context.scene['weapon_effect_fixture'] = json.dumps(dict(
                row=row, root=result.root.name, actor=actor.name, weapon=weapon.name,
                actor_action=actions[0].name, weapon_action=actions[1].name,
                manifest=result.root[effects.MANIFEST].name,
                selected=sorted(obj.name for obj in context.selected_objects),
                active=context.view_layer.objects.active.name,
                frame=context.scene.frame_current, subframe=context.scene.frame_subframe))
            blend = output.with_suffix('.blend')
            bpy.context.preferences.filepaths.save_version = 0
            bpy.ops.wm.save_as_mainfile(filepath=str(blend), check_existing=False)
            return dict(saved_blend=str(blend))
        run_case(report, 'rename_pointer_identity_and_save', rename_and_save)


def reopen_cases(effects, report):
    import bpy
    context = bpy.context
    expected = json.loads(context.scene['weapon_effect_fixture'])
    root = bpy.data.objects[expected['root']]
    actor = bpy.data.objects[expected['actor']]
    weapon = bpy.data.objects[expected['weapon']]

    def validate():
        assert root[effects.OWNER] == actor and root['ruri_effect_anchor'] == weapon
        assert set(root[effects.MEMBERS]) == set(root.children_recursive)
        assert root[effects.MANIFEST] == bpy.data.texts[expected['manifest']]
        assert actor.animation_data.action == bpy.data.actions[expected['actor_action']]
        assert weapon.animation_data.action == bpy.data.actions[expected['weapon_action']]
        assert actor.animation_data.action != weapon.animation_data.action
        assert context.scene.frame_current == expected['frame']
        assert abs(context.scene.frame_subframe - expected['subframe']) < 1e-6
        assert sorted(obj.name for obj in context.selected_objects) == expected['selected']
        assert context.view_layer.objects.active.name == expected['active']
        # Idempotence must resolve renamed pointers, without any source read/load.
        with patch.object(effects.datasets, '_rows', side_effect=AssertionError('Unexpected source read')), \
                patch.object(effects.loading, 'load', side_effect=AssertionError('Unexpected reload')):
            result = effects.import_effect(context, actor, expected['row'],
                                           anchor=weapon, bone='fixture_socket')
        assert result.root == root and not result.created
        errors = []
        for frame in (1, 13, 21):
            context.scene.frame_set(frame)
            errors.append(matrix_error(root.matrix_world,
                                       weapon.matrix_world @ weapon.pose.bones['fixture_socket'].matrix))
        assert max(errors) < 1e-5, errors
        return dict(pointer_roundtrip=True, copy_transforms_max_error=max(errors))
    run_case(report, 'clean_reopen_renamed_ID_pointers_actions_context_follow', validate)

    def remove():
        members = [obj.name for obj in root[effects.MEMBERS]]
        effects.remove_effect(context, root)
        assert all(name not in bpy.data.objects for name in members + [expected['root']])
        assert expected['manifest'] not in bpy.data.texts
        assert actor.name in bpy.data.objects and weapon.name in bpy.data.objects
        return 'Managed hierarchy removed after clean reopen; actor and weapon retained'
    run_case(report, 'clean_reopen_remove', remove)


def spawn_clean_reopen(args, output):
    import bpy
    child_output = output.with_name(output.stem + '-reopen.json')
    command = [bpy.app.binary_path, '--background', '--factory-startup', '--disable-autoexec',
               str(output.with_suffix('.blend')), '--python-exit-code', '1', '--python',
               str(Path(__file__).resolve()), '--', '--mode', 'reopen',
               '--deps', args.deps, '--backend', args.backend, '--output', str(child_output)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
    output.with_name(output.stem + '-reopen.log').write_text(
        completed.stdout + '\n' + completed.stderr, encoding='utf-8')
    assert completed.returncode == 0, completed.stdout[-3000:] + completed.stderr[-3000:]
    child = json.loads(child_output.read_text(encoding='utf-8'))
    assert child['passed'], child
    return dict(report=str(child_output), cases=child['cases'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--deps', required=True)
    parser.add_argument('--backend', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--mode', choices=('fixture', 'reopen'), default='fixture')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    import bpy
    report = dict(mode=args.mode, blender=bpy.app.version_string,
                  build_hash=bpy.app.build_hash.decode(), fixture=True,
                  boundaries=['Patched source rows/load and declared synthetic root basis; real Blender data and lifecycle',
                              'No game-resource, particle-playback or rendered-appearance claim'], cases=[])
    try:
        assert report['build_hash'] == '73cfbda0a06d', report['build_hash']
        effects = bootstrap(args)
        report['source'] = dict(path=str(Path(effects.__file__).resolve()),
                              sha256=hashlib.sha256(Path(effects.__file__).read_bytes()).hexdigest())
        if args.mode == 'reopen':
            reopen_cases(effects, report)
        else:
            fixture_cases(effects, report, output)
            if all(case['passed'] for case in report['cases']):
                run_case(report, 'independent_factory_startup_reopen',
                         lambda: spawn_clean_reopen(args, output))
    except Exception:
        report['cases'].append(dict(name='initialization', passed=False, error=traceback.format_exc()))
    report['passed'] = bool(report['cases']) and all(case['passed'] for case in report['cases'])
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    marker = 'WEAPON_EFFECT_FIXTURE_PASS' if report['passed'] else 'WEAPON_EFFECT_FIXTURE_FAIL'
    output.with_suffix('.marker').write_text(marker + '\n', encoding='utf-8')
    print(marker, str(output), flush=True)
    if not report['passed']:
        raise RuntimeError(marker)


if __name__ == '__main__':
    main()
