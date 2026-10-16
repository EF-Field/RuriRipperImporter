# Weapon resources and optional equipment assembly

## Standalone imports

Weapon opens on **武器资源** by default. Like Character, its compact pane selector
is followed by category, shared search/rules, the resource list, shared import
options and Load/Reveal. Open an index, scan, select a row and Load; no character,
equipment slot or mount is required. Materials and referenced textures use the
ordinary import pipeline, including the selected Game Shaders setting. Scanning
does not import anything or alter existing scene objects.

The matching private reader publishes `endfield.weapon.resources`: exact top-level
weapon prefab routes, including `misc` props/skill resources and unknown families.
The latter are standalone source resources, not a claim of equipment eligibility.
Ambiguous CAB routes stay visible with an empty load payload. Chinese display
names preserve the technical name; full source paths and status remain searchable.
Switching installs/reloading maps invalidates the displayed catalog for loading
until it is scanned again. A failed scan also invalidates the prior catalog.

Existing saved pane selections remain unchanged. Mount, effects and static glow
remain separate panes; standalone import never steals the selected character.

## Explicit equipment selection

The Weapon / Mount pane now separates conventional equipment from fixed character
resources. Use the matching private backend built with this feature.

1. Open the install's existing resource index in the usual browser.
2. Character imports automatically set Weapon's actor to the last successfully
   imported rig. Its pointer-icon button selects that rig for subsequent character
   actions; the actor picker can still be set manually. Read its weapon slots.
3. Select an **equipment** slot, then scan the equipment catalog.
4. Explicitly select a resource. Scanning selects nothing by default.
5. Choose **装配／替换所选武器**. A successful replacement commits that character's
   selection; an import failure keeps its previous weapon and choice.

Choices live on each character, survive save/reopen and are supplied back to the
reader as an explicit slot-to-prefab mapping. No live player loadout is read.
Fixed props stay in their original slots and retain their own manual preview.

The compact mount pane has no separate catalog heading/search field or redundant
bottom preview notice. Chinese/internal resource labels remain unchanged. Following
Character imports is independent of animation auto-sync, clears previous actor's
slot/action candidates, and does not steal the target during weapon/prop imports.
The shared import-completion notification carries only caller UI metadata and the
host build result; it does not interpret seeds or change backend data parsing.

## Catalog boundary

The private backend enumerates exact prefab container paths from the loaded
CabTable. It groups by full path and counts distinct CAB owners. Ambiguous routes
remain visible but unselectable. Conventional known families are selectable;
unknown families are explicitly unclassified. Misc props are not equipment rows.
This catalog does not decode WeaponBasicTable, claim a table weapon ID, infer
signature ownership, or validate in-game equipment-type restrictions. Display
labels are prefab asset names. There is no guessed signature recommendation.

## Assembly contract

The selected resource fills an equipment slot; the slot still owns its authored
idle/fight mount and uniform scale. Resource state, mount state, default visibility
and selection provenance are separate columns. Cross-weapon edges retain their
target slot and mount key. Parents are prepared before children, with cycle and
missing-dependency checks. Hidden dependencies are retained in this manual preview;
this is not automatic gameplay visibility.

Character targets resolve through stamped rig identity. Cross-weapon mount keys
resolve through authored component entries and exact transform paths, never a
Handle/leaf-name guess. Multiple component entries for one key are ambiguous.
An unrepresented target can carry source local transforms from its nearest
represented ancestor bone; an unresolved/generated target fails explicitly.
Independent/world mounts are not silently converted to a character hand bone.

Column vectors, rightmost operation first:

`weapon world = parent frame world * mount offset * slot scale * inverse(host root turn) * imported root`

The ordinary import retains prefab transforms and the weapon's separate skeleton.
Before reading imported root world matrices, the assembler evaluates Blender's
dependency graph. The materialiser writes local transforms; reading an unevaluated
world matrix can introduce an extra root turn, especially for rigid weapons.
This assembly does not impose a weapon anchor, game skill timing or a per-character
rotation correction. Old version-2 direct attachments remain reusable; replacing
an untagged legacy tree or a tree with user-added objects requires manual review.
Replacing a parent with dependent sockets is rejected instead of deleting them.

