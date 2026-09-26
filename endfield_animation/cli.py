from __future__ import annotations

import argparse
import json
from pathlib import Path

from .controller_log import parse_controller_log_file
from .blend_tree import infer_simple1d_snapshot
from .layer_composition import augment_plan_with_runtime_layers, build_layer_composition
from .planner import build_playback_plan
from .runtime_timeline import extract_runtime_layers, extract_runtime_timeline
from .phase_replay import replay_phase_corrections
from .frame_time_mapping import write_frame_time_map
from .offline_action_bake import BakeConfig, bake_action_data


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="endfield-animation")
    commands = parser.add_subparsers(dest="command", required=True)
    graph = commands.add_parser("parse-controller")
    graph.add_argument("--log", type=Path, required=True)
    graph.add_argument("--out", type=Path, required=True)
    plan = commands.add_parser("build-plan")
    plan.add_argument("--graph", type=Path, required=True)
    plan.add_argument("--spec", type=Path, required=True)
    plan.add_argument("--out", type=Path, required=True)
    timeline = commands.add_parser("extract-runtime")
    timeline.add_argument("--csv", type=Path, required=True)
    timeline.add_argument("--entry-qpc", type=int, required=True)
    timeline.add_argument("--component", required=True)
    timeline.add_argument("--layer", type=int, default=0)
    timeline.add_argument("--duration", type=float, default=20.0)
    timeline.add_argument("--out", type=Path, required=True)
    layers = commands.add_parser("extract-runtime-layers")
    layers.add_argument("--csv", type=Path, required=True)
    layers.add_argument("--entry-qpc", type=int, required=True)
    layers.add_argument("--component", required=True)
    layers.add_argument("--duration", type=float, default=20.0)
    layers.add_argument("--graph", type=Path)
    layers.add_argument("--identity-csv", type=Path)
    layers.add_argument("--out", type=Path, required=True)
    composition = commands.add_parser("build-layer-composition")
    composition.add_argument("--graph", type=Path, required=True)
    composition.add_argument("--runtime", type=Path, required=True)
    composition.add_argument("--out", type=Path, required=True)
    augment = commands.add_parser("augment-plan-layers")
    augment.add_argument("--plan", type=Path, required=True)
    augment.add_argument("--composition", type=Path, required=True)
    augment.add_argument("--runtime", type=Path, required=True)
    augment.add_argument("--out", type=Path, required=True)
    blend = commands.add_parser("infer-entry-blend")
    blend.add_argument("--graph", type=Path, required=True)
    blend.add_argument("--machine", type=int, required=True)
    blend.add_argument("--state", type=int, required=True)
    blend.add_argument("--effective-length", type=float, required=True)
    blend.add_argument("--normalized-time", type=float, required=True)
    blend.add_argument("--out", type=Path, required=True)
    replay = commands.add_parser("replay-phase-correction")
    replay.add_argument("--input", type=Path, required=True)
    replay.add_argument("--out", type=Path, required=True)
    replay.add_argument("--manifest", type=Path)
    replay.add_argument("--base-pose", type=Path, help="explicit phase-0/phase-2 pose capture for quaternion source")
    replay.add_argument("--expected-nodes", type=int, default=610)
    replay.add_argument("--expected-frames", type=int, default=494)
    time_map = commands.add_parser("frame-time-map")
    time_map.add_argument("--input", type=Path, required=True)
    time_map.add_argument("--out", type=Path, required=True)
    time_map.add_argument("--acl", type=Path)
    bake = commands.add_parser("bake-offline-action")
    bake.add_argument("--dataset", type=Path, required=True)
    bake.add_argument("--armature", type=Path, required=True)
    bake.add_argument("--out", type=Path, required=True)
    bake.add_argument("--enabled", action="store_true", help="explicitly request the offline adapter")
    bake.add_argument("--action-name", default="Endfield_R7C_OfflineAction")
    args = parser.parse_args(argv)
    if args.command == "parse-controller":
        _write(args.out, parse_controller_log_file(args.log))
    elif args.command == "build-plan":
        _write(args.out, build_playback_plan(_read(args.graph), _read(args.spec)))
    elif args.command == "extract-runtime":
        _write(args.out, extract_runtime_timeline(
            args.csv, entry_qpc=args.entry_qpc, component=args.component,
            layer=args.layer, duration_seconds=args.duration))
    elif args.command == "extract-runtime-layers":
        _write(args.out, extract_runtime_layers(
            args.csv, entry_qpc=args.entry_qpc, component=args.component,
            duration_seconds=args.duration,
            graph=_read(args.graph) if args.graph else None,
            identity_path=args.identity_csv))
    elif args.command == "build-layer-composition":
        _write(args.out, build_layer_composition(_read(args.graph), _read(args.runtime)))
    elif args.command == "augment-plan-layers":
        _write(args.out, augment_plan_with_runtime_layers(
            _read(args.plan), _read(args.composition), _read(args.runtime)))
    elif args.command == "infer-entry-blend":
        _write(args.out, infer_simple1d_snapshot(
            _read(args.graph), machine=args.machine, state=args.state,
            effective_length=args.effective_length, normalized_time=args.normalized_time))
    elif args.command == "frame-time-map":
        write_frame_time_map(args.input, args.out, args.acl)
    elif args.command == "bake-offline-action":
        _write(args.out, bake_action_data(
            args.dataset, args.armature,
            config=BakeConfig(enabled=args.enabled, action_name=args.action_name)))
    else:
        result = replay_phase_corrections(
            args.input, args.out, manifest_path=args.manifest, base_pose_path=args.base_pose,
            expected_nodes=args.expected_nodes, expected_frames=args.expected_frames)
        if not result["module_enabled"]:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
