"""Deterministic BlendTree evaluation and runtime snapshot inference."""

from __future__ import annotations

from typing import Any


def simple1d_weights(thresholds: list[float], value: float) -> list[float]:
    if not thresholds:
        return []
    if value <= thresholds[0]:
        return [1.0] + [0.0] * (len(thresholds) - 1)
    if value >= thresholds[-1]:
        return [0.0] * (len(thresholds) - 1) + [1.0]
    weights = [0.0] * len(thresholds)
    for index, (left, right) in enumerate(zip(thresholds, thresholds[1:])):
        if left <= value <= right:
            factor = 0.0 if right == left else (value - left) / (right - left)
            weights[index] = 1.0 - factor
            weights[index + 1] = factor
            break
    return weights


def infer_simple1d_snapshot(
    graph: dict[str, Any], *, machine: int, state: int,
    effective_length: float, normalized_time: float, tolerance: float = 1.0 / 60.0,
) -> dict[str, Any]:
    record = graph["states"][f"{machine}:{state}"]
    root = next(node for node in record["nodes"] if node["node"] == 0)
    child_by_index = {node["node"]: node for node in record["nodes"]}
    children = [child_by_index[index] for index in root.get("childIndices", [])]
    thresholds = [float(value) for value in root.get("thresholds", [])]
    matches = []
    for index, child in enumerate(children):
        clip = graph["clips"].get(str(child.get("clipSlot")), {})
        duration = clip.get("duration")
        if duration is not None and abs(float(duration) - effective_length) <= tolerance:
            matches.append((index, child, clip))
    if len(matches) != 1:
        return {
            "schema": "endfield.animation.blend-tree-snapshot.v1",
            "machine": machine, "state": state, "resolved": False,
            "reason": f"effective length matched {len(matches)} children",
        }
    index, child, clip = matches[0]
    value = thresholds[index]
    weights = simple1d_weights(thresholds, value)
    return {
        "schema": "endfield.animation.blend-tree-snapshot.v1",
        "machine": machine,
        "state": state,
        "resolved": True,
        "parameterHash": root.get("parameterHash"),
        "parameterValue": value,
        "thresholds": thresholds,
        "children": [
            {"node": item["node"], "clip": item.get("clipName"), "weight": weights[i]}
            for i, item in enumerate(children)
        ],
        "sourceClip": clip.get("name"),
        "sourceDuration": float(clip["duration"]),
        "sourceNormalized": normalized_time,
        "sourceSeconds": (normalized_time % 1.0) * float(clip["duration"]),
        "evidence": "runtime effective state length uniquely matched serialized BlendTree child duration",
    }
