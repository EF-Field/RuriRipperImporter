"""Blender assembly of the weapon slots the game reader publishes.

The socket follows the character; weapon bones and their Actions remain independent.
No game paths, slot numbers or bone names are inferred here.
"""

import json
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from mathutils import Matrix

from ....Host.Blender import rig_identity
from ....Kernel.app import browser, loading
from ....Kernel.bridge import cabmap_state
from ....Kernel import statement
from .. import datasets
from .. import weapon_contract
from .. import names_zh

STATE = 'ruri_endfield_weapons'
OWNER = 'ruri_weapon_owner'
SLOT = 'ruri_weapon_slot'
SPACE_VERSION = 'ruri_weapon_space_version'
SELECTIONS = 'ruri_weapon_equipment'
PART = 'ruri_weapon_attachment'
PARENT_SLOT = 'ruri_weapon_parent_slot'
STATUSES = {
    'ready': '就绪', 'equipment_required': '需要装备选择',
    'cross_weapon_mount': '需要跨武器挂接', 'missing_mount': '挂点未解析',
    'missing_or_ambiguous_prefab': '武器资源未唯一解析',
    'ambiguous_prefab': '资源路径存在多个来源',
    'unclassified_resource': '尚未确认的武器资源类别',
}


def rows_for(actor, selections=None):
    seed = rig_identity.seed_of(actor)
    if not seed:
        raise ValueError('请选择由插件导入、带来源信息的角色骨架')
    if cabmap_state.BRIDGE is None:
        raise ValueError('请先在资源浏览器打开游戏目录与索引')
    choices = weapon_contract.selections(actor.get(SELECTIONS, '')) if selections is None else selections
    args = {'equipment': weapon_contract.selection_json(choices)} if choices else {}
    return datasets._rows(datasets.WEAPONS, seed=seed, **args)


def catalog_rows():
    if cabmap_state.BRIDGE is None:
        raise ValueError('请先打开资源索引，并使用匹配版本的后端')
    return datasets._rows(datasets.WEAPON_CATALOG)


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


def _target(actor, row, sockets):
    """Resolve a declared parent frame, never a leaf-name guess on another weapon."""
    if row.get('mount_kind') != 'weapon' and row['status'] != 'cross_weapon_mount':
        identity = rig_identity.of(actor)
        if identity is None:
            raise ValueError('角色缺少骨骼来源标记，请使用插件重新导入')
        bone = identity.bone_of(row['bone'])
        if not bone or row['bone'] in identity.ambiguous_unity_names:
            raise ValueError('角色挂点缺失或重名：' + row['bone'])
        return actor, bone, Matrix.Identity(4), -1
    parent_slot = weapon_contract.slot_number(row['target_slot'])
    parent = sockets[parent_slot]
    mounts = datasets._rows(datasets.WEAPON_MOUNTS, seed=parent['ruri_weapon_seed'], basis='blender')
    chain = weapon_contract.mount_ancestry(mounts, row['weapon_mount'])
    rigs = [(o, rig_identity.of(o)) for o in parent.children_recursive if o.type == 'ARMATURE']
    for index in range(len(chain) - 1, -1, -1):
        matches = [(rig, bone) for rig, identity in rigs if identity
                   for bone, path in identity.bone_to_path.items() if path == chain[index]['path']]
        if len(matches) > 1:
            raise ValueError('父武器挂点对应多个骨架，需检查完整路径身份')
        if matches:
            target, bone = matches[0]
            offset = Matrix.Identity(4)
            for node in chain[index + 1:]:
                values = node['local']
                offset = offset @ Matrix([values[i:i + 4] for i in range(0, 16, 4)])
            return target, bone, offset, parent_slot
    raise ValueError('父武器挂点尚未对应到导入骨架；保留原挂接，请检查路径或生成节点')


def _same_frame(socket, target, bone, offset):
    constraints = list(socket.constraints)
    return (len(constraints) == 1 and constraints[0].type == 'COPY_TRANSFORMS'
            and constraints[0].target == target and constraints[0].subtarget == bone
            and not constraints[0].mute and constraints[0].influence == 1
            and constraints[0].target_space == 'WORLD' and constraints[0].owner_space == 'WORLD'
            and socket.get('ruri_weapon_mount_matrix', '') == json.dumps([list(v) for v in offset]))


