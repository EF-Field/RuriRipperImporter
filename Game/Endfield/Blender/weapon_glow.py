"""Static Blender emission on already imported weapon materials only.

No reader, game paths, source decoding or reverse-engineering tools are used.
Shared source materials remain intact. An additive, texture-masked emission
branch is rebuilt after the normal host compiles a managed material's source.
"""
import json

import bpy
from bpy.props import BoolProperty, CollectionProperty, FloatProperty, FloatVectorProperty, PointerProperty, StringProperty

from ....Host.Blender import material_builder
from . import weapons

STATE = 'ruri_weapon_glow_panel'
SETTINGS = 'ruri_weapon_glow'
BASE = 'ruri_glow_source_material'
OWNER = 'ruri_glow_weapon_owner'
TAG = 'ruri_glow_node'
LINK = 'ruri_glow_surface_source'
ERROR = 'ruri_glow_error'
BINDINGS = 'ruri_glow_binding_links'
RECORD = 'ruri_glow_settings_record'
_HYDRATING = set()
# Artist reference preset, not a recovered game uniform. Scene-linear RGBA.
NORMAL_COLOR = (.16, .055, 1.0, 1.0)
STRING_STRENGTH = 128.0


def record_settings(material):
    """RNA groups are not enumerated by Material.keys() in Blender 5.3.

    Keep a plain content record for the host's material replacement path.
    Image/ID pointers stay remappable, not fragile name-only references.
    """
    settings = getattr(material, SETTINGS)
    record = dict(role=settings.role, enabled=settings.enabled,
                  color=list(settings.color), strength=settings.strength)
    for key in ('mask', 'mask_secondary'):
        if getattr(settings, key) is not None:
            record[key] = getattr(settings, key)
    material[RECORD] = record


def hydrate_settings(material):
    if RECORD not in material:
        return
    record = material[RECORD]
    settings = getattr(material, SETTINGS)
    pointer = material.as_pointer()
    _HYDRATING.add(pointer)
    try:
        settings.role = record.get('role', '')
        settings.color = record.get('color', NORMAL_COLOR)
        settings.strength = record.get('strength', 3)
        settings.mask = record.get('mask')
        settings.mask_secondary = record.get('mask_secondary')
        settings.enabled = record.get('enabled', False)
    finally:
        _HYDRATING.discard(pointer)


def image_of(material, key):
    value = material.get('ruri_uber_images', {}).get(key)
    return value if isinstance(value, bpy.types.Image) else bpy.data.images.get(value or '')


def meshes_of(target):
    return [obj for obj in [target] + list(target.children_recursive) if obj.type == 'MESH']


def target_of(context):
    state = getattr(context.scene, STATE)
    if state.target:
        target = state.target
    else:
        target = context.object
        while target and weapons.OWNER not in target and target.parent:
            target = target.parent
        if not target or weapons.OWNER not in target:
            actor = getattr(context.scene, weapons.STATE).actor
            candidates = [obj for obj in context.scene.objects if actor and obj.get(weapons.OWNER) == actor]
            if len(candidates) != 1:
                raise ValueError('请在武器目标栏选择 Weapon slot 挂接或独立武器骨架')
            target = candidates[0]
    if target.name not in context.scene.objects or not meshes_of(target):
        raise ValueError('武器目标不在当前场景，或没有网格')
    # An explicitly selected mesh/rig is allowed, but a character root is not.
    if any(obj.get(weapons.OWNER) == target for obj in context.scene.objects):
        raise ValueError('请选择武器挂接，角色根骨架不作为静态发光目标')
    return target


def owned_materials(target):
    return list(dict.fromkeys(slot.material for obj in meshes_of(target) for slot in obj.material_slots
                             if slot.material and slot.material.get(OWNER) == target and slot.material.get(BASE)))


