"""Manual resource-state imports. Never evaluates player or equipment conditions.

Each import creates an independent assembly. Source node names drive the declared
renderer predicate and mounts; Blender-renamed labels are never game identities.
"""
import json
import math
from contextlib import contextmanager
from uuid import uuid4

import bpy
from bpy.props import EnumProperty, PointerProperty, StringProperty
from mathutils import Matrix, Vector

from ....Host.Blender import material_builder, materialise, material_panel, rig_identity
from ....Kernel.app import browser, loading
from .. import datasets, names_zh, weapon_catalog
from . import weapons, weapon_effects

STATE = 'ruri_endfield_weapon_states'
OWNER = 'ruri_weapon_state_owner'
MANIFEST = 'ruri_weapon_state_manifest'
SOURCE_NAME = 'ruri_weapon_state_source_name'
CLOCK = 'ruri_weapon_state_clock'
BLOCKS = ('objects', 'meshes', 'armatures', 'materials', 'images', 'actions', 'collections', 'node_groups', 'texts')


def plan_for(seed, appearance, deco, deco_key=''):
    rows = datasets._rows('endfield.weapon.state', seed=seed, appearance=appearance,
                          deco=deco, deco_key=deco_key, basis='blender')
    if len(rows) != 1:
        raise ValueError('后端未返回唯一的武器状态计划，请使用匹配后端')
    plan = json.loads(rows[0]['plan'])
    if (plan['deco'] != deco or plan['requested_appearance'] != appearance
            or plan['slot_policy'] != 'replace_entire_array' or plan['renderer_name_contains'] != '_vfx_'):
        raise ValueError('后端状态契约不匹配')
    return plan


def _snapshot():
    return {name: set(getattr(bpy.data, name)) for name in BLOCKS}


@contextmanager
def _fresh_materials(source):
    """Keep provider name-based proxy construction away from existing content."""
    names = {getattr(m, 'name', '') for m in source.materials.values()}
    held = [(m, m.name) for m in bpy.data.materials if m.name in names]
    try:
        for mat, _ in held:
            mat.name = 'State material guard ' + uuid4().hex
        yield
    finally:
        for mat, name in held:
            incoming = bpy.data.materials.get(name)
            if incoming is not None and incoming != mat:
                incoming.name = name + ' · state'
            mat.name = name


def finalize(material):
    """Drive only this assembly's declared engine-time inputs; keep shader math intact.

    Unity _Time = (t/20, t, 2t, 3t). Scene frames supply t in seconds.
    https://docs.unity3d.com/6000.0/Documentation/Manual/SL-UnityShaderVariables.html
    Drivers use built-in expressions only and survive save/load and graph recompiles.
    """
    scene = material.get(CLOCK)
    entry = material_panel.stack_of(material)
    if not isinstance(scene, bpy.types.Scene) or entry is None or material.node_tree is None:
        return
    declared = entry['stack'].GLOBALS
    for name, spec in declared.items():
        if spec.get('role') != 'time' or name != '_Time' or spec.get('type') != 'VECTOR4':
            continue
        for node in material.node_tree.nodes:
            if node.type != 'GROUP':
                continue
            for socket_name, factors in ((name, (.05, 1., 2.)), (name + '_w', (3.,))):
                socket = node.inputs.get(socket_name)
                if socket is None or socket.is_linked:
                    continue
                for i, factor in enumerate(factors):
                    curve = socket.driver_add('default_value', i) if len(factors) > 1 else socket.driver_add('default_value')
                    driver = curve.driver
                    driver.type = 'SCRIPTED'
                    while driver.variables:
                        driver.variables.remove(driver.variables[0])
                    for key, path in (('fps', 'render.fps'), ('base', 'render.fps_base')):
                        var = driver.variables.new()
                        var.name = key
                        var.type = 'SINGLE_PROP'
                        var.targets[0].id_type = 'SCENE'
                        var.targets[0].id = scene
                        var.targets[0].data_path = path
                    driver.expression = 'frame*base/fps*' + repr(factor)


