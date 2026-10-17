"""Native controls and opt-in artist emission on imported weapon materials.

The private reader declares channel policy from live host facts, without asset reload.
Shared source materials remain intact. Native controls use the original stack;
only explicit artist overlays add a texture-masked emission branch.
"""
import json

import bpy
from bpy.props import BoolProperty, CollectionProperty, FloatProperty, FloatVectorProperty, PointerProperty, StringProperty

from ....Host.Blender import material_builder
from . import weapons, weapon_channels

STATE = 'ruri_weapon_glow_panel'
SETTINGS = 'ruri_weapon_glow'
BASE = 'ruri_glow_source_material'
OWNER = 'ruri_glow_weapon_owner'
TAG = 'ruri_glow_node'
LINK = 'ruri_glow_surface_source'
ERROR = 'ruri_glow_error'
BINDINGS = 'ruri_glow_binding_links'
RECORD = 'ruri_glow_settings_record'
NATIVE = 'ruri_glow_native_control'
PREVIEW = 'ruri_glow_manual_preview_object'
VISIBILITY = 'ruri_glow_manual_preview_visibility'
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
    # Invalidate before resolving: a removed scene target must not leave the
    # previous weapon's actionable rows on screen after an unsuccessful scan.
    state.regions.clear()
    state.channels.clear()
    state.scanned_target = None
    target = target_of(context)
    materials = list(dict.fromkeys(slot.material.get(BASE, slot.material)
                    for obj in meshes_of(target) for slot in obj.material_slots if slot.material))
    # Old saved panel pointers are migration input only, never a second catalog.
    state.string_material = state.pattern_material = None
    state.target = target
    state.scanned_target = target
    owned = {mat[BASE]: mat for mat in owned_materials(target)}
    for mat in materials:
        live = owned.get(mat, mat)
        channels = weapon_channels.discover(live, refresh=True)
        for channel in channels:
            item = state.channels.add()
            item.material, item.kind, item.role = mat, channel['kind'], channel['label']
            item.selected = bool(channel['gate'])
            item.detail = ('扫描时原生开关已开启' if channel['enabled'] else '扫描时原生开关关闭') if channel['gate'] else '保留原 Shader；展开查看原生参数'
        if not channels:
            item = state.channels.add()
            item.material, item.kind, item.role = mat, 'UNKNOWN', '待确认材质'
            status = live.get(weapon_channels.STATUS, '')
            item.detail = status if status.startswith(('UNKNOWN:', 'CACHED:')) else '未确认有效原生通道；不会自动点亮或替换材质'
        # Native materials use their source graph, never an automatic grayscale
        # overlay. Existing artist-authored overlays remain editable on rescan.
        if channels and (mat not in owned or owned[mat].get(NATIVE)):
            continue
        candidate = next(iter(weapon_channels.describe(live)['manual']), None)
        mask = image_of(mat, candidate['image']) if candidate else None
        if not mask and mat not in owned:
            continue
        item = state.regions.add()
        item.material = mat
        item.selected = bool((candidate and candidate['selected']) or mat in owned)
        item.role = candidate['role'] if candidate else '独立区域'
        item.mask = mask
        # A MainTex is only a candidate. Neither VFX nor a material name proves
        # an emissive role, an auxiliary-mask product, or a default visible state.
        if mat in owned:
            settings = getattr(owned[mat], SETTINGS)
            item.role, item.mask = settings.role, settings.mask
            item.mask_secondary = settings.mask_secondary
    unknown = sum(channel.kind == 'UNKNOWN' for channel in state.channels)
    state.note = '原生通道 %d 项；待确认 %d 项；手动候选 %d 项' % (len(state.channels) - unknown, unknown, len(state.regions))


def add_region(context):
    state = getattr(context.scene, STATE)
    target = target_of(context)
    if state.scanned_target != target:
        state.regions.clear()
        state.channels.clear()
        state.target = target
        state.scanned_target = target
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
    candidate = next((row for row in weapon_channels.describe(material)['manual'] if row['selected']), None)
    item.mask = image_of(material, candidate['image']) if candidate else None
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
        if material.get(PREVIEW):
            preview_visibility(material[PREVIEW])
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
    if material.get(PREVIEW):
        preview_visibility(material[PREVIEW])


def preview_visibility(obj):
    """Explicit artist preview visibility, never inferred gameplay state."""
    saved = obj.get(VISIBILITY)
    if saved is None:
        return
    previews = [s.material for s in obj.material_slots if s.material and s.material.get(PREVIEW) == obj]
    enabled = any(getattr(mat, SETTINGS).enabled for mat in previews)
    obj.hide_viewport = False if enabled else bool(saved['viewport'])
    obj.hide_render = False if enabled else bool(saved['render'])
    if obj.name in bpy.context.view_layer.objects:
        obj.hide_set(False if enabled else bool(saved['layer']))
    if not previews:
        del obj[VISIBILITY]


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


