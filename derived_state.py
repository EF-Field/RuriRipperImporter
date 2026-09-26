"""场景派生态的唯一调度器 —— 「什么时候重建 Ruri 生成的场景衍生物」只在这里回答一次。

派生态 = 不是从资产直接读出来、而是**由场景真值算出来**的东西:顶点腿(壳层位移 /
反壳描边 / 脸部骨骼基座)、材质的环境查询兑现节点、灯表像素、合成器后处理链。
它们的共同点是「输入变了就必须重算,不重算画面静默错」。

## 为什么不是各导入路径自己调 apply_xxx

那等于要求**每一个入口都记得手动收尾**,漏一个就是画面上毫无痕迹的缺失。实测漏了四条:

* NPC 装配路径从不跑顶点腿(壳毛/描边/脸基座全无);
* 浏览器直接导入角色不跑顶点腿(只有 roster 面板那一条补跑了);
* 场景窗口导入两样都不跑;
* 剧情单元建完过场相机后没人重算描边的视图基。

真源不该是「N 个调用点」,而是「一次事实变更 → 调度器决定跑哪些阶段」。
于是导入器**只管造东西**(造完 announce 一声),面板**一行收尾都不写**。

## 事实与阶段

事实(fact)= 派生态依赖的场景真值。阶段(stage)= 一段派生态,声明自己读哪些事实。
调度器把「本批脏了哪些事实」映射成「跑哪些阶段」:

* 新增一条派生态 = STAGES 表加一行;
* 新增一条导入路径 = **零行**(它造对象时已经经过 announce 了);
* 新增一个游戏 = 零行(阶段本体由各游戏生成物自注册进 material_builder 的注册表,
  这里只认注册表,不认任何游戏)。

阶段本体不在这里:生成的着色栈自己 `register_vertex_stage` / `register_capability_rewire`
/ `register_light_table_refresh` / `register_post_stage`(那是生成器拥有的契约)。本模块
只拥有**时机**:谁在什么变更下跑、跑在哪个范围上。

## 时机是空闲态,不是操作符结束

批量导入会造几百个对象,逐个收尾是 O(n²);而相机拖动每帧都在变。所以 announce 只打脏
标记,真正落地由一个去抖计时器在事件循环空闲时做一次 —— 一次导入 = 一次收敛。
"""

from __future__ import annotations

import time
import traceback

import bpy

try:
    from . import material_builder
except ImportError:  # standalone (non-package) testing
    import material_builder


# ---- 事实 ----
OBJECTS = "objects"            # 有新对象进场
MATERIALS = "materials"        # 有新材质进场
CAMERA = "camera"              # 活动相机的身份/位姿/投影/输出分辨率
LIGHT_SET = "light_set"        # 灯的增删/类型/可见性(生成栈的灯表:改像素即生效,零重接)
LIGHT_VALUES = "light_values"  # 灯的位姿/颜色/强度/锥角(同上,表像素)
WORLD = "world"                # 世界被换(环境采样是建组时快照,只有这件事还要重接兑现面)
RIG = "rig"                    # 骨架的骨骼名册变了(顶点腿的骨骼基座按名字接进几何节点)

ALL_FACTS = frozenset((OBJECTS, MATERIALS, CAMERA, LIGHT_SET, LIGHT_VALUES, WORLD, RIG))

# 去抖窗口:批量导入的几百次 announce、相机拖动的每帧变更,都收敛成末尾的一次落地。
DEBOUNCE_SECONDS = 0.1

# 最近一次落地里炸掉的阶段,面板照着喊。派生态失败在画面上与「着色器本来就长这样」
# 完全无法区分,所以它必须留下能被看见的痕迹,而不是只在控制台滚过去。
LAST_ERROR = ""


