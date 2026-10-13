# Working rules

- `main` is the Blender 5.3 / Statement development and release line. Start new
  work from main; do not treat `codex/blender-5.2` as the default development line.
- Preserve the 5.2 compatibility branch and its legacy ABI/runtime. Backport
  necessary fixes separately; keep the two runtime directories distinct.
- User accepted model and animation imports on 2026-10-13. This is not approval
  of all materials, effects, physics, characters, or complete game-render parity.
- The current tested host is Blender 5.3 Alpha `73cfbda0a06d`. Other 5.3 builds
  require their own compatibility checks.
- Deliver the installable add-on and matching backend. The user installs and
  imports manually; avoid automatic scene launch/UI preparation.
- Diagnostic scene tools are background-only. A successful background test is
  not GUI/visual proof.
- Keep game parsing in backend game hooks. Blender code owns UI/scene assembly.
- Generated shader directories belong to the generator. Keep handwritten host
  adapters outside them and preserve SHA-locked vendor payload bytes.
- Public packages exclude private sources, runtime DLLs, type trees and game
  fixtures. Private runtime packages stay in the private repository.
- Preserve installed add-ons, preferences, dirty scenes and unrelated worktrees.
- Codex MSIX AppData paths are not host filesystem proof. Distinguish logical,
  resolved physical and host-expected paths before validation or modification.
- Checkpoint locally. Push only when the user explicitly requests it.
