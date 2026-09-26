"""Extract state/transition changes from the runtime Animator snapshot CSV."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def extract_runtime_timeline(
    path: str | Path, *, entry_qpc: int, component: str, layer: int,
    duration_seconds: float,
) -> dict[str, Any]:
    end_qpc = entry_qpc + int(duration_seconds * 10_000_000)
    changes: list[dict[str, Any]] = []
    previous = None
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            qpc = int(row["qpc"])
            if qpc < entry_qpc or qpc > end_qpc:
                continue
            if row["self"].lower() != component.lower() or int(row["layer"]) != layer:
                continue
            signature = (row["current_short_hash"], row["next_short_hash"], row["in_transition"])
            if signature == previous:
                continue
            previous = signature
            changes.append({
                "seconds": (qpc - entry_qpc) / 10_000_000.0,
                "qpc": qpc,
                "frame": int(row["frame"]),
                "currentHash": int(row["current_short_hash"]),
                "currentNormalized": float(row["current_normalized"]),
                "currentLength": float(row["current_length"]),
                "nextHash": int(row["next_short_hash"]),
                "nextNormalized": float(row["next_normalized"]),
                "nextLength": float(row["next_length"]),
                "inTransition": row["in_transition"] == "1",
                "runtimeDuration": float(row["transition_f4"]),
                "runtimeProgress": float(row["transition_f5"]),
            })
    return {
        "schema": "endfield.animation.runtime-timeline.v1",
        "source": str(Path(path).resolve()),
        "entryQpc": entry_qpc,
        "component": component,
        "layer": layer,
        "durationSeconds": duration_seconds,
        "changes": changes,
    }


def extract_runtime_layers(
    path: str | Path, *, entry_qpc: int, component: str,
    duration_seconds: float, graph: dict[str, Any] | None = None,
    identity_path: str | Path | None = None,
) -> dict[str, Any]:
    """Extract state and weight changes for every Animator API layer."""
    end_qpc = entry_qpc + int(duration_seconds * 10_000_000)
    state_names: dict[tuple[int, int], dict[str, Any]] = {}
    machine_by_layer: dict[int, int] = {}
    if graph:
        machine_by_layer = {
            int(key): int(value["machine"]) for key, value in graph.get("layers", {}).items()
        }
        for state in graph.get("states", {}).values():
            state_names[(int(state["machine"]), int(state["nameId"]))] = state
    layer_names: dict[int, str] = {}
    controller_name = None
    if identity_path:
        with Path(identity_path).open("r", encoding="utf-8-sig", newline="") as handle:
            for identity in csv.DictReader(handle):
                if identity["self"].lower() != component.lower() or identity.get("query_ok") != "1":
                    continue
                layer_names.setdefault(int(identity["layer"]), identity["layer_name"])
                controller_name = controller_name or identity.get("controller_name")

    rows: dict[int, list[dict[str, Any]]] = {}
    transition_samples: dict[int, list[dict[str, Any]]] = {}
    previous: dict[int, tuple[str, ...]] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            qpc = int(row["qpc"])
            if qpc < entry_qpc or qpc > end_qpc or row["self"].lower() != component.lower():
                continue
            layer = int(row["layer"])
            if row["in_transition"] == "1":
                transition_samples.setdefault(layer, []).append({
                    "seconds": (qpc - entry_qpc) / 10_000_000.0,
                    "frame": int(row["frame"]),
                    "weight": float(row["weight"]),
                    "currentHash": int(row["current_short_hash"]),
                    "currentNormalized": float(row["current_normalized"]),
                    "currentLength": float(row["current_length"]),
                    "nextHash": int(row["next_short_hash"]),
                    "nextNormalized": float(row["next_normalized"]),
                    "nextLength": float(row["next_length"]),
                    "duration": float(row["transition_f4"]),
                    "progress": float(row["transition_f5"]),
                })
            signature = (
                row["current_short_hash"], row["next_short_hash"], row["in_transition"], row["weight"]
            )
            if signature == previous.get(layer):
                continue
            previous[layer] = signature
            machine = machine_by_layer.get(layer, layer)
            current_hash, next_hash = int(row["current_short_hash"]), int(row["next_short_hash"])
            current = state_names.get((machine, current_hash))
            next_state = state_names.get((machine, next_hash))
            rows.setdefault(layer, []).append({
                "seconds": (qpc - entry_qpc) / 10_000_000.0,
                "qpc": qpc,
                "frame": int(row["frame"]),
                "weight": float(row["weight"]),
                "currentHash": current_hash,
                "currentState": None if current is None else current["state"],
                "currentNormalized": float(row["current_normalized"]),
                "currentLength": float(row["current_length"]),
                "nextHash": next_hash,
                "nextState": None if next_state is None else next_state["state"],
                "nextNormalized": float(row["next_normalized"]),
                "nextLength": float(row["next_length"]),
                "inTransition": row["in_transition"] == "1",
                "runtimeDuration": float(row["transition_f4"]),
                "runtimeProgress": float(row["transition_f5"]),
            })
    layers = []
    for layer in sorted(rows):
        definition = (graph or {}).get("layers", {}).get(str(layer), {})
        layers.append({
            "runtimeLayer": layer,
            "name": layer_names.get(layer),
            "machine": machine_by_layer.get(layer, layer),
            "serialized": definition,
            "changes": rows[layer],
            "transitionSamples": transition_samples.get(layer, []),
        })
    return {
        "schema": "endfield.animation.runtime-layers.v1",
        "source": str(Path(path).resolve()),
        "entryQpc": entry_qpc,
        "component": component,
        "controllerName": controller_name,
        "durationSeconds": duration_seconds,
        "layers": layers,
    }
