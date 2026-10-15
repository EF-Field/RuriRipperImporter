"""Isolated synthetic Blender regression; zero reader, game or installed-addon access.

Run factory-startup/background with --output after --. Imports the real weapon
assembler and identity reader, while replacing only resource acquisition.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--addon-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    args.output.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode = True
    import bpy
    from mathutils import Matrix, Euler, Vector
    assert bpy.app.background and bpy.app.build_hash == b'73cfbda0a06d'
    root = args.addon_root.resolve()
    for name in ['Fixture', 'Fixture.Game', 'Fixture.Game.Endfield', 'Fixture.Game.Endfield.Blender',
                 'Fixture.Host', 'Fixture.Host.Blender', 'Fixture.Kernel', 'Fixture.Kernel.app',
                 'Fixture.Kernel.bridge']:
        module = ModuleType(name)
        module.__path__ = [str(root / '/'.join(name.split('.')[1:]))]
        sys.modules[name] = module
    def stub(name, **attributes):
        module = ModuleType(name)
        module.__dict__.update(attributes)
        sys.modules[name] = module
        return module
    browser = stub('Fixture.Kernel.app.browser', as_options=lambda state: {}, state_of=lambda context: None)
    loading = stub('Fixture.Kernel.app.loading')
    bridge = stub('Fixture.Kernel.bridge.cabmap_state', BRIDGE=object())
    # An arbitrary shared host-facing turn, deliberately not a character patch.
    turn = Euler((0, 0, .73)).to_matrix().to_4x4()
    stub('Fixture.Kernel.statement', basis=lambda basis: {'root': SimpleNamespace(tolist=lambda: list(turn))})
    datasets = stub('Fixture.Game.Endfield.datasets', WEAPONS='fixture.slots',
                    WEAPON_CATALOG='fixture.catalog', WEAPON_MOUNTS='fixture.mounts')
    stub('Fixture.Game.Endfield.roster', STATE='ruri_roster')
    def module(name, path):
        spec = importlib.util.spec_from_file_location(name, root / path)
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[name] = loaded
        spec.loader.exec_module(loaded)
        return loaded
    identity = module('Fixture.Host.Blender.rig_identity', 'Host/Blender/rig_identity.py')
    contract = module('Fixture.Game.Endfield.weapon_contract', 'Game/Endfield/weapon_contract.py')
    weapons = module('Fixture.Game.Endfield.Blender.weapons', 'Game/Endfield/Blender/weapons.py')
    for cls in weapons.CLASSES:
        bpy.utils.register_class(cls)
    setattr(bpy.types.Scene, weapons.STATE, bpy.props.PointerProperty(type=weapons.RURI_PG_weapons))
    state = getattr(bpy.context.scene, weapons.STATE)
    checks = []
    def check(value, name):
        assert value, name
        checks.append(name)
    def reject(call, name):
        try:
            call()
        except ValueError:
            checks.append(name)
            return
        raise AssertionError('Expected failure: ' + name)
    def error(a, b):
        return max(abs(a[i][j] - b[i][j]) for i in range(4) for j in range(4))
    def rig(name, path, leaf):
        data = bpy.data.armatures.new(name)
        obj = bpy.data.objects.new(name, data)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        bone = data.edit_bones.new(leaf)
        bone.head, bone.tail = (.1, .2, .3), (.1, .6, .3)
        bpy.ops.object.mode_set(mode='OBJECT')
        identity.stamp(obj, {path: {'bone': leaf, 'local': [v for row in Matrix.Identity(4) for v in row]}})
        return obj
    actor = rig('Synthetic actor', 'Body/Grip', 'Grip')
    actor[identity.SEED_PROP] = 'fixture:actor'
    actor.matrix_world = Matrix.Translation((2, -1, .4)) @ Euler((.12, -.2, .3)).to_matrix().to_4x4()
    actor.pose.bones['Grip'].rotation_mode = 'XYZ'
    actor.pose.bones['Grip'].rotation_euler.z = .2
    actor.pose.bones['Grip'].keyframe_insert('rotation_euler', frame=1)
    actor.pose.bones['Grip'].rotation_euler.z = .6
    actor.pose.bones['Grip'].keyframe_insert('rotation_euler', frame=9)
    actor_action = actor.animation_data.action
    state.actor = actor
    state.mode = 'fight'
    authored = Matrix.Translation((.11, -.07, .24)) @ Euler((.3, .1, -.2)).to_matrix().to_4x4()
    imported = []
    def load(context, seeds, options):
        weapon = rig('Synthetic ' + seeds[0], 'Root/Pivot', 'Pivot')
        mesh = bpy.data.meshes.new('Synthetic weapon mesh')
        mesh.from_pydata([(0, 0, 0), (.1, 0, 0), (0, .2, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new('Synthetic weapon mesh', mesh)
        bpy.context.collection.objects.link(obj)
        obj.parent = weapon
        modifier = obj.modifiers.new('Synthetic independent rig', 'ARMATURE')
        modifier.object = weapon
        # The real materialiser assigns matrix_basis, not matrix_world. Blender
        # leaves matrix_world stale until dependency-graph evaluation. A loader
        # stub using the world setter concealed reversed rigid weapon imports.
        weapon.matrix_basis = turn @ authored
        imported.append(weapon)
        if seeds[0] == 'fixture:FAIL':
            raise ValueError('Synthetic partial import failure')
        return SimpleNamespace(missing=[], warnings=[])
    loading.load = load
    def row(slot=7, **values):
        return dict(dict(character='fixture:character', slot=slot, mode='fight', visible=False,
                         seed='fixture:A', weapon='fixture:A', bone='Grip', scale=.85, status='ready',
                         config='fixture:config', resource_kind='equipment', mount_kind='character'), **values)
    catalog = [dict(asset='Fixture A', seed='fixture:A', family='fixture', status='ready'),
               dict(asset='Fixture B', seed='fixture:B', family='fixture', status='ready'),
               dict(asset='Fixture FAIL', seed='fixture:FAIL', family='fixture', status='ready')]
    requests = []
    def rows(dataset, **args):
        requests.append((dataset, args))
        if dataset == datasets.WEAPON_CATALOG:
            return catalog
        if dataset == datasets.WEAPONS:
            choices = contract.selections(args.get('equipment', ''))
            seed = choices.get('7')
            return [row(seed=seed or '', weapon=seed or '', status='ready' if seed else 'equipment_required')]
        if dataset == datasets.WEAPON_MOUNTS:
            return mount_rows
        raise AssertionError(dataset)
    datasets._rows = rows
    check(bpy.ops.ruri.endfield_read_weapons() == {'FINISHED'}, 'read equipment placeholder')
    check(state.rows[0].resource_kind == 'equipment', 'equipment slot is distinct from fixed props')
    check(bpy.ops.ruri.endfield_scan_weapon_catalog() == {'FINISHED'}, 'catalog operator')
    check(len(state.resources) == 3 and state.resource_index == -1, 'scan has no automatic first selection')
    check(weapons.SELECTIONS not in actor, 'scan never chooses equipment')
    state.resource_index = 0
    check(bpy.ops.ruri.endfield_equip_weapon() == {'FINISHED'}, 'real equip operator')
    socket = next(o for o in bpy.data.objects if o.get(weapons.OWNER) == actor)
    weapon = next(o for o in socket.children if o.type == 'ARMATURE')
    check(error(weapon.matrix_basis, Matrix.Scale(.85, 4) @ authored) < 1e-6,
          'root turn cancelled once; authored rotation and scaled translation retained')
    snapshot = set(bpy.data.objects)
    again, created = weapons.attach(bpy.context, actor, row())
    check(again == socket and not created and set(bpy.data.objects) == snapshot, 'repeat is idempotent')
    for frame in (1, 5, 9):
        bpy.context.scene.frame_set(frame)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        target = actor.evaluated_get(depsgraph)
        expected = target.matrix_world @ target.pose.bones['Grip'].matrix
        check(error(socket.evaluated_get(depsgraph).matrix_world, expected) < 1e-5,
              'socket follows posed actor frame %d' % frame)
    actor.data.bones['Grip'].name = 'User renamed grip'
    check(weapons.attach(bpy.context, actor, row())[0] == socket, 'identity survives bone rename')
    before = set(bpy.data.objects)
    before_meshes = set(bpy.data.meshes)
    before_rigs = set(bpy.data.armatures)
    old_selection = actor[weapons.SELECTIONS]
    reject(lambda: weapons.equip_selected(bpy.context, actor, 7, 'fixture:FAIL'), 'failed switch raises')
    check(set(bpy.data.objects) == before and set(bpy.data.meshes) == before_meshes
          and set(bpy.data.armatures) == before_rigs, 'failed import cleans objects and data')
    check(actor[weapons.SELECTIONS] == old_selection and socket in bpy.data.objects[:],
          'failed switch retains old socket and explicit choice')
    check(actor.animation_data.action == actor_action, 'character action unchanged after failure')
    new_socket, made = weapons.equip_selected(bpy.context, actor, 7, 'fixture:B')
    check(made and len([o for o in bpy.data.objects if o.get(weapons.OWNER) == actor]) == 1,
          'successful replacement leaves exactly one equipment socket')
    check(contract.selections(actor[weapons.SELECTIONS]) == {'7': 'fixture:B'}, 'per-actor choice committed')
    reject(lambda: weapons.equip_selected(bpy.context, actor, 7, 'fixture:stale'), 'stale catalog rejected')
    unrelated = bpy.data.objects.new('User accessory', None)
    bpy.context.collection.objects.link(unrelated)
    unrelated.parent = new_socket
    reject(lambda: weapons.equip_selected(bpy.context, actor, 7, 'fixture:A'), 'user-added objects protect replacement')
    unrelated.parent = None

    flat = lambda m: [v for line in m for v in line]
    offset = Matrix.Translation((.17, -.08, .04)) @ Euler((-.2, .15, .1)).to_matrix().to_4x4()
    chain = [dict(path='', local=flat(Matrix.Identity(4))), dict(path='Root', local=flat(Matrix.Identity(4))),
             dict(path='Root/Pivot', local=flat(Matrix.Identity(4))), dict(path='Root/Pivot/Socket', local=flat(offset))]
    mount_rows = [dict(key=100, path='Root/Pivot/Socket', owner_path='', source='fixture:component',
                       ancestry=json.dumps(chain), status='ready', basis='blender')]
    parent = row(18, resource_kind='fixed', seed='fixture:P', scale=1)
    child = row(9, seed='fixture:C', bone='', status='cross_weapon_mount', mount_kind='weapon',
                target_slot=18, weapon_mount=100, scale=.6)
    child_socket, _ = weapons.attach(bpy.context, actor, child, rows=[child, parent])
    parent_socket = next(o for o in bpy.data.objects if o.get(weapons.OWNER) == actor and o.get(weapons.SLOT) == 18)
    parent_rig = next(o for o in parent_socket.children if o.type == 'ARMATURE')
    child_rig = next(o for o in child_socket.children if o.type == 'ARMATURE')
    check(error(child_rig.matrix_basis, offset @ Matrix.Scale(.6, 4) @ authored) < 1e-6,
          'cross-weapon nonunit scale and nonzero offset order')
    check(child_socket.constraints[0].target == parent_rig and child_socket[weapons.PARENT_SLOT] == 18,
          'cross-weapon edge uses parent rig, not actor bone')
    for frame, angle in ((1, .1), (9, .8)):
        parent_rig.pose.bones['Pivot'].rotation_mode = 'XYZ'
        parent_rig.pose.bones['Pivot'].rotation_euler.y = angle
        parent_rig.pose.bones['Pivot'].keyframe_insert('rotation_euler', frame=frame)
    positions = []
    for frame in (1, 5, 9):
        bpy.context.scene.frame_set(frame)
        dg = bpy.context.evaluated_depsgraph_get()
        target = parent_rig.evaluated_get(dg)
        expected = target.matrix_world @ target.pose.bones['Pivot'].matrix @ offset @ Matrix.Scale(.6, 4) @ authored
        actual = child_rig.evaluated_get(dg).matrix_world
        check(error(actual, expected) < 1e-5, 'cross-weapon animated world transform frame %d' % frame)
        positions.append(actual.translation.copy())
    check((positions[-1] - positions[0]).length > 1e-4, 'child follows parent weapon animation')
    reject(lambda: weapons.attach(bpy.context, actor, dict(parent, seed='fixture:other'), replace=True),
           'parent replacement protects dependent weapon')
    stable = set(bpy.data.objects)
    mount_rows.append(dict(mount_rows[0], source='fixture:second-component'))
    reject(lambda: weapons.attach(bpy.context, actor, dict(child, slot=10), rows=[parent, dict(child, slot=10)]),
           'duplicate component mount key rejected')
    check(set(bpy.data.objects) == stable, 'ambiguous mount rollback leaves scene intact')
    mount_rows.pop()
    graph_parent = dict(parent, slot=34, seed='fixture:new-parent')
    graph_child = dict(child, slot=35, target_slot=34, seed='fixture:FAIL')
    stable_meshes, stable_rigs = set(bpy.data.meshes), set(bpy.data.armatures)
    reject(lambda: weapons.attach(bpy.context, actor, graph_child, rows=[graph_child, graph_parent]),
           'child import failure rejects whole dependency graph')
    check(set(bpy.data.objects) == stable and set(bpy.data.meshes) == stable_meshes
          and set(bpy.data.armatures) == stable_rigs, 'whole dependency graph rolls back including new parent')
    cyclic = dict(child, target_slot=9)
    reject(lambda: weapons.attach(bpy.context, actor, cyclic, rows=[cyclic]), 'cycle rejected before import')
    check(set(bpy.data.objects) == stable and actor.animation_data.action == actor_action, 'cycle preserves scene/action')
    check(unrelated.name in bpy.data.objects, 'unrelated user accessory survives')

    # Rigid prefabs can produce several root empties with nested mesh children.
    # No edit-mode operation or world-matrix setter evaluates their transforms.
    rigid_roots = []
    rigid_child_local = Matrix.Translation((.04, .02, -.03)) @ Euler((.2, -.1, .3)).to_matrix().to_4x4()
    rigid_authored = [authored, Matrix.Translation((-.2, .3, .1)) @ Matrix.Diagonal((-1, 2, .5, 1))]
    def load_rigid(context, seeds, options):
        for index, local in enumerate(rigid_authored):
            root_obj = bpy.data.objects.new('Rigid root %d' % index, None)
            context.collection.objects.link(root_obj)
            data = bpy.data.meshes.new('Rigid mesh %d' % index)
            data.from_pydata([(0, 0, 0), (.1, 0, 0), (0, .2, 0)], [], [(0, 1, 2)])
            child_obj = bpy.data.objects.new('Rigid child %d' % index, data)
            context.collection.objects.link(child_obj)
            child_obj.parent = root_obj
            child_obj.matrix_basis = rigid_child_local
            root_obj.matrix_basis = turn @ local
            rigid_roots.append(root_obj)
        return SimpleNamespace(missing=[], warnings=[])
    with patch.object(loading, 'load', side_effect=load_rigid):
        rigid_socket, _ = weapons.attach(bpy.context, actor, row(77, seed='fixture:rigid'))
    target = actor.matrix_world @ actor.pose.bones['User renamed grip'].matrix
    for index, (root_obj, local) in enumerate(zip(rigid_roots, rigid_authored)):
        expected = Matrix.Scale(.85, 4) @ local
        check(error(root_obj.matrix_basis, expected) < 1e-6,
              'fresh rigid root %d evaluated before root-turn cancellation' % index)
        check(error(root_obj.children[0].matrix_world, target @ expected @ rigid_child_local) < 1e-5,
              'rigid child %d preserves authored hierarchy and transform' % index)
    for obj in list(rigid_socket.children_recursive):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.objects.remove(rigid_socket, do_unlink=True)

    bpy.ops.wm.save_as_mainfile(filepath=str(args.output / 'synthetic-equipment.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(args.output / 'synthetic-equipment.blend'), load_ui=False, use_scripts=False)
    actor = bpy.data.objects['Synthetic actor']
    check(contract.selections(actor[weapons.SELECTIONS]) == {'7': 'fixture:B'}, 'selection persists across save/reopen')
    sockets = [o for o in bpy.data.objects if o.get(weapons.OWNER) == actor]
    check(len(sockets) == 3 and all(o.constraints[0].target for o in sockets), 'attachments persist across save/reopen')
    check(actor.animation_data.action is not None, 'character action persists')
    report = dict(blender=bpy.app.version_string, build_hash=bpy.app.build_hash.decode(),
                  addon_root=str(root),
                  synthetic_only=True, reader_loaded=False, game_files_read=False,
                  checks=checks, passed=len(checks), requests=[name for name, args in requests],
                  boundary='Numerical host assembly/UI tests, not real weapon grip visual acceptance or game runtime parity.')
    (args.output / 'equipment-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('WEAPON_EQUIPMENT_SYNTHETIC_PASS', json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