class Change:
    """一次落地要处理的变更:脏了哪些事实、这批新造了什么、范围是不是整场景。

    ``whole_scene`` 为真时,已经存在的产物也失效了(相机动了 → 每个描边壳的视图基都
    过期;灯集合变了 → 每个材质的兑现分支都可能变),所以阶段必须扫全场,而不是只看
    这批新对象。"""

    __slots__ = ("facts", "objects", "materials", "whole_scene", "scene", "view_layer")

    def __init__(self, facts, objects, materials, whole_scene, scene, view_layer=None):
        self.facts = frozenset(facts)
        self.objects = objects
        self.materials = materials
        self.whole_scene = whole_scene
        self.scene = scene
        self.view_layer = view_layer

    def __repr__(self):
        return "<Change {0} objects={1} materials={2}{3}>".format(
            ",".join(sorted(self.facts)), len(self.objects), len(self.materials),
            " whole-scene" if self.whole_scene else "")


class Stage:
    """一段派生态。``facts`` 是它读的事实集合,与本批脏事实有交集就跑。"""

    __slots__ = ("name", "facts", "run")

    def __init__(self, name, facts, run):
        self.name = name
        self.facts = frozenset(facts)
        self.run = run

    def __repr__(self):
        return "<Stage {0} reads={1}>".format(self.name, ",".join(sorted(self.facts)))


def _run_capabilities(change):
    """材质的环境查询兑现面重接。只剩一个触发者:**世界被换**(环境采样是建组时快照)。

    灯**一概不进这条路** —— 缺省主光是从 Blender 内置闭包反解出来的(六轴辐照度探针),
    材质树里没有任何灯物体指针,加灯/删灯/挪灯/换色由依赖图重算闭包就完了。
    唯一还绑灯的是用户主动指定的逐角色覆盖灯,由设置它的算子对那一张材质单独重接。

    这条纪律的理由是量出来的:重接是 O(材质 × 树),单张 NPR 角色材质 ~0.8s、24 张 20 秒。
    摆灯是美术每秒都在做的事,绝不能和它挂钩。"""
    scope = None if change.whole_scene else change.materials
    return material_builder.rewire_capabilities(scope)


def _run_light_tables(_change):
    return material_builder.refresh_light_tables()


def _run_vertex(change):
    """顶点腿。相机基轴是逐对象烘进几何节点树的快照,所以相机一变就得全场重建;
    单纯多了几个对象时只处理这几个。

    骨骼名册也在这条路上:脸部基座是按**当下骨名**接进 GeometryNodeBoneInfo 的,而名字
    是改得动的东西 —— 绑定的身份存在骨的印记上,这里负责把那份身份重新翻成当下的名字。
    不重接就是 Exists=False、基座属性一个点都不写、SDF 悄悄回到绑定姿势。"""
    # Scene Strip 求值时当前 UI 场景通常仍是剪辑场景。按来源 View Layer 明确传入
    # 对象与相机，避免跨 Scene 扫描共享对象，也让纯 VSE Scene 成为零成本路径。
    if change.whole_scene:
        scope = list(change.view_layer.objects) if change.view_layer is not None else list(change.scene.objects)
    else:
        scope = change.objects
    if not scope or change.scene.camera is None:
        return 0
    return material_builder.apply_vertex_stages(objects=scope, camera=change.scene.camera)


def _run_post(change):
    return len(material_builder.apply_post_stages(change.scene))


def _run_material_panels(change):
    """材质参数面板是图的镜子,图刚建好就得照一次 —— 否则面板显示的是接口缺省值,
    用户一动某一格就把**没回读过的其它格**按缺省写进图里。"""
    from . import material_panel

    pool = list(bpy.data.materials) if change.whole_scene else change.materials
    return material_panel.sync_all(pool)


# 表就是调度策略的全部。顺序 = 注册顺序:兑现节点先接好,顶点腿再按材质真值建树,
# 后处理最后落在合成器上(三者互不读对方产物,顺序只为报告好读)。
STAGES = (
    Stage("capabilities", (WORLD,), _run_capabilities),
    Stage("light-tables", (LIGHT_SET, LIGHT_VALUES), _run_light_tables),
    Stage("vertex", (OBJECTS, MATERIALS, CAMERA, RIG), _run_vertex),
    # 后处理读的其实是「这个场景现在在放游戏内容了吗」:网格、材质、游戏自己的灯,
    # 任何一样进场都是证据(展示台可以只上太阳不上美术,那时也该有 tonemap)。
    # 装过就跳过,所以在灯上反复触发也只是一次 installed() 判断。
    Stage("post", (OBJECTS, MATERIALS, LIGHT_SET), _run_post),
    Stage("material-panels", (MATERIALS,), _run_material_panels),
)


