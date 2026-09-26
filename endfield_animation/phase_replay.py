"""Exact, offline phase-2 replay from the R4-B local TRS correction dataset.

This module is deliberately independent of Blender and the production importer.  It
replays only the arithmetic already materialized by R4-B; it does not interpolate,
extrapolate, solve, or infer an execution stage.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import math
from pathlib import Path
from typing import Any, Iterable, Mapping


LOG = logging.getLogger("endfield_animation.phase_replay")
_VEC3 = ("x", "y", "z")
_QUAT = ("x", "y", "z", "w")


def _finite(value: str, field: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} is not finite")
    return result


def _vector(row: Mapping[str, str], prefix: str, labels: Iterable[str] = _VEC3) -> list[float]:
    return [_finite(row[f"{prefix}_{label}"], f"{prefix}_{label}") for label in labels]


def _normalize(q: Iterable[float]) -> list[float]:
    values = [float(value) for value in q]
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or norm == 0.0:
        raise ValueError("quaternion has zero/non-finite norm")
    return [value / norm for value in values]


def _qmul(a: Iterable[float], b: Iterable[float]) -> list[float]:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ]


def _qangle_degrees(a: Iterable[float], b: Iterable[float]) -> float:
    qa = _normalize(a)
    qb = _normalize(b)
    dot = abs(sum(x * y for x, y in zip(qa, qb)))
    return math.degrees(2.0 * math.acos(max(0.0, min(1.0, dot))))


def _max_abs_delta(actual: Iterable[float], expected: Iterable[float]) -> float:
    return max(abs(float(a) - float(b)) for a, b in zip(actual, expected))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _load_rotation_reference(
    path: Path, diagnostics: list[dict[str, Any]]
) -> tuple[dict[tuple[int, int, str], list[float]], dict[tuple[int, int, str], list[float]]]:
    """Load explicit phase-0/phase-2 quaternions from the R4-B source capture."""
    before: dict[tuple[int, int, str], list[float]] = {}
    after: dict[tuple[int, int, str], list[float]] = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    row = json.loads(line)
                    if row.get("event") not in (None, "pose_sample"):
                        continue
                    phase = int(row["phase"])
                    if phase not in (0, 2):
                        continue
                    key = (int(row["engine_frame"]), int(row["node"]), str(row["path"]))
                    target = before if phase == 0 else after
                    if key in target:
                        raise ValueError("duplicate rotation reference key")
                    target[key] = _normalize(row["local_rotation"])
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    _diagnostic(diagnostics, "WARNING", "rotation_reference.row_invalid", str(exc), path=str(path), line=line_number)
                    return {}, {}
    except (OSError, UnicodeError) as exc:
        _diagnostic(diagnostics, "WARNING", "rotation_reference.read_failed", str(exc), path=str(path))
        return {}, {}
    if not before or not after:
        _diagnostic(diagnostics, "WARNING", "rotation_reference.incomplete", "phase-0 and phase-2 quaternion references are required", path=str(path), phase0=len(before), phase2=len(after))
        return {}, {}
    return before, after


def _diagnostic(diagnostics: list[dict[str, Any]], level: str, code: str, message: str, **context: Any) -> None:
    item = {"level": level, "code": code, "message": message, "context": context}
    diagnostics.append(item)
    log = LOG.warning if level == "WARNING" else LOG.info
    log("%s: %s; context=%s", code, message, context)


def _validate_group(
    rows: list[dict[str, str]],
    *,
    frame: int,
    expected_nodes: int | None,
    node_paths: dict[int, str],
    diagnostics: list[dict[str, Any]],
) -> tuple[bool, dict[tuple[int, int, str], dict[str, str]]]:
    """Validate one complete frame before writing any of its replay rows."""
    keyed: dict[tuple[int, int, str], dict[str, str]] = {}
    node_seen: dict[int, str] = {}
    invalid = False
    for row in rows:
        try:
            row_frame = int(row["engine_frame"])
            node = int(row["node"])
            path = row["path"]
            if row_frame != frame or not path:
                raise ValueError("frame or path identity mismatch")
            key = (row_frame, node, path)
            if key in keyed or node in node_seen:
                raise ValueError("duplicate engine_frame+node_id+path or node identity")
            if node in node_paths and node_paths[node] != path:
                raise ValueError("node path differs from the established path identity")
            node_seen[node] = path
            keyed[key] = row
            # Parse every arithmetic input before accepting the frame.  This keeps
            # malformed rows from becoming partially reconstructed output.
            _vector(row, "local_position_before")
            _vector(row, "local_position_correction")
            _vector(row, "local_scale_before")
            _vector(row, "local_scale_correction")
            _vector(row, "rotation_correction", _QUAT)
            _vector(row, "local_position_after")
            _vector(row, "local_scale_after")
            _vector(row, "local_rotation_after", _QUAT) if "local_rotation_after_x" in row else None
        except (KeyError, TypeError, ValueError) as exc:
            invalid = True
            _diagnostic(diagnostics, "WARNING", "frame.row_invalid", str(exc), frame=frame, node=row.get("node"), path=row.get("path"))
    if expected_nodes is not None and len(keyed) != expected_nodes:
        invalid = True
        _diagnostic(diagnostics, "WARNING", "frame.node_count_mismatch", f"expected {expected_nodes} nodes, got {len(keyed)}", frame=frame)
    if invalid:
        _diagnostic(diagnostics, "WARNING", "frame.skipped", "entire frame skipped; no partial replay rows written", frame=frame)
        return False, {}
    node_paths.update(node_seen)
    return True, keyed


def replay_phase_corrections(
    input_csv: str | Path,
    output_csv: str | Path,
    *,
    manifest_path: str | Path | None = None,
    base_pose_path: str | Path | None = None,
    expected_nodes: int | None = 610,
    expected_frames: int | None = 494,
) -> dict[str, Any]:
    """Replay R4-B local corrections into phase-2 TRS rows.

    Rows are consumed frame-by-frame.  A frame is emitted only when every row has a
    unique ``engine_frame + node + path`` identity, its path agrees with earlier
    frames, and all required numeric fields are finite.  No row is synthesized.
    ``module_enabled`` is true only for a complete, diagnostic-free expected dataset.
    """
    source = Path(input_csv)
    output = Path(output_csv)
    diagnostics: list[dict[str, Any]] = []
    manifest: dict[str, Any] = {
        "schema": "endfield.animation.runtime-contract.r5-c.phase-correction-replay.v1",
        "status": "DISABLED_INPUT_MISSING",
        "module_enabled": False,
        "read_only": True,
        "game_started": False,
        "production_importer_touched": False,
        "interpolation": False,
        "extrapolation": False,
        "solver_label": None,
        "input": str(source.resolve()),
        "output": str(output.resolve()),
        "rotation_reference": None,
        "core_source": str(Path(__file__).resolve()),
        "core_sha256": _sha256(Path(__file__)),
        "expected_nodes_per_frame": expected_nodes,
        "expected_frames": expected_frames,
        "accepted_frames": 0,
        "skipped_frames": 0,
        "accepted_rows": 0,
        "max_position_error": 0.0,
        "max_scale_error": 0.0,
        "max_rotation_error_deg": 0.0,
        "diagnostics": diagnostics,
        "arithmetic": {
            "position": "local_position_before + local_position_correction",
            "rotation": "normalize(rotation_correction * normalize(local_rotation_before))",
            "scale": "local_scale_before + local_scale_correction",
            "join_key": "engine_frame + node + path",
        },
    }
    if not source.is_file():
        _diagnostic(diagnostics, "WARNING", "input.missing", "correction dataset file is missing", path=str(source))
        if manifest_path:
            _write_manifest(manifest, Path(manifest_path))
        return manifest

    # R4-B materialized position/scale source and the quaternion delta, while the
    # explicit phase-0/phase-2 quaternions remain in its recorded source capture.
    # Resolve that companion by manifest; a caller may provide a checked capture
    # explicitly.  No identity quaternion is invented when it is absent.
    rotation_reference = Path(base_pose_path) if base_pose_path else None
    if rotation_reference is None:
        r4b_manifest = source.with_name("r4b_phase_trs_correction_manifest.v1.json")
        if r4b_manifest.is_file():
            try:
                rotation_reference = Path(json.loads(r4b_manifest.read_text(encoding="utf-8"))["source_capture"])
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                _diagnostic(diagnostics, "WARNING", "rotation_reference.manifest_invalid", str(exc), path=str(r4b_manifest))
    before_rotations: dict[tuple[int, int, str], list[float]] = {}
    after_rotations: dict[tuple[int, int, str], list[float]] = {}
    if rotation_reference is not None:
        manifest["rotation_reference"] = str(rotation_reference.resolve())
        before_rotations, after_rotations = _load_rotation_reference(rotation_reference, diagnostics)
    else:
        _diagnostic(diagnostics, "WARNING", "rotation_reference.missing", "R4-B dataset has no explicit quaternion source")

    output.parent.mkdir(parents=True, exist_ok=True)
    node_paths: dict[int, str] = {}
    accepted_frames: list[int] = []
    skipped_frames: list[int] = []
    fieldnames: list[str] | None = None
    wrote_header = False
    current_frame: int | None = None
    current_rows: list[dict[str, str]] = []

    def flush_frame(writer: csv.DictWriter | None) -> None:
        nonlocal wrote_header
        if current_frame is None:
            return
        ok, keyed = _validate_group(
            current_rows,
            frame=current_frame,
            expected_nodes=expected_nodes,
            node_paths=node_paths,
            diagnostics=diagnostics,
        )
        if not ok:
            skipped_frames.append(current_frame)
            return
        assert writer is not None
        replay_rows: list[dict[str, Any]] = []
        for row in keyed.values():
            before_position = _vector(row, "local_position_before")
            correction_position = _vector(row, "local_position_correction")
            before_scale = _vector(row, "local_scale_before")
            correction_scale = _vector(row, "local_scale_correction")
            key = (current_frame, int(row["node"]), row["path"])
            before_rotation = before_rotations.get(key)
            expected_rotation = after_rotations.get(key)
            correction_rotation = _normalize(_vector(row, "rotation_correction", _QUAT))
            if before_rotation is None or expected_rotation is None:
                _diagnostic(diagnostics, "WARNING", "frame.rotation_reference_missing", "entire frame skipped; quaternion references must match engine_frame+node+path", frame=current_frame, node=row.get("node"), path=row.get("path"))
                skipped_frames.append(current_frame)
                return
            replay_position = [a + b for a, b in zip(before_position, correction_position)]
            replay_rotation = _normalize(_qmul(correction_rotation, before_rotation))
            replay_scale = [a + b for a, b in zip(before_scale, correction_scale)]
            expected_position = _vector(row, "local_position_after")
            expected_scale = _vector(row, "local_scale_after")
            position_error = _max_abs_delta(replay_position, expected_position)
            scale_error = _max_abs_delta(replay_scale, expected_scale)
            rotation_error = _qangle_degrees(replay_rotation, expected_rotation)
            out = dict(row)
            out.update({
                "replay_phase": "2",
                "local_position_replayed_x": replay_position[0],
                "local_position_replayed_y": replay_position[1],
                "local_position_replayed_z": replay_position[2],
                "local_rotation_replayed_x": replay_rotation[0],
                "local_rotation_replayed_y": replay_rotation[1],
                "local_rotation_replayed_z": replay_rotation[2],
                "local_rotation_replayed_w": replay_rotation[3],
                "local_scale_replayed_x": replay_scale[0],
                "local_scale_replayed_y": replay_scale[1],
                "local_scale_replayed_z": replay_scale[2],
                "position_error": position_error,
                "scale_error": scale_error,
                "rotation_error_deg": rotation_error,
            })
            replay_rows.append(out)
        if not wrote_header:
            writer.writeheader()
            wrote_header = True
        for out in replay_rows:
            writer.writerow(out)
        manifest["accepted_rows"] += len(replay_rows)
        manifest["max_position_error"] = max(manifest["max_position_error"], max(float(row["position_error"]) for row in replay_rows))
        manifest["max_scale_error"] = max(manifest["max_scale_error"], max(float(row["scale_error"]) for row in replay_rows))
        manifest["max_rotation_error_deg"] = max(manifest["max_rotation_error_deg"], max(float(row["rotation_error_deg"]) for row in replay_rows))
        accepted_frames.append(current_frame)

    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle, output.open("w", encoding="utf-8", newline="") as out_handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError("correction dataset has no header")
            fieldnames = list(reader.fieldnames) + [
                "replay_phase", "local_position_replayed_x", "local_position_replayed_y", "local_position_replayed_z",
                "local_rotation_replayed_x", "local_rotation_replayed_y", "local_rotation_replayed_z", "local_rotation_replayed_w",
                "local_scale_replayed_x", "local_scale_replayed_y", "local_scale_replayed_z", "position_error", "scale_error", "rotation_error_deg",
            ]
            writer = csv.DictWriter(out_handle, fieldnames=fieldnames, extrasaction="ignore")
            for row in reader:
                try:
                    frame = int(row["engine_frame"])
                except (KeyError, TypeError, ValueError) as exc:
                    _diagnostic(diagnostics, "WARNING", "row.frame_invalid", str(exc), row=row)
                    if current_frame is not None:
                        skipped_frames.append(current_frame)
                    current_frame = None
                    current_rows = []
                    continue
                if current_frame is None:
                    current_frame = frame
                elif frame != current_frame:
                    flush_frame(writer)
                    current_frame = frame
                    current_rows = []
                current_rows.append(row)
            flush_frame(writer)
    except (OSError, ValueError) as exc:
        _diagnostic(diagnostics, "WARNING", "input.read_failed", str(exc), path=str(source))
        manifest["status"] = "DISABLED_INPUT_INVALID"
        manifest["skipped_frames"] = sorted(set(skipped_frames))
        if manifest_path:
            _write_manifest(manifest, Path(manifest_path))
        return manifest

    manifest["accepted_frames"] = len(accepted_frames)
    manifest["skipped_frames"] = sorted(set(skipped_frames))
    manifest["frame_range"] = [min(accepted_frames), max(accepted_frames)] if accepted_frames else []
    contiguous = bool(accepted_frames) and all(b == a + 1 for a, b in zip(accepted_frames, accepted_frames[1:]))
    manifest["frame_sequence_contiguous"] = contiguous
    if accepted_frames and not contiguous:
        _diagnostic(diagnostics, "WARNING", "frame.sequence_gap", "accepted frame sequence contains a gap", frame_range=manifest["frame_range"])
    manifest["source_sha256"] = _sha256(source)
    if output.exists():
        manifest["output_sha256"] = _sha256(output)
    complete = (
        bool(accepted_frames)
        and not diagnostics
        and (expected_frames is None or len(accepted_frames) == expected_frames)
        and contiguous
        and (expected_nodes is None or manifest["accepted_rows"] == len(accepted_frames) * expected_nodes)
        and manifest["max_position_error"] == 0.0
        and manifest["max_scale_error"] == 0.0
        and manifest["max_rotation_error_deg"] <= 2.5e-6
    )
    manifest["acceptance"] = {
        "required_rows": (len(accepted_frames) * expected_nodes) if expected_nodes is not None else None,
        "rows_exact": expected_nodes is None or manifest["accepted_rows"] == len(accepted_frames) * expected_nodes,
        "frame_sequence_contiguous": contiguous,
        "position_error_zero": manifest["max_position_error"] == 0.0,
        "scale_error_zero": manifest["max_scale_error"] == 0.0,
        "rotation_error_deg_lte_2_5e-6": manifest["max_rotation_error_deg"] <= 2.5e-6,
    }
    manifest["module_enabled"] = complete
    manifest["status"] = "READY_EXACT_REPLAY" if complete else "DISABLED_INCOMPLETE_OR_DIAGNOSTIC"
    if manifest_path:
        _write_manifest(manifest, Path(manifest_path))
    return manifest


def _write_manifest(value: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