def _attach_one(context, actor, row, target, bone, offset, parent_slot, existing, options, replace):
    slot = int(row['slot'])
    if len(existing) > 1:
        raise ValueError('该槽位已有多个挂接，请先整理重复对象')
    old = existing[0] if existing else None
    if old:
        # Legacy direct sockets have the same identity frame but no recorded matrix.
        legacy_frame = target == actor and old.get('ruri_weapon_mount_matrix') is None
        same = (old.get('ruri_weapon_seed') == row['seed'] and old.get('ruri_weapon_mode') == row['mode']
                and old.get('ruri_weapon_scale', float(row['scale'])) == float(row['scale']))
        if same and (legacy_frame or _same_frame(old, target, bone, offset)):
            constraints = list(old.constraints)
            if (old.name not in context.scene.objects or not old.children or len(constraints) != 1
                    or constraints[0].type != 'COPY_TRANSFORMS' or constraints[0].target != target
                    or constraints[0].subtarget != bone or constraints[0].mute or constraints[0].influence != 1
                    or constraints[0].target_space != 'WORLD' or constraints[0].owner_space != 'WORLD'
                    or constraints[0].head_tail != 0
                    or int(old.get(SPACE_VERSION, 1)) < 2):
                raise ValueError('现有挂接已改变或来自旧版，请先检查约束及方向')
            return old, None
        if not replace:
            raise ValueError('该槽位已有其他武器或模式；装备武器请使用“装配／替换所选武器”')
        old_parts = list(old.children_recursive)
        if any(o.get(PART) != old for o in old_parts):
            raise ValueError('原挂接含未标记的旧版或用户对象，请先保留或手动整理')
        if any(o != old and o.get(OWNER) == actor and
               (o.get(PARENT_SLOT, -1) == slot or any(c.target in old_parts for c in o.constraints if c.type == 'COPY_TRANSFORMS'))
               for o in bpy.data.objects):
            raise ValueError('其他武器依赖此槽位，请先整理依赖挂接后再替换')
    before = set(bpy.data.objects)
    built = loading.load(context, [row['seed']], options)
    created = set(bpy.data.objects) - before
    if not created or not any(o.type == 'MESH' for o in created) or built.missing:
        raise ValueError('武器导入不完整：' + '; '.join(map(str, built.missing or built.warnings)))
    # The materialiser writes matrix_basis and parent links. matrix_world can
    # still be identity until Blender evaluates them (notably rigid weapons).
    # Read the completed standalone frame before cancelling its host root turn.
    context.view_layer.update()
    roots = [o for o in created if o.parent not in created]
    socket = bpy.data.objects.new('Weapon slot %d' % slot, None)
    context.collection.objects.link(socket)
    socket.empty_display_type = 'PLAIN_AXES'
    socket.empty_display_size = 0.08
    constraint = socket.constraints.new('COPY_TRANSFORMS')
    constraint.name = 'Authored weapon mount'
    constraint.target, constraint.subtarget = target, bone
    constraint.target_space = constraint.owner_space = 'WORLD'
    constraint.head_tail = 0
    for obj in roots:
        local = obj.matrix_world.copy()
        obj.parent = socket
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_basis = offset @ Matrix.Scale(float(row['scale']), 4) @ attachment_basis() @ local
    for obj in created:
        obj[PART] = socket
    socket[OWNER], socket[SLOT], socket[SPACE_VERSION] = actor, slot, 2
    socket[PARENT_SLOT] = parent_slot
    socket['ruri_weapon_mount_matrix'] = json.dumps([list(v) for v in offset])
    socket['ruri_weapon_seed'], socket['ruri_weapon_mode'] = row['seed'], row['mode']
    socket['ruri_weapon_config'] = row['config']
    socket['ruri_weapon_resource_kind'] = row.get('resource_kind', 'fixed')
    socket['ruri_weapon_scale'] = float(row['scale'])
    socket['ruri_weapon_warnings'] = '\n'.join(built.warnings)
    context.view_layer.update()
    return socket, old


