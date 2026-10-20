# Blender 5.3 upstream follow-up - 2026-10-17

Merged importer upstream `c4ef041` (five commits after `fb77f98`). This brings
external Blender `RuriManifest.json` package/stack manifests, updated generated
runtime and node libraries, Substance `RuriPipeline.json` companions, and the
vertex MainLight capability using the first Sun in scene order.

Backend pin: `8af0fd81abafbff0f32be001a676daa2f8737303`, including upstream
`f96b19f` and ShaderDecompiler `fab0925`. The latter backend changes only docs;
runtime C#/project inputs and the owned private adapter remain unchanged.

## History and conflicts

The fork remote had rewritten main history (`4a578ed` became `0a35efc`, with
only the remapped backend gitlink differing in the tree). Saved the original
local reference as `archive/pre-sync-20261017-round2`, aligned to the remote,
and replayed the two local weapon-effect commits. Range-diff confirmed their
patches unchanged: `0f0f8bf` -> `4197d92`, `d14f95a` -> `9ffe57b`.
The old backup is local only, not a push target.

CLAUDE.md was the sole textual conflict. Kept upstream's numbered layout and
restored our main/5.3, private Hook, generated-byte and isolated-test policies.
All files under the four generated shader trees match upstream index bytes;
no generated implementation was hand-edited.

## Checks

- Host-free frontend tests: 43/43, including 4 new manifest contract tests now
  included in package CI; backend private boundary tests 4/4.
- Factory-startup Blender 5.3 Alpha `73cfbda0a06d`: four games, 12 shader stacks,
  all 224 named node groups loaded and matched their manifest stamp.
- Vertex-light checks: no Sun returns no answer; the first scene Sun is used
  by a relative Object Info node; missing color is explicitly unprovided;
  attenuation constants remain one; removing the first Sun selects the next.
- Native weapon channel checks: discovery, one-click toggles, RNA UI, isolated
  material writes/repeat/restore, effects without MainTex, explicit unknown-mesh
  preview toggle/restore and target behavior pass. Fresh-process save/reopen
  passes with the regenerated libraries.
- The synthetic save reports expected C:/D: cross-drive relative-path warnings;
  the fresh reopen passed. No game assets or fixtures are packaged publicly.

Logs and the temporary synthetic scene: `C:/temp/Ruri-upstream-20261017-round2`.
These checks establish package/runtime contracts, not manual visual parity or
the provenance of an AllShader reference version. No installed add-on,
preferences, accepted runtime snapshot or legacy 5.2 checkout was modified.