Existing attachments are not silently rotated by the fix. If an old attachment
was created with the stale-matrix defect, preserve the file, then remove that
socket and its weapon objects and import the selected weapon again. Reusing an
existing socket intentionally preserves its current transforms and animation.

## Verification

### Native material effects (Blender)

Weapon → 材质光效 → choose the weapon root (or use 使用选中武器) →
识别已有武器材质 → 准备所选独立控制 → expand its native parameters.
Changing the target invalidates old rows. A target unlinked from the current
scene is rejected, with an explicit selection button rather than a silent
fallback to a different object or the whole character.
The target covers its mesh descendants, not unrelated siblings. For an import
with multiple separate roots, explicitly group those roots under a common empty
and choose that empty to include the whole assembly.

Discovery uses the owning generated stack's live interface and bound source
images, not weapon/material name patterns. Native Emission and Parallax are
separate controls even on one material. Prepare makes one object-local material
copy per source while retaining its original switches, color/HDR, intensity,
UV/sampler and shader math. Parameters use the shared material panel's guarded
readback and original stack writer. No extra emission branch is added.
Repeated prepare retains edits; 恢复武器原材质 restores the prior slot links.

Existing effect-shader materials are listed separately, including ones without
MainTex; depth-only/refraction shaders are not asserted to be emissive. They are
opt-in for a local copy and retain their full native interface. Unclassified
materials (including hidden geometry using a default material) are 待确认,
never automatically brightened or assigned a guessed effect material. Visibility
icons are direct Blender object controls, separate from material restoration.
Scanning/preparing never changes object visibility.

手动叠加 remains an explicit artist-editing tool, not a reconstruction of game
effects. Native materials no longer also receive automatic grayscale overlays.
To add an overlay after preparing a native-only copy, restore it first, add the
manual region and prepare again. Existing saved overlays remain supported.
No potential-level logic, animation events or runtime material replacement is
implemented. Native graph control tests are not game-render/visual acceptance.

- `tools/verify_weapon_channels_blender.py`: real generated-graph discovery,
  source-preserving shared-mesh copies, native RNA writes, HDR, idempotence,
  invalid scene targets, unknown hidden materials and saved-record reopening.

- `tools/test_weapon_catalog.py`: standalone display projection, ambiguous load
  payloads, map/install invalidation and shared-command/host-neutral contracts.
- `tools/verify_weapon_catalog_blender.py`: isolated real-index scan, category and
  search filtering, shared Load command, actual model/material/packed-texture
  imports, filled-list RNA rendering and preservation of a character target.
  Additional synthetic guards cover ambiguous rows and reader failures.
- `tools/verify_weapon_catalog_reopen_blender.py`: a separate no-addon/no-autoexec
  reopen verifies source pixels, mesh/material links and packed images. Neither
  this nor the source-import test establishes final visual/game-render parity.
- `tools/test_weapon_equipment_contract.py`: host-free synthetic contract checks.
- `tools/test_import_completion.py`: import completion, exception isolation and
  last-character selection without game/backend dependencies.
- `tools/verify_weapon_ui_blender.py`: real Blender RNA, stepped import notifications,
  compact row/removal contract, selection operator and register/unregister lifecycle.
- `tools/verify_weapon_equipment_blender.py`: synthetic Blender 5.3 background
  checks for the real operators, frame matrices, replacement/rollback, cross-weapon
  animation, identity rename and save/reopen. No game reader or assets are opened.
- Private `tests/Weapons`: synthetic catalog/choice tests and compilation against
  the accepted reader API.

Synthetic numerical tests are not real-character grip visual acceptance or proof
of in-game compatibility. Test real imports manually before adopting the candidate.
