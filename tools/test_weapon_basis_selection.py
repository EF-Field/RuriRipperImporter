"""Regression for attaching a standalone import to a bone and retaining a play target."""
import importlib.util
import os
from pathlib import Path
import sys


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--backend', required=True)
    p.add_argument('--deps', required=True)
    p.add_argument('--game-root', required=True)
    p.add_argument('--probe', action='store_true')
    p.add_argument('--actor-clip')
    p.add_argument('--output')
    args = p.parse_args(sys.argv[sys.argv.index('--')+1:])
    sys.path.insert(0, args.deps)
    os.environ['RURI_RIPPERHOOK_BIN'] = args.backend
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('RuriRipperImporter', root/'__init__.py',
                                                submodule_search_locations=[str(root)])
    addon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = addon
    spec.loader.exec_module(addon)
    addon.register()
    import bpy
    from mathutils import Matrix
    from RuriRipperImporter.Kernel.bridge import pythonnet_bridge as pn, cabmap_state
    from RuriRipperImporter.Kernel import statement, host
    from RuriRipperImporter.Game.Endfield.Blender import weapons
    bridge = pn.RipperBridge('Endfield_1.5.3', args.game_root)
    bridge.load_cab_map(str(Path(args.game_root)/'Endfield.cabmap'))
    cabmap_state.BRIDGE = bridge
    socket = next(o for o in bpy.data.objects if weapons.OWNER in o)
    actor = socket[weapons.OWNER]
    weapon = next(o for o in socket.children_recursive if o.type == 'ARMATURE')
    turn = Matrix(statement.basis('blender')['root'].tolist())
    error = max(abs(weapon.matrix_basis[i][j] - (turn.inverted() @ weapon.matrix_basis)[i][j])
                for i in range(4) for j in range(4))
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    bpy.context.view_layer.objects.active = None
    print('REPRO', 'standalone_root', list(turn), 'double_turn_difference', error,
          'unselected_play_target', host.selected_rig(bpy.context), flush=True)
    if args.probe:
        return
    # Synthetic imported roots emulate a standalone import, using the actual basis
    # table, not a guessed half-turn. The authored local offset must survive.
    from unittest.mock import patch
    from RuriRipperImporter.Host.Blender import rig_identity
    from RuriRipperImporter.Kernel.statement import Built
    offset = Matrix.Translation((0.1, 0.2, 0.3))
    imported = []
    def load(*a, **kw):
        mesh = bpy.data.meshes.new('weapon regression mesh')
        obj = bpy.data.objects.new('weapon regression', mesh)
        bpy.context.collection.objects.link(obj)
        obj.matrix_world = turn @ offset
        imported.append(obj)
        return Built(objects=[obj])
    bone = socket.constraints[0].subtarget
    row = dict(status='ready', seed='test', slot=997, mode='fight', scale=1,
               config='test', bone=rig_identity.of(actor).unity_name_of(bone))
    with patch.object(weapons.loading, 'load', side_effect=load):
        made, _ = weapons.attach(bpy.context, actor, row)
    actual = imported[0].matrix_basis
    assert max(abs(actual[i][j]-offset[i][j]) for i in range(4) for j in range(4)) < 1e-5, actual
    assert host.selected_rig(bpy.context) == actor, 'Adding weapon lost the character play target'
    weapon.select_set(True)
    bpy.context.view_layer.objects.active = weapon
    assert host.selected_rig(bpy.context) == weapon, 'Explicit weapon animation target was overridden'
    old_action = weapon.animation_data.action
    original = weapon.matrix_basis.copy()
    assert weapons.repair_socket(socket)
    expected = turn.inverted() @ original
    assert max(abs(weapon.matrix_basis[i][j]-expected[i][j]) for i in range(4) for j in range(4)) < 1e-5
    assert not weapons.repair_socket(socket)
    assert weapon.animation_data.action == old_action
    if args.actor_clip:
        # Same stepped route used by ruri.import_selected, without an explicit rig.
        # Isolate only browser display bookkeeping, not selection or clip loading.
        from RuriRipperImporter.Kernel.app import browser
        from contextlib import ExitStack
        from types import SimpleNamespace
        weapons.select_actor(bpy.context, actor)
        actor.animation_data_clear()
        with ExitStack() as stack:
            stack.enter_context(patch.object(browser, 'as_options', return_value={}))
            for name in ('_sync_texture_roles', '_rebuild_window', '_redraw', '_announce'):
                stack.enter_context(patch.object(browser, name))
            list(browser._load_steps(bpy.context, SimpleNamespace(), [], [args.actor_clip], False))
        assert actor.animation_data and actor.animation_data.action
        assert weapon.animation_data.action == old_action
        print('IMPORT_SELECTED_AFTER_WEAPON_PASS', actor.animation_data.action.name, flush=True)
    bpy.data.objects.remove(imported[0], do_unlink=True)
    bpy.data.objects.remove(made, do_unlink=True)
    if args.output:
        bpy.context.scene.frame_set(9)
        bpy.ops.wm.save_as_mainfile(filepath=args.output)
    print('WEAPON_BASIS_SELECTION_PASS', flush=True)


if __name__ == '__main__':
    main()