def apply(context, native_only=None):
    state = getattr(context.scene, STATE)
    target = target_of(context)
    if state.scanned_target is not None and state.scanned_target != target:
        raise ValueError('武器目标已变化，请重新扫描')
    native = (list(native_only) if native_only is not None else
              list(dict.fromkeys(item.material for item in state.channels
                                 if item.selected and item.kind != 'UNKNOWN')))
    regions = ([] if native_only is not None else
               [(item.material, item.role, item.mask, item.mask_secondary)
                for item in state.regions if item.selected])
    if native_only is None and not state.regions:
        # Support old saved selections without requiring either half of the pair.
        regions = [(mat, role, image_of(mat, key), None)
                   for mat, role, key in ((state.string_material, '光弦', '_MainTex'),
                                          (state.pattern_material, '纹路', '_EmissionMap')) if mat]
    if not regions and not native:
        state.note = '未选择发光区域，原材质保持不变'
        return
    overlay_sources = [entry[0] for entry in regions]
    sources = list(dict.fromkeys(overlay_sources + native))
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
    if len(set(overlay_sources)) != len(overlay_sources):
        raise ValueError('同一来源材质只添加一个区域；不同网格可分别选择目标')
    if any(mat.get(NATIVE) and mat.get(BASE) in overlay_sources for mat in owned_materials(target)):
        raise ValueError('此材质已有原生控制，请先恢复原材质，再准备手动叠加')
    made, bindings = [], []
    try:
        overlays = {mat.get(BASE, mat): (role, mask, secondary) for mat, role, mask, secondary in regions}
        for source in resolved:
            role, mask, secondary = overlays.get(source, ('原生通道', None, None))
            existing = [mat for mat in owned_materials(target) if mat.get(BASE) == source]
            if len(existing) > 1:
                raise ValueError('同一来源存在多份受管材质，请先整理')
            if existing:
                # Never silently replace an existing artist overlay with native
                # defaults or reset a user's native adjustments on repeated apply.
                rebuild(existing[0])
                continue
            material = source.copy()
            made.append(material)
            material.name = source.name + ' · 静态' + role
            material[BASE], material[OWNER] = source, target
            material[NATIVE] = source not in overlays
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
        state.note = '已准备对象局部材质副本；原生参数与源一致，手动叠加默认关闭'
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
    for obj in dict.fromkeys(item[0] for item in todo):
        preview_visibility(obj)
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


class RURI_PG_weapon_channel(bpy.types.PropertyGroup):
    material: PointerProperty(type=bpy.types.Material)
    kind: StringProperty()
    role: StringProperty()
    detail: StringProperty()
    selected: BoolProperty(name='准备独立控制', default=False)
    expanded: BoolProperty(name='展开参数', default=False)


def target_changed(self, context):
    if self.target != self.scanned_target:
        self.regions.clear()
        self.channels.clear()
        self.string_material = self.pattern_material = None
        self.scanned_target = None
        self.note = '目标已变化，请识别当前武器材质'


class RURI_PG_weapon_glow_panel(bpy.types.PropertyGroup):
    target: PointerProperty(type=bpy.types.Object, update=target_changed)
    scanned_target: PointerProperty(type=bpy.types.Object)
    channels: CollectionProperty(type=RURI_PG_weapon_channel)
    regions: CollectionProperty(type=RURI_PG_glow_region)
    material: PointerProperty(type=bpy.types.Material)
    string_material: PointerProperty(type=bpy.types.Material)
    pattern_material: PointerProperty(type=bpy.types.Material)
    note: StringProperty()
    advanced: BoolProperty(name='高级手动叠加', default=False)


def toggle_native(context, material, kind):
    target = target_of(context)
    if material is None:
        raise ValueError('请选择有效原生通道')
    source = material.get(BASE, material)
    live = next((mat for mat in owned_materials(target) if mat.get(BASE) == source), source)
    channel = weapon_channels.channel_of(live, kind)
    if channel is None:
        raise ValueError('原生通道已变化，请重新识别')
    entry, groups = weapon_channels.interface(live)
    gate = channel['gate']
    enabled = channel['enabled']
    apply(context, native_only=[source])
    live = next(mat for mat in owned_materials(target) if mat.get(BASE) == source)
    entry, groups = weapon_channels.interface(live)
    if gate:
        row = next(row for group in groups for row in group['rows'] if row['name'] == gate)
        entry['stack'].panel_write(live, row, not enabled)
    from ....Host.Blender import material_panel
    material_panel.sync(live)
    state = getattr(context.scene, STATE)
    for item in state.channels:
        if item.material == source and item.kind == kind:
            item.expanded = True
    state.note = (('已关闭' if enabled else '已开启') + channel['label']
                  if gate else '已打开原生特效参数；没有添加额外发光')
    return live