def attach(context, actor, row, options=None, *, rows=None, replace=False):
    """Attach a dependency graph atomically; replacements keep the old tree until success."""
    if context.mode != 'OBJECT':
        raise ValueError('请切换到物体模式')
    if actor is None or actor.type != 'ARMATURE' or actor.name not in context.scene.objects:
        raise ValueError('请选择当前场景中的角色骨架')
    cross = row.get('mount_kind') == 'weapon' or row['status'] == 'cross_weapon_mount'
    graph_rows = rows if rows is not None else rows_for(actor) if cross else [row]
    order = weapon_contract.attachment_order(graph_rows, row)
    slot = int(row['slot'])
    before = set(bpy.data.objects)
    data_before = {name: set(getattr(bpy.data, name)) for name in
                   ('meshes', 'armatures', 'materials', 'images', 'actions', 'collections', 'node_groups')}
    selected = list(context.selected_objects)
    active = context.view_layer.objects.active
    frame, subframe = context.scene.frame_current, context.scene.frame_subframe
    succeeded = False
    try:
        sockets, replaced = {}, []
        for current in order:
            current_slot = int(current['slot'])
            target, bone, offset, parent_slot = _target(actor, current, sockets)
            existing = [o for o in before if o.get(OWNER) == actor and o.get(SLOT) == current_slot]
            made, old = _attach_one(context, actor, current, target, bone, offset, parent_slot,
                                    existing, options or {}, replace and current_slot == slot)
            sockets[current_slot] = made
            if old is not None:
                replaced.append(old)
        # All imports and parent resolutions succeeded. Only tagged objects of the
        # explicitly replaced slot are removed; shared datablocks are left intact.
        for old in replaced:
            for obj in list(old.children_recursive):
                bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.objects.remove(old, do_unlink=True)
        succeeded = True
        return sockets[slot], sockets[slot] not in before
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
            try:
                if obj.name in context.view_layer.objects:
                    obj.select_set(True)
            except ReferenceError:
                pass  # An explicitly replaced weapon can have been selected.
        try:
            context.view_layer.objects.active = active if active and active.name in context.view_layer.objects else None
        except ReferenceError:
            context.view_layer.objects.active = None
        if succeeded:
            select_actor(context, actor)


class RURI_PG_weapon_row(bpy.types.PropertyGroup):
    slot: IntProperty()
    mode: StringProperty()
    status: StringProperty()
    detail: StringProperty()
    resource_kind: StringProperty()


class RURI_PG_equipment_resource(bpy.types.PropertyGroup):
    seed: StringProperty()
    family: StringProperty()
    status: StringProperty()


class RURI_UL_equipment_resources(bpy.types.UIList):
    def filter_items(self, context, data, property):
        query = data.catalog_search.strip().casefold()
        flags = [self.bitflag_filter_item if not query or query in (item.name + ' ' + item.family).casefold()
                 else 0 for item in getattr(data, property)]
        return flags, []

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0, flt_flag=0):
        layout.label(text=item.name, icon='MESH_DATA' if item.status == 'ready' else 'ERROR')


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
    resources: CollectionProperty(type=RURI_PG_equipment_resource)
    resource_index: IntProperty(default=-1)
    catalog_search: StringProperty(name='搜索武器', update=lambda self, context: setattr(self, 'resource_index', -1))


def populate_slots(state, actor, rows):
    state.rows.clear()
    state.actor = actor
    state.seed = rig_identity.seed_of(actor)
    for row in sorted(rows, key=lambda r: (r['status'] != 'ready', not bool(r['visible']), int(r['slot']))):
        if row['mode'] != state.mode:
            continue
        item = state.rows.add()
        item.slot, item.mode, item.status = int(row['slot']), row['mode'], row['status']
        item.resource_kind = row.get('resource_kind', 'equipment' if row['status'] == 'equipment_required' else 'fixed')
        item.name = '%d · %s' % (item.slot, names_zh.weapon_label(row['weapon'].rsplit('/', 1)[-1]) or '装备武器')
        item.detail = '%s · %s%s' % (STATUSES.get(row['status'], row['status']), row['bone'],
                                    '' if row['visible'] else ' · 默认隐藏（技能时序未接入）')
    state.index = 0


def equip_selected(context, actor, slot, seed, options=None):
    """Commit the user choice only after the new attachment graph has succeeded."""
    if not actor or not actor.is_editable:
        raise ValueError('请指定当前文件中可编辑的角色骨架')
    matches = [r for r in catalog_rows() if r['seed'] == seed]
    if len(matches) != 1 or matches[0]['status'] != 'ready':
        raise ValueError('武器已不在唯一可用的当前目录中，请重新扫描')
    choices = weapon_contract.selections(actor.get(SELECTIONS, ''))
    choices[str(weapon_contract.slot_number(slot))] = seed
    encoded = weapon_contract.selection_json(choices)
    rows = rows_for(actor, choices)
    selected = [r for r in rows if int(r['slot']) == slot and r['mode'] == getattr(context.scene, STATE).mode]
    if len(selected) != 1 or selected[0].get('resource_kind') != 'equipment':
        raise ValueError('请选择角色的装备槽；固定配饰保持独立')
    socket, created = attach(context, actor, selected[0], options, rows=rows, replace=True)
    actor[SELECTIONS] = encoded
    state = getattr(context.scene, STATE)
    state.candidates.clear()
    state.candidate_seed = ''
    populate_slots(state, actor, rows)
    state.index = next(i for i, r in enumerate(state.rows) if r.slot == slot)
    return socket, created


