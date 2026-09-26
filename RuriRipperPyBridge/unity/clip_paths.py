"""Re-anchoring an AnimationClip's curve bindings onto a real skeleton.

Two independent problems, one join key:

* **Hashed paths.** When the rig wasn't in the export scope, AssetRipper cannot
  restore a curve's binding to a transform-path string and writes the raw Unity
  binding hash instead: ``path_0x<CRC32>_<random>``. The hash is CRC32 of the
  UTF-8 path -- verified empirically against the real game
  (``crc32(b"Root") == 0xB6C65665``, matching its ``path_0xB6C65665_WvpMuNH``
  placeholder exactly, across every probe).
* **Different nesting depth.** Unity hashes the path RELATIVE to the Animator's
  own node, while an imported armature records paths from the prefab ROOT, and
  model variants nest the rig at different depths (confirmed against the real
  game: a uimodel's clip paths start ``Root/Bip001/...`` while a postmodel
  armature stamps ``chr_0013_aglina_postmodel/.../Root/Bip001/...``). Whole-path
  equality -- and whole-path CRC -- therefore never matches across variants.

Both are solved by hashing every SUFFIX of every armature path, so the join is
prefix-agnostic while remaining exact path-structure identity: the same segments
Unity itself hashed, just re-anchored. This is not display-name guessing.

``clip`` throughout is a ``clip_curves.ClipCurves`` (the zero-parse blob
payload or the regex disk parser's output) -- the one canonical clip form.
"""

from __future__ import annotations

import os
import re
import zlib

from .hierarchy import ANIMATOR_ROOT_PATH

# AssetRipper's placeholder for a binding it could not restore to a string.
_HASHED_PATH_RE = re.compile(r"^path_0x([0-9A-Fa-f]{1,8})_")


def build_suffix_crc_table(path_to_bone):
    """{CRC32 -> full stamped path} over EVERY level-suffix of every bone path.

    Enumerating each path's suffixes ("a/b/c", "b/c", "c") makes the join
    prefix-agnostic: the clip's Animator-relative path IS one of the suffixes
    whenever the bone genuinely exists under the selected skeleton. On a
    suffix-CRC collision the LONGEST suffix wins -- a leaf-only match can be
    ambiguous, a long chain can't."""
    table = {}
    for path in path_to_bone:
        # The animator root is bound by its own empty path and never by a hash, so it has
        # no suffix to join on -- and letting it in would put crc32("") = 0 in the table,
        # a key any "path_0x0_" placeholder would then wrongly resolve to.
        if path == ANIMATOR_ROOT_PATH:
            continue
        parts = path.split("/")
        for i in range(len(parts)):
            suffix = "/".join(parts[i:])
            crc = zlib.crc32(suffix.encode("utf-8")) & 0xFFFFFFFF
            prev = table.get(crc)
            if prev is None or len(suffix) > prev[0]:
                table[crc] = (len(suffix), path)
    return {crc: path for crc, (_length, path) in table.items()}


def entry_crc(path):
    """The binding CRC32 a curve entry's path stands for: a hashed placeholder
    carries it literally, a restored string path hashes to it -- one join key
    for both forms."""
    hash_match = _HASHED_PATH_RE.match(path)
    if hash_match:
        return int(hash_match.group(1), 16)
    return zlib.crc32(path.encode("utf-8")) & 0xFFFFFFFF


def avatar_path_aliases(avatar, path_to_bone):
    """Join renamed prefab joints using an Avatar ancestor AND descendant.

    Never guess from a similar leaf name. An unmatched direct child can be
    identified only when its already-matched parent and exact descendant
    suffixes select one prefab child. Ambiguous branches remain unmatched.
    """
    tos = avatar.get("m_TOS", ())
    source = set(tos.values()) if isinstance(tos, dict) else {entry.get("second", "") for entry in tos}
    source = {p for p in source if isinstance(p, str) and p}
    target = set(path_to_bone)
    table = build_suffix_crc_table(path_to_bone)
    resolved = {p: p if p in target else table.get(entry_crc(p)) for p in source if p}
    for path in sorted(resolved, key=lambda p: (p.count("/"), p)):
        if resolved[path] is not None:
            continue
        parent, _, leaf = path.rpartition("/")
        actual_parent = resolved.get(parent)
        if actual_parent is None:
            continue
        direct = actual_parent + "/" + leaf
        if direct in target:
            resolved[path] = direct
            continue
        suffixes = [p[len(path):] for p in source if p.startswith(path + "/")]
        children = [p for p in target if p.rpartition("/")[0] == actual_parent]
        votes = []
        for suffix in suffixes:
            matches = {child for child in children if child + suffix in target}
            if matches:
                votes.append(matches)
        # Require agreement of all available evidence, not first-match wins.
        candidates = set.intersection(*votes) if votes else set()
        if len(candidates) == 1:
            candidate = next(iter(candidates))
            if candidate not in resolved.values():
                resolved[path] = candidate
    return {p: actual for p, actual in resolved.items() if actual is not None and p != actual}


def repair_hashed_clip_paths(clip, path_to_bone, path_aliases=None):
    """Rewrite a clip's curve paths (in place) to the target skeleton's own full
    paths, joining through the suffix-CRC table.

    Hashed placeholders resolve by their literal CRC32; already-restored string
    paths that don't literally appear in ``path_to_bone`` (rig nested at a
    different depth in this variant) resolve by hashing. Paths that already
    match verbatim are left untouched. Returns (repaired, unmatched)."""
    table = build_suffix_crc_table(path_to_bone)
    for alias, canonical in (path_aliases or {}).items():
        if canonical in path_to_bone:
            table.setdefault(entry_crc(alias), canonical)
    trace_path = os.environ.get("RURI_CLIP_PATH_TRACE")
    trace_rows = []
    repaired = 0
    unmatched = 0
    kinds = ("rotation", "position", "scale", "euler", "float")
    for kind, channels in zip(kinds, clip.all_channel_lists()):
        for channel in channels:
            path = channel.path or ""
            if not path or path in path_to_bone:
                continue
            crc = entry_crc(path)
            real = table.get(crc)
            if real is None:
                unmatched += 1
                if trace_path:
                    trace_rows.append((kind, path, crc, "", "unmatched"))
                continue
            if trace_path:
                trace_rows.append((kind, path, crc, real, "repaired"))
            channel.path = real
            repaired += 1
    if trace_path:
        needs_header = not os.path.exists(trace_path) or os.path.getsize(trace_path) == 0
        with open(trace_path, "a", encoding="utf-8", newline="") as stream:
            if needs_header:
                stream.write("clip\tkind\toriginal_path\tcrc32\tresolved_path\tstatus\n")
            for kind, path, crc, real, status in trace_rows:
                stream.write(f"{clip.name}\t{kind}\t{path}\t0x{crc:08X}\t{real}\t{status}\n")
    return repaired, unmatched


def clip_path_match_ratio(clip, path_to_bone):
    """Fraction of a clip's transform-curve paths that resolve to a bone of the
    target skeleton -- the compatibility check for importing a clip onto a
    skeleton the user picked. Same suffix-CRC join as the repair, so a clip
    anchored anywhere inside the hierarchy counts as matching. Returns
    (ratio, total); (0.0, 0) for a clip with no transform curves at all (e.g. a
    pure blendshape clip)."""
    table = build_suffix_crc_table(path_to_bone)
    total = 0
    matched = 0
    for channels in clip.transform_channel_lists():
        for channel in channels:
            path = channel.path or ""
            if not path:
                continue
            total += 1
            if path in path_to_bone or entry_crc(path) in table:
                matched += 1
    return (matched / total if total else 0.0), total