def toggle_preview(context, obj, material):
    """One-click, per-object manual emission. Not recovered source VFX."""
    target = target_of(context)
    if obj is None or obj not in meshes_of(target) or material is None:
        raise ValueError('请选择当前武器里的网格与材质')
    source = material.get(BASE, material)
    indices = [i for i, s in enumerate(obj.material_slots) if s.material and s.material.get(BASE, s.material) == source]
    if not indices or obj.library or source.library:
        raise ValueError('请选择此网格上的本地材质')
    if obj.animation_data and any(d.data_path in ('hide_viewport', 'hide_render') for d in obj.animation_data.drivers):
        raise ValueError('此网格显隐已有驱动，请先检查原驱动')
    copies = list(dict.fromkeys(obj.material_slots[i].material for i in indices))
    existing = [m for m in copies if m.get(PREVIEW) == obj]
    if existing:
        if len(existing) != 1:
            raise ValueError('此网格有多份预览材质，请先恢复原材质')
        settings = getattr(existing[0], SETTINGS)
        settings.enabled = not settings.enabled
        return existing[0]
    if any(m.get(BASE) for m in copies):
        raise ValueError('此区域已有独立控制，请先恢复原材质')
    baseline = obj.get(VISIBILITY)
    if baseline is None:
        obj[VISIBILITY] = dict(viewport=obj.hide_viewport, render=obj.hide_render, layer=obj.hide_get())
    material = source.copy()
    bindings = []
    try:
        material.name = source.name + ' · 手动发光预览'
        material[BASE], material[OWNER], material[NATIVE] = source, target, False
        material_builder.content(material)
        settings = getattr(material, SETTINGS)
        settings.role = '手动预览（不是游戏源材质）'
        settings.color = (1, 1, 1, 1)
        settings.strength = 3
        settings.mask = settings.mask_secondary = None
        settings.enabled = True
        if material.get(ERROR):
            raise ValueError(material[ERROR])
        for index in indices:
            slot = obj.material_slots[index]
            bindings.append((index, slot.link))
            links = dict(obj.get(BINDINGS, {}))
            links[str(index)] = slot.link
            obj[BINDINGS] = links
            slot.link, slot.material = 'OBJECT', material
        material[PREVIEW] = obj
        preview_visibility(obj)
        return material
    except Exception:
        for index, link in reversed(bindings):
            slot = obj.material_slots[index]
            if link == 'DATA':
                slot.material = None
            slot.link = link
            if link == 'OBJECT':
                slot.material = source
            links = dict(obj.get(BINDINGS, {}))
            links.pop(str(index), None)
            obj[BINDINGS] = links
        preview_visibility(obj)
        if material.users == int(material.use_fake_user):
            material.use_fake_user = False
            bpy.data.materials.remove(material)
        raise


class RURI_OT_weapon_manual_preview(bpy.types.Operator):
    bl_idname = 'ruri.endfield_weapon_manual_preview'
    bl_label = '手动发光预览'
    bl_description = '显示这个网格并增加可调人工自发光；不是已恢复游戏光效材质。再次点击关闭并恢复原显隐'
    bl_options = {'REGISTER', 'UNDO'}
    object_name: StringProperty()
    material_name: StringProperty()

    def execute(self, context):
        try:
            toggle_preview(context, bpy.data.objects.get(self.object_name), bpy.data.materials.get(self.material_name))
        except Exception as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class RURI_OT_weapon_channel_toggle(bpy.types.Operator):
    bl_idname = 'ruri.endfield_weapon_channel_toggle'
    bl_label = '切换原生光效'
    bl_description = '直接开启或关闭此原生通道；首次点击自动创建武器局部副本，保留共享源材质'
    bl_options = {'REGISTER', 'UNDO'}
    material_name: StringProperty()
    kind: StringProperty()

    def execute(self, context):
        try:
            toggle_native(context, bpy.data.materials.get(self.material_name), self.kind)
        except Exception as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


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


