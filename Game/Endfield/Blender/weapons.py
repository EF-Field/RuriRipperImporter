"""Blender assembly of the weapon slots the game reader publishes.

The socket follows the character; weapon bones and their Actions remain independent.
No game paths, slot numbers or bone names are inferred here.
"""

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from mathutils import Matrix

from ....Host.Blender import rig_identity
from ....Kernel.app import browser, loading
from ....Kernel.bridge import cabmap_state
from ....Kernel import statement
from .. import datasets

STATE = 'ruri_endfield_weapons'
OWNER = 'ruri_weapon_owner'
SLOT = 'ruri_weapon_slot'
SPACE_VERSION = 'ruri_weapon_space_version'
STATUSES = {
    'ready': '就绪', 'equipment_required': '需要装备选择',
    'cross_weapon_mount': '需要跨武器挂接', 'missing_mount': '挂点未解析',
    'missing_or_ambiguous_prefab': '武器资源未唯一解析',
}


def rows_for(actor):
    seed = rig_identity.seed_of(actor)
    if not seed:
        raise ValueError('请选择由插件导入、带来源信息的角色骨架')
    if cabmap_state.BRIDGE is None:
        raise ValueError('请先在资源浏览器打开游戏目录与索引')
    return datasets._rows(datasets.WEAPONS, seed=seed)


def select_actor(context, actor):
    for obj in context.selected_objects:
        obj.select_set(False)
    actor.hide_set(False)
    actor.select_set(True)
    context.view_layer.objects.active = actor


def attachment_basis():
    # A standalone import has a host-facing root turn. The actor's socket already
    # carries that turn. Retain authored transforms, remove only the declared frame.
    return Matrix(statement.basis('blender')['root'].tolist()).inverted()


def repair_socket(socket):
    if int(socket.get(SPACE_VERSION, 1)) >= 2:
        return False
    turn = attachment_basis()
    for child in socket.children:
        child.matrix_basis = turn @ child.matrix_basis
    socket[SPACE_VERSION] = 2
    return True


def attach(context, actor, row, options=None):
    """Attach one resolved slot transactionally. Repeated requests reuse its socket."""
    if context.mode != 'OBJECT':
        raise ValueError('请切换到物体模式')
    if actor is None or actor.type != 'ARMATURE' or actor.name not in context.scene.objects:
        raise ValueError('请选择当前场景中的角色骨架')
    if row['status'] != 'ready' or not row['seed']:
        raise ValueError(STATUSES.get(row['status'], row['status']))
    identity = rig_identity.of(actor)
    if identity is None:
        raise ValueError('角色缺少骨骼来源标记，请使用插件重新导入')
    bone = identity.bone_of(row['bone'])
    if not bone or row['bone'] in identity.ambiguous_unity_names:
        raise ValueError('角色挂点缺失或重名：' + row['bone'])
    slot = int(row['slot'])
    existing = [o for o in bpy.data.objects if o.get(OWNER) == actor and o.get(SLOT) == slot]
    if existing:
        if len(existing) != 1:
            raise ValueError('该槽位已有多个挂接，请先整理重复对象')
        socket = existing[0]
        if socket.get('ruri_weapon_seed') != row['seed'] or socket.get('ruri_weapon_mode') != row['mode']:
            raise ValueError('该槽位已有其他武器或挂接状态；请先移除原挂接')
        if not socket.children:
            raise ValueError('该槽位的武器对象已被移除；请先删除空挂接再添加')
        constraints = list(socket.constraints)
        if (socket.name not in context.scene.objects or len(constraints) != 1
                or constraints[0].type != 'COPY_TRANSFORMS' or constraints[0].target != actor
                or constraints[0].subtarget != bone or constraints[0].mute
                or constraints[0].influence != 1):
            raise ValueError('现有挂接已被修改；请先检查该槽位的约束')
        if int(socket.get(SPACE_VERSION, 1)) < 2:
            raise ValueError('此挂接来自旧版，请点击“修复旧挂接方向”')
        select_actor(context, actor)
        return socket, False
    before = set(bpy.data.objects)
    data_before = {name: set(getattr(bpy.data, name)) for name in
                   ('meshes', 'armatures', 'materials', 'images', 'actions', 'collections', 'node_groups')}
    selected = list(context.selected_objects)
    active = context.view_layer.objects.active
    frame, subframe = context.scene.frame_current, context.scene.frame_subframe
    succeeded = False
    try:
        # The normal import route retains shader options and separate rig identity.
        built = loading.load(context, [row['seed']], options or {})
        created = set(bpy.data.objects) - before
        if not created or not any(o.type == 'MESH' for o in created) or built.missing:
            raise ValueError('武器导入不完整：' + '; '.join(map(str, built.missing or built.warnings)))
        roots = [o for o in created if o.parent not in created]
        socket = bpy.data.objects.new('Weapon slot %d' % slot, None)
        context.collection.objects.link(socket)
        socket.empty_display_type = 'PLAIN_AXES'
        socket.empty_display_size = 0.08
        constraint = socket.constraints.new('COPY_TRANSFORMS')
        constraint.name = 'Character weapon mount'
        constraint.target = actor
        constraint.subtarget = bone
        constraint.target_space = 'WORLD'
        constraint.owner_space = 'WORLD'
        constraint.head_tail = 0
        for obj in roots:
            local = obj.matrix_world.copy()
            obj.parent = socket
            obj.matrix_parent_inverse = Matrix.Identity(4)
            obj.matrix_basis = Matrix.Scale(float(row['scale']), 4) @ attachment_basis() @ local
        socket[OWNER] = actor  # ID reference survives renames and save/reopen.
        socket[SLOT] = slot
        socket[SPACE_VERSION] = 2
        socket['ruri_weapon_seed'] = row['seed']
        socket['ruri_weapon_mode'] = row['mode']
        socket['ruri_weapon_config'] = row['config']
        socket['ruri_weapon_warnings'] = '\n'.join(built.warnings)
        context.view_layer.update()
        succeeded = True
        return socket, True
    except Exception:
        # Remove only this transaction's objects, including a partially built rig.
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for obj in set(bpy.data.objects) - before:
            bpy.data.objects.remove(obj, do_unlink=True)
        for name, prior in data_before.items():
            blocks = getattr(bpy.data, name)
            for block in set(blocks) - prior:
                if block.users == 0:
                    blocks.remove(block)
        raise
    finally:
        context.scene.frame_set(frame, subframe=subframe)
        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in selected:
            if obj.name in context.view_layer.objects:
                obj.select_set(True)
        context.view_layer.objects.active = active
        if succeeded:
            select_actor(context, actor)


