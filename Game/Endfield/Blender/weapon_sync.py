"""Optional weapon companions for the ordinary character animation import path."""
import bpy

from ....Host.Blender import animation_builder, rig_identity
from ....Kernel.app import loading
from .. import datasets

NOTE = 'ruri_weapon_note'
LAST_CLIP = 'ruri_weapon_last_clip'
ACTION_SEED = 'ruri_weapon_action_seed'
ACTION_OWNER = 'ruri_weapon_action_owner'


def catalog(row, clip_name=''):
    return datasets._rows('endfield.weapon.animations', weapon=row['seed'],
                          character=row['character'], clip=clip_name)


def owned_sockets(actor):
    from . import weapons
    return [obj for obj in bpy.data.objects if obj.get(weapons.OWNER) == actor]


def is_weapon(rig):
    from . import weapons
    parent = rig.parent
    while parent:
        if parent.get(weapons.OWNER):
            return True
        parent = parent.parent
    return False


def apply(context, actor, row, seed, options):
    from . import weapons
    socket, _ = weapons.attach(context, actor, row, options)
    rigs = [obj for obj in socket.children_recursive if obj.type == 'ARMATURE']
    if len(rigs) != 1:
        raise ValueError('该武器没有唯一的动画骨架')
    rig = rigs[0]
    if rig.animation_data and any(not track.mute for track in rig.animation_data.nla_tracks):
        raise ValueError('武器已有启用的 NLA 轨道，请先处理混合再同步')
    scene = context.scene
    rate = scene.render.fps / scene.render.fps_base
    actor_action = actor.animation_data.action if actor.animation_data else None
    if actor_action:
        rate = float(actor_action.get(animation_builder.SAMPLE_RATE_KEY, rate))
    cached = [a for a in bpy.data.actions if a.get(ACTION_SEED) == seed
              and a.get(ACTION_OWNER) == rig and a.get('ruri_weapon_sync_rate') == rate]
    if len(cached) == 1:
        action = cached[0]
        animation_builder.adopt_action(rig, action, action.slots[0], frame_range=False)
        context.scene.frame_set(scene.frame_current, subframe=scene.frame_subframe)
        return
    before = set(bpy.data.actions)
    try:
        count, lines = loading.perform(context, [seed], rig,
                                       dict(options, skip_companions=True), activate=False)
        new = set(bpy.data.actions) - before
        if count != 1 or len(new) != 1:
            raise ValueError('请选择单个武器动作：' + '; '.join(lines))
        action = next(iter(new))
        curves = [fc for layer in action.layers for strip in layer.strips
                  for bag in strip.channelbags for fc in bag.fcurves]
        if not curves:
            raise ValueError('动作没有匹配此武器的骨骼通道')
        source_rate = float(action.get(animation_builder.SAMPLE_RATE_KEY, rate))
        if source_rate <= 0 or rate <= 0:
            raise ValueError('动作采样率无效')
        # Share seconds, not equal sample indices. Do not stretch to equal durations:
        # a 282-frame weapon clip and a 301-frame body clip are different spans.
        factor = rate / source_rate
        if abs(factor - 1) > 1e-8:
            for curve in curves:
                for point in curve.keyframe_points:
                    point.co.x *= factor
                    point.handle_left.x *= factor
                    point.handle_right.x *= factor
                curve.update()
        action[ACTION_SEED] = seed
        action[ACTION_OWNER] = rig
        action['ruri_weapon_sync_rate'] = rate
        action[animation_builder.SAMPLE_RATE_KEY] = rate
        animation_builder.adopt_action(rig, action, action.slots[0], frame_range=False)
        context.scene.frame_set(scene.frame_current, subframe=scene.frame_subframe)
    except Exception:
        for action in set(bpy.data.actions) - before:
            if not rig.animation_data or rig.animation_data.action != action:
                action.use_fake_user = False
                if action.users == 0:
                    bpy.data.actions.remove(action)
        raise