class RURI_OT_weapon_glow_target(bpy.types.Operator):
    bl_idname = 'ruri.endfield_weapon_glow_target'
    bl_label = '使用选中武器'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        target = context.object
        if target is None:
            self.report({'WARNING'}, '请先选中武器网格或根对象')
            return {'CANCELLED'}
        while target.parent and weapons.OWNER not in target:
            target = target.parent
        state = getattr(context.scene, STATE)
        previous = state.target
        state.target = target
        try:
            scan(context)
        except Exception as exc:
            state.target = previous
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class RURI_OT_weapon_glow_apply(bpy.types.Operator):
    bl_idname = 'ruri.endfield_weapon_glow_apply'
    bl_label = '准备所选独立控制'
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
    layout.operator(RURI_OT_weapon_glow_target.bl_idname, icon='EYEDROPPER')
    layout.operator(RURI_OT_weapon_glow_scan.bl_idname)
    valid = bool(state.target and state.target.name in context.scene.objects)
    if state.target and not valid:
        layout.label(text='目标已离开当前场景，请重新选择武器', icon='ERROR')
        return
    if not valid:
        layout.label(text='先选中武器，再点击“使用选中武器”', icon='INFO')
        return
    if valid:
        owned = {mat[BASE]: mat for mat in owned_materials(state.target)}
        for channel in state.channels:
            box = layout.box()
            if channel.material is None:
                box.label(text='材质已移除，请重新扫描', icon='ERROR')
                continue
            box.label(text=channel.role)
            box.label(text=channel.material.name)
            if channel.kind != 'UNKNOWN':
                live = owned.get(channel.material)
                enabled = False
                descriptor = weapon_channels.channel_of(live or channel.material, channel.kind)
                if descriptor is None:
                    box.label(text='通道已变化，请重新识别', icon='INFO')
                    continue
                if descriptor['gate']:
                    enabled = descriptor['enabled']
                    action = box.operator(RURI_OT_weapon_channel_toggle.bl_idname,
                                          text='关闭' if enabled else '开启', icon='LIGHT')
                else:
                    box.label(text='保留已有特效 Shader；不是额外发光', icon='INFO')
                    action = box.operator(RURI_OT_weapon_channel_toggle.bl_idname, text='调整原材质')
                action.material_name, action.kind = channel.material.name, channel.kind
                if live:
                    box.prop(channel, 'expanded', text='颜色／强度等参数')
                    if channel.expanded:
                        weapon_channels.draw(box, live, channel.kind)
                if state.advanced:
                    box.prop(channel, 'selected')
            else:
                box.label(text='未确认游戏光效材质；下方是人工预览', icon='INFO')
                box.label(text=channel.detail[:90], icon='INFO')
            users = [obj for obj in meshes_of(state.target) if any(
                slot.material and slot.material.get(BASE, slot.material) == channel.material for slot in obj.material_slots)]
            for obj in users:
                if channel.kind == 'UNKNOWN':
                    box.label(text=obj.name)
                    preview = next((s.material for s in obj.material_slots if s.material and
                                    s.material.get(PREVIEW) == obj and s.material.get(BASE) == channel.material), None)
                    on = preview is not None and getattr(preview, SETTINGS).enabled
                    action = box.operator(RURI_OT_weapon_manual_preview.bl_idname,
                                          text='关闭手动预览' if on else '手动发光预览', icon='LIGHT')
                    action.object_name, action.material_name = obj.name, channel.material.name
                    if preview:
                        settings = getattr(preview, SETTINGS)
                        box.prop(settings, 'color', text='预览颜色')
                        box.prop(settings, 'strength', text='预览亮度')
                if state.advanced and (obj.hide_viewport or obj.hide_render or channel.kind == 'UNKNOWN' or not descriptor['gate']):
                    row = box.row(align=True)
                    row.label(text=obj.name)
                    row.prop(obj, 'hide_viewport', text='', icon='HIDE_ON')
                    row.prop(obj, 'hide_render', text='', icon='RESTRICT_RENDER_ON')
        layout.prop(state, 'advanced')
        layout.operator(RURI_OT_weapon_glow_restore.bl_idname)
        layout.label(text='开启 = 原生开关；手动预览 = 人工自发光', icon='INFO')
        if not state.advanced:
            return
        layout.label(text='高级手动叠加（不代表游戏原效果）')
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
            if material.get(NATIVE) or material.get(PREVIEW):
                continue
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
    layout.label(text='原生控制保留颜色／HDR／透明；待确认项不自动点亮')
    if state.note:
        layout.label(text=state.note[:90])


CLASSES = (RURI_PG_weapon_glow, RURI_PG_glow_region, RURI_PG_weapon_channel, RURI_PG_weapon_glow_panel,
           RURI_OT_glow_add_region, RURI_OT_weapon_glow_scan,
           RURI_OT_weapon_glow_apply, RURI_OT_weapon_glow_restore, RURI_OT_weapon_glow_normal,
           RURI_OT_weapon_glow_target, RURI_OT_weapon_channel_toggle, RURI_OT_weapon_manual_preview)


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
