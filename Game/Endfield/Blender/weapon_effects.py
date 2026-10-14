"""Authored projectile-effect resources, not an inferred gameplay timeline.

The private reader owns config and component parsing. This host imports ordinary
geometry through Statement and retains particle declarations as editable source
metadata. A particle declaration is never counted as a rendered particle.
"""
import json
from dataclasses import dataclass

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from mathutils import Matrix

from ....Host.Blender import materialise, rig_identity
from ....Kernel.app import browser, loading
from ....Kernel.bridge import cabmap_state
from .. import datasets
from . import weapons

STATE = 'ruri_endfield_effects'
OWNER = 'ruri_effect_owner'
IDENTITY = 'ruri_effect_identity'
MEMBERS = 'ruri_effect_members'
MANIFEST = 'ruri_effect_manifest'
SCHEMA = 1
DATA_BLOCKS = ('meshes', 'armatures', 'materials', 'images', 'actions',
               'collections', 'node_groups', 'texts', 'lights', 'cameras')
STATUS = {'ready': '资源就绪', 'renderer_vfx_only': '材质显隐配置（另项）',
          'missing_or_ambiguous_prefab': '特效资源未唯一解析',
          'missing_prefab': '特效 Prefab 缺失', 'ambiguous_prefab': '特效 Prefab 重名',
          'invalid_effect_name': '特效名称格式异常'}
PHASES = {'mainEffects': '飞行／主效果', 'launchEffects': '发射', 'hitEffects': '命中',
          'blockEffects': '阻挡', 'reachEffects': '抵达', 'finishEffects': '结束'}


@dataclass
class Imported:
    root: object
    created: bool
    meshes: int
    particles: int


def rows_for(actor):
    if cabmap_state.BRIDGE is None:
        raise ValueError('请先打开游戏目录与索引')
    seed = rig_identity.seed_of(actor)
    if not seed:
        raise ValueError('请选择由插件导入、带来源信息的角色骨架')
    return [dict(row, _actor_seed=seed) for row in
            datasets._rows(datasets.PROJECTILE_EFFECTS, seed=seed)]


def _restore_selection(context, selected, active):
    for obj in context.selected_objects:
        obj.select_set(False)
    for obj in selected:
        if obj.name in context.view_layer.objects:
            obj.select_set(True)
    if active is not None and active.name in context.view_layer.objects:
        context.view_layer.objects.active = active


def _remove_new(before, blocks):
    for obj in list(set(bpy.data.objects) - before):
        bpy.data.objects.remove(obj, do_unlink=True)
    # Repeat for dependencies: materials release images/groups, rigs release Actions.
    for _ in range(3):
        for name in DATA_BLOCKS:
            collection = getattr(bpy.data, name)
            for block in list(set(collection) - blocks[name]):
                if block.users == int(block.use_fake_user):
                    block.use_fake_user = False
                    collection.remove(block)


def _validate_existing(root, context, actor, row, anchor, bone, preview_source_meshes):
    if (root.name not in context.scene.objects or root.get('ruri_effect_schema') != SCHEMA
            or root.get('ruri_effect_seed') != row['seed']
            or root.get('ruri_effect_anchor') != anchor
            or root.get('ruri_effect_bone', '') != bone
            or bool(root.get('ruri_effect_preview_templates', False)) != bool(preview_source_meshes)):
        raise ValueError('现有特效来源或挂接不同，请先检查或移除此实例')
    members = list(root.get(MEMBERS, ()))
    if not members or any(obj is None or obj.name not in context.scene.objects for obj in members):
        raise ValueError('现有特效对象已变化，请先检查此实例')
    if set(root.children_recursive) != set(members):
        raise ValueError('现有特效层级已变化，请先检查此实例')
    manifest = root.get(MANIFEST)
    if manifest is None or manifest.name not in bpy.data.texts:
        raise ValueError('现有特效来源清单缺失')
    constraints = list(root.constraints)
    if anchor is None:
        if constraints:
            raise ValueError('现有特效挂接约束已被修改')
    elif (len(constraints) != 1 or constraints[0].type != 'COPY_TRANSFORMS'
          or constraints[0].target != anchor or constraints[0].subtarget != bone
          or constraints[0].mute or constraints[0].influence != 1
          or constraints[0].target_space != 'WORLD' or constraints[0].owner_space != 'WORLD'):
        raise ValueError('现有特效挂接约束已被修改')


def _source_target(value):
    if not value:
        return None
    return value.get('target', value)


