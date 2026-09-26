"""Join serialized layer masks with runtime observations into a composition manifest."""

from __future__ import annotations

from typing import Any
from copy import deepcopy


def _state_by_hash(graph: dict[str, Any], machine: int, state_hash: int):
    return next((state for state in graph.get("states", {}).values()
                 if int(state["machine"]) == machine and int(state["nameId"]) == state_hash), None)


def build_layer_composition(
    graph: dict[str, Any], runtime_layers: dict[str, Any]
) -> dict[str, Any]:
    """Describe every observed controller layer without inventing bone mappings."""
    result = []
    for observed in runtime_layers.get("layers", []):
        layer = int(observed["runtimeLayer"])
        definition = graph.get("layers", {}).get(str(layer), {})
        machine = int(definition.get("machine", observed.get("machine", layer)))
        states = []
        seen = set()
        for change in observed.get("changes", []):
            for key in ("currentHash", "nextHash"):
                state_hash = int(change.get(key, 0))
                if not state_hash or state_hash in seen:
                    continue
                seen.add(state_hash)
                state = _state_by_hash(graph, machine, state_hash)
                nodes = [] if state is None else [node for node in state.get("nodes", []) if node.get("clipName")]
                states.append({
                    "hash": state_hash,
                    "state": None if state is None else state["state"],
                    "clips": list(dict.fromkeys(node["clipName"] for node in nodes)),
                    "blendTree": bool(state and state.get("nodes") and state.get("clipSlot") is None),
                })
        weights = [float(change["weight"]) for change in observed.get("changes", [])]
        body_mask = definition.get("bodyMask")
        skeleton_items = definition.get("skeletonMask", {}).get("items", [])
        active_hashes = [int(item["PathHash"]) for item in skeleton_items
                         if float(item.get("Weight", 0.0)) > 0.0]
        simple_state_clips = [state["clips"][0] for state in states if len(state["clips"]) == 1]
        all_simple = (bool(states) and bool(simple_state_clips)
                      and all(len(state["clips"]) <= 1 and not state["blendTree"] for state in states))
        result.append({
            "runtimeLayer": layer,
            "name": observed.get("name"),
            "machine": machine,
            "blendMode": "additive" if int(definition.get("blendMode", 0)) == 1 else "override",
            "defaultWeight": definition.get("defaultWeight"),
            "observedWeightRange": [min(weights), max(weights)] if weights else None,
            "bodyMask": body_mask,
            "activeSkeletonPathHashes": active_hashes,
            "states": states,
            "compileStatus": (
                "ready-for-unmasked-full-body"
                if body_mask == {"Word0": 4294967295, "Word1": 4294967295, "Word2": 33554431}
                and not skeleton_items and all_simple else
                "ready-for-skeleton-hash-mask" if active_hashes and all_simple else
                "blend-tree-weights-needed" if not all_simple else "bone-mask-binding-needed"
            ),
        })
    return {
        "schema": "endfield.animation.layer-composition.v1",
        "controllerName": runtime_layers.get("controllerName"),
        "layers": result,
    }


