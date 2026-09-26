"""Resolve a deterministic controller route and compile it to a Blender-ready plan."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _condition_matches(condition: dict[str, Any], parameters: dict[str, Any]) -> bool | None:
    event = str(condition.get("EventID"))
    if event not in parameters:
        return None
    value = parameters[event]
    mode = condition.get("ConditionModeE")
    threshold = condition.get("EventThreshold", 0)
    if mode == "If":
        return bool(value)
    if mode == "IfNot":
        return not bool(value)
    if mode == "Greater":
        return float(value) > float(threshold)
    if mode == "Less":
        return float(value) < float(threshold)
    if mode == "Equals":
        return float(value) == float(threshold)
    if mode == "NotEqual":
        return float(value) != float(threshold)
    return None


def _transition_matches(transition: dict[str, Any], parameters: dict[str, Any]) -> bool | None:
    results = [_condition_matches(condition, parameters) for condition in transition["conditions"]]
    if not results:
        return True
    if any(result is False for result in results):
        return False
    if any(result is None for result in results):
        return None
    return True


def _transitions(graph: dict[str, Any], machine: int, source: int) -> list[dict[str, Any]]:
    return sorted(
        (item for item in graph["transitions"]
         if item["machine"] == machine and item["sourceState"] == source),
        key=lambda item: item["edge"],
    )


def _resolve_destination(
    graph: dict[str, Any], machine: int, destination: int, parameters: dict[str, Any]
) -> tuple[int | None, list[dict[str, Any]]]:
    trace: list[dict[str, Any]] = []
    seen: set[int] = set()
    while destination >= 30000:
        selector = destination - 30000
        if selector in seen:
            return None, trace
        seen.add(selector)
        pseudo_state = -(selector + 2)
        choices = _transitions(graph, machine, pseudo_state)
        selected = next((item for item in choices if _transition_matches(item, parameters) is True), None)
        if selected is None:
            return None, trace
        trace.append({"selector": selector, "edge": selected["edge"]})
        destination = int(selected["Destination"])
    return destination, trace


def _state_clip(graph: dict[str, Any], machine: int, state: int) -> tuple[str | None, float | None, bool]:
    record = graph["states"].get(f"{machine}:{state}")
    if not record:
        return None, None, False
    slot = record.get("clipSlot")
    clip = graph["clips"].get(str(slot)) if slot is not None else None
    return (clip or {}).get("name"), record.get("speed"), bool(record.get("loop"))


def resolve_route(
    graph: dict[str, Any], *, machine: int, start_state: int,
    parameter_phases: list[dict[str, Any]], max_steps: int = 32,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Walk one explicitly parameterised scenario through the controller graph.

    Each phase supplies parameter values and may supply ``holdSeconds``. A phase is
    consumed when it selects one transition. This prevents a static parameter snapshot
    from accidentally walking through several states in the same logical frame.
    """
    state = start_state
    route: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for phase_index, phase in enumerate(parameter_phases[:max_steps]):
        parameters = {str(key): value for key, value in phase.get("parameters", {}).items()}
        choices = _transitions(graph, machine, state)
        matches = [item for item in choices if _transition_matches(item, parameters) is True]
        if not matches:
            unresolved.append(f"phase {phase_index}: no resolved transition from state {state}")
            break
        selected = matches[0]
        destination, selector_trace = _resolve_destination(
            graph, machine, int(selected.get("DestinationState", selected.get("Destination"))), parameters
        )
        if destination is None:
            unresolved.append(f"phase {phase_index}: selector destination unresolved from state {state}")
            break
        source_clip, source_speed, source_loop = _state_clip(graph, machine, state)
        target_clip, target_speed, target_loop = _state_clip(graph, machine, destination)
        route.append({
            "sourceState": state,
            "sourceClip": source_clip,
            "sourceSpeed": source_speed,
            "sourceLoop": source_loop,
            "targetState": destination,
            "targetClip": target_clip,
            "targetSpeed": target_speed,
            "targetLoop": target_loop,
            "edge": selected["edge"],
            "duration": float(selected.get("TransitionDuration", 0.0)),
            "fixedDuration": bool(selected.get("HasFixedDuration", True)),
            "exitTime": float(selected.get("ExitTime", 0.0)),
            "hasExitTime": bool(selected.get("HasExitTime", False)),
            "offset": float(selected.get("TransitionOffset", 0.0)),
            "holdSeconds": phase.get("holdSeconds"),
            "startSeconds": phase.get("startSeconds"),
            "selectorTrace": selector_trace,
            "evidence": phase.get("evidence", "serialized-controller"),
        })
        state = destination
    return route, unresolved