class RURI_PG_weapon_row(bpy.types.PropertyGroup):
    slot: IntProperty()
    mode: StringProperty()
    status: StringProperty()
    detail: StringProperty()


class RURI_PG_weapon_action(bpy.types.PropertyGroup):
    seed: StringProperty()


class RURI_PG_weapons(bpy.types.PropertyGroup):
    actor: PointerProperty(name='角色', type=bpy.types.Object,
                           poll=lambda self, obj: obj.type == 'ARMATURE')
    seed: StringProperty()
    mode: EnumProperty(name='状态', items=[('fight', '战斗', ''), ('idle', '待机', '')], default='fight')
    rows: CollectionProperty(type=RURI_PG_weapon_row)
    index: IntProperty()
    auto_sync: BoolProperty(name='导入角色动作时自动匹配武器', default=True)
    candidates: CollectionProperty(type=RURI_PG_weapon_action)
    candidate_index: IntProperty()
    candidate_slot: IntProperty(default=-1)
    candidate_seed: StringProperty()


def populate_slots(state, actor, rows):
    state.rows.clear()
    state.actor = actor
    state.seed = rig_identity.seed_of(actor)
    for row in sorted(rows, key=lambda r: (r['status'] != 'ready', not bool(r['visible']), int(r['slot']))):
        if row['mode'] != state.mode:
            continue
        item = state.rows.add()
        item.slot, item.mode, item.status = int(row['slot']), row['mode'], row['status']
        item.name = '%d · %s' % (item.slot, row['weapon'].rsplit('/', 1)[-1] or '装备武器')
        item.detail = '%s · %s%s' % (STATUSES.get(row['status'], row['status']), row['bone'],
                                    '' if row['visible'] else ' · 默认隐藏（技能时序未接入）')
    state.index = 0


class RURI_OT_read_weapons(bpy.types.Operator):
    bl_idname = 'ruri.endfield_read_weapons'
    bl_label = '读取角色武器'
    bl_description = '从游戏配置读取固定武器、可见状态和挂点'

    def execute(self, context):
        state = getattr(context.scene, STATE)
        actor = state.actor or rig_identity.armature_of(context.object)
        state.rows.clear()
        state.seed = ''
        try:
            rows = rows_for(actor)
            populate_slots(state, actor, rows)
            state.candidates.clear()
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class RURI_OT_add_weapon(bpy.types.Operator):
    bl_idname = 'ruri.endfield_add_weapon'
    bl_label = '添加武器到角色'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        state = getattr(context.scene, STATE)
        try:
            if not state.actor or rig_identity.seed_of(state.actor) != state.seed or not state.rows:
                raise ValueError('角色已改变，请重新读取武器配置')
            selected = state.rows[state.index]
            if selected.mode != state.mode:
                raise ValueError('状态已改变，请重新读取武器配置')
            # Resolve again through the current session; persisted UI rows are not authority.
            row = next(r for r in rows_for(state.actor)
                       if int(r['slot']) == selected.slot and r['mode'] == state.mode)
            options = browser.as_options(browser.state_of(context))
            socket, created = attach(context, state.actor, row, options)
            self.report({'INFO'}, '已添加：' + socket.name if created else '该槽位已添加，保留现有武器与动画')
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


