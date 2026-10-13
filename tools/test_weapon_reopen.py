"""Run with --factory-startup --disable-autoexec and the saved regression .blend."""


def main():
    import bpy
    sockets = [o for o in bpy.data.objects if 'ruri_weapon_owner' in o]
    assert len(sockets) == 1
    socket = sockets[0]
    actor = socket['ruri_weapon_owner']
    weapon = next(o for o in socket.children_recursive if o.type == 'ARMATURE')
    assert actor.animation_data.action != weapon.animation_data.action
    constraint = socket.constraints[0]
    assert constraint.target == actor and constraint.subtarget == 'User renamed mount'
    maximum = 0.0
    middle = weapon.pose.bones.get('slot_M_string_01_vfx')
    samples = []
    for frame in range(301):
        bpy.context.scene.frame_set(frame)
        expected = actor.matrix_world @ actor.pose.bones[constraint.subtarget].matrix
        maximum = max(maximum, max(abs(socket.matrix_world[i][j] - expected[i][j])
                                   for i in range(4) for j in range(4)))
        if middle:
            samples.append(tuple(middle.location))
    assert maximum < 1e-5, maximum
    if middle:
        assert max(abs(a-b) for sample in samples for a,b in zip(sample, samples[0])) > 1e-4
        bpy.context.scene.frame_set(30)
        before = weapon.matrix_world @ middle.matrix.translation
        actor.location.x += 2
        bpy.context.view_layer.update()
        after = weapon.matrix_world @ middle.matrix.translation
        assert abs(after.x-before.x-2) < 1e-4
    assert all(not b.constraints for b in weapon.pose.bones)
    print('WEAPON_REOPEN_PASS', maximum, 'middle_string', middle is not None, flush=True)


if __name__ == '__main__':
    main()