def _rollback(before):
    for obj in set(bpy.data.objects) - before['objects']:
        bpy.data.objects.remove(obj, do_unlink=True)
    # Material graphs release images/groups; armatures release Actions.
    for _ in range(4):
        for name in BLOCKS[1:]:
            blocks = getattr(bpy.data, name)
            for block in set(blocks) - before[name]:
                # Runtime shader caches belong to their provider, not this import.
                # Removing them leaves the provider holding invalid RNA handles.
                if not block.is_runtime_data and block.users == int(block.use_fake_user):
                    block.use_fake_user = False
                    blocks.remove(block)


def _mount(name, nodes, indexed, model_objects, fallback):
    if not name:
        return fallback, '', False
    found = list(dict.fromkeys((indexed[n.index], '') for n in nodes
                              if n.name == name and n.index in indexed))
    for obj in model_objects:
        if obj.type != 'ARMATURE':
            continue
        identity = rig_identity.of(obj)
        if identity and name in identity.ambiguous_unity_names:
            raise ValueError('效果挂点骨骼重名：' + name)
        bone = identity.bone_of(name) if identity else None
        if bone:
            found.append((obj, bone))
    found = list(dict.fromkeys(found))
    if len(found) > 1:
        raise ValueError('效果挂点未唯一对应：' + name)
    return (*found[0], False) if found else (fallback, '', True)


def bind_materials(targets, materials, enabled):
    """Only objects of the new assembly are passed here; their mesh data is local."""
    for obj in targets:
        if obj.type != 'MESH':
            raise ValueError('状态材质目标不是网格')
        if not obj.is_editable or not obj.data.is_editable:
            raise ValueError('状态材质目标为只读数据')
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        obj.data.materials.clear()
        for material in materials:
            obj.data.materials.append(material)
        # Unity's empty Renderer array draws nothing. Blender's zero-slot mesh
        # would draw a default grey surface instead, so hide that empty carrier.
        obj.hide_viewport = obj.hide_render = not (enabled and materials)
        obj.hide_set(False)