# ---- 待落地队列（按 Scene + View Layer 隔离）----
_pending = {}
_flushing = False


def _view_layer_for(scene, view_layer=None):
    if view_layer is not None:
        try:
            if view_layer.id_data is scene:
                return view_layer
        except (ReferenceError, AttributeError):
            pass
    context_layer = getattr(bpy.context, "view_layer", None)
    if getattr(bpy.context, "scene", None) is scene and context_layer is not None:
        return context_layer
    return scene.view_layers[0] if scene.view_layers else None


def _scene_key(scene, view_layer=None):
    layer = _view_layer_for(scene, view_layer)
    return (scene.as_pointer(), 0 if layer is None else layer.as_pointer())


def announce(*datablocks):
    """生产者报告新数据；批次绑定调用当下的 Scene/View Layer。"""
    facts = set()
    objects = []
    materials = []
    for block in datablocks:
        if isinstance(block, bpy.types.Object):
            facts.add(OBJECTS)
            objects.append(block)
            if block.type == "LIGHT":
                facts.add(LIGHT_SET)
        elif isinstance(block, bpy.types.Material):
            facts.add(MATERIALS)
            materials.append(block)
    if facts:
        _mark(facts, objects=objects, materials=materials)


def _mark(facts, objects=(), materials=(), whole_scene=False, scene=None, view_layer=None):
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return
    view_layer = _view_layer_for(scene, view_layer)
    key = _scene_key(scene, view_layer)
    batch = _pending.get(key)
    if batch is None:
        batch = {"scene": scene, "view_layer": view_layer, "facts": set(),
                 "objects": [], "materials": [], "whole_scene": False, "marked_at": 0.0}
        _pending[key] = batch
    batch["facts"].update(facts)
    batch["objects"].extend(objects)
    batch["materials"].extend(materials)
    batch["whole_scene"] = batch["whole_scene"] or whole_scene
    batch["marked_at"] = time.monotonic()
    _arm_timer()


def _arm_timer():
    if _flushing or bpy.app.timers.is_registered(_tick):
        return
    bpy.app.timers.register(_tick, first_interval=DEBOUNCE_SECONDS)


def _tick():
    if not _pending:
        return None
    now = time.monotonic()
    due = [key for key, batch in list(_pending.items())
           if now - batch["marked_at"] >= DEBOUNCE_SECONDS]
    if not due:
        return max(0.01, min(DEBOUNCE_SECONDS - (now - batch["marked_at"])
                             for batch in _pending.values()))
    for key in due:
        flush(_key=key)
    return DEBOUNCE_SECONDS if _pending else None


def _live(datablocks):
    alive = []
    seen = set()
    for block in datablocks:
        try:
            pointer = block.as_pointer()
            block.name
        except ReferenceError:
            continue
        if pointer not in seen:
            alive.append(block)
            seen.add(pointer)
    return alive


def _in_view_layer(objects, scene, view_layer):
    pool = view_layer.objects if view_layer is not None else scene.objects
    return [obj for obj in objects if pool.get(obj.name) is obj]


def flush(scene=None, view_layer=None, _key=None):
    """只落地指定来源 Scene/View Layer 的批次。"""
    global _flushing, LAST_ERROR
    if _flushing:
        return None
    if _key is None:
        scene = scene or getattr(bpy.context, "scene", None)
        if scene is None:
            return None
        view_layer = _view_layer_for(scene, view_layer)
        _key = _scene_key(scene, view_layer)
    batch = _pending.pop(_key, None)
    if batch is None:
        return None
    scene = batch["scene"]
    view_layer = _view_layer_for(scene, batch["view_layer"])
    change = Change(batch["facts"],
                    _in_view_layer(_live(batch["objects"]), scene, view_layer),
                    _live(batch["materials"]), batch["whole_scene"], scene, view_layer)
    _flushing = True
    failures = []
    try:
        with bpy.context.temp_override(scene=scene, view_layer=view_layer):
            for stage in STAGES:
                if not (stage.facts & change.facts):
                    continue
                try:
                    stage.run(change)
                except Exception as error:
                    traceback.print_exc()
                    print("[ruri-derived] !! 阶段 '{0}' 失败:{1}".format(stage.name, error), flush=True)
                    failures.append("{0}: {1}".format(stage.name, error))
    finally:
        _flushing = False
        _resnapshot(scene, view_layer)
        if _pending:
            _arm_timer()
    LAST_ERROR = "; ".join(failures)
    return change


