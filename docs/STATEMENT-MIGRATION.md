# Statement migration validation

Based on upstream `66ea967a797daa8969657aa6d7cd1501cd53845f` without importing the
legacy integration repository's history. Private implementation and game fixtures
remain solely in the private submodule. No upstream pull request was submitted.

The public backend fork `KawakazeNotFound/Ruri.RipperHook` is based on upstream
`9a9d67f3963d3f52caca10edd476547a282eba21` and ShaderDecompiler
`6a67d178c5c4530a54d3f086bcb1817a98b85298`. Retarget/Statement adapters are now
committed there, rather than existing only as local patches. It carries Avatar scale/rest data, restores authored
binding paths, and routes custom clip decoding through the private hook.

The frontend pins the public backend at `Ruri.RipperHook`; that repository pins
the private `Source/Endfield-GameHook`. No private hook is directly attached to
the frontend anymore. Actual versions are recorded by the two Git links.
Game-specific profile recognition is registered by the private adapter; the
public solver defaults to stock semantics without that adapter.

Validated on Blender 5.3.0 Alpha `73cfbda0a06d`:

- Full addon registration with the new generated shader modules.
- Character roster payload through `loading.load`, upright model and 556 bones.
- Raw game Attack01 through `loading.perform`: 301 frames, 60 fps, 386 compared
  paths, none missing; maximum local matrix component error 0.0001215041 against
  the previously accepted offline reference. This number is not a distance unit.
- Reference data is read only by tests, never by the importer.

Boundaries: material appearance was not compared (plain-material render), other
clips and game runtime blending remain unverified, and this test does not certify
every UI operator. The old Steam Blender installation was left untouched.

The new backend uses RCM7 cabmaps. An old RCM6 map requires rebuilding. The bounded
regression used an isolated converted map with empty new facts; it did not replace
the installed map and does not certify new fact-dependent game features.