def draw_mount(layout, context):
    state = getattr(context.scene, STATE)
    layout.prop(state, 'auto_sync')
    layout.prop(state, 'actor')
    layout.operator('ruri.endfield_select_weapon_actor', text='选择角色（继续导入角色动作）')
    layout.prop(state, 'mode')
    layout.operator(RURI_OT_read_weapons.bl_idname)
    layout.template_list('UI_UL_list', 'endfield_weapons', state, 'rows', state, 'index', rows=4)
    if 0 <= state.index < len(state.rows):
        selected = state.rows[state.index]
        layout.label(text=selected.detail)
        row = layout.row()
        row.enabled = selected.status == 'ready' and selected.mode == state.mode
        row.operator(RURI_OT_add_weapon.bl_idname, icon='ADD')
    from . import weapon_sync
    if state.actor and state.actor.get(weapon_sync.NOTE):
        box = layout.box()
        box.label(text='Note', icon='INFO')
        for line in state.actor[weapon_sync.NOTE].splitlines():
            box.label(text=line)
    layout.operator('ruri.endfield_weapon_actions', text='读取可选武器动作')
    if state.candidates:
        layout.template_list('UI_UL_list', 'weapon_actions', state, 'candidates',
                             state, 'candidate_index', rows=3)
        layout.operator('ruri.endfield_apply_weapon_action', text='加载此武器动作（可不选）', icon='ACTION')
    layout.label(text='仅唯一完整动作名匹配自动加载；其余留待选择')
    layout.label(text='隐藏槽位手动预览；技能切换与特效未接入')
    if state.actor and any(o.get(OWNER) == state.actor and int(o.get(SPACE_VERSION, 1)) < 2
                           for o in context.scene.objects):
        layout.operator('ruri.endfield_repair_weapon_basis')


class RURI_OT_select_weapon_actor(bpy.types.Operator):
    bl_idname = 'ruri.endfield_select_weapon_actor'
    bl_label = '选择角色'

    def execute(self, context):
        actor = getattr(context.scene, STATE).actor
        if not actor or actor.name not in context.view_layer.objects or context.mode != 'OBJECT':
            self.report({'ERROR'}, '请在物体模式指定当前视图层的角色骨架')
            return {'CANCELLED'}
        select_actor(context, actor)
        return {'FINISHED'}


class RURI_OT_repair_weapon_basis(bpy.types.Operator):
    bl_idname = 'ruri.endfield_repair_weapon_basis'
    bl_label = '修复旧挂接方向'
    bl_description = '仅对本功能旧版创建的挂接移除重复导入朝向；保留武器动作'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        state = getattr(context.scene, STATE)
        if not state.actor or context.mode != 'OBJECT':
            return {'CANCELLED'}
        try:
            sockets = [o for o in context.scene.objects if o.get(OWNER) == state.actor]
            count = sum(repair_socket(o) for o in sockets)
            select_actor(context, state.actor)
            context.view_layer.update()
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, '已修复 %d 个旧挂接，武器动作保持不变' % count)
        return {'FINISHED'}


class RURI_OT_weapon_actions(bpy.types.Operator):
    bl_idname = 'ruri.endfield_weapon_actions'
    bl_label = '读取可选武器动作'

    def execute(self, context):
        from . import weapon_sync
        try:
            weapon_sync.manual_refresh(context)
        except Exception as exc:
            self.report({'WARNING'}, str(exc).splitlines()[0])
            return {'CANCELLED'}
        return {'FINISHED'}


class RURI_OT_apply_weapon_action(bpy.types.Operator):
    bl_idname = 'ruri.endfield_apply_weapon_action'
    bl_label = '加载此武器动作'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from . import weapon_sync
        try:
            weapon_sync.manual_apply(context)
        except Exception as exc:
            actor = getattr(context.scene, STATE).actor
            if actor:
                actor[weapon_sync.NOTE] = str(exc).splitlines()[0][:200]
            return {'CANCELLED'}
        return {'FINISHED'}


CLASSES = (RURI_PG_weapon_row, RURI_PG_weapon_action, RURI_PG_weapons, RURI_OT_read_weapons, RURI_OT_add_weapon,
           RURI_OT_select_weapon_actor, RURI_OT_repair_weapon_basis, RURI_OT_weapon_actions,
           RURI_OT_apply_weapon_action)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    setattr(bpy.types.Scene, STATE, PointerProperty(type=RURI_PG_weapons))
    from . import weapon_sync
    loading.register_performance_listener(weapon_sync.on_performance)
    from .. import weapon
    weapon.register_section('mount', draw_mount)


def unregister():
    from .. import weapon
    weapon.drop_section('mount')
    from . import weapon_sync
    loading.unregister_performance_listener(weapon_sync.on_performance)
    delattr(bpy.types.Scene, STATE)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