def rebuild_all():
    scene = getattr(bpy.context, "scene", None)
    view_layer = getattr(bpy.context, "view_layer", None)
    _mark(ALL_FACTS, whole_scene=True, scene=scene, view_layer=view_layer)
    return flush(scene=scene, view_layer=view_layer)


# ---- 监视器:没有生产者的那半边 ----
# 加载器造东西会 announce;用户拖相机、挪灯、改输出分辨率没有生产者,只能看依赖图。
# 两条闸分开判,因为代价差一个数量级:相机签名是 O(1),灯签名要扫全场对象。

_snapshots = {}


def _objects_for(scene, view_layer=None):
    return view_layer.objects if view_layer is not None else scene.objects


def _light_set_signature(scene, view_layer=None):
    signature = []
    for obj in _objects_for(scene, view_layer):
        if obj.type != "LIGHT":
            continue
        try:
            visible = obj.visible_get()
        except Exception:
            visible = not obj.hide_viewport
        signature.append((obj.name, obj.data.type, visible))
    signature.sort()
    return tuple(signature)


def _world_signature(scene):
    """世界的身份。环境采样是各材质建组时的快照,换世界是唯一还需要重接兑现面的事件
    —— 所以它是独立事实,不再混在灯集合签名里(混着的时候,加一盏灯也会触发全场重接)。"""
    return scene.world.name_full if scene.world is not None else None


def _light_values_signature(scene, view_layer=None):
    signature = []
    for obj in _objects_for(scene, view_layer):
        if obj.type != "LIGHT":
            continue
        light = obj.data
        signature.append((
            obj.name,
            tuple(round(c, 5) for row in obj.matrix_world for c in row),
            tuple(round(c, 5) for c in light.color),
            round(light.energy, 5),
            round(getattr(light, "spot_size", 0.0), 5),
            round(getattr(light, "spot_blend", 0.0), 5),
        ))
    signature.sort()
    return tuple(signature)


def _camera_signature(scene):
    """描边宽度是按投影矩阵与真实 backbuffer 像素解的(见生成物 apply_vertex_stage),
    所以「相机变了」包含镜头与输出设置,不只是位姿。"""
    camera = scene.camera
    if camera is None:
        return None
    data = camera.data
    render = scene.render
    return (
        camera.name_full,
        tuple(round(c, 5) for row in camera.matrix_world for c in row),
        getattr(data, "type", ""),
        round(getattr(data, "angle_y", 0.0), 6),
        round(getattr(data, "ortho_scale", 0.0), 6),
        round(getattr(data, "shift_x", 0.0), 6),
        round(getattr(data, "shift_y", 0.0), 6),
        render.resolution_x, render.resolution_y, render.resolution_percentage,
        round(render.pixel_aspect_x, 5), round(render.pixel_aspect_y, 5),
    )


def _rig_signature(scene, view_layer=None):
    """骨骼名册。摆姿势不在其内 —— 那是每帧都在变的东西,而这里问的是「名字还是不是那些」。"""
    signature = []
    for obj in _objects_for(scene, view_layer):
        if obj.type != "ARMATURE" or obj.data is None:
            continue
        signature.append((obj.name_full, tuple(bone.name for bone in obj.data.bones)))
    signature.sort()
    return tuple(signature)


def _rig_touched(depsgraph):
    """只认 **Armature 数据块**:摆姿势 / 播放动画标记的是 Object,一帧一次;改名、加删骨、
    退出编辑模式标记的才是数据本身。判据下在这里,签名才不必每帧扫几百根骨。"""
    for update in depsgraph.updates:
        if isinstance(update.id, bpy.types.Armature):
            return True
    return False