def _mesh_templates(context, components, nodes, placed, values):
    """Source mesh mode only: never invent billboard particles or physics."""
    count = 0
    for item in components:
        if item['kind'] != 'particle_renderer':
            continue
        data = json.loads(item['parameters'])
        if int(data.get('render_mode', -1)) != 4:
            continue
        mesh = _source_target(data.get('mesh'))
        materials = [_source_target(value) for value in data.get('materials', ())]
        if not mesh or any(value is None for value in materials):
            raise ValueError('粒子源网格／材质引用缺失：' + item['name'])
        candidates = [placed.get(node.index) for node in nodes if node.path == item['path']]
        targets = list(dict.fromkeys(obj for obj in candidates if obj is not None))
        if len(targets) != 1:
            raise ValueError('粒子源挂点未唯一物化：' + item['path'])
        seeds = list(dict.fromkeys([mesh['resource_seed']] + [value['resource_seed'] for value in materials]))
        with loading.read(seeds, values) as source:
            obj = materialise.materialise_mesh_asset(context, source, mesh['source_key'],
                    [value['source_key'] for value in materials], values, 'Source mesh · ' + item['name'])
        obj.parent = targets[0]
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_basis = Matrix.Identity(4)
        obj['ruri_effect_source_template'] = True
        obj['ruri_effect_template_note'] = '静态粒子源网格模板；非发射粒子、非游戏初始可见状态'
        count += 1
    return count


def import_effect(context, actor, row, options=None, *, anchor=None, bone='', preview_source_meshes=False):
    """Transactionally import one authored resource. Placement is explicitly manual."""
    if context.mode != 'OBJECT':
        raise ValueError('请切换到物体模式')
    if actor is None or actor.type != 'ARMATURE' or actor.name not in context.scene.objects:
        raise ValueError('请选择当前场景中的角色骨架')
    if row['status'] != 'ready' or not row['seed']:
        raise ValueError(STATUS.get(row['status'], row['status']))
    if row.get('_actor_seed') and row['_actor_seed'] != rig_identity.seed_of(actor):
        raise ValueError('角色来源已改变，请重新读取此角色的特效目录')
    if anchor is not None:
        if anchor.name not in context.scene.objects:
            raise ValueError('挂接目标不在当前场景')
        if bone and (anchor.type != 'ARMATURE' or bone not in anchor.pose.bones):
            raise ValueError('所选挂接骨骼缺失：' + bone)
    elif bone:
        raise ValueError('请先选择挂接目标')
    existing = [obj for obj in bpy.data.objects
                if obj.get(OWNER) == actor and obj.get(IDENTITY) == row['identity']]
    if existing:
        if len(existing) != 1:
            raise ValueError('此来源已有多个实例，请先整理重复对象')
        root = existing[0]
        _validate_existing(root, context, actor, row, anchor, bone, preview_source_meshes)
        return Imported(root, False, int(root['ruri_effect_meshes']), int(root['ruri_effect_particles']))

    components = datasets._rows(datasets.EFFECT_COMPONENTS, seed=row['seed'])
    particles = sum(item['kind'] == 'particle' for item in components)
    if not any(item['kind'] == 'transform' for item in components):
        raise ValueError('特效来源未返回可导入的层级')
    before = set(bpy.data.objects)
    blocks = {name: set(getattr(bpy.data, name)) for name in DATA_BLOCKS}
    selected, active = list(context.selected_objects), context.view_layer.objects.active
    frame, subframe = context.scene.frame_current, context.scene.frame_subframe
    succeeded = False
    try:
        values = dict(options or {}, import_empties=True, import_animations=False,
                      source_game='Endfield', import_inactive=True)
        templates = 0
        if preview_source_meshes:
            with loading.read([row['seed']], values) as stated:
                built, indexed = materialise.materialise_indexed(context, stated, values)
                templates = _mesh_templates(context, components, stated.nodes, indexed, values)
        else:
            built = loading.load(context, [row['seed']], values)
        created = set(bpy.data.objects) - before
        if not created or built.missing:
            raise ValueError('特效层级导入不完整：' + '; '.join(map(str, built.missing or built.warnings)))
        root = bpy.data.objects.new('Effect · ' + row['name'], None)
        context.collection.objects.link(root)
        root.empty_display_type = 'PLAIN_AXES'
        root.empty_display_size = .08
        roots = [obj for obj in created if obj.parent not in created]
        for obj in roots:
            local = obj.matrix_world.copy()
            obj.parent = root
            obj.matrix_parent_inverse = Matrix.Identity(4)
            obj.matrix_basis = (weapons.attachment_basis() @ local) if anchor is not None else local
        if anchor is None:
            root.location = context.scene.cursor.location
        else:
            constraint = root.constraints.new('COPY_TRANSFORMS')
            constraint.name = 'Manual effect preview anchor'
            constraint.target = anchor
            constraint.subtarget = bone
            constraint.target_space = 'WORLD'
            constraint.owner_space = 'WORLD'
            constraint.head_tail = 0
        meshes = sum(obj.type == 'MESH' and not obj.get('ruri_effect_source_template') for obj in created)
        manifest = bpy.data.texts.new('Effect source · ' + row['name'] + '.json')
        manifest.use_fake_user = False
        manifest.use_module = False
        manifest.write(json.dumps(dict(schema=SCHEMA, source=row, components=components,
                                      warnings=built.warnings, placement='manual_preview',
                                      particle_playback='pending', event_timing='UNKNOWN'),
                                  ensure_ascii=False, indent=2))
        root[OWNER] = actor
        root[IDENTITY] = row['identity']
        root[MEMBERS] = list(created)
        root[MANIFEST] = manifest
        root['ruri_effect_schema'] = SCHEMA
        root['ruri_effect_seed'] = row['seed']
        if anchor is not None:
            root['ruri_effect_anchor'] = anchor
        root['ruri_effect_bone'] = bone
        root['ruri_effect_meshes'] = meshes
        root['ruri_effect_particles'] = particles
        root['ruri_effect_templates'] = templates
        root['ruri_effect_preview_templates'] = bool(preview_source_meshes)
        root['ruri_effect_note'] = ('源网格 %d／静态模板 %d；粒子参数 %d（播放待实现）；非攻击时间轴'
                                   % (meshes, templates, particles))
        context.view_layer.update()
        succeeded = True
        return Imported(root, True, meshes, particles)
    finally:
        if not succeeded:
            _remove_new(before, blocks)
        context.scene.frame_set(frame, subframe=subframe)
        _restore_selection(context, selected, active)