def augment_plan_with_runtime_layers(
    plan: dict[str, Any], composition: dict[str, Any], runtime_layers: dict[str, Any]
) -> dict[str, Any]:
    """Append runtime-varying, full-body, single-clip layers to a playback plan."""
    output = deepcopy(plan)
    end = max(float(segment["end"]) for segment in output.get("segments", []))
    observed_by_layer = {
        int(layer["runtimeLayer"]): layer for layer in runtime_layers.get("layers", [])
    }
    added = []
    for layer in composition.get("layers", []):
        index = int(layer["runtimeLayer"])
        if index == int(output.get("layerIdentity", {}).get("runtimeAnimatorLayer", 0)):
            continue
        if not str(layer.get("compileStatus", "")).startswith("ready-for-"):
            continue
        weight_range = layer.get("observedWeightRange")
        if not weight_range or float(weight_range[0]) == float(weight_range[1]):
            continue
        states = layer.get("states", [])
        clips = list(dict.fromkeys(clip for state in states for clip in state.get("clips", [])))
        if len(clips) != 1:
            continue
        changes = observed_by_layer.get(index, {}).get("changes", [])
        first = next((i for i, item in enumerate(changes) if float(item["weight"]) != float(changes[0]["weight"])), None)
        if first is None:
            continue
        start_change = changes[first]
        start = float(start_change["seconds"])
        clip_phase = (float(start_change["currentNormalized"]) % 1.0) * float(start_change["currentLength"])
        influence = [[float(item["seconds"]), float(item["weight"])]
                     for item in changes[first:]]
        segment = {
            "id": f"runtime-layer-{index}",
            "layer": index,
            "layerName": layer.get("name"),
            "clip": clips[0],
            "start": start,
            "end": end,
            "clipStart": clip_phase,
            "loop": True,
            # Blender's COMBINE mode applies quaternion/scale channels relative
            # to their property defaults. Plain ADD sums quaternion components
            # and produced explosive limb transforms on the real Typhoea rig.
            "blendType": "COMBINE" if layer.get("blendMode") == "additive" else "REPLACE",
            "additiveReferenceFrame": 0.0 if layer.get("blendMode") == "additive" else None,
            "maskPathHashes": layer.get("activeSkeletonPathHashes", []),
            "influence": influence,
            "evidence": "runtime-layer-weight-readback-plus-serialized-full-body-mask",
        }
        output["segments"].append(segment)
        added.append(index)

    # Constant-weight override layers still animate through state crossfades. Compile
    # a single-clip state from the sampled Animator transition progress.
    for layer in composition.get("layers", []):
        index = int(layer["runtimeLayer"])
        if index in added or index == int(output.get("layerIdentity", {}).get("runtimeAnimatorLayer", 0)):
            continue
        if not str(layer.get("compileStatus", "")).startswith("ready-for-"):
            continue
        clip_by_hash = {int(state["hash"]): state["clips"][0]
                        for state in layer.get("states", []) if len(state.get("clips", [])) == 1}
        observed = observed_by_layer.get(index, {})
        samples = observed.get("transitionSamples", [])
        for state_hash, clip in clip_by_hash.items():
            incoming = [sample for sample in samples if int(sample["nextHash"]) == state_hash]
            outgoing = [sample for sample in samples if int(sample["currentHash"]) == state_hash]
            if not incoming:
                continue
            first = incoming[0]
            start = max(0.0, float(first["seconds"]) - float(first["progress"]) * float(first["duration"]))
            influence = [[start, 0.0]]
            influence.extend([float(sample["seconds"]), float(sample["progress"]) * float(sample["weight"])]
                             for sample in incoming)
            incoming_end = min(end, float(incoming[-1]["seconds"]) +
                               (1.0 - float(incoming[-1]["progress"])) *
                               float(incoming[-1]["duration"]))
            influence.append([incoming_end, float(incoming[-1]["weight"])])
            if outgoing:
                outgoing_start = max(incoming_end, float(outgoing[0]["seconds"]) -
                                     float(outgoing[0]["progress"]) *
                                     float(outgoing[0]["duration"]))
                influence.append([outgoing_start, float(outgoing[0]["weight"])])
                influence.extend([float(sample["seconds"]), (1.0 - float(sample["progress"])) * float(sample["weight"])]
                                 for sample in outgoing)
                last = outgoing[-1]
                segment_end = min(end, float(last["seconds"]) +
                                  (1.0 - float(last["progress"])) * float(last["duration"]))
                influence.append([segment_end, 0.0])
            else:
                segment_end = end
            clip_phase = max(0.0, float(first["nextNormalized"]) * float(first["nextLength"])
                             - float(first["progress"]) * float(first["duration"]))
            output["segments"].append({
                "id": f"runtime-layer-{index}-state-{state_hash}",
                "layer": index,
                "layerName": layer.get("name"),
                "clip": clip,
                "start": start,
                "end": segment_end,
                "clipStart": clip_phase,
                "loop": True,
                "blendType": "COMBINE" if layer.get("blendMode") == "additive" else "REPLACE",
                "additiveReferenceFrame": 0.0 if layer.get("blendMode") == "additive" else None,
                "maskPathHashes": layer.get("activeSkeletonPathHashes", []),
                "influence": influence,
                "evidence": "runtime-state-transition-progress-plus-serialized-skeleton-mask",
            })
            added.append(index)
            break
    output["compiledRuntimeLayers"] = added
    return output
