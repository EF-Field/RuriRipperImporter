"""Evidence-aware frame to Animator normalized-time mapping.

This module consumes an observed pose-pair CSV.  It deliberately operates only on
rows that were observed: no interpolation, loop fitting, transition-weight
inference, or cross-process identity join is performed here.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Any


SCHEMA = "endfield.animation.runtime-contract.r6c.frame-normalized-time.v1"
QPC_SECONDS = 10_000_000.0  # project runtime_timeline convention


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite numeric value: {value!r}")
    return result


def _stable_frame_rows(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collapse 610 node rows into one state/time row per observed engine frame."""
    by_frame: dict[int, dict[str, Any]] = {}
    row_count = 0
    malformed = 0
    consistency_errors: list[dict[str, Any]] = []
    consistency_error_count = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"engine_frame", "phase0_qpc", "state", "current_full_path_hash", "normalized_time"}
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise ValueError(f"missing required columns: {missing}")
        for row in reader:
            row_count += 1
            try:
                frame = int(row["engine_frame"])
                qpc = int(row["phase0_qpc"])
                state = row["state"]
                full_hash = int(row["current_full_path_hash"])
                normalized = _float(row["normalized_time"])
            except (KeyError, TypeError, ValueError):
                malformed += 1
                continue
            candidate = {
                "engine_frame": frame,
                "phase0_qpc": qpc,
                "phase0_qpc_min": qpc,
                "phase0_qpc_max": qpc,
                "state": state,
                "full_path_hash": full_hash,
                "normalized_time": normalized,
                "node_rows": 1,
            }
            previous = by_frame.get(frame)
            if previous is None:
                by_frame[frame] = candidate
                continue
            previous["node_rows"] += 1
            previous["phase0_qpc_min"] = min(previous["phase0_qpc_min"], qpc)
            previous["phase0_qpc_max"] = max(previous["phase0_qpc_max"], qpc)
            for field in ("state", "full_path_hash", "normalized_time"):
                if previous[field] != candidate[field]:
                    consistency_error_count += 1
                    if len(consistency_errors) < 32:
                        consistency_errors.append({
                            "engine_frame": frame,
                            "field": field,
                            "first": previous[field],
                            "observed": candidate[field],
                        })
                    break
    frames = [by_frame[key] for key in sorted(by_frame)]
    counts = Counter(int(item["node_rows"]) for item in frames)
    return frames, {
        "raw_rows": row_count,
        "malformed_rows": malformed,
        "observed_frames": len(frames),
        "frame_node_row_counts": {str(key): value for key, value in sorted(counts.items())},
        "consistency_error_count": consistency_error_count,
        "consistency_errors_sample": consistency_errors,
    }