def remove_effect(context, root):
    """Only remove this feature's exact managed hierarchy; preserve user-added children."""
    if root is None or root.get('ruri_effect_schema') != SCHEMA or root.name not in context.scene.objects:
        raise ValueError('请选择本功能导入的特效实例')
    members = {obj for obj in root.get(MEMBERS, ()) if obj is not None}
    if set(root.children_recursive) != members:
        raise ValueError('特效层级已变化，请先移出新增对象或整理层级')
    manifest = root.get(MANIFEST)
    for obj in members | {root}:
        bpy.data.objects.remove(obj, do_unlink=True)
    if manifest is not None and manifest.users == int(manifest.use_fake_user):
        manifest.use_fake_user = False
        bpy.data.texts.remove(manifest)


class RURI_PG_effect_row(bpy.types.PropertyGroup):
    payload: StringProperty()


class RURI_PG_effects(bpy.types.PropertyGroup):
    actor: PointerProperty(type=bpy.types.Object, poll=lambda _, obj: obj.type == 'ARMATURE')
    rows: CollectionProperty(type=RURI_PG_effect_row)
    index: IntProperty(default=0, min=0)
    query: StringProperty(name='筛选配置／效果')
    placement: EnumProperty(items=(('CURSOR', '3D 游标位置', '手动查看资源，不推断发射或命中位置'),
                                  ('ANCHOR', '手动选择挂点', '仅预览跟随，不代表游戏事件挂接')))
    anchor: PointerProperty(type=bpy.types.Object)
    bone: StringProperty()
    preview_source_meshes: BoolProperty(name='静态粒子源网格预览', default=False,
                                       description='仅展示 mesh 粒子的原始几何与材质，不模拟发射或运动')
    instance: PointerProperty(type=bpy.types.Object)
    note: StringProperty()