def build_playback_plan(graph: dict[str, Any], specification: dict[str, Any]) -> dict[str, Any]:
    """Compile montage entry + observed stop + controller route to timed segments."""
    spec = deepcopy(specification)
    machine = int(spec.get("machine", 0))
    fps = float(spec.get("fps", 60.0))
    montage = spec["montage"]
    runtime_layer = int(montage.get("runtimeLayer", montage.get("layer", machine)))
    config_layer = montage.get("configLayer", montage.get("layer"))
    route, unresolved = resolve_route(
        graph,
        machine=machine,
        start_state=int(spec["returnState"]),
        parameter_phases=spec.get("parameterPhases", []),
    )

    stop = float(montage["stopSeconds"])
    exit_duration = float(montage["exitDuration"])
    entry_duration = float(montage.get("entryDuration", 0.0))
    cursor = 0.0
    segments: list[dict[str, Any]] = []

    return_clip, _, return_loop = _state_clip(graph, machine, int(spec["returnState"]))
    entry_source = montage.get("entrySourceClip")
    if entry_source and entry_duration > 0:
        segments.append({
            "id": "pre-state",
            "layer": runtime_layer,
            "clip": entry_source,
            "start": 0.0,
            "end": entry_duration,
            "clipStart": float(montage.get("entrySourceSeconds", 0.0)),
            "loop": bool(montage.get("entrySourceLoop", return_loop)),
            "influence": [[0.0, 1.0], [entry_duration, 0.0]],
            "evidence": montage.get("entrySourceEvidence", "serialized-entry-crossfade-source"),
        })
    elif entry_duration > 0:
        unresolved.append("entry source state/blend-tree pose is not compiled")
    segments.append({
        "id": "montage",
        "layer": runtime_layer,
        "clip": montage["clip"],
        "start": 0.0,
        "end": stop + exit_duration,
        "clipStart": 0.0,
        "clipFreezeAt": stop,
        "loop": False,
        "influence": ([[0.0, 0.0], [entry_duration, 1.0]]
                      if entry_source and entry_duration else [[0.0, 1.0]])
                     + [[stop, 1.0], [stop + exit_duration, 0.0]],
        "evidence": montage.get("evidence", "runtime-observed-stop"),
    })
    segments.append({
        "id": "return-state",
        "layer": runtime_layer,
        "clip": return_clip,
        "start": stop,
        "end": stop + exit_duration,
        "clipStart": float(montage.get("returnNormalizedOffset", 0.0)),
        "loop": return_loop,
        "influence": [[stop, 0.0], [stop + exit_duration, 1.0]],
        "evidence": "runtime-observed-destination",
    })
    cursor = stop + exit_duration

    previous = segments[-1]
    for index, edge in enumerate(route):
        hold = edge.get("holdSeconds")
        if hold is None:
            unresolved.append(f"state {edge['sourceState']}: transition start time needs holdSeconds")
            break
        observed_start = edge.get("startSeconds")
        transition_start = (float(observed_start) if observed_start is not None
                            else cursor + float(hold))
        source_length = float(spec.get("clipLengths", {}).get(edge.get("sourceClip"), 0.0))
        target_length = float(spec.get("clipLengths", {}).get(edge.get("targetClip"), 0.0))
        duration = edge["duration"] if edge["fixedDuration"] else edge["duration"] * source_length
        if edge["hasExitTime"] and observed_start is None:
            transition_start = max(transition_start, previous["start"] + edge["exitTime"] * source_length)
        transition_end = transition_start + duration
        previous["end"] = transition_end
        previous["influence"].extend([[transition_start, 1.0], [transition_end, 0.0]])
        target = {
            "id": f"state-{edge['targetState']}-{index}",
            "layer": runtime_layer,
            "clip": edge["targetClip"],
            "start": transition_start,
            "end": transition_end,
            "clipStart": edge["offset"] * target_length,
            "loop": edge["targetLoop"],
            "influence": [[transition_start, 0.0], [transition_end, 1.0]],
            "transition": edge,
            "evidence": edge["evidence"],
        }
        segments.append(target)
        previous = target
        cursor = transition_end

    tail = float(spec.get("tailSeconds", 2.0))
    if segments:
        segments[-1]["end"] = max(float(segments[-1]["end"]), cursor + tail)
    return {
        "schema": "endfield.animation.playback-plan.v1",
        "character": spec.get("character"),
        "action": montage.get("name"),
        "scenario": spec.get("scenario", "single-press-no-followup"),
        "fps": fps,
        "curveStatus": spec.get("curveStatus", "linear-model-not-engine-weight-readback"),
        "layerIdentity": {
            "configMontageLayer": config_layer,
            "runtimeAnimatorLayer": runtime_layer,
            "controllerMachine": machine,
            "status": spec.get("layerIdentityStatus", "explicit-namespaces"),
        },
        "entryStateSnapshot": spec.get("entryStateSnapshot"),
        "parallelLayers": spec.get("parallelLayers", []),
        "segments": segments,
        "route": route,
        "unresolved": unresolved,
        "sources": spec.get("sources", []),
    }
