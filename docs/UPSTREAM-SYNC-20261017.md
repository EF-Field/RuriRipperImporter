# Blender 5.3 / Statement upstream check - 2026-10-17

- Importer upstream `ShiyumeMeguri/RuriRipperImporter` remains at
  `fb77f982c97c6e3d72a998782c76c18cae39fabf`, already included in local main.
- Backend is pinned to `e15fa9f258e1396f26bf372e57284dbc9f461e47` after merging
  upstream `72fafab79be2d82d4eac5896df3c63e26e3aa936` and removing its private
  `Source/Ruri.GameHook` dependency. The public `Ruri.Hook` framework remains.
- Own private adapter stays separate, pinned by the backend to
  `1a0d74fa2d78165b0c2458f3aade9a634eb12c87`.
- Frontend workflow tests: 39 pass. Public/private kernel builds and VFS/weapon
  backend tests pass; details and scope are in the backend's
  `Source/Build/UPSTREAM-SYNC-20261017.md`.
- [AllShader_1.6.3.7z](https://github.com/ShiyumeMeguri/FractalMiner/blob/main/Assets/Project/EndField/AllShader_1.6.3.7z)
  exists as a separate FractalMiner reference archive. Its presence does not
  establish that the importer's Blender shader libraries use those bytes.

Local checkpoint only: no push, installation changes, accepted-runtime snapshot
replacement or Blender visual acceptance. Legacy Blender 5.2 is unchanged.