class RURI_OT_read_effects(bpy.types.Operator):
    bl_idname = 'ruri.endfield_read_effects'
    bl_label = '读取箭矢／命中特效'

    def execute(self, context):
        state = getattr(context.scene, STATE)
        actor = state.actor or getattr(context.scene, weapons.STATE).actor
        try:
            rows = rows_for(actor)
            identities = [row['identity'] for row in rows]
            if len(set(identities)) != len(identities):
                raise ValueError('特效来源标识重复')
            encoded = [json.dumps(row, ensure_ascii=False) for row in rows]
            state.rows.clear()
            state.actor = actor
            state.index = 0
            for row, payload in zip(rows, encoded):
                item = state.rows.add()
                item.name = '%s · %s · %s' % (row['template'].rsplit('_archery_', 1)[-1],
                                             PHASES.get(row['phase'], row['phase']), row['name'])
                item.payload = payload
            state.note = '读取 %d 项投射物配置引用；动作触发时序待解析' % len(rows)
        except Exception as exc:
            state.note = str(exc).splitlines()[0]
            self.report({'WARNING'}, state.note)
            return {'CANCELLED'}
        return {'FINISHED'}


class RURI_OT_import_effect(bpy.types.Operator):
    bl_idname = 'ruri.endfield_import_effect'
    bl_label = '导入特效资源（首阶段）'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        state = getattr(context.scene, STATE)
        if not 0 <= state.index < len(state.rows):
            return {'CANCELLED'}
        try:
            if state.placement == 'ANCHOR' and state.anchor is None:
                raise ValueError('请选择手动挂接目标')
            result = import_effect(context, state.actor, json.loads(state.rows[state.index].payload),
                                   browser.as_options(browser.state_of(context)),
                                   anchor=state.anchor if state.placement == 'ANCHOR' else None,
                                   bone=state.bone if state.placement == 'ANCHOR' else '',
                                   preview_source_meshes=state.preview_source_meshes)
            state.instance = result.root
            state.note = result.root['ruri_effect_note']
        except Exception as exc:
            state.note = str(exc).splitlines()[0]
            self.report({'WARNING'}, state.note)
            return {'CANCELLED'}
        self.report({'INFO'}, state.note)
        return {'FINISHED'}


class RURI_OT_remove_effect(bpy.types.Operator):
    bl_idname = 'ruri.endfield_remove_effect'
    bl_label = '移除此特效实例'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        state = getattr(context.scene, STATE)
        try:
            remove_effect(context, state.instance)
            state.instance = None
            state.note = '已移除管理对象；共享数据保留'
        except Exception as exc:
            self.report({'WARNING'}, str(exc).splitlines()[0])
            return {'CANCELLED'}
        return {'FINISHED'}


class RURI_UL_effects(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.name, icon='PARTICLES')

    def filter_items(self, context, data, propname):
        query = data.query.strip().casefold()
        return ([self.bitflag_filter_item if not query or query in item.name.casefold() else 0
                 for item in getattr(data, propname)], [])


class RURI_PT_effects(bpy.types.Panel):
    bl_label = 'Endfield 武器攻击特效 · 首阶段'
    bl_idname = 'RURI_PT_endfield_effects'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'RuriRipper'

    def draw(self, context):
        layout = self.layout
        state = getattr(context.scene, STATE)
        layout.prop(state, 'actor', text='角色')
        layout.operator(RURI_OT_read_effects.bl_idname)
        layout.prop(state, 'query')
        layout.template_list('RURI_UL_effects', 'endfield_effects', state, 'rows', state, 'index', rows=5)
        if state.rows and state.index < len(state.rows):
            row = json.loads(state.rows[state.index].payload)
            layout.label(text=STATUS.get(row['status'], row['status']))
            layout.prop(state, 'placement', text='预览位置')
            layout.prop(state, 'preview_source_meshes')
            if state.placement == 'ANCHOR':
                layout.prop(state, 'anchor', text='跟随对象')
                if state.anchor and state.anchor.type == 'ARMATURE':
                    layout.prop_search(state, 'bone', state.anchor.data, 'bones', text='骨骼')
            button = layout.row()
            button.enabled = row['status'] == 'ready'
            button.operator(RURI_OT_import_effect.bl_idname)
        layout.label(text='粒子：源参数导入；动态播放待实现', icon='INFO')
        layout.label(text='触发／发射／命中：未自动同步动作')
        if state.note:
            layout.label(text=state.note[:100])
        layout.prop(state, 'instance', text='管理实例')
        layout.operator(RURI_OT_remove_effect.bl_idname)


CLASSES = (RURI_PG_effect_row, RURI_PG_effects, RURI_OT_read_effects,
           RURI_OT_import_effect, RURI_OT_remove_effect, RURI_UL_effects, RURI_PT_effects)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    setattr(bpy.types.Scene, STATE, PointerProperty(type=RURI_PG_effects))


def unregister():
    delattr(bpy.types.Scene, STATE)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