def scan(context):
    state = getattr(context.scene, STATE)
    target = target_of(context)
    materials = list(dict.fromkeys(slot.material.get(BASE, slot.material)
                    for obj in meshes_of(target) for slot in obj.material_slots if slot.material))
    state.regions.clear()
    # Old saved panel pointers are migration input only, never a second catalog.
    state.string_material = state.pattern_material = None
    state.target = target
    owned = {mat[BASE]: mat for mat in owned_materials(target)}
    for mat in materials:
        emission = image_of(mat, '_EmissionMap')
        main = image_of(mat, '_MainTex')
        if not emission and not main and mat not in owned:
            continue
        item = state.regions.add()
        item.material = mat
        item.selected = bool(emission or mat in owned)
        item.role = '纹路' if emission else '独立区域'
        item.mask = emission or main
        # A MainTex is only a candidate. Neither VFX nor a material name proves
        # an emissive role, an auxiliary-mask product, or a default visible state.
        if mat in owned:
            settings = getattr(owned[mat], SETTINGS)
            item.role, item.mask = settings.role, settings.mask
            item.mask_secondary = settings.mask_secondary
    state.note = ('找到 %d 个候选区域；普通贴图候选需确认，新区域默认关闭' % len(state.regions)
                  if state.regions else '未发现发光贴图候选；可以保持原材质，或手动添加区域')


def add_region(context):
    state = getattr(context.scene, STATE)
    target = target_of(context)
    material = state.material
    originals = {slot.material.get(BASE, slot.material) for obj in meshes_of(target)
                 for slot in obj.material_slots if slot.material}
    if material is None:
        raise ValueError('请先选择此目标上的材质')
    material = material.get(BASE, material)
    if material not in originals:
        raise ValueError('所选材质不属于此目标')
    if any(item.material == material for item in state.regions):
        raise ValueError('此材质已在区域列表中，请直接勾选或编辑')
    item = state.regions.add()
    item.material, item.selected = material, True
    item.role = '独立区域'
    item.mask = image_of(material, '_EmissionMap')
    state.target = target
    state.note = '已添加独立区域；无遮罩表示整个材质，新区域默认关闭'


def _output(material):
    outputs = [node for node in material.node_tree.nodes if node.bl_idname == 'ShaderNodeOutputMaterial']
    active = [node for node in outputs if node.is_active_output]
    if len(active) != 1 or not active[0].inputs['Surface'].is_linked:
        raise ValueError('材质需要一个已连接的活动 Surface 输出：' + material.name)
    return active[0]


def _source_socket(material, output):
    socket = output.inputs['Surface'].links[0].from_socket
    if not socket.node.get(TAG):
        material[LINK] = json.dumps([socket.node.name, socket.identifier])
        return socket
    if LINK not in material:
        raise ValueError('静态发光的原 Surface 记录缺失')
    name, identifier = json.loads(material[LINK])
    node = material.node_tree.nodes.get(name)
    if node is None:
        raise ValueError('原 Surface 节点已变化，请先检查材质')
    source = next((value for value in node.outputs if value.identifier == identifier), None)
    if source is None:
        raise ValueError('原 Surface 插口已变化，请先检查材质')
    return source


def rebuild(material):
    if material.library or not material.get(BASE) or not material.node_tree:
        return
    tree = material.node_tree
    output = _output(material)
    source = _source_socket(material, output)
    settings = getattr(material, SETTINGS)
    for node in list(tree.nodes):
        if node.get(TAG):
            tree.nodes.remove(node)
    tree.links.new(source, output.inputs['Surface'])
    if not settings.enabled:
        material[ERROR] = ''
        return
    frame = tree.nodes.new('NodeFrame')
    frame[TAG] = True
    frame.label = '武器静态发光 · ' + settings.role
    def node(kind, label):
        made = tree.nodes.new(kind)
        made[TAG] = True
        made.label = label
        made.parent = frame
        return made
    emission = node('ShaderNodeEmission', '独立区域自发光')
    emission.inputs['Color'].default_value = settings.color
    emission.inputs['Strength'].default_value = settings.strength
    for image in (settings.mask, settings.mask_secondary):
        if image is None:
            continue
        # Reuse the existing sampler where unique: preserve UV/ST and sampler state.
        samplers = [value for value in tree.nodes if value.bl_idname == 'ShaderNodeTexImage'
                    and value.image == image and not value.get(TAG)]
        if len(samplers) == 1:
            sampled = samplers[0].outputs['Color']
        else:
            texture = node('ShaderNodeTexImage', '静态遮罩 · ' + image.name)
            texture.image = image
            sampled = texture.outputs['Color']
        gray = node('ShaderNodeRGBToBW', 'RGB 发光遮罩（不使用全白 Alpha）')
        tree.links.new(sampled, gray.inputs['Color'])
        multiply = node('ShaderNodeMath', '遮罩 × 发光强度')
        multiply.operation = 'MULTIPLY'
        previous = emission.inputs['Strength']
        if previous.is_linked:
            tree.links.new(previous.links[0].from_socket, multiply.inputs[0])
        else:
            multiply.inputs[0].default_value = settings.strength
        tree.links.new(gray.outputs['Val'], multiply.inputs[1])
        tree.links.new(multiply.outputs[0], emission.inputs['Strength'])
    add = node('ShaderNodeAddShader', '保留原材质＋局部发光')
    tree.links.new(source, add.inputs[0])
    tree.links.new(emission.outputs[0], add.inputs[1])
    tree.links.new(add.outputs[0], output.inputs['Surface'])
    material[ERROR] = ''


