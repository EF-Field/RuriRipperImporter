# Blender 5.3 installation (Windows x64)

1. Install Blender 5.3 or newer and Microsoft .NET 10 SDK x64 (includes the
   .NET and ASP.NET Core runtimes required by the backend). Our regression host
   is Blender 5.3 Alpha; other builds need their own compatibility checks.
2. Open this repository's **Actions > Package Blender Add-on**, choose a successful
   run and download **RuriRipperImporter-Blender53** from Artifacts. Sign in to
   GitHub to download artifacts. Extract that download once: it contains the
   installable `RuriRipperImporter-Blender53.zip` and `SHA256SUMS.txt`.
3. In Blender: **Edit > Preferences > Add-ons > dropdown > Install from Disk**.
   Select the inner add-on ZIP and enable **RuriRipperImporter**. Its package root
   is already named correctly; no manual rename or Git clone is needed.
4. On first enable the plugin attempts to install its Python dependencies into
   its own workspace. Keep internet access available and inspect the console for
   dependency errors. Initial offline installation requires pre-provisioned wheels.
5. Obtain a compatible backend separately and extract it outside the add-on.
   Set **Ruri-RipperHook Bin Dir** in the add-on preferences to the directory
   directly containing `Ruri.RipperHook.dll` and
   `Ruri.RipperHook.CLI.runtimeconfig.json`. Preserve all sibling dependencies.
   Save preferences and restart Blender after changing backend versions.
6. Open the 3D Viewport sidebar with **N**, select **RuriRipper**, then **Assets >
   Add Install**, choose Game Root and build/load the resource index. Import a
   character before applying animation with **Play On Rig**. Old RCM6 indices
   should be rebuilt for this Statement backend rather than reused as RCM7.

## Endfield: Load Expressions

This feature requires a matching private backend that publishes
`endfield.morph.library` and its detail datasets. An older Statement snapshot
that imports models and body animation is not sufficient. The separately
delivered Load Expressions candidate needs both its frontend ZIP and runtime.

1. Save your current work, install the matching add-on, select the candidate's
   `statement-runtime` folder as Bin Dir, and restart Blender.
2. Load the game's resource index. Select the imported character's armature or a
   mesh skinned to it, and select the corresponding character in the roster.
3. Click **Load Expressions**, then open **Face > Library**. Static **Emotions**
   and **Poses** can be applied; **Rest Face** resets the bound controls.
4. Animated entries are built with **Build Checked Actions**, not applied as a
   static pose. Large animation/dialogue families are scoped to the character;
   the status reports what was skipped. Shared poses/emotions remain available.

The game's SkeletalMorph library drives facial bones; it is distinct from
**Find Expressions**, which lists authored mesh Shape Keys. Loading this library
does not enable **Retarget Face** or **Import Cloth**. Visual acceptance and
other-character/NPC coverage remain separate from the background regression.

The `bound/total` count beside an entry counts unique controls with effective
targets on this rig, versus all controls the entry names. It does not count
textures, keyframes or completeness of game-runtime expression playback.
`0/total` entries are dimmed; the shared library includes controls whose authored
mapping is empty on this character. Static entries are clicked/applied, while
animated entries must be checked and baked. A full ratio does not guarantee a
large visible change: weights may be tiny, or several entries may share the same
static pose. Applying an emotion currently previews its static pose only; it does
not schedule the game's automatic blinking/micro-expression state machine.

## Endfield: add character weapons

Requires the matching private Statement backend publishing
`endfield.character.weapons`; install the frontend and backend together and
restart Blender. Existing installed files are not patched automatically.

1. Open the game index and import the character normally.
2. Import and activate a character animation normally. By default the weapon
   section's **导入角色动作时自动匹配武器** option attaches matching fixed weapons
   and loads their matching animation. Character and weapon keep separate rigs
   and Actions, with playback aligned in seconds at the character sample rate.
3. Open **N > RuriRipper > Endfield 角色武器** for a small **Note** if no unique
   match was found. The character import still succeeds. You may ignore the note,
   or choose a weapon slot, click **读取可选武器动作**, select a row and click
   **加载此武器动作（可不选）**. No Import(Append) or manual rig selection is needed
   for this dedicated button. An existing weapon Action is retained on a miss.
