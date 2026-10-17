# Blender 5.3 upstream follow-up, round 3 - 2026-10-17

Merged importer upstream `a9573219851fcf0227eb4026815b7e7650050696`
(four commits after `c4ef041`). This retains upstream map-picture/selection
interfaces, stand-in rig retarget routing, and the regenerated Endfield shader
bundle with its updated wetting-table capacity. All generated shader files
match the upstream Git object bytes; none were manually modified.

## Merge boundaries

- `Game/Endfield/datasets.py`: retain our JSON/numeric imports together with
  upstream's picture/staging import; both dataset groups remain present.
- `Host/Blender/materialise.py`: retain our indexed/loose-mesh entry points and
  upstream's stand-in `build_rig` function, each defined once.
- `Kernel/app/loading.py`: retain upstream own/foreign-clip routing and the
  fork's optional performance companions, including opt-out and failure notes.
- Continue using the public backend fork and our private adapter. Do not
  restore the upstream-private module or move game fixtures into this repository.

## Verification

- 84 host-free checks, including six new merge-seam tests now run in CI.
- Python AST validation of the runtime trees and private-module boundary gates.
- Four game shader bundles: 12 stacks, 224 node-group stamps; first-Sun and
  absent-Sun behavior. Native material toggles, isolated writes and offline
  fresh-process rebuild/reopen pass against the updated generated libraries.
- Real character/morph/effect regression: 116 checks, 231 bound controls,
  no unresolved target, and all 17 authored references to two effect resources.
- Six real weapon/prop material imports; synthetic equipment 41 checks;
  effect fixture 11 cases including rollback/clean reopen; Weapon UI routing,
  state persistence and register/unregister lifecycle.

Matching public/private kernels compile with zero errors; the tested runtime
is pinned by the final dependency checkpoint. Logs and temporary scenes stay
outside the source checkout at `C:/temp/Ruri-upstream-20261017-round3`.

Upstream's newly exposed map UI does not by itself establish that our private
adapter supplies every map dataset. The actual external AnimationRetarget
solver/plugin, native disassembly and manual visual acceptance are separate
checks. Installed add-ons/preferences/scenes and the legacy runtime remain
unchanged. No push or deployment is included in this synchronization.