def finalize(material):
    if material.get(BASE):
        hydrate_settings(material)
        rebuild(material)


def changed(self, context):
    material = self.id_data
    if (not isinstance(material, bpy.types.Material) or not material.get(BASE)
            or material.as_pointer() in _HYDRATING):
        return
    try:
        record_settings(material)
        rebuild(material)
    except Exception as exc:
        material[ERROR] = str(exc).splitlines()[0]


def apply(context):
    state = getattr(context.scene, STATE)
    target = target_of(context)
    regions = [(item.material, item.role, item.mask, item.mask_secondary)
               for item in state.regions if item.selected]
    if not state.regions:
        # Support old saved selections without requiring either half of the pair.
        regions = [(mat, role, image_of(mat, key), None)
                   for mat, role, key in ((state.string_material, '光弦', '_MainTex'),
                                          (state.pattern_material, '纹路', '_EmissionMap')) if mat]
    if not regions:
        state.note = '未选择发光区域，原材质保持不变'
        return
    sources = [entry[0] for entry in regions]
    if any(mat is None or mat.library for mat in sources):
        raise ValueError('请选择有效的本地材质')
    meshes = meshes_of(target)
    if target.library or any(obj.library for obj in meshes):
        raise ValueError('请选择本地武器对象；共享网格使用对象级材质副本')
    current = {slot.material for obj in meshes for slot in obj.material_slots}
    originals = {mat.get(BASE, mat) for mat in current if mat}
    if any(mat.get(BASE, mat) not in originals for mat in sources):
        raise ValueError('所选材质不属于此武器')
    resolved = [mat.get(BASE, mat) for mat in sources]
    if len(set(resolved)) != len(resolved):
        raise ValueError('同一来源材质只添加一个区域；不同网格可分别选择目标')
    made, bindings = [], []
    try:
        for source, (_, role, mask, secondary) in zip(resolved, regions):
            existing = [mat for mat in owned_materials(target) if mat.get(BASE) == source]
            if len(existing) > 1:
                raise ValueError('同一来源存在多份受管材质，请先整理')
            if existing:
                rebuild(existing[0])
                continue
            material = source.copy()
            made.append(material)
            material.name = source.name + ' · 静态' + role
            material[BASE], material[OWNER] = source, target
            material_builder.content(material)
            settings = getattr(material, SETTINGS)
            settings.role = role
            settings.color = (1, 1, 1, 1)
            settings.mask = mask
            settings.mask_secondary = secondary
            settings.strength = 3
            settings.enabled = False
            record_settings(material)
            rebuild(material)
            for obj in meshes:
                for index, slot in enumerate(obj.material_slots):
                    if slot.material != source:
                        continue
                    bindings.append((obj, index, slot.link, source))
                    links = dict(obj.get(BINDINGS, {}))
                    links[str(index)] = slot.link
                    obj[BINDINGS] = links
                    # Object-local override also protects linked mesh datablocks.
                    slot.link = 'OBJECT'
                    slot.material = material
        state.target = target
        state.note = '已准备独立发光区域；新区域默认关闭，已有调整保留'
    except Exception:
        for obj, index, link, source in reversed(bindings):
            slot = obj.material_slots[index]
            if link == 'DATA':
                slot.material = None
            slot.link = link
            if link == 'OBJECT':
                slot.material = source
            links = dict(obj.get(BINDINGS, {}))
            links.pop(str(index), None)
            obj[BINDINGS] = links
        for mat in made:
            if mat.users == int(mat.use_fake_user):
                mat.use_fake_user = False
                bpy.data.materials.remove(mat)
        raise


