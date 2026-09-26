"""Automatic Endfield action-chain expansion for the Ruri animation importer."""

from __future__ import annotations

import json
from importlib import resources

import bpy

from ...endfield_animation.blender_nla import build_nla
from ... import prefab_importer
from ...RuriRipperPyBridge.unity import bridge_asset_db, discovery
from ...RuriRipperPyBridge.session import cabmap_state
from ...RuriRipperPyBridge.unity import class_registry


ATTACK_ACTION = "A_actor_typhoea_battle_attack_01"


def _plan_path():
    return resources.files("RuriRipperImporter.endfield_animation").joinpath(
        "data/typhoea_attack01_plan.json")


def _clip_name(db, guid):
    try:
        clip = db.clip_curves(guid)
        return clip.name if clip else None
    except (KeyError, ValueError):
        return None


def _required_names(plan):
    return list(dict.fromkeys(segment["clip"] for segment in plan["segments"] if segment.get("clip")))


def _build_from_db(db, names, arm_obj, maps, path_to_meshobjects, options):
    wanted = {name.lower() for name in names}
    guids = [ref["guid"] for ref in discovery.discover_clip_refs(db)
             if ref["name"].lower() in wanted]
    if not guids:
        return 0, []
    built, warnings, _actions = prefab_importer.build_selected_animations(
        db, arm_obj, maps, path_to_meshobjects or {}, guids, options,
        activate=False)
    return built, warnings


def _missing_cabs(names):
    wanted = {name.lower() for name in names}
    result = []
    for row in cabmap_state.ROWS:
        if "AnimationClip" not in row.get("type_names", ""):
            continue
        path = row.container_path().replace("\\", "/")
        leaf = path.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
        if leaf in wanted and row["cab"] not in result:
            result.append(row["cab"])
    return result


def maybe_build(context, imported_guids, db, arm_obj, maps, options, path_to_meshobjects=None):
    """Expand Attack01 into its evidenced return chain and build managed NLA tracks."""
    imported_names = {_clip_name(db, guid) for guid in imported_guids}
    if ATTACK_ACTION not in imported_names:
        return False, []

    plan_file = _plan_path()
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    required = _required_names(plan)
    missing = [name for name in required if bpy.data.actions.get(name) is None]
    warnings = []
    if missing:
        _built, current_warnings = _build_from_db(
            db, missing, arm_obj, maps, path_to_meshobjects, options)
        warnings.extend(current_warnings)
        missing = [name for name in required if bpy.data.actions.get(name) is None]

    if missing:
        cabs = _missing_cabs(missing)
        if cabs:
            clip_id = class_registry.id_for_name("AnimationClip")
            assets, _roots, _seed_roots, clips_by_cab, _scene_roots = \
                cabmap_state.BRIDGE.import_cabs(cabs, export_class_ids=[clip_id])
            extra_db = bridge_asset_db.BridgeAssetDatabase(
                assets,
                clip_curve_blobs=cabmap_state.BRIDGE.clip_curves_by_guid,
                mesh_blobs=cabmap_state.BRIDGE.mesh_blobs_by_guid,
                asset_paths=cabmap_state.BRIDGE.asset_paths_by_guid,
                texture_srgb=cabmap_state.BRIDGE.texture_srgb_by_guid)
            _built, extra_warnings = _build_from_db(
                extra_db, missing, arm_obj, maps, path_to_meshobjects, options)
            warnings.extend(extra_warnings)

    missing = [name for name in required if bpy.data.actions.get(name) is None]
    if missing:
        warnings.append("Action chain incomplete; missing: " + ", ".join(missing))
        return False, warnings

    build_nla(str(plan_file), arm_obj.name, path_to_bone=maps.get("path_to_bone") or {})
    context.scene.frame_start = 0
    context.scene.frame_end = max(
        int(segment["end"] * float(plan["fps"])) for segment in plan["segments"])
    context.scene.render.fps = int(plan["fps"])
    return True, warnings
