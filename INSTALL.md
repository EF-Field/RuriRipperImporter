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