def normal(context):
    """Explicit preset for new or previous-version copies; never auto-migrate art."""
    target = target_of(context)
    materials = owned_materials(target)
    if not any(getattr(mat, SETTINGS).role == '光弦' for mat in materials):
        raise ValueError('此弓参考预设仅适用于明确标记为“光弦”的区域')
    for material in (mat for mat in materials if getattr(mat, SETTINGS).role in ('光弦', '纹路')):
        settings = getattr(material, SETTINGS)
        pointer = material.as_pointer()
        _HYDRATING.add(pointer)
        try:
            settings.color = NORMAL_COLOR
            settings.enabled = settings.role == '光弦'
            if settings.role == '光弦':
                settings.strength = STRING_STRENGTH
        finally:
            _HYDRATING.discard(pointer)
        record_settings(material)
        rebuild(material)
    getattr(context.scene, STATE).note = '弓参考预设：蓝紫光弦开启，纹路关闭；其他区域保持原样'


def restore(context):
    target = target_of(context)
    todo = []
    for obj in meshes_of(target):
        for index, slot in enumerate(obj.material_slots):
            material = slot.material
            if material is None or material.get(OWNER) != target or not material.get(BASE):
                continue
            source = material[BASE]
            link = obj.get(BINDINGS, {}).get(str(index))
            if link not in ('DATA', 'OBJECT'):
                raise ValueError('原材质绑定记录缺失，请先检查此武器')
            if link == 'DATA' and obj.data.materials[index] != source:
                raise ValueError('共享网格原材质槽已被修改，保留现有绑定')
            todo.append((obj, index, link, source, material))
    for obj, index, link, source, material in todo:
        slot = obj.material_slots[index]
        if link == 'DATA':
            slot.material = None
        slot.link = link
        if link == 'OBJECT':
            slot.material = source
        links = dict(obj.get(BINDINGS, {}))
        links.pop(str(index), None)
        obj[BINDINGS] = links
    for material in set(item[-1] for item in todo):
        if material.users == int(material.use_fake_user):
            material.use_fake_user = False
            bpy.data.materials.remove(material)
    getattr(context.scene, STATE).note = '已恢复原材质；外部共享的副本保留'


class RURI_PG_weapon_glow(bpy.types.PropertyGroup):
    role: StringProperty()
    enabled: BoolProperty(name='启用静态发光', default=False, update=changed)
    color: FloatVectorProperty(name='发光颜色', size=4, subtype='COLOR', min=0, max=1,
                               default=(1, 1, 1, 1), update=changed)
    strength: FloatProperty(name='发光强度', min=0, soft_max=20, max=1000, default=3, update=changed)
    mask: PointerProperty(name='发光遮罩', type=bpy.types.Image, update=changed)
    mask_secondary: PointerProperty(name='辅助遮罩', type=bpy.types.Image, update=changed)


class RURI_PG_glow_region(bpy.types.PropertyGroup):
    material: PointerProperty(type=bpy.types.Material)
    selected: BoolProperty(name='选择区域', default=False)
    role: StringProperty(name='区域标签', default='独立区域')
    mask: PointerProperty(name='遮罩（空为整个材质）', type=bpy.types.Image)
    mask_secondary: PointerProperty(name='辅助遮罩（可选）', type=bpy.types.Image)


class RURI_PG_weapon_glow_panel(bpy.types.PropertyGroup):
    target: PointerProperty(type=bpy.types.Object)
    regions: CollectionProperty(type=RURI_PG_glow_region)
    material: PointerProperty(type=bpy.types.Material)
    string_material: PointerProperty(type=bpy.types.Material)
    pattern_material: PointerProperty(type=bpy.types.Material)
    note: StringProperty()