class RURI_OT_scan_weapon_catalog(bpy.types.Operator):
    bl_idname = 'ruri.endfield_scan_weapon_catalog'
    bl_label = '扫描装备武器目录'
    bl_description = '按当前索引的精确预制体路径扫描；配饰独立，不推断专武或游戏装备限制'

    def execute(self, context):
        state = getattr(context.scene, STATE)
        state.resources.clear()
        state.resource_index = -1
        try:
            for row in catalog_rows():
                item = state.resources.add()
                item.name = names_zh.weapon_label(row['asset'])
                item.seed, item.family, item.status = row['seed'], row['family'], row['status']
            self.report({'INFO'}, '已扫描 %d 个资源，请明确选择一项' % len(state.resources))
        except Exception as exc:
            state.resources.clear()
            self.report({'ERROR'}, '目录读取失败，请检查匹配后端：' + str(exc).splitlines()[0])
            return {'CANCELLED'}
        return {'FINISHED'}


class RURI_OT_equip_weapon(bpy.types.Operator):
    bl_idname = 'ruri.endfield_equip_weapon'
    bl_label = '装配／替换所选武器'
    bl_description = '使用装备槽的挂接关系和缩放；成功后再替换旧武器，角色动作保持不变'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        state = getattr(context.scene, STATE)
        try:
            if (not state.actor or rig_identity.seed_of(state.actor) != state.seed
                    or not 0 <= state.index < len(state.rows) or not 0 <= state.resource_index < len(state.resources)):
                raise ValueError('请先读取角色装备槽，并在目录中明确选择武器')
            selected = state.rows[state.index]
            if selected.mode != state.mode or selected.resource_kind != 'equipment':
                raise ValueError('请选择当前模式的装备槽；配饰与技能道具保持独立')
            resource = state.resources[state.resource_index]
            if state.catalog_search.strip().casefold() not in (resource.name + ' ' + resource.family).casefold():
                raise ValueError('当前选择被搜索条件隐藏，请重新选择目录项')
            socket, created = equip_selected(context, state.actor, selected.slot, resource.seed,
                                             browser.as_options(browser.state_of(context)))
            self.report({'INFO'}, '已装配：' + socket.name if created else '已装备此武器，保留原动画')
        except Exception as exc:
            self.report({'ERROR'}, str(exc).splitlines()[0])
            return {'CANCELLED'}
        return {'FINISHED'}


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
        if selected.resource_kind == 'equipment':
            box = layout.box()
            box.label(text='装备武器 · 由你选择', icon='OUTLINER_OB_MESH')
            box.operator(RURI_OT_scan_weapon_catalog.bl_idname)
            box.prop(state, 'catalog_search')
            box.template_list('RURI_UL_equipment_resources', 'equipment_catalog', state, 'resources',
                              state, 'resource_index', rows=5)
            box.label(text='资源目录不推断专武归属或游戏装备限制')
            if 0 <= state.resource_index < len(state.resources):
                resource = state.resources[state.resource_index]
                if resource.status != 'ready':
                    box.label(text=STATUSES.get(resource.status, resource.status), icon='ERROR')
            row = box.row()
            row.enabled = (selected.mode == state.mode and 0 <= state.resource_index < len(state.resources)
                           and state.resources[state.resource_index].status == 'ready')
            row.operator(RURI_OT_equip_weapon.bl_idname, icon='CONSTRAINT_BONE')
        row = layout.row()
        row.enabled = selected.status in ('ready', 'cross_weapon_mount') and selected.mode == state.mode
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


CLASSES = (RURI_PG_weapon_row, RURI_PG_weapon_action, RURI_PG_equipment_resource, RURI_UL_equipment_resources,
           RURI_PG_weapons, RURI_OT_scan_weapon_catalog, RURI_OT_equip_weapon, RURI_OT_read_weapons, RURI_OT_add_weapon,
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
