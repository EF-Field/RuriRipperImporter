"""Parse the reproducible ControllerGraph diagnostics emitted by Ruri-RipperHook.

The parser deliberately consumes the diagnostic wire form instead of scraping Unity
YAML.  It preserves hashes and raw fields so names recovered later can be attached
without changing graph identity.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable


_PREFIX = re.compile(r"^\[(?P<kind>[^]]+)]\s+(?P<rest>.*)$")
_TRAILING_BODY = re.compile(r"(?P<body>\w+\s*\{.*\})$")
_HEAD_PAIR = re.compile(r"(\w+)=('(?:[^']*)'|\S+)")
_ACL_IDENTITY = re.compile(r"^'(?P<name>[^']+)'\s+pathID=(?P<path>-?\d+)")
_ROOT_ACL = re.compile(r"^'(?P<name>[^']+)'\s+.*\bduration=(?P<duration>[0-9.eE+-]+)")


def _atom(value: str) -> Any:
    value = value.strip().strip("'")
    if value in {"True", "False"}:
        return value == "True"
    if value in {"<missing>", "null", "None"}:
        return None
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _pairs(text: str) -> dict[str, Any]:
    return {match.group(1): _atom(match.group(2)) for match in _HEAD_PAIR.finditer(text)}


def _body_fields(text: str | None) -> dict[str, Any]:
    if not text or "{" not in text:
        return {}
    inside = text[text.find("{") + 1 : text.rfind("}")]
    result: dict[str, Any] = {}
    for item in inside.split(";"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        # Nested diagnostic summaries contain commas/brackets but no semicolons.
        result[key.strip()] = _atom(value)
    return result


def parse_controller_log(lines: Iterable[str]) -> dict[str, Any]:
    graph: dict[str, Any] = {
        "schema": "endfield.controller-graph.v1",
        "layers": {},
        "parameters": {},
        "clips": {},
        "states": {},
        "selectors": {},
        "transitions": [],
    }
    path_names: dict[int, str] = {}
    clip_durations: dict[str, float] = {}
    transition_index: dict[tuple[int, int, int], dict[str, Any]] = {}

    for raw in lines:
        line = raw.rstrip("\r\n")
        match = _PREFIX.match(line)
        if not match:
            continue
        kind = match.group("kind")
        rest = match.group("rest")
        body_match = _TRAILING_BODY.search(rest)
        body = body_match.group("body") if body_match else None
        head_text = rest[: body_match.start()].rstrip() if body_match else rest
        head = _pairs(head_text)
        fields = _body_fields(body)

        if kind == "ACLProbe":
            identity = _ACL_IDENTITY.match(rest)
            if identity:
                path_names[int(identity.group("path"))] = identity.group("name")
        elif kind == "RootACL":
            identity = _ROOT_ACL.match(rest)
            if identity:
                clip_durations[identity.group("name")] = float(identity.group("duration"))
        elif kind == "ControllerGraphLayer":
            layer = int(head["layer"])
            graph["layers"].setdefault(str(layer), {"layer": layer}).update({
                "layer": layer,
                "machine": int(head["machine"]),
                "defaultWeight": float(head["weight"]),
                "blendMode": int(head["blendMode"]),
                "ikPass": bool(head["ikPass"]),
            })
        elif kind == "ControllerLayerDetail":
            layer = int(head["layer"])
            detail = fields
            target = graph["layers"].setdefault(str(layer), {"layer": layer})
            for source, destination in (
                ("Binding", "binding"),
                ("StateMachineIndex", "machine"),
                ("StateMachineSynchronizedLayerIndex", "synchronizedLayer"),
                ("SyncedLayerAffectsTiming", "synchronizedAffectsTiming"),
                ("DefaultWeight", "defaultWeight"),
                ("LayerBlendingMode", "blendMode"),
                ("IKPass", "ikPass"),
            ):
                if source in detail:
                    target[destination] = detail[source]
        elif kind == "ControllerLayerMask":
            layer = int(head["layer"])
            target = graph["layers"].setdefault(str(layer), {"layer": layer})
            mask_field = str(head["field"])
            if mask_field == "BodyMask":
                target["bodyMask"] = {
                    key: int(value) for key, value in fields.items() if key.startswith("Word")
                }
            else:
                target.setdefault("skeletonMask", {"items": []})
        elif kind in {"ControllerMaskItem", "ControllerSkeletonMaskItem"}:
            layer = int(head["layer"])
            target = graph["layers"].setdefault(str(layer), {"layer": layer})
            target.setdefault("skeletonMask", {"items": []})["items"].append({
                "field": head.get("field"),
                "index": int(head["index"]),
                **fields,
            })
        elif kind == "ControllerParameter":
            parameter = {"ordinal": int(head["index"]), **fields}
            if "ID" in parameter:
                graph["parameters"][str(parameter["ID"])] = parameter
        elif kind == "ControllerGraphClip":
            slot = int(head["slot"])
            graph["clips"][str(slot)] = {
                "slot": slot,
                "pathId": int(head["pathID"]),
                "name": head.get("name"),
            }
        elif kind == "ControllerGraphState":
            machine, state = int(head["machine"]), int(head["state"])
            graph["states"][f"{machine}:{state}"] = {
                "machine": machine,
                "state": state,
                "nameId": int(head["nameID"]),
                "pathId": int(head["pathID"]),
                "fullPathId": int(head["fullPathID"]),
                "loop": bool(head["loop"]),
                "speed": float(head["speed"]),
                "ikOnFeet": bool(head["ikOnFeet"]),
                "writeDefaults": bool(head["writeDefaults"]),
                "clipSlot": None,
                "nodes": [],
            }
        elif kind == "ControllerGraphNode":
            key = f"{int(head['machine'])}:{int(head['state'])}"
            if key in graph["states"]:
                clip_slot = int(head["clipID"])
                graph["states"][key]["nodes"].append({
                    "tree": int(head.get("tree", 0)),
                    "node": int(head["node"]),
                    "clipSlot": None if clip_slot == 4294967295 else clip_slot,
                    "clipIndex": int(head.get("clipIndex", 0)),
                    "blend": head.get("blend"),
                })
                if int(head["node"]) == 0 and clip_slot != 4294967295:
                    graph["states"][key]["clipSlot"] = clip_slot
        elif kind == "ControllerBlendNode":
            key = f"{int(head['machine'])}:{int(head['state'])}"
            state = graph["states"].get(key)
            if state:
                node = next((item for item in state["nodes"]
                             if item["tree"] == int(head["tree"])
                             and item["node"] == int(head["node"])), None)
                if node is not None:
                    node.update({
                        "parameterHash": None if fields.get("BlendEventID") == 4294967295 else fields.get("BlendEventID"),
                        "parameterYHash": None if fields.get("BlendEventYID") == 4294967295 else fields.get("BlendEventYID"),
                        "cycleOffset": float(fields.get("CycleOffset", 0.0)),
                        "duration": float(fields.get("Duration", 0.0)),
                        "mirror": bool(fields.get("Mirror", False)),
                        "childIndices": [],
                        "thresholds": [],
                    })
        elif kind == "ControllerBlendChild":
            key = f"{int(head['machine'])}:{int(head['state'])}"
            state = graph["states"].get(key)
            if state:
                node = next((item for item in state["nodes"]
                             if item["tree"] == int(head["tree"])
                             and item["node"] == int(head["node"])), None)
                if node is not None:
                    node.setdefault("childIndices", []).append(int(head["value"]))
        elif kind == "ControllerBlendDataItem" and str(head.get("field", "")).endswith("ChildThresholdArray"):
            key = f"{int(head['machine'])}:{int(head['state'])}"
            state = graph["states"].get(key)
            if state:
                node = next((item for item in state["nodes"]
                             if item["tree"] == int(head["tree"])
                             and item["node"] == int(head["node"])), None)
                if node is not None:
                    node.setdefault("thresholds", []).append(float(head["value"]))
        elif kind == "ControllerSelector":
            machine, selector = int(head["machine"]), int(head["selector"])
            graph["selectors"][f"{machine}:{selector}"] = {
                "machine": machine,
                "selector": selector,
                **fields,
            }
        elif kind == "ControllerTransition":
            machine, state, edge = int(head["machine"]), int(head["state"]), int(head["edge"])
            transition = {
                "machine": machine,
                "sourceState": state,
                "edge": edge,
                "selector": "SelectorTransitionConstant" in (body or ""),
                "conditions": [],
                **fields,
            }
            graph["transitions"].append(transition)
            transition_index[(machine, state, edge)] = transition
        elif kind == "ControllerCondition":
            key = (int(head["machine"]), int(head["state"]), int(head["edge"]))
            if key in transition_index:
                transition_index[key]["conditions"].append(fields)

    for clip in graph["clips"].values():
        if not clip.get("name"):
            clip["name"] = path_names.get(clip["pathId"])
        if clip.get("name") in clip_durations:
            clip["duration"] = clip_durations[clip["name"]]
    for state in graph["states"].values():
        for node in state["nodes"]:
            slot = node.get("clipSlot")
            node["clipName"] = (graph["clips"].get(str(slot)) or {}).get("name")
    return graph


def parse_controller_log_file(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8-sig", errors="replace") as handle:
        return parse_controller_log(handle)
