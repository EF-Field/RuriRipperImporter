# Blender 5.3 main sync - 2026-10-18

Merged upstream `46d972b1b241a3ef4b65eb26b1dc5feaeefbc34c` (three commits
after `a957321`): runtime-only level-medium datablock births, sun half-angle
degrees converted to Blender diameter radians, and the regenerated Endfield
effect bundle including FogSimple. The frontend merge had no textual conflicts.
Generated Endfield shader files exactly match upstream Git bytes.

Backend pin: `ea209d8f77e0899283b9997df3a8e93e4356170d`, containing upstream
`bfb28ed` while keeping the retired upstream-private gitlink deleted. Own private
adapter/runtime remains `f53b8dd`; no backend runtime code changed in this round.
The earlier local synchronization/runtime commits are included in this push.

## Fresh checks

- All package-CI host-free test scripts: 65 test cases; includes three added
  light-unit/non-angle/runtime-birth regression cases in test_upstream_sync.py.
- Private-module boundary: 4 tests. Private package/provenance: 20 tests;
  shipped-reader weapon checks 114, coverage/channel checks 63 and neutral
  source-projection checks 54; runtime source sync and 138-file package verified.
- Blender 5.3 Alpha `73cfbda0a06d`, isolated factory startup: four games,
  12 stacks, all 228 named node groups loaded and matched manifest stamps;
  first/absent Sun behavior passes. FogSimple builds a 413-node material.
- Real Blender sun data receives radians(2 * half-angle-degrees), independent
  of exposure. Medium application creates 9 runtime-only datablocks in the
  synthetic scene; saved-library inspection excludes marked runtime data but
  retains content lights. Withdraw removes the medium/copies and restores the
  original point-light volume share. The save emits expected cross-drive asset
  path warnings, not a test failure.

Logs and synthetic scenes: `C:/temp/Ruri-upstream-20261018`. The FogSimple
construction test has no opaque scene-depth context, so its OpaqueDistanceBehind
capability reports the declared absent value; this is not a render comparison.
No fresh real-game scene import, external retarget solver or native disassembly
was exercised. Installed files, preferences, user scenes and legacy 5.2 were not
modified. No new manual visual acceptance is claimed.