def import_state(context, seed, appearance='base', deco='none', options=None, *, deco_key=''):
    if context.mode != 'OBJECT':
        raise ValueError('请切换到物体模式')
    # Resolve every exact resource first. Unsupported branches leave the scene alone.
    plan = plan_for(seed, appearance, deco, deco_key)
    values = dict(options or {}, source_game='Endfield', import_empties=True,
                  import_inactive=True, import_animations=False, game_shaders=True)
    before = _snapshot()
    selected, active = list(context.selected_objects), context.view_layer.objects.active
    frame, subframe = context.scene.frame_current, context.scene.frame_subframe
    succeeded = False
    try:
        root = bpy.data.objects.new(names_zh.weapon_label(plan['weapon']) +
                (' · 满潜' if plan['refined'] else ' · 普通') + ' · ' + deco, None)
        context.collection.objects.link(root)
        root.empty_display_size = .1
        warnings = list(plan['warnings'])
        with loading.read([plan['seed']], values) as stated:
            nodes = list(stated.nodes)
            start = set(bpy.data.objects)
            with _fresh_materials(stated):
                built, indexed = materialise.materialise_indexed(context, stated, values)
            model_objects = set(bpy.data.objects) - start
            if built.missing or not any(o.type == 'MESH' for o in model_objects):
                raise ValueError('武器模型导入不完整：' + '; '.join(map(str, built.missing)))
            warnings.extend(map(str, built.warnings))
            for n in nodes:
                if n.index in indexed:
                    indexed[n.index][SOURCE_NAME] = n.name
                    indexed[n.index]['ruri_weapon_state_source_path'] = n.path
            model_roots = [o for o in model_objects if o.parent not in model_objects]
            for obj in model_roots:
                obj.parent = root
                obj.matrix_parent_inverse = Matrix.Identity(4)
            source_roots = list(dict.fromkeys(indexed[n.index] for n in nodes
                               if n.parent < 0 and n.index in indexed))
            if len(source_roots) != 1:
                raise ValueError('武器源根未唯一物化，保留原场景')
            fallback = source_roots[0]
            targets = list(dict.fromkeys(indexed[n.index] for n in nodes
                           if n.mesh and plan['renderer_name_contains'] in n.name and n.index in indexed))
        materials = []
        seeds = list(dict.fromkeys(m['seed'] for m in plan['materials']))
        if seeds:
            with loading.read(seeds, values) as source:
                builder = material_builder.MaterialBuilder(source, values)
                for m in plan['materials']:
                    if m['source_key'] not in source.materials:
                        raise ValueError('装饰材质源身份缺失：' + m['name'])
                    with _fresh_materials(source):
                        mat = builder.build(m['source_key'])
                    mat[OWNER] = root
                    materials.append(mat)
        if deco != 'none' and materials and not targets:
            raise ValueError('没有匹配源名称 _vfx_ 的 Renderer；主体保持原样')
        bind_materials(targets, materials, deco != 'none')
        effect_records = []
        context.view_layer.update()
        for effect in plan['effects']:
            offset = effect['offset']
            if len(offset) != 3 or not all(math.isfinite(v) for v in offset):
                raise ValueError('效果偏移不是有限三维向量')
            target, bone, used_fallback = _mount(effect['mount_point'], nodes, indexed, model_objects, fallback)
            if used_fallback:
                warnings.append('效果挂点缺失，按源规则挂到武器根：' + effect['mount_point'])
            anchor = bpy.data.objects.new('Decoration · ' + effect['name'], None)
            context.collection.objects.link(anchor)
            if bone:
                follow = bpy.data.objects.new('Decoration bone mount', None)
                context.collection.objects.link(follow)
                follow.parent = root
                constraint = follow.constraints.new('COPY_TRANSFORMS')
                constraint.target, constraint.subtarget = target, bone
                constraint.target_space = constraint.owner_space = 'WORLD'
                anchor.parent = follow
            else:
                anchor.parent = target
            anchor.matrix_parent_inverse = Matrix.Identity(4)
            anchor.location = Vector(offset)
            components = datasets._rows(datasets.EFFECT_COMPONENTS, seed=effect['seed'])
            pending = [c for c in components if c['kind'] in ('particle', 'particle_renderer', 'unsupported_component')]
            if pending:
                warnings.append(effect['name'] + '：粒子／程序化效果仅保留源声明，尚未模拟')
            start = set(bpy.data.objects)
            with loading.read([effect['seed']], values) as source:
                with _fresh_materials(source):
                    result = materialise.materialise(context, source, values)
                if result.missing:
                    raise ValueError('装饰效果导入不完整：' + effect['name'])
                warnings.extend(map(str, result.warnings))
            created = set(bpy.data.objects) - start
            context.view_layer.update()
            for obj in created:
                if obj.parent not in created:
                    local = obj.matrix_world.copy()
                    obj.parent = anchor
                    obj.matrix_parent_inverse = Matrix.Identity(4)
                    obj.matrix_basis = weapons.attachment_basis() @ local
            effect_records.append(dict(effect, fallback=used_fallback, bone=bone, components=components))
        for mat in set(bpy.data.materials) - before['materials']:
            mat[OWNER] = root
            mat[CLOCK] = context.scene
            finalize(mat)
        manifest = bpy.data.texts.new('Weapon state · ' + root.name + '.json')
        manifest.use_module = False
        manifest.write(json.dumps(dict(schema=1, plan=plan, effects=effect_records, warnings=warnings), ensure_ascii=False))
        root[MANIFEST] = manifest
        root['ruri_weapon_state_seed'] = plan['seed']
        root['ruri_weapon_state_deco'] = deco
        root['ruri_weapon_state_note'] = '\n'.join(warnings)
        for obj in set(bpy.data.objects) - before['objects']:
            if obj != root:
                obj[OWNER] = root
        root['ruri_weapon_state_members'] = list(set(bpy.data.objects) - before['objects'] - {root})
        root.location = context.scene.cursor.location
        context.view_layer.update()
        succeeded = True
        return root
    finally:
        if not succeeded:
            _rollback(before)
        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in selected:
            if obj.name in context.view_layer.objects:
                obj.select_set(True)
        if active and active.name in context.view_layer.objects:
            context.view_layer.objects.active = active
        elif active is None:
            context.view_layer.objects.active = None
        if (context.scene.frame_current, context.scene.frame_subframe) != (frame, subframe):
            context.scene.frame_set(frame, subframe=subframe)


