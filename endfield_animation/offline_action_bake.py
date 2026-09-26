"""Default-offline adapter from R7-B action-ready poses to a new Action.

The core is Blender-free and emits a deterministic action-data artifact.  The
optional ``materialize_blender_action`` helper is deliberately explicit: it
creates a new action and never edits NLA strips or an existing action.  Samples
are copied at their observed engine frames; there is no interpolation or
extrapolation.
"""

from __future__ import annotations

import json
import math
import os
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA = "endfield.animation.runtime-contract.r7c.action-ready-pose.v1"
ACTION_SCHEMA = "endfield.animation.runtime-contract.r7c.baked-action.v1"


@dataclass(frozen=True)
class BakeConfig:
    enabled: bool = False
    action_name: str = "Endfield_R7C_OfflineAction"
    skip_frame_on_mismatch: bool = True


def _diagnostic(level: str, code: str, message: str, **context: Any) -> dict[str, Any]:
    return {"level": level, "code": code, "message": message, "context": context}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _finite_vector(value: Any, length: int, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f"{label} must have {length} components")
    result = [float(item) for item in value]
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{label} contains non-finite value")
    return result


def _load_pose_frames(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if path.suffix.lower() == ".csv":
        return _load_pose_csv(path)
    value = _read_json(path)
    if isinstance(value, dict):
        if value.get("schema") not in {None, SCHEMA}:
            raise ValueError(f"unsupported action-ready schema: {value.get('schema')!r}")
        frames = value.get("frames")
    else:
        frames = value
    if not isinstance(frames, list):
        raise ValueError("action-ready dataset requires a frames list")
    diagnostics: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    for frame in frames:
        if not isinstance(frame, dict):
            diagnostics.append(_diagnostic("WARNING", "FRAME_NOT_OBJECT", "frame skipped"))
            continue
        try:
            engine_frame = int(frame["engine_frame"])
            nodes = frame["nodes"]
        except (KeyError, TypeError, ValueError):
            diagnostics.append(_diagnostic("WARNING", "FRAME_FIELDS_MISSING", "frame skipped"))
            continue
        if not isinstance(nodes, list):
            diagnostics.append(_diagnostic("WARNING", "FRAME_NODES_NOT_LIST", "frame skipped", engine_frame=engine_frame))
            continue
        normalized.append({
            "engine_frame": engine_frame,
            "time_seconds": None if frame.get("time_seconds") is None else float(frame["time_seconds"]),
            "normalized_time": None if frame.get("normalized_time") is None else float(frame["normalized_time"]),
            "nodes": nodes,
        })
    return normalized, diagnostics


def _load_pose_csv(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read the R7-B flat `494 x 555` Blender pose-basis table."""
    required = {
        "engine_frame", "node", "path", "builder_bone",
        "pose_position_blender_x", "pose_position_blender_y", "pose_position_blender_z",
        "pose_rotation_blender_w", "pose_rotation_blender_x", "pose_rotation_blender_y", "pose_rotation_blender_z",
        "pose_scale_blender_x", "pose_scale_blender_y", "pose_scale_blender_z",
    }
    grouped: dict[int, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise ValueError(f"R7-B CSV missing required columns: {missing}")
        for row in reader:
            try:
                frame = int(row["engine_frame"])
                node = {
                    "node_id": int(row["node"]),
                    "path": row["path"],
                    "bone_name_in_dataset": row["builder_bone"],
                    "pose_position": [_finite_vector([
                        row["pose_position_blender_x"], row["pose_position_blender_y"], row["pose_position_blender_z"]
                    ], 3, "pose_position")[i] for i in range(3)],
                    "pose_rotation": [_finite_vector([
                        row["pose_rotation_blender_w"], row["pose_rotation_blender_x"], row["pose_rotation_blender_y"], row["pose_rotation_blender_z"]
                    ], 4, "pose_rotation")[i] for i in range(4)],
                    "pose_scale": [_finite_vector([
                        row["pose_scale_blender_x"], row["pose_scale_blender_y"], row["pose_scale_blender_z"]
                    ], 3, "pose_scale")[i] for i in range(3)],
                }
            except (KeyError, TypeError, ValueError) as exc:
                diagnostics.append(_diagnostic("WARNING", "CSV_ROW_INVALID", "row skipped", error=str(exc)))
                continue
            group = grouped.setdefault(frame, {"engine_frame": frame, "nodes": []})
            group["nodes"].append(node)
    return [grouped[key] for key in sorted(grouped)], diagnostics


def _load_armature(path: Path) -> tuple[dict[tuple[int, str], str], list[dict[str, Any]]]:
    if path.suffix.lower() == ".jsonl":
        records = []
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                if line.strip():
                    records.append(json.loads(line))
        bones = [{"node_id": item.get("runtime_node"), "path": item.get("runtime_path"),
                  "bone_name": item.get("builder_bone"), "status": item.get("status")} for item in records]
    else:
        value = _read_json(path)
        bones = value.get("bones") if isinstance(value, dict) else value
    if not isinstance(bones, list):
        raise ValueError("armature manifest requires a bones list")
    mapping: dict[tuple[int, str], str] = {}
    diagnostics: list[dict[str, Any]] = []
    for bone in bones:
        try:
            key = (int(bone["node_id"]), str(bone["path"]))
            name = str(bone["bone_name"])
        except (KeyError, TypeError, ValueError):
            diagnostics.append(_diagnostic("WARNING", "BONE_FIELDS_MISSING", "bone skipped"))
            continue
        if bone.get("status") not in {None, "EXACT_PATH"}:
            diagnostics.append(_diagnostic("WARNING", "BONE_MAPPING_NOT_EXACT", "non-exact mapping omitted", node_id=key[0], path=key[1], status=bone.get("status")))
            continue
        if not name:
            diagnostics.append(_diagnostic("WARNING", "BONE_NAME_EMPTY", "bone skipped", node_id=key[0], path=key[1]))
            continue
        if key in mapping and mapping[key] != name:
            diagnostics.append(_diagnostic("WARNING", "BONE_KEY_DUPLICATE", "duplicate node/path skipped", node_id=key[0], path=key[1]))
            continue
        mapping[key] = name
    return mapping, diagnostics


def bake_action_data(dataset_path: str | Path, armature_path: str | Path, *, config: BakeConfig | None = None) -> dict[str, Any]:
    """Build a new-action data artifact, gated by an explicit feature flag."""
    config = config or BakeConfig()
    diagnostics: list[dict[str, Any]] = []
    dataset = Path(dataset_path).resolve()
    armature = Path(armature_path).resolve()
    base = {
        "schema": ACTION_SCHEMA,
        "feature_flag": "ENDFIELD_R7_ACTION_BAKE_ENABLED",
        "feature_enabled": bool(config.enabled),
        "dataset": str(dataset),
        "armature": str(armature),
        "action_name": config.action_name,
        "engine_frame_key": "engine_frame",
        "interpolation": "none",
        "extrapolation": "none",
        "nla_touched": False,
        "existing_action_touched": False,
        "channels": [],
        "accepted_frames": [],
        "diagnostics": diagnostics,
    }
    if not config.enabled:
        diagnostics.append(_diagnostic("INFO", "FEATURE_DISABLED", "offline Action bake is disabled by default"))
        if not dataset.is_file():
            diagnostics.append(_diagnostic("WARNING", "DATASET_MISSING", "action-ready dataset is missing", path=str(dataset)))
        if not armature.is_file():
            diagnostics.append(_diagnostic("WARNING", "ARMATURE_MISSING", "armature manifest is missing", path=str(armature)))
        base["status"] = "DISABLED_FEATURE_FLAG"
        base["module_enabled"] = False
        return base
    if os.environ.get("ENDFIELD_R7_ACTION_BAKE_ENABLED", "0") != "1":
        diagnostics.append(_diagnostic("WARNING", "FEATURE_ENV_DISABLED", "explicit environment gate is not enabled"))
        if not dataset.is_file():
            diagnostics.append(_diagnostic("WARNING", "DATASET_MISSING", "action-ready dataset is missing", path=str(dataset)))
        if not armature.is_file():
            diagnostics.append(_diagnostic("WARNING", "ARMATURE_MISSING", "armature manifest is missing", path=str(armature)))
        base["status"] = "DISABLED_FEATURE_FLAG"
        base["module_enabled"] = False
        return base
    if not dataset.is_file():
        diagnostics.append(_diagnostic("WARNING", "DATASET_MISSING", "action-ready dataset is missing", path=str(dataset)))
        base["status"] = "DISABLED_INPUT_MISSING"
        base["module_enabled"] = False
        return base
    if not armature.is_file():
        diagnostics.append(_diagnostic("WARNING", "ARMATURE_MISSING", "armature manifest is missing", path=str(armature)))
        base["status"] = "DISABLED_INPUT_MISSING"
        base["module_enabled"] = False
        return base
    try:
        frames, frame_diagnostics = _load_pose_frames(dataset)
        mapping, bone_diagnostics = _load_armature(armature)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        diagnostics.append(_diagnostic("WARNING", "INPUT_CONTRACT_INVALID", "input contract rejected", error=str(exc)))
        base["status"] = "DISABLED_INPUT_INVALID"
        base["module_enabled"] = False
        return base
    diagnostics.extend(frame_diagnostics)
    diagnostics.extend(bone_diagnostics)
    if not mapping:
        diagnostics.append(_diagnostic("WARNING", "ARMATURE_EMPTY", "no usable armature bones"))
        base["status"] = "DISABLED_ARMATURE_EMPTY"
        base["module_enabled"] = False
        return base
    channels: dict[str, dict[str, Any]] = {}
    accepted_frames: list[int] = []
    seen_frames: set[int] = set()
    for frame in sorted(frames, key=lambda item: item["engine_frame"]):
        number = frame["engine_frame"]
        if number in seen_frames:
            diagnostics.append(_diagnostic("WARNING", "FRAME_DUPLICATE", "duplicate frame skipped", engine_frame=number))
            continue
        seen_frames.add(number)
        rows: dict[tuple[int, str], dict[str, Any]] = {}
        frame_bad = False
        for node in frame["nodes"]:
            try:
                key = (int(node["node_id"]), str(node["path"]))
            except (KeyError, TypeError, ValueError):
                frame_bad = True
                diagnostics.append(_diagnostic("WARNING", "NODE_FIELDS_MISSING", "frame skipped", engine_frame=number))
                continue
            if key in rows:
                frame_bad = True
                diagnostics.append(_diagnostic("WARNING", "NODE_DUPLICATE", "frame skipped", engine_frame=number, node_id=key[0], path=key[1]))
                continue
            if key not in mapping:
                diagnostics.append(_diagnostic("WARNING", "NODE_PATH_MISMATCH", "unmatched node omitted", engine_frame=number, node_id=key[0], path=key[1]))
                continue
            dataset_bone = node.get("bone_name_in_dataset")
            if dataset_bone and dataset_bone != mapping[key]:
                frame_bad = True
                diagnostics.append(_diagnostic("WARNING", "BONE_NAME_MISMATCH", "frame skipped", engine_frame=number, node_id=key[0], path=key[1], dataset_bone=dataset_bone, armature_bone=mapping[key]))
                continue
            try:
                if "pose_position" in node:
                    rows[key] = {
                        "position": _finite_vector(node["pose_position"], 3, "pose_position"),
                        "rotation": _finite_vector(node["pose_rotation"], 4, "pose_rotation"),
                        "scale": _finite_vector(node["pose_scale"], 3, "pose_scale"),
                    }
                else:
                    local_rotation = _finite_vector(node["local_rotation"], 4, "local_rotation")
                    rows[key] = {
                        "position": _finite_vector(node["local_position"], 3, "local_position"),
                        # R7-C action data stores Blender's WXYZ order. R5-style
                        # local source rows are XYZW and are converted here.
                        "rotation": [local_rotation[3], local_rotation[0], local_rotation[1], local_rotation[2]],
                        "scale": _finite_vector(node["local_scale"], 3, "local_scale"),
                    }
            except (KeyError, TypeError, ValueError) as exc:
                frame_bad = True
                diagnostics.append(_diagnostic("WARNING", "NODE_TRS_INVALID", "frame skipped", engine_frame=number, error=str(exc)))
        missing = set(mapping) - set(rows)
        if missing and config.skip_frame_on_mismatch:
            diagnostics.append(_diagnostic("WARNING", "FRAME_NODE_SET_MISMATCH", "frame skipped because required node/path set is incomplete", engine_frame=number, missing_count=len(missing)))
            continue
        if frame_bad and config.skip_frame_on_mismatch:
            continue
        if not rows:
            diagnostics.append(_diagnostic("WARNING", "FRAME_NO_MATCHED_NODES", "frame skipped", engine_frame=number))
            continue
        accepted_frames.append(number)
        for key, trs in rows.items():
            bone_name = mapping[key]
            channel = channels.setdefault(bone_name, {"bone_name": bone_name, "node_id": key[0], "path": key[1], "location": [], "rotation_quaternion": [], "scale": []})
            channel["location"].append([number, *trs["position"]])
            channel["rotation_quaternion"].append([number, *trs["rotation"]])
            channel["scale"].append([number, *trs["scale"]])
    base["channels"] = [channels[name] for name in sorted(channels)]
    base["accepted_frames"] = accepted_frames
    base["accepted_frame_count"] = len(accepted_frames)
    base["channel_count"] = len(channels)
    base["module_enabled"] = bool(accepted_frames and channels)
    base["status"] = "READY_NEW_ACTION_DATA" if base["module_enabled"] and not diagnostics else ("READY_NEW_ACTION_DATA_WITH_WARNINGS" if base["module_enabled"] else "DISABLED_NO_VALID_ROWS")
    return base


def materialize_blender_action(bpy: Any, armature_obj: Any, baked: dict[str, Any], *, action_name: str | None = None) -> Any:
    """Materialize only the supplied baked data into a newly-created Blender Action."""
    if not baked.get("feature_enabled") or not baked.get("module_enabled"):
        raise ValueError("baked action data is not enabled and validated")
    action = bpy.data.actions.new(action_name or baked["action_name"])
    action.use_fake_user = True
    action["endfield_r7c_source_schema"] = baked.get("schema", ACTION_SCHEMA)
    action["endfield_r7c_engine_frame_key"] = "engine_frame"
    action["endfield_r7c_interpolation"] = "CONSTANT"
    action["endfield_r7c_extrapolation"] = "CONSTANT"
    for channel in baked["channels"]:
        bone_name = channel["bone_name"]
        pose_bone = armature_obj.pose.bones.get(bone_name)
        if pose_bone is None:
            raise ValueError(f"validated channel bone is missing from target armature: {bone_name}")
        pose_bone.rotation_mode = "QUATERNION"
        for data_path, key_name, size in ((f'pose.bones["{bone_name}"].location', "location", 3),
                                          (f'pose.bones["{bone_name}"].rotation_quaternion', "rotation_quaternion", 4),
                                          (f'pose.bones["{bone_name}"].scale', "scale", 3)):
            for index in range(size):
                curve = action.fcurves.new(data_path=data_path, index=index, action_group=bone_name)
                keys = channel[key_name]
                curve.keyframe_points.add(len(keys))
                for point, row in zip(curve.keyframe_points, keys):
                    point.co = (float(row[0]), float(row[index + 1]))
                    point.interpolation = "CONSTANT"
                curve.extrapolation = "CONSTANT"
                curve.update()
    return action
