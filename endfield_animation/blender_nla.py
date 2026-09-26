"""Blender adapter for ``endfield.animation.playback-plan.v1``.

Kept outside the core planner so graph extraction and tests run without bpy.
"""

from __future__ import annotations

import json
import math
import re
import zlib
from pathlib import Path


_BONE_PATH = re.compile(r'^pose\.bones\["([^"\\]*(?:\\.[^"\\]*)*)"\]')


def _source_time_at_strip_end(action_start: float, start_frame: float, end_frame: float) -> float:
    """Map one Blender scene frame to one source-action frame.

    ``start_frame`` and ``end_frame`` have already been converted from seconds
    by the caller.  Multiplying their delta by FPS again makes a 60 FPS action
    advance 60 source frames per scene frame, which turns short looped actions
    into a two-pose flicker near the end of the playback plan.
    """
    return action_start + (end_frame - start_frame)


def _relative_quaternion(reference, value):
    """Return ``inverse(reference) * value`` for Blender-order WXYZ tuples."""
    rw, rx, ry, rz = (float(component) for component in reference)
    qw, qx, qy, qz = (float(component) for component in value)
    length = math.sqrt(rw * rw + rx * rx + ry * ry + rz * rz)
    if length <= 1e-12:
        rw, rx, ry, rz = 1.0, 0.0, 0.0, 0.0
    else:
        rw, rx, ry, rz = rw / length, rx / length, ry / length, rz / length
    length = math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz)
    if length <= 1e-12:
        qw, qx, qy, qz = 1.0, 0.0, 0.0, 0.0
    else:
        qw, qx, qy, qz = qw / length, qx / length, qy / length, qz / length
    result = (
        rw * qw + rx * qx + ry * qy + rz * qz,
        rw * qx - rx * qw - ry * qz + rz * qy,
        rw * qy + rx * qz - ry * qw - rz * qx,
        rw * qz - rx * qy + ry * qx - rz * qw,
    )
    length = math.sqrt(sum(component * component for component in result))
    return tuple(component / length for component in result)


def _fcurve_collections(action):
    """Yield mutable F-Curve collections for legacy and layered Actions.

    Newly-created Blender 5.x actions can temporarily lack the compatibility
    ``Action.fcurves`` view until their slot is assigned to an animated ID.
    Their curves already exist in keyframe-strip channelbags, so operate on
    that native representation when the compatibility property is absent.
    """
    try:
        yield action.fcurves
        return
    except AttributeError:
        pass
    seen = set()
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            for channelbag in getattr(strip, "channelbags", ()):
                marker = channelbag.as_pointer()
                if marker not in seen:
                    seen.add(marker)
                yield channelbag.fcurves


def _make_reference_relative(action, reference_frame, layer):
    """Turn an exported absolute Action into a Blender COMBINE delta Action.

    Unity additive Animator layers consume a pose relative to the clip's
    additive reference pose.  The importer currently exports the solved
    Humanoid result as absolute pose-bone channels; feeding those values
    directly to NLA COMBINE applies the pose a second time and folds limbs over
    the body.  Rebase each channel against the selected reference frame first.
    """
    action.name = f"EF_DELTA_L{layer}_{action.name}"
    for curves in _fcurve_collections(action):
        by_path = {}
        for curve in curves:
            by_path.setdefault(curve.data_path, {})[curve.array_index] = curve
        for data_path, components in by_path.items():
            if data_path.endswith("rotation_quaternion") and all(i in components for i in range(4)):
                channels = [components[i] for i in range(4)]
                reference = tuple(curve.evaluate(reference_frame) for curve in channels)
                frames = sorted({float(point.co[0]) for curve in channels
                                 for point in curve.keyframe_points})
                samples = []
                previous = None
                for frame in frames:
                    value = tuple(curve.evaluate(frame) for curve in channels)
                    delta = _relative_quaternion(reference, value)
                    if previous is not None and sum(a * b for a, b in zip(previous, delta)) < 0.0:
                        delta = tuple(-component for component in delta)
                    samples.append((frame, delta))
                    previous = delta
                for index, curve in enumerate(channels):
                    values = {round(frame, 6): delta[index] for frame, delta in samples}
                    for point in curve.keyframe_points:
                        point.co[1] = values[round(float(point.co[0]), 6)]
                        point.interpolation = "LINEAR"
            elif data_path.endswith("location") or data_path.endswith("rotation_euler"):
                for curve in components.values():
                    reference = curve.evaluate(reference_frame)
                    for point in curve.keyframe_points:
                        point.co[1] -= reference
                        point.interpolation = "LINEAR"
            elif data_path.endswith("scale"):
                for curve in components.values():
                    reference = curve.evaluate(reference_frame)
                    for point in curve.keyframe_points:
                        point.co[1] = point.co[1] / reference if abs(reference) > 1e-12 else 1.0
                        point.interpolation = "LINEAR"
    return action


