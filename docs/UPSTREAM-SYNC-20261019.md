# Blender 5.3 main sync - 2026-10-19

Merged upstream `c3b7fb4715254065f10a9c6cb849426fed01d71b` without textual
conflicts. enumerate_table no longer stores one process-wide last table, and
search_table receives the active tab's own rows explicitly. The backend now
assigns different dataset handles to different resource-map instances.

Backend pin: `084e9d89eb9c0e71970ece526c5cc4894e6845b3`, including upstream
`878683d` and private source `feb603a` (KWZE.GameHook). The public in-tree
Ruri.Hook remains; the upstream-private Ruri.GameHook stays removed. Updated
the fork-routing comment to the current private submodule path.

## Verification and delivery

- Package-CI host-free scripts: 68 test cases. Three added search regressions
  cover later enumeration not replacing the first table, forwarding active rows
  with sort/filter state, and no cross-map fallback for an empty tab.
- Both compiled kernel profiles and the new generic adapter/map/PNG/late-hook
  regressions pass; public compiled privacy audit passes. See the backend's
  Source/Build/UPSTREAM-SYNC-20261019.md for the exact scope.
- One real weapon imports 3 meshes/8 textures on Blender 5.3 Alpha
  `73cfbda0a06d`; native emission/parallax control isolation/restoration passes.
- Synthetic native controls/save and a fresh offline reopen without the reader
  pass. Existing generated shader files were not edited by this sync.

Logs, temporary scenes and compiled outputs: `C:/temp/Ruri-upstream-20261019`.
The matching rebuilt runtime is a separate private candidate package, not a
replacement of the accepted private snapshot. Its manifest records the new
kernel/Hook bytes and current source identities. No installation, preferences,
user-scene or legacy-5.2 changes, and no new manual visual acceptance.
