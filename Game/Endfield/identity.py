"""Who a rig IS, in this game's own words: the npc template it was assembled from, the face-morph
avatar the game assigns it, the SkeletalMorph tag of the character it is.

What the face system asks about a rig standing in the document. Loading is not here: what a
member loads as is the hook's statement source, reached through the kernel's one load.

Nothing here imports a host.
"""

from __future__ import annotations

import re

from . import datasets

# charId -> {"model", "tag", "asset"}, read once per session from the game's own character data
# assets -- the only place the game states a character's tag.
_CHARACTER_MODELS = {}

# name -> the npc prefab info the game files under it, or None for a name that is not an npc
# template. Read on demand and remembered: it is an install constant.
_NPC_INFO = {}
_BLENDER_SUFFIX = re.compile(r"\.\d{3}$")
_PLAYABLE_ID = re.compile(r"^chr_\d+_(.+)$")


def morph_scope(value):
    """A pasted playable id/rig name -> its expression-library token.

    Preserve NPC template ids and custom scopes: NPC declarations use their
    complete template identity, not the playable-character naming convention.
    Blender's instance suffix is not part of either entity's identity.
    """
    key = _BLENDER_SUFFIX.sub("", str(value or "").strip().lower())
    matched = _PLAYABLE_ID.fullmatch(key)
    if matched is None:
        return key
    token = matched.group(1)
    for suffix in ("_postmodel", "_uimodel"):
        if token.endswith(suffix):
            token = token[:-len(suffix)]
            break
    return token


def _character_models():
    """Every character's declared model and tag, read as one batch: the data assets share a
    handful of bundles, so paying per character would re-resolve one closure thirty times."""
    if not _CHARACTER_MODELS:
        cabs = datasets.character_model_cabs()
        if cabs:
            _CHARACTER_MODELS.update(datasets.character_models(cabs))
    return _CHARACTER_MODELS


def npc_info(name):
    """What the game's own prefab info says about an npc template, or None when ``name`` is not
    one (a playable character's rig, a rig from another tool).

    A rig this add-on assembled is NAMED after its template, so an object's own name is a valid
    key -- minus Blender's uniquifying ``.001`` suffix, which is the object's, not the entity's."""
    key = _BLENDER_SUFFIX.sub("", (name or "").strip())
    if not key:
        return None
    if key not in _NPC_INFO:
        try:
            info = datasets.npc_parts(key)
        except Exception:
            info = None
        _NPC_INFO[key] = info if info and info.get("parts") else None
    return _NPC_INFO[key]


def npc_template(name):
    """The npc template ``name`` IS, or "" when it names none -- what a panel keys an entity's
    own per-line assets by, exactly."""
    return "" if npc_info(name) is None else _BLENDER_SUFFIX.sub("", name.strip())


def declared_face_morph(template_id):
    """The face-morph avatar the game itself assigns an npc template (``facialMorphAvatarName``),
    or "" for a name that is not an npc template. For an npc it names something entirely unlike
    the npc itself (``npc_spl_adaxier_01`` wears ``ardashir``)."""
    info = npc_info(template_id)
    return "" if info is None else info.get("facial_morph", "")


def character_tag(token):
    """The SkeletalMorph tag the game itself assigns a character, matched from a rig's name
    token; 0 when the token names no character in the roster's own data."""
    needle = (token or "").strip().lower()
    if not needle:
        return 0
    for character_id, declared in _character_models().items():
        if needle in character_id.lower() and declared.get("tag"):
            try:
                return int(declared["tag"])
            except ValueError:
                return 0
    return 0


def forget():
    """Drop what one session cached; an install's answers are not the next one's."""
    _CHARACTER_MODELS.clear()
    _NPC_INFO.clear()