class RURI_OT_glow_add_region(bpy.types.Operator):
    bl_idname = 'ruri.endfield_glow_add_region'
    bl_label = '添加独立区域'
    def execute(self, context):
        try:
            add_region(context)
        except Exception as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class RURI_OT_weapon_glow_scan(bpy.types.Operator):
    bl_idname = 'ruri.endfield_weapon_glow_scan'
    bl_label = '识别已有武器材质'
    def execute(self, context):
        try:
            scan(context)
        except Exception as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class RURI_OT_weapon_glow_apply(bpy.types.Operator):
    bl_idname = 'ruri.endfield_weapon_glow_apply'
    bl_label = '应用所选发光区域'
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        try:
            apply(context)
        except Exception as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class RURI_OT_weapon_glow_restore(bpy.types.Operator):
    bl_idname = 'ruri.endfield_weapon_glow_restore'
    bl_label = '恢复武器原材质'
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        try:
            restore(context)
        except Exception as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class RURI_OT_weapon_glow_normal(bpy.types.Operator):
    bl_idname = 'ruri.endfield_weapon_glow_normal'
    bl_label = '弓参考预设：仅光弦发光'
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        try:
            normal(context)
        except Exception as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


def draw_glow(layout, context):
    state = getattr(context.scene, STATE)
    layout.prop(state, 'target', text='武器目标')
    layout.operator(RURI_OT_weapon_glow_scan.bl_idname)
    for item in state.regions:
        box = layout.box()
        box.prop(item, 'selected', text=item.material.name if item.material else '材质已移除')
        box.prop(item, 'role', text='区域标签')
        box.prop(item, 'mask')
        box.prop(item, 'mask_secondary')
    layout.prop(state, 'material', text='手动添加材质')
    layout.operator(RURI_OT_glow_add_region.bl_idname)
    layout.operator(RURI_OT_weapon_glow_apply.bl_idname)
    if state.target and any(getattr(mat, SETTINGS).role == '光弦' for mat in owned_materials(state.target)):
        layout.operator(RURI_OT_weapon_glow_normal.bl_idname)
    if state.target and state.target.name in context.scene.objects:
        for material in owned_materials(state.target):
            settings = getattr(material, SETTINGS)
            box = layout.box()
            box.label(text=material.name + ' · ' + settings.role)
            box.prop(settings, 'enabled')
            box.prop(settings, 'color')
            box.prop(settings, 'strength')
            box.prop(settings, 'mask')
            box.prop(settings, 'mask_secondary')
            if material.get(ERROR):
                box.label(text=material[ERROR][:90], icon='ERROR')
    layout.operator(RURI_OT_weapon_glow_restore.bl_idname)
    layout.label(text='仅 Blender 静态材质；不涉及游戏动态逻辑', icon='INFO')
    layout.label(text='自发光≠光晕；合成器辉光保持原设置')
    layout.label(text='贴图候选不代表游戏显隐；无需光弦与纹路配对')
    if state.note:
        layout.label(text=state.note[:90])


CLASSES = (RURI_PG_weapon_glow, RURI_PG_glow_region, RURI_PG_weapon_glow_panel,
           RURI_OT_glow_add_region, RURI_OT_weapon_glow_scan,
           RURI_OT_weapon_glow_apply, RURI_OT_weapon_glow_restore, RURI_OT_weapon_glow_normal)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    setattr(bpy.types.Material, SETTINGS, PointerProperty(type=RURI_PG_weapon_glow))
    setattr(bpy.types.Scene, STATE, PointerProperty(type=RURI_PG_weapon_glow_panel))
    material_builder.MATERIAL_FINALIZERS.add(finalize)
    from .. import weapon
    weapon.register_section('glow', draw_glow)


def unregister():
    from .. import weapon
    weapon.drop_section('glow')
    material_builder.MATERIAL_FINALIZERS.remove(finalize)
    delattr(bpy.types.Scene, STATE)
    delattr(bpy.types.Material, SETTINGS)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