def remove_state(context, root):
    if not root or root.name not in context.scene.objects or MANIFEST not in root:
        raise ValueError('请选择本工具导入的武器状态实例')
    children = list(root.children_recursive)
    members = list(root.get('ruri_weapon_state_members', ()))
    if set(children) != set(members) or any(o.get(OWNER) != root for o in children):
        raise ValueError('状态实例含用户添加的对象，请先移出后再删除')
    manifest = root[MANIFEST]
    data = {o.data for o in children if o.data is not None}
    materials = {m for m in bpy.data.materials if m.get(OWNER) == root}
    for obj in children:
        bpy.data.objects.remove(obj, do_unlink=True)
    # Include owned objects reparented outside the hierarchy only by rejecting them.
    bpy.data.objects.remove(root, do_unlink=True)
    for block in data:
        if block.users == 0:
            if isinstance(block, bpy.types.Mesh):
                bpy.data.meshes.remove(block)
            elif isinstance(block, bpy.types.Armature):
                bpy.data.armatures.remove(block)
    for mat in materials:
        if mat.users == 0 and not mat.use_fake_user:
            bpy.data.materials.remove(mat)
    if manifest.users == 0:
        bpy.data.texts.remove(manifest)


class RURI_PG_weapon_states(bpy.types.PropertyGroup):
    appearance: EnumProperty(name='模型外观', items=(('base', '普通', ''), ('refined', '满潜', '资源缺失时回退普通模型')))
    deco: EnumProperty(name='基质装饰', items=(('none', '关闭', ''), ('gemDeco', 'gemDeco', '手动选择源装饰分支'),
                                               ('gemMaxDeco', 'gemMaxDeco', '手动选择源装饰分支')))
    deco_key: StringProperty(name='配置键覆盖', description='通常留空；仅在明确需要独立模板配置时填写')
    instance: PointerProperty(type=bpy.types.Object)
    note: StringProperty()


class RURI_OT_import_weapon_state(bpy.types.Operator):
    bl_idname = 'ruri.endfield_import_weapon_state'
    bl_label = '导入所选武器状态（新实例）'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        state = getattr(context.scene, STATE)
        try:
            if not weapon_catalog.current(context):
                raise ValueError('资源索引已改变，请重新扫描武器')
            picked = weapon_catalog.BOUND.picked(weapon_catalog.state_of(context))
            if not picked or not picked.payload:
                raise ValueError('请明确选择一个武器资源')
            state.instance = import_state(context, picked.payload, state.appearance, state.deco,
                    browser.as_options(browser.state_of(context)), deco_key=state.deco_key)
            state.note = state.instance.get('ruri_weapon_state_note', '') or '已导入独立状态实例；原场景武器保持原样'
            self.report({'INFO'}, '已导入：' + state.instance.name)
        except Exception as exc:
            state.note = str(exc).splitlines()[0]
            self.report({'ERROR'}, state.note)
            return {'CANCELLED'}
        return {'FINISHED'}


class RURI_OT_remove_weapon_state(bpy.types.Operator):
    bl_idname = 'ruri.endfield_remove_weapon_state'
    bl_label = '移除此状态实例'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        state = getattr(context.scene, STATE)
        try:
            remove_state(context, state.instance)
            state.instance = None
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


def draw(layout, context):
    weapon_catalog.draw(layout, context, verbs=False)
    state = getattr(context.scene, STATE)
    box = layout.box()
    box.prop(state, 'appearance')
    box.prop(state, 'deco')
    box.prop(state, 'deco_key')
    box.operator(RURI_OT_import_weapon_state.bl_idname, icon='IMPORT')
    box.label(text='手动资源状态；原生 Shader / 时间驱动；粒子模拟另项', icon='INFO')
    if state.note:
        box.label(text=state.note, icon='INFO')
    box.prop(state, 'instance', text='状态实例')
    box.operator(RURI_OT_remove_weapon_state.bl_idname, icon='TRASH')


CLASSES = (RURI_PG_weapon_states, RURI_OT_import_weapon_state, RURI_OT_remove_weapon_state)


def register():
    from .. import weapon
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    setattr(bpy.types.Scene, STATE, PointerProperty(type=RURI_PG_weapon_states))
    material_builder.MATERIAL_FINALIZERS.add(finalize)
    weapon.register_section('states', draw)


def unregister():
    from .. import weapon
    weapon.drop_section('states')
    material_builder.MATERIAL_FINALIZERS.remove(finalize)
    delattr(bpy.types.Scene, STATE)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