4. Manual attachment is still available: choose **战斗** or **待机**, click
   **读取角色武器**, select a ready slot and **添加武器到角色**. Automatic mounting
   uses this chosen mode, normally visible fixed slots plus already attached slots;
   it does not infer skill visibility. Repeated imports reuse attachments and the
   managed weapon Action for the same source/rate/rig.

The matching backend must also publish `endfield.weapon.animations`. Matching is
conservative: exact full action suffix within the weapon's own animation library,
not fuzzy similarity or a proven game controller transition. Zero or multiple
candidates need manual choice. NLA blending is left for manual handling. Batch
imports synchronize only the first activated character clip; inactive Actions
do not start a weapon performance. Switching Actions later in the editor is not
an import and does not invoke this automatic pairing.

After attachment, the character becomes the active selection so the ordinary
animation import targets it even though the scene now has two rigs. Use
**选择角色（继续导入角色动作）** to select it again, or explicitly select the
weapon armature to import weapon animation.

For scenes made with the first weapon candidate, use **修复旧挂接方向** once.
It removes the duplicated standalone-import facing transform without changing
weapon Actions. New attachments apply this conversion automatically. Only
attachments carrying this feature's ownership/version stamps are affected.

Fixed prefab slots are resolved from the game's character configuration, with
authored mount names and scale, not guessed from object names. Rename-safe bone
identity is used. A socket follows the character bone; no constraints are added
to the weapon's internal bones. The attachment survives saving and reopening
without the plugin. Retain the normal external textures required by the scene.

Equipment-dependent and cross-weapon mounts are labelled and disabled. Hidden
slots can be manually previewed but are not scheduled by skill state. Automatic
skill visibility switching and effects are not included.
To replace a slot or change its idle/fight mount, first remove its socket and
weapon hierarchy. A modified existing constraint is reported rather than
silently replaced. Background regression is not visual/game-runtime acceptance.

## Optional Endfield legacy character shading

In Blender 5.3, open **N > RuriRipper > Endfield Shader Compatibility**.
Choose **Legacy 5.2 Compatible**. Subsequent character imports use the pinned
legacy shader; for characters already in the scene, click **Apply Mode to Scene
Characters**. Choose **Native 5.3** and apply again to return to current shading.
The choice is saved per scene, not globally in Blender preferences.

This changes character materials and their generated outline/vertex modifiers,
not meshes, armatures, animation curves or backend decoding. Original geometry
and animation imports remain on the Statement architecture. The existing
character-material bindings are replaced, including other users of shared
materials; save a scene copy before applying. Native mode remains the default.
Scene shaders and post-processing remain native. This is not Blender 5.2 support.
Lighting/world settings are retained: matching the old look also requires
matching its lighting; this option does not delete user lamps or choose an HDRI.

## Which backend?

- The public backend repository's **Build Hooks** workflow emits
  **RipperHook-PureRelease** (and a separate FModel artifact). PureRelease excludes
  private game adapters. It is not the Endfield-enabled backend.
- Endfield support requires access to `KawakazeNotFound/Endfield-GameHook`, or a
  separately supplied compatible private runtime. Its **Package Verified Runtime**
  workflow emits **Endfield-Statement-Runtime-Windows-x64**, containing
  `Endfield-Statement-Runtime.zip`. Extract that inner ZIP and select its
  `statement-runtime` folder as Bin Dir. This packages the verified snapshot;
  it is not a fresh source rebuild. `runtime` is the legacy ABI, not this version.
- Public frontend packages never contain backend binaries, private sources or
  game test fixtures. Private artifacts stay in the private repository.

Actions checks packaging/build boundaries. It does not replace a full Blender
GUI/material/all-animation regression. The validated animation case is raw
Attack01, 556 bones, 301 frames at 60 fps with no missing reference paths.
## Load Expressions field contract 2

Install the matching frontend **and** Hook Bin together. The expanded expression
reader imports avatar/control identity metadata, explicit BlendShape hash/index
maps, complete float/Vector4 shader declarations and typed emotion/animation
settings. An older Hook Bin is rejected with a contract-version message.

