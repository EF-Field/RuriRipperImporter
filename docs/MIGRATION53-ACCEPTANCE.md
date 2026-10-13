# Blender 5.3 migration candidate

## Adopted mainline, 2026-10-13

The user manually checked the installable candidate and reported that models and
animations were satisfactory, then selected Blender 5.3 as the primary line.
`main` is now the 5.3 / Statement development and release line; 5.2 remains a
separate legacy compatibility-maintenance line. Exact user-tested asset names and
coverage were not specified. Material/effect/physics/all-character acceptance
remains separate from this model/animation approval.

Install/import manually. Automatic review launching was discontinued after its
startup sidebar update crashed this Alpha in a windowless UI context. The
background scene helper is diagnostic-only and is not part of the add-on ZIP.

Target host is Blender 5.3.0 Alpha `73cfbda0a06d`, explicitly selected by the user.
Other Alpha/Beta/Release builds are separate compatibility targets.

The frontend uses the main Kernel/Host architecture and Statement ABI. The
private hook includes Dense16 restoration and a separate format-2 Statement
type-tree pack; the legacy pack and installed Blender 5.2 environment stay
unchanged. Do not combine legacy and Statement runtime directories.

## Reproducible technical gates

- Public backend `Source/Build/build-kernel.ps1 -PrivateHook` with the compatible
  dependency snapshot and provisioned NuGet feed.
- Private `tests/Dense16`: production codec tests, including twelve rejection cases.
- Public `Source/Build/UpgradeTypeTree` with `--self-test`: exact dump-chain match,
  retained renamed trees byte-identical, six invalid-input rejection cases.
- `tools/test_migration53.py`: fresh real-game Statement imports, 556-bone model,
  raw Attack01/reference comparisons, and 22 weapon clips with external independent
  Dense16 sample fixtures. All reference data is comparison-only.
- `tools/test_migration53_scene.py`: fresh-process save/reopen, rig/action/slot
  identity, shader-group reconstruction, explicit review-fixture vertex rebuild,
  and an actual EEVEE render.
- `tools/test_legacy_blender.py`: registered compatibility UI, native/legacy switch,
  idempotence, save/reopen, real new-material dispatch and unregister lifecycle.

External game fixtures and output scenes are not public package inputs. Isolated
workspace/profile paths are explicit; Codex MSIX AppData is not host installation
proof. Background tests are not independent user-GUI visual acceptance.

## Handwritten legacy adapter

The adapter and pinned vendor snapshot live under `Game/Endfield/Blender/`.
`shader/Blender/` remains wholly generator-owned. Original vendor runtime and
character library hashes are unchanged. The game host-projection lifecycle
registers the compatibility panel explicitly; the adapter reads the generated
package entrypoint rather than a removed `ruri_endfield.py` facade.

## Review boundary

The review fixture places the weapon separately, under neutral review lighting.
It is not an extracted game lighting setup, weapon attachment or skill-event
timeline. Character and weapon are raw clips, not runtime layer blending.

Upstream native vertex trees are runtime-only and deliberately not automatically
rebuilt on file load. The background diagnostic explicitly prepares its fixture's
vertex stages. It must not be used as a silent whole-scene rebuild for
user production files. Ordinary save/reopen alone does not certify outline/fur
continuity; normal-workflow treatment of this upstream behavior remains a
separate migration issue.

Current beta compositor effects-stack compatibility is not certified by the
selected Alpha. Full animation-library sweeps, other characters, runtime
blending/physics/VFX and final game-render parity remain separate gates.