def _segment(frames: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    for frame in frames:
        if not groups or frame["full_path_hash"] != groups[-1][-1]["full_path_hash"]:
            groups.append([])
        groups[-1].append(frame)
    return groups


def _segment_summary(group: list[dict[str, Any]], next_frame: dict[str, Any] | None) -> dict[str, Any]:
    values = [float(item["normalized_time"]) for item in group]
    deltas = [b - a for a, b in zip(values, values[1:])]
    qpcs = [int(item["phase0_qpc"]) for item in group]
    qpc_deltas = [b - a for a, b in zip(qpcs, qpcs[1:])]
    rates = [delta / (qpc_delta / QPC_SECONDS)
             for delta, qpc_delta in zip(deltas, qpc_deltas) if qpc_delta > 0]
    decreases = [index for index, delta in enumerate(deltas, start=1) if delta < 0]
    return {
        "state": group[0]["state"],
        "full_path_hash": group[0]["full_path_hash"],
        "frame_start": group[0]["engine_frame"],
        "frame_end": group[-1]["engine_frame"],
        "frame_count": len(group),
        "qpc_start": qpcs[0],
        "qpc_end": qpcs[-1],
        "duration_seconds_project_qpc": (qpcs[-1] - qpcs[0]) / QPC_SECONDS,
        "normalized_start": values[0],
        "normalized_end": values[-1],
        "normalized_min": min(values),
        "normalized_max": max(values),
        "normalized_delta_sum_observed": sum(deltas),
        "normalized_delta_min": min(deltas) if deltas else None,
        "normalized_delta_max": max(deltas) if deltas else None,
        "normalized_delta_mean": mean(deltas) if deltas else None,
        "normalized_delta_median": median(deltas) if deltas else None,
        "normalized_rate_per_second_min": min(rates) if rates else None,
        "normalized_rate_per_second_max": max(rates) if rates else None,
        "normalized_rate_per_second_mean": mean(rates) if rates else None,
        "qpc_delta_min": min(qpc_deltas) if qpc_deltas else None,
        "qpc_delta_max": max(qpc_deltas) if qpc_deltas else None,
        "normalized_decrease_observed": bool(decreases),
        "loop_observed": False,
        "loop_status": "not_observed" if not decreases else "candidate_decrease_observed",
        "transition_out": None if next_frame is None else {
            "next_frame": next_frame["engine_frame"],
            "next_state": next_frame["state"],
            "next_full_path_hash": next_frame["full_path_hash"],
            "next_normalized_time": next_frame["normalized_time"],
            "weight": "not_recorded",
        },
    }


def analyze_frame_normalized_time(input_path: str | Path) -> dict[str, Any]:
    """Return a deterministic, observed-only frame/time contract."""
    path = Path(input_path).resolve()
    frames, ingest = _stable_frame_rows(path)
    # Each pose row carries its own callback query timestamp.  Anchor the
    # frame to the earliest observed timestamp, while preserving spread below.
    frames = [{**frame, "phase0_qpc": frame["phase0_qpc_min"]} for frame in frames]
    gaps = []
    for previous, current in zip(frames, frames[1:]):
        difference = current["engine_frame"] - previous["engine_frame"]
        if difference != 1:
            gaps.append({"from_frame": previous["engine_frame"], "to_frame": current["engine_frame"], "missing_count": difference - 1})
    output_frames: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for current in frames:
        same_segment = previous is not None and previous["full_path_hash"] == current["full_path_hash"]
        contiguous = previous is not None and current["engine_frame"] - previous["engine_frame"] == 1
        delta = current["normalized_time"] - previous["normalized_time"] if same_segment and contiguous else None
        qpc_delta = current["phase0_qpc"] - previous["phase0_qpc"] if same_segment and contiguous else None
        output_frames.append({
            **current,
            "seconds_from_first_qpc": (current["phase0_qpc"] - frames[0]["phase0_qpc"]) / QPC_SECONDS if frames else None,
            "normalized_delta_observed": delta,
            "qpc_delta_observed": qpc_delta,
            "normalized_rate_per_second_observed": (
                delta / (qpc_delta / QPC_SECONDS) if delta is not None and qpc_delta and qpc_delta > 0 else None
            ),
            "boundary": "segment_start" if previous is None or not same_segment else None,
        })
        previous = current
    groups = _segment(frames)
    summaries = []
    for index, group in enumerate(groups):
        summaries.append(_segment_summary(group, groups[index + 1][0] if index + 1 < len(groups) else None))
    transitions = [summary["transition_out"] for summary in summaries if summary["transition_out"]]
    return {
        "schema": SCHEMA,
        "source": str(path),
        "source_sha256": _sha256(path),
        "read_only": True,
        "interpolation": "none",
        "transition_weight": "not_recorded",
        "qpc_seconds_convention": QPC_SECONDS,
        "ingest": ingest,
        "frame_range": [frames[0]["engine_frame"], frames[-1]["engine_frame"]] if frames else [],
        "frame_count": len(frames),
        "route": [{"state": item["state"], "full_path_hash": item["full_path_hash"]} for item in summaries],
        "segments": summaries,
        "transitions": transitions,
        "frame_gaps": gaps,
        "trajectory": output_frames,
        "status": "READY_OBSERVED_FRAME_TIME_MAP" if frames and not ingest["malformed_rows"] and not ingest["consistency_error_count"] else "WARN_OBSERVED_FRAME_TIME_MAP",
    }


def summarize_acl_float_tracks(input_path: str | Path) -> dict[str, Any]:
    """Summarize the checked-in ACL float artifact without decoding new values."""
    path = Path(input_path).resolve()
    header: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        raw = []
        for line in handle:
            if line.startswith("#"):
                parts = line[1:].rstrip("\n").split("\t", 1)
                if len(parts) == 2:
                    header[parts[0].strip()] = parts[1].strip()
                continue
            raw.append(line)
        reader = csv.DictReader(raw, delimiter="\t")
        rows = list(reader)
    sample_count = int(header.get("frameCount", "0"))
    tracks_by_kind = Counter("RootMotion" if row["name"].startswith("Root") else
                              "Motion" if row["name"].startswith("Motion") else
                              "Limb" if any(row["name"].startswith(prefix) for prefix in ("Left", "Right")) else
                              "Muscle" for row in rows)
    nonzero = 0
    for row in rows:
        if any(float(row[f"f{i}"]) != 0.0 for i in range(sample_count)):
            nonzero += 1
    return {
        "schema": "endfield.animation.runtime-contract.r6c.acl-float-source.v1",
        "source": str(path),
        "source_sha256": _sha256(path),
        "clip": header.get("clip"),
        "sample_rate_hz": int(header.get("sampleRate", "0")),
        "frame_count": sample_count,
        "track_count": len(rows),
        "nonzero_track_count": nonzero,
        "tracks_by_kind": dict(sorted(tracks_by_kind.items())),
        "status": "SOURCE_OBSERVED_ONLY",
    }


def write_frame_time_map(input_path: str | Path, manifest_path: str | Path, acl_path: str | Path | None = None) -> dict[str, Any]:
    """Write manifest plus compact trajectory CSV for downstream timeline builders."""
    manifest_file = Path(manifest_path).resolve()
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    result = analyze_frame_normalized_time(input_path)
    if acl_path:
        result["acl_float_source"] = summarize_acl_float_tracks(acl_path)
    trajectory_path = manifest_file.with_name("frame_normalized_trajectory.csv")
    fields = ["engine_frame", "phase0_qpc", "phase0_qpc_min", "phase0_qpc_max", "seconds_from_first_qpc", "state", "full_path_hash", "normalized_time", "normalized_delta_observed", "qpc_delta_observed", "normalized_rate_per_second_observed", "boundary", "node_rows"]
    with trajectory_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in result["trajectory"]:
            writer.writerow({field: row.get(field) for field in fields})
    result["trajectory_csv"] = str(trajectory_path)
    result["trajectory_row_count"] = len(result["trajectory"])
    result["trajectory"] = "see trajectory_csv"
    manifest_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