The static preview additionally drives explicitly mapped eyebrow Shape Keys and
existing shader uniform sockets. Non-All renderer masks require explicit renderer
role metadata; linked sockets and ambiguous mesh targets are reported rather than
rewired or guessed. Shared Shape Keys and shader components bake one sampled
FCurve per target; multiple contributing controls do not create duplicate curves.

Blink/special-eye/micro-expression references and timing settings are retained,
but automatic emotion scheduling and complete game-render parity are separate
features. Apply remains a static preview. Source/import/number checks do not
replace manual visual acceptance.

Save your own work before replacing an installed package and restarting Blender.
Do not unregister/reload the addon inside an unsaved scene to replace its CLR or
RNA classes. Candidate packages do not modify the existing installed runtime.

## 武器攻击特效：首阶段候选

此功能需配套的 **WeaponEffects-Phase1** 后端候选；已验收的旧后端没有
`endfield.character.projectile_effects` 和 `endfield.effect.components` 数据集。
这批候选不是完整攻击特效播放，也不替代原模型、动作及材质验收。

1. 手动安装匹配的插件与 Hook Bin，重启 Blender；原安装与场景请先自行保存。
2. 正常导入角色及动作。在侧栏 **Endfield 武器攻击特效 · 首阶段** 选角色，
   点击 **读取箭矢／命中特效**。昨日的武器动作配对照常保留。
3. 用 **筛选配置／效果** 找投射物配置，例如 `attack_01`，选择飞行或命中条目。
   目录列的是角色所属投射物的真实配置引用，不表示已经解出动作触发帧。
4. 默认在 3D 游标处手动查看资源；也可主动指定跟随对象／骨骼。
   **静态粒子源网格预览** 仅显示 mesh 模式粒子的原始几何与材质模板。
   Billboard、发射数量、寿命、噪声、拖尾、粒子运动和碰撞均未模拟。
5. 点击 **导入特效资源（首阶段）**。粒子参数、曲线、渐变和真实资源引用存入
   本实例的 `Effect source` JSON 文本；文本不执行代码。结果提示区分普通网格、
   静态模板与粒子参数，零普通网格不代表粒子已显示。
6. 相同来源与挂接的重复请求复用实例；切换模板预览或挂接选项前先移除旧实例。
   **移除此特效实例** 只删除本功能管理的层级；新增外部子对象会阻止删除，
   共享网格／材质与外部引用的来源文本保留。

当前真实资源测试对象为提弗洛斯。粒子动态播放、攻击轨迹重建、箭矢飞行与
命中位置、动作／技能时序、其他角色以及手动视觉一致性验收仍待后续实施。

## 武器静态发光：光弦与纹路

此项只操作已经导入 Blender 的网格、材质与贴图；无需新增后端接口，
也不读取游戏代码或启动逆向工具。它是可调的 Blender 静态表现，
不表示已还原游戏中的技能状态、材质切换或动态粒子逻辑。

1. 打开侧栏 **RuriRipper → Endfield 武器静态发光**。
2. **武器目标**选择武器挂接，例如 `Weapon slot 10`，而非角色根骨架。
3. 点击 **识别已有武器材质**，检查 **光弦材质**与**纹路材质**。
   提弗洛斯当前验证的光弦来源为 `M_fx_typhoea_objectline_001_zjm`，
   主体来源为 `M_wpn_misc_0051_01`。角色识别不唯一时手动选择。
4. 点击 **应用光弦／纹路静态发光**；两组分别调颜色、强度与开关。
   纹路使用已有 `_EmissionMap` 的 RGB 遮罩，光弦使用已有主图／辅助遮罩；
   这些贴图的 Alpha 可能全白，因此不以 Alpha 代替发光区域。
5. 用**材质预览**或**渲染**检查效果。自发光与周边光晕是两件事，
   本功能保持原合成器／辉光设置，不给角色或整个画面追加辉光。
6. **恢复武器原材质**撤回受管绑定。副本只绑定此武器的对象材质槽，
   原材质与共享网格数据槽保持原状；外部仍在使用的副本保留。

发光记录随 `.blend` 保存，插件重建材质时恢复。重复应用复用副本，
不会叠加发光分支。已导入贴图不足或绑定被外部修改时提示检查，
本功能不补猜游戏资源或状态。原安装、源场景及动作保持保留。