def _lights_touched(depsgraph):
    for update in depsgraph.updates:
        block = update.id
        if isinstance(block, (bpy.types.Light, bpy.types.World, bpy.types.Collection)):
            return True
        if isinstance(block, bpy.types.Object) and getattr(block, "type", "") == "LIGHT":
            return True
    return False


def _camera_touched(depsgraph):
    for update in depsgraph.updates:
        block = update.id
        if isinstance(block, (bpy.types.Camera, bpy.types.Scene)):
            return True
        if isinstance(block, bpy.types.Object) and getattr(block, "type", "") == "CAMERA":
            return True
    return False


def _resnapshot(scene, view_layer=None):
    view_layer = _view_layer_for(scene, view_layer)
    _snapshots[_scene_key(scene, view_layer)] = {
        "light_set": _light_set_signature(scene, view_layer),
        "light_values": _light_values_signature(scene, view_layer),
        "camera": _camera_signature(scene),
        "world": _world_signature(scene),
        "rig": _rig_signature(scene, view_layer),
    }


@bpy.app.handlers.persistent
def _on_depsgraph_update(scene, depsgraph):
    if _flushing or scene is None:
        return
    view_layer = _view_layer_for(scene, getattr(depsgraph, "view_layer", None))
    key = _scene_key(scene, view_layer)
    state = _snapshots.get(key)
    if state is None:
        _resnapshot(scene, view_layer)
        return
    if _rig_touched(depsgraph):
        rig = _rig_signature(scene, view_layer)
        if rig != state["rig"]:
            state["rig"] = rig
            _mark((RIG,), whole_scene=True, scene=scene, view_layer=view_layer)
    if _lights_touched(depsgraph):
        world = _world_signature(scene)
        if world != state["world"]:
            state["world"] = world
            _mark((WORLD,), whole_scene=True, scene=scene, view_layer=view_layer)
        light_set = _light_set_signature(scene, view_layer)
        light_values = _light_values_signature(scene, view_layer)
        if light_set != state["light_set"]:
            state["light_set"], state["light_values"] = light_set, light_values
            _mark((LIGHT_SET,), whole_scene=True, scene=scene, view_layer=view_layer)
        elif light_values != state["light_values"]:
            state["light_values"] = light_values
            _mark((LIGHT_VALUES,), whole_scene=True, scene=scene, view_layer=view_layer)
    if _camera_touched(depsgraph):
        camera = _camera_signature(scene)
        if camera != state["camera"]:
            state["camera"] = camera
            _mark((CAMERA,), whole_scene=True, scene=scene, view_layer=view_layer)


@bpy.app.handlers.persistent
def _on_load_post(_path):
    _pending.clear()
    _snapshots.clear()
    for scene in bpy.data.scenes:
        for view_layer in scene.view_layers:
            _resnapshot(scene, view_layer)


def register():
    handlers = bpy.app.handlers
    if _on_depsgraph_update not in handlers.depsgraph_update_post:
        handlers.depsgraph_update_post.append(_on_depsgraph_update)
    if _on_load_post not in handlers.load_post:
        handlers.load_post.append(_on_load_post)
    _snapshots.clear()
    # addon_utils 在 register() 期间会把 bpy.data 替换成 _RestrictData；此时只挂 handler。
    # 正常运行时可立即建基线，受限阶段则由 load_post / 首次 depsgraph 更新惰性建基线。
    scenes = getattr(bpy.data, "scenes", None)
    if scenes is not None:
        for scene in scenes:
            for view_layer in scene.view_layers:
                _resnapshot(scene, view_layer)


def unregister():
    handlers = bpy.app.handlers
    if _on_depsgraph_update in handlers.depsgraph_update_post:
        handlers.depsgraph_update_post.remove(_on_depsgraph_update)
    if _on_load_post in handlers.load_post:
        handlers.load_post.remove(_on_load_post)
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    _pending.clear()
    _snapshots.clear()