def on_performance(context, actor, clip, landed, options):
    from . import weapons
    if actor.type != 'ARMATURE' or is_weapon(actor):
        return
    if (rig_identity.source_of(actor) or options.get('source_game')) != 'Endfield':
        return
    state = getattr(context.scene, weapons.STATE)
    if not state.auto_sync:
        return
    state.actor = actor
    actor[LAST_CLIP] = clip.name
    state.candidates.clear()
    if actor.animation_data and any(not track.mute for track in actor.animation_data.nla_tracks):
        actor[NOTE] = '角色有启用的 NLA 混合，武器动作请手动选择；角色导入已完成'
        return
    notes = []
    try:
        rows = weapons.rows_for(actor)
        weapons.populate_slots(state, actor, rows)
        attached = {int(o[weapons.SLOT]) for o in owned_sockets(actor)}
        eligible = [r for r in rows if r['mode'] == state.mode and r['status'] == 'ready'
                    and (r['visible'] or int(r['slot']) in attached)]
        if not eligible:
            notes.append('当前状态没有可自动挂接的固定武器，可手动选择或忽略')
        for row in eligible:
            try:
                matches = [r for r in catalog(row, clip.name) if r['match']]
                if len(matches) != 1:
                    notes.append('槽 %d：%s，可手动选择或忽略' % (int(row['slot']),
                                 '未匹配动作' if not matches else '多个候选，未自动选择'))
                    if int(row['slot']) in attached:
                        notes.append('现有武器动作保持不变')
                    continue
                apply(context, actor, row, matches[0]['seed'], options)
            except Exception as exc:
                notes.append('槽 %d：%s' % (int(row['slot']), str(exc).splitlines()[0][:180]))
    except Exception as exc:
        notes.append('武器自动匹配未完成：' + str(exc).splitlines()[0][:180])
    actor[NOTE] = '\n'.join(notes)
    # Only the companion result changes here. The character's already imported
    # Action, active slot, playback range and frame rate are never reassigned.


def manual_refresh(context):
    from . import weapons
    state = getattr(context.scene, weapons.STATE)
    actor = state.actor
    if not actor:
        raise ValueError('请先指定角色')
    rows = weapons.rows_for(actor)
    if not state.rows or state.seed != rig_identity.seed_of(actor):
        weapons.populate_slots(state, actor, rows)
    selected = state.rows[state.index]
    row = next(r for r in rows if int(r['slot']) == selected.slot and r['mode'] == state.mode)
    state.candidates.clear()
    state.candidate_slot = selected.slot
    state.candidate_seed = rig_identity.seed_of(actor)
    for candidate in catalog(row, actor.get(LAST_CLIP, '')):
        entry = state.candidates.add()
        entry.name = candidate['name']
        entry.seed = candidate['seed']
    state.candidate_index = 0
    if not state.candidates:
        actor[NOTE] = '此武器目录没有可选动作；可以忽略，角色动作保持不变'


def manual_apply(context):
    from . import weapons
    from ....Kernel.app import browser
    state = getattr(context.scene, weapons.STATE)
    actor = state.actor
    if not actor or state.candidate_seed != rig_identity.seed_of(actor):
        raise ValueError('角色已变化，请重新读取武器动作')
    if not state.candidates or state.rows[state.index].slot != state.candidate_slot:
        raise ValueError('武器已变化，请重新读取武器动作')
    row = next(r for r in weapons.rows_for(actor)
               if int(r['slot']) == state.candidate_slot and r['mode'] == state.mode)
    seed = state.candidates[state.candidate_index].seed
    # Validate persisted UI state against the current game's library.
    if seed not in {r['seed'] for r in catalog(row)}:
        raise ValueError('动作已不在当前武器目录，请刷新')
    apply(context, actor, row, seed, browser.as_options(browser.state_of(context)))
    actor[NOTE] = '已手动加载武器动作；角色动作保持不变'