def _masked_action(action, path_hashes, path_to_bone, layer):
    if not path_hashes or not path_to_bone:
        return action
    wanted = {int(value) for value in path_hashes}
    bone_names = set()
    for path, bone in path_to_bone.items():
        parts = str(path).split("/")
        hashes = {zlib.crc32("/".join(parts[i:]).encode("utf-8")) & 0xFFFFFFFF
                  for i in range(len(parts))}
        if hashes & wanted:
            bone_names.add(getattr(bone, "name", str(bone)))
    if not bone_names:
        raise ValueError(f"layer {layer} skeleton mask matched no imported bone")
    masked = action.copy()
    masked.name = f"EF_MASKED_L{layer}_{action.name}"
    for curves in _fcurve_collections(masked):
        for curve in list(curves):
            match = _BONE_PATH.match(curve.data_path)
            if match and match.group(1) not in bone_names:
                curves.remove(curve)
    return masked


def build_nla(plan_path: str, armature_name: str, *, clear_managed=True, path_to_bone=None):
    import bpy

    path = Path(plan_path)
    plan = json.loads(path.read_text(encoding="utf-8-sig"))
    if plan.get("schema") != "endfield.animation.playback-plan.v1":
        raise ValueError("unsupported playback-plan schema")
    armature = bpy.data.objects[armature_name]
    animation = armature.animation_data_create()
    if clear_managed:
        for track in list(animation.nla_tracks):
            if track.name.startswith("EF L"):
                animation.nla_tracks.remove(track)
    fps = float(plan["fps"])
    built = []
    for index, segment in enumerate(plan["segments"]):
        clip = segment.get("clip")
        action = bpy.data.actions.get(clip) if clip else None
        if action is None:
            raise KeyError(f"playback-plan action is not loaded: {clip!r}")
        action = _masked_action(action, segment.get("maskPathHashes", []), path_to_bone, segment["layer"])
        if segment.get("blendType") == "COMBINE":
            action = _make_reference_relative(
                action, float(segment.get("additiveReferenceFrame", action.frame_range[0])),
                segment["layer"])
        start = float(segment["start"]) * fps
        end = float(segment["end"]) * fps
        track = animation.nla_tracks.new()
        track.name = f"EF L{segment['layer']} {segment['id']}"
        strip = track.strips.new(segment["id"], int(start), action)
        strip.action_frame_start = float(action.frame_range[0])
        strip.action_frame_end = float(action.frame_range[1])
        strip.frame_start = start
        strip.frame_end = max(start + 1.0, end)
        strip.blend_type = segment.get("blendType", "REPLACE")
        strip.extrapolation = "NOTHING"
        strip.use_animated_influence = True
        # Drive source time explicitly. Mutating action_frame_start after
        # frame_end makes Blender resize the strip, while repeat with a nonzero
        # clipStart loops only the truncated tail. Animated time preserves the
        # measured strip bounds and wraps the complete action range.
        strip.use_animated_time = True
        strip.use_animated_time_cyclic = bool(segment.get("loop"))
        action_start = float(action.frame_range[0]) + float(segment.get("clipStart", 0.0)) * fps
        strip.strip_time = action_start
        strip.keyframe_insert(data_path="strip_time", frame=start)
        freeze = segment.get("clipFreezeAt")
        if freeze is not None:
            frozen_time = action_start + (float(freeze) - float(segment["start"])) * fps
            strip.strip_time = frozen_time
            strip.keyframe_insert(data_path="strip_time", frame=float(freeze) * fps)
            strip.keyframe_insert(data_path="strip_time", frame=end)
        else:
            strip.strip_time = _source_time_at_strip_end(action_start, start, end)
            strip.keyframe_insert(data_path="strip_time", frame=end)
        for second, value in segment.get("influence", []):
            strip.influence = float(value)
            strip.keyframe_insert(data_path="influence", frame=float(second) * fps)
        for curve in strip.fcurves:
            for point in curve.keyframe_points:
                point.interpolation = "LINEAR"
        built.append(strip.name)
    armature["endfield_playback_plan"] = str(path.resolve())
    armature["endfield_curve_status"] = plan.get("curveStatus", "")
    # The initially selected clip is normally still the armature's active
    # Action. Leaving it there evaluates it on top of the managed NLA stack and
    # effectively applies Attack01 twice. The actions remain in bpy.data and in
    # their NLA strips after unlinking the active slot.
    animation.action = None
    return built
