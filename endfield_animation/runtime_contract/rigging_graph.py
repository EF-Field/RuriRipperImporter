"""Evidence-gated RigBuilder/RigLayer/constraint manifests.

The manifest deliberately models construction order separately from execution order.
``serialized_order`` is copied from the input and is never inferred from a Job's
inputs, outputs, or names.  Runtime modules are enabled only when their required
evidence gates are present.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .diagnostics import DiagnosticEvent, info, warning


SCHEMA = "endfield.animation.rigging-graph.v1"
GAP = "GAP"

EVIDENCE_KINDS = frozenset(
    {
        "serialized-field",
        "direct-call",
        "vtable",
        "formula",
        "serialized-order",
        "runtime-observed",
        "engine-gap",
        "binder-contract",
        "animation-stream-abi",
        "prefab-instance-order",
        "float-property-binding",
    }
)

KNOWN_FIELDS: dict[str, frozenset[str]] = {
    "hgikprepareeffectorsconstraint": frozenset(
        {
            "componentRoot",
            "transformAndNormals",
            "sourceTransforms",
            "effectorsAndNormalsProperty",
            "count",
        }
    ),
    "hgprepareikeffectorconstraint": frozenset(
        {
            "componentRoot",
            "source",
            "target",
            "groundNormal",
            "positionOffset",
            "rotationWeight",
            "lockPositionWorld",
            "positionLockWeight",
            "maxPitchDegree",
            "maxRollDegree",
            "groundNormalProperty",
            "positionOffsetProperty",
            "rotationWeightProperty",
            "lockPositionWorldProperty",
            "positionLockWeightProperty",
            "maxPitchDegreeProperty",
            "maxRollDegreeProperty",
        }
    ),
    "hgtwoboneikconstraint": frozenset(
        {
            "root",
            "mid",
            "tip",
            "hint",
            "target",
            "componentRotation",
            "targetPositionWeight",
            "targetRotationWeight",
            "hintWeight",
            "maintainTargetPositionOffset",
            "maintainTargetRotationOffset",
            "targetPositionWeightFloatProperty",
            "targetRotationWeightFloatProperty",
            "hintWeightFloatProperty",
            "groundNormalProperty",
            "componentRotationProperty",
        }
    ),
    "bipedikrigging": frozenset(
        {
            "limbs",
            "pelvis",
            "limbCount",
            "ikCurveHashes",
            "footLockCurveHashes",
            "IK_CTRL_CURVE_PREFIX",
            "IK_LOCK_ENABLE_CURVE_PREFIX",
        }
    ),
    "footlock": frozenset(
        {
            "lockExitThreshold",
            "lockWeightSmooth",
            "lockAnchorBreakDistancePadding3D",
            "lockAnchorBreakRotationAngle",
            "lockProbeMissTolerance",
            "rootTeleportDistSq",
            "lastSwitchSource",
            "lockWeight",
            "lockAnchorNormal",
            "lockAnchorLocalPosition",
            "lockAnchorWorldFallback",
            "lockAnchorColliderProxy",
            "lockAnchorLimbRootForwardOnPlane",
            "probeHit",
            "probeNormal",
            "probeMissDuration",
        }
    ),
}

# Metadata names in the GameAssembly dump include the private serialized names;
# retain both spellings so a type-tree export can be loaded without renaming.
KNOWN_FIELDS.update(
    {
        "hgikprepareeffectorsconstraintdata": KNOWN_FIELDS["hgikprepareeffectorsconstraint"],
        "hgprepareikeffectorconstraintdata": KNOWN_FIELDS["hgprepareikeffectorconstraint"],
        "hgtwoboneikconstraintdata": KNOWN_FIELDS["hgtwoboneikconstraint"],
        "footlockconfig": KNOWN_FIELDS["footlock"],
        "footlockdata": KNOWN_FIELDS["footlock"],
    }
)
for _key in ("hgikprepareeffectorsconstraint", "hgikprepareeffectorsconstraintdata"):
    KNOWN_FIELDS[_key] = KNOWN_FIELDS[_key] | frozenset(
        {"_componentRoot", "_transformAndNormals", "_sourceTransforms"}
    )
for _key in ("hgprepareikeffectorconstraint", "hgprepareikeffectorconstraintdata"):
    KNOWN_FIELDS[_key] = KNOWN_FIELDS[_key] | frozenset(
        {
            "_componentRoot", "_source", "_target", "_groundNormal", "_positionOffset",
            "_rotationWeight", "_lockPositionWorld", "_positionLockWeight",
            "_maxPitchDegree", "_maxRollDegree",
        }
    )
for _key in ("hgtwoboneikconstraint", "hgtwoboneikconstraintdata"):
    KNOWN_FIELDS[_key] = KNOWN_FIELDS[_key] | frozenset(
        {
            "_root", "_mid", "_tip", "_hint", "_componentRotation",
            "_targetPositionWeight", "_targetRotationWeight", "_hintWeight",
            "_maintainTargetPositionOffset", "_maintainTargetRotationOffset",
        }
    )
for _key in ("bipedikrigging",):
    KNOWN_FIELDS[_key] = KNOWN_FIELDS[_key] | frozenset(
        {"_limbs", "_pelvis", "_limbCount", "_ikCurveHashes", "_footLockCurveHashes"}
    )
for _key in ("footlockconfig", "footlockdata", "footlock"):
    KNOWN_FIELDS[_key] = KNOWN_FIELDS[_key] | frozenset(
        {
            "_lockExitThreshold", "_lockWeightSmooth", "_lockAnchorBreakDistancePadding3D",
            "_lockAnchorBreakRotationAngle", "_lockProbeMissTolerance", "_rootTeleportDistSq",
            "_lastSwitchSource", "_lockWeight", "_lockAnchorNormal", "_lockAnchorLocalPosition",
            "_lockAnchorWorldFallback", "_lockAnchorColliderProxy",
            "_lockAnchorLimbRootForwardOnPlane", "_probeHit", "_probeNormal", "_probeMissDuration",
        }
    )


def _type_key(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    kind: str
    source: str | None = None
    detail: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceRecord":
        evidence_id = str(value.get("id", value.get("evidence_id", ""))).strip()
        kind = str(value.get("kind", "")).strip()
        if not evidence_id or not kind:
            raise ValueError("evidence records require id and kind")
        return cls(evidence_id, kind, value.get("source"), value.get("detail"))


@dataclass(frozen=True)
class RuntimeModule:
    name: str
    enabled: bool
    required_evidence: tuple[str, ...]
    present_evidence: tuple[str, ...]
    gaps: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        return "enabled" if self.enabled else "disabled"


@dataclass(frozen=True)
class ConstraintManifest:
    name: str
    type_name: str
    serialized_order: int
    fields: Mapping[str, Any] = field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    job_io: Mapping[str, Any] | None = None
    static_candidate_order: tuple[str, ...] = ()

    @property
    def type_key(self) -> str:
        return _type_key(self.type_name)

    @property
    def supported_fields(self) -> Mapping[str, Any]:
        known = KNOWN_FIELDS.get(self.type_key, frozenset())
        return {key: value for key, value in self.fields.items() if key in known}

    @property
    def unknown_fields(self) -> tuple[str, ...]:
        known = KNOWN_FIELDS.get(self.type_key, frozenset())
        return tuple(key for key in self.fields if key not in known)


@dataclass(frozen=True)
class RuntimeComponentManifest:
    """Typed BipedIKRigging/FootLock data carried beside graph constraints."""

    name: str
    type_name: str
    fields: Mapping[str, Any] = field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()

    @property
    def type_key(self) -> str:
        return _type_key(self.type_name)

    @property
    def supported_fields(self) -> Mapping[str, Any]:
        known = KNOWN_FIELDS.get(self.type_key, frozenset())
        return {key: value for key, value in self.fields.items() if key in known}

    @property
    def unknown_fields(self) -> tuple[str, ...]:
        known = KNOWN_FIELDS.get(self.type_key, frozenset())
        return tuple(key for key in self.fields if key not in known)


@dataclass(frozen=True)
class RigLayerManifest:
    name: str
    serialized_order: int
    constraints: tuple[ConstraintManifest, ...]
    evidence_ids: tuple[str, ...] = ()
    active: bool | None = None


@dataclass(frozen=True)
class RiggingGraphManifest:
    schema: str
    character: str | None
    layers: tuple[RigLayerManifest, ...]
    evidence: tuple[EvidenceRecord, ...]
    modules: Mapping[str, RuntimeModule]
    gaps: tuple[str, ...]
    execution_order: tuple[str, ...] | None = None
    job_io_relations: tuple[Mapping[str, Any], ...] = ()
    diagnostics: tuple[DiagnosticEvent, ...] = ()
    components: tuple[RuntimeComponentManifest, ...] = ()

    @property
    def serialized_order(self) -> tuple[str, ...]:
        """Return the input list order, without sorting or normalizing it."""
        return tuple(layer.name for layer in self.layers)

    @property
    def runtime_enabled(self) -> bool:
        return any(module.enabled for module in self.modules.values())

    def module(self, name: str) -> RuntimeModule:
        return self.modules[name]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "character": self.character,
            "layers": [
                {
                    "name": layer.name,
                    "serialized_order": layer.serialized_order,
                    "active": layer.active,
                    "evidence_ids": list(layer.evidence_ids),
                    "constraints": [
                        {
                            "name": constraint.name,
                            "type": constraint.type_name,
                            "serialized_order": constraint.serialized_order,
                            "fields": dict(constraint.fields),
                            "evidence_ids": list(constraint.evidence_ids),
                            "job_io": constraint.job_io,
                            "static_candidate_order": list(constraint.static_candidate_order),
                        }
                        for constraint in layer.constraints
                    ],
                }
                for layer in self.layers
            ],
            "components": [
                {
                    "name": component.name,
                    "type": component.type_name,
                    "fields": dict(component.fields),
                    "evidence_ids": list(component.evidence_ids),
                }
                for component in self.components
            ],
            "evidence": [
                {
                    "id": item.evidence_id,
                    "kind": item.kind,
                    "source": item.source,
                    "detail": item.detail,
                }
                for item in self.evidence
            ],
            "modules": {
                name: {
                    "status": module.status,
                    "enabled": module.enabled,
                    "required_evidence": list(module.required_evidence),
                    "present_evidence": list(module.present_evidence),
                    "gaps": list(module.gaps),
                }
                for name, module in self.modules.items()
            },
            "gaps": list(self.gaps),
            "execution_order": None if self.execution_order is None else list(self.execution_order),
            "job_io_relations": [dict(item) for item in self.job_io_relations],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


def _as_ids(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, Sequence):
        raise ValueError("evidence_ids must be a string or sequence")
    return tuple(str(item) for item in value)


def _load_source(source: Mapping[str, Any] | str | Path) -> Mapping[str, Any]:
    if isinstance(source, Mapping):
        return source
    path = Path(source)
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_ordered_constraints(layer: Mapping[str, Any]) -> tuple[tuple[ConstraintManifest, ...], bool]:
    raw_constraints = layer.get("constraints", [])
    if not isinstance(raw_constraints, Sequence) or isinstance(raw_constraints, (str, bytes)):
        raise ValueError("layer.constraints must be a sequence")
    parsed: list[ConstraintManifest] = []
    order_gap = False
    for index, raw in enumerate(raw_constraints):
        if not isinstance(raw, Mapping):
            raise ValueError("constraint entries must be objects")
        if "serialized_order" not in raw:
            order_gap = True
            serialized_order = index
        else:
            serialized_order = int(raw["serialized_order"])
        fields = raw.get("fields", raw.get("data", {}))
        if not isinstance(fields, Mapping):
            raise ValueError("constraint.fields must be an object")
        candidate = raw.get("static_candidate_order", raw.get("candidate_order", ()))
        parsed.append(
            ConstraintManifest(
                name=str(raw.get("name", f"constraint-{index}")),
                type_name=str(raw.get("type", raw.get("type_name", ""))),
                serialized_order=serialized_order,
                fields=dict(fields),
                evidence_ids=_as_ids(raw.get("evidence_ids", raw.get("evidence"))),
                job_io=raw.get("job_io"),
                static_candidate_order=tuple(str(item) for item in candidate),
            )
        )
    return tuple(parsed), order_gap


def _parse_components(source: Any) -> tuple[RuntimeComponentManifest, ...]:
    if source is None:
        return ()
    if not isinstance(source, Sequence) or isinstance(source, (str, bytes)):
        raise ValueError("components must be a sequence")
    parsed: list[RuntimeComponentManifest] = []
    for index, raw in enumerate(source):
        if not isinstance(raw, Mapping):
            raise ValueError("component entries must be objects")
        fields = raw.get("fields", raw.get("data", {}))
        if not isinstance(fields, Mapping):
            raise ValueError("component.fields must be an object")
        parsed.append(
            RuntimeComponentManifest(
                name=str(raw.get("name", f"component-{index}")),
                type_name=str(raw.get("type", raw.get("type_name", ""))),
                fields=dict(fields),
                evidence_ids=_as_ids(raw.get("evidence_ids", raw.get("evidence"))),
            )
        )
    return tuple(parsed)


def _module(
    name: str,
    required: tuple[str, ...],
    available: set[str],
    base_gaps: Sequence[str] = (),
) -> RuntimeModule:
    missing = tuple(kind for kind in required if kind not in available)
    gaps = tuple(base_gaps) + tuple(f"{GAP}:missing-evidence:{kind}" for kind in missing)
    return RuntimeModule(name, not missing and not base_gaps, required, tuple(sorted(available & set(required))), gaps)


def parse_rigging_graph(source: Mapping[str, Any] | str | Path) -> RiggingGraphManifest:
    """Parse an evidence-gated graph without promoting candidates to facts.

    Structural order fields are mandatory. Missing evidence is represented as GAP and
    disables the affected runtime module; it does not trigger a guessed fallback.
    """
    diagnostics: list[DiagnosticEvent] = []
    source_label = "mapping" if isinstance(source, Mapping) else str(source)
    try:
        raw = _load_source(source)
    except (OSError, ValueError, TypeError) as error:
        diagnostics.append(
            warning(
                "rigging.source.load_failed",
                "rigging graph source could not be loaded",
                source=source_label,
                error=type(error).__name__,
            )
        )
        raise
    diagnostics.append(
        info("rigging.source.loaded", "rigging graph source loaded", source=source_label)
    )
    diagnostics.append(info("rigging.parse.started", "rigging graph parse started", source=source_label))
    schema = str(raw.get("schema", ""))
    evidence = tuple(EvidenceRecord.from_dict(item) for item in raw.get("evidence", []))
    by_id = {item.evidence_id: item for item in evidence}
    available = {item.kind for item in evidence}
    gaps: list[str] = []
    if schema != SCHEMA:
        gaps.append(f"{GAP}:schema:{schema or 'missing'}")
        diagnostics.append(
            warning(
                "rigging.parse.schema_gap",
                "rigging graph schema is outside the locked contract",
                schema=schema or None,
            )
        )
    if "serialized-order" not in available:
        gaps.append(f"{GAP}:missing-evidence:serialized-order")
        diagnostics.append(
            warning(
                "rigging.serialized_order.evidence_missing",
                "serialized-order evidence is missing",
            )
        )

    graph = raw.get("rig_builder", raw)
    if not isinstance(graph, Mapping):
        diagnostics.append(
            warning(
                "rigging.parse.structure_error",
                "rig_builder must be an object",
            )
        )
        raise ValueError("rig_builder must be an object")
    raw_layers = graph.get("layers", [])
    if not isinstance(raw_layers, Sequence) or isinstance(raw_layers, (str, bytes)):
        diagnostics.append(
            warning(
                "rigging.parse.structure_error",
                "layers must be a sequence",
            )
        )
        raise ValueError("layers must be a sequence")
    try:
        components = _parse_components(raw.get("components", raw.get("rigging_components")))
    except ValueError:
        diagnostics.append(
            warning(
                "rigging.parse.structure_error",
                "components must be a sequence of objects with object fields",
            )
        )
        raise
    layers: list[RigLayerManifest] = []
    order_gap = False
    seen_layer_orders: set[int] = set()
    if not raw_layers:
        order_gap = True
        gaps.append(f"{GAP}:serialized-order:empty-layer-list")
        diagnostics.append(
            warning(
                "rigging.serialized_order.empty",
                "RigBuilder layer list is empty",
            )
        )
    for index, raw_layer in enumerate(raw_layers):
        if not isinstance(raw_layer, Mapping):
            diagnostics.append(
                warning(
                    "rigging.parse.structure_error",
                    "layer entry must be an object",
                    index=index,
                )
            )
            raise ValueError("layer entries must be objects")
        if "serialized_order" not in raw_layer:
            order_gap = True
            gaps.append(f"{GAP}:layer-order:{raw_layer.get('name', index)}")
            diagnostics.append(
                warning(
                    "rigging.serialized_order.layer_missing",
                    "RigLayer lacks explicit serialized_order",
                    layer=raw_layer.get("name", index),
                )
            )
            # Preserve the list position as a diagnostic value, not as evidence.
            serialized_order = index
        else:
            try:
                serialized_order = int(raw_layer["serialized_order"])
            except (TypeError, ValueError):
                diagnostics.append(
                    warning(
                        "rigging.serialized_order.invalid",
                        "RigLayer serialized_order is not an integer",
                        layer=raw_layer.get("name", index),
                    )
                )
                raise ValueError("layer serialized_order must be an integer")
        if serialized_order in seen_layer_orders:
            order_gap = True
            gaps.append(f"{GAP}:duplicate-layer-order:{serialized_order}")
            diagnostics.append(
                warning(
                    "rigging.serialized_order.duplicate_layer",
                    "RigLayer serialized_order is duplicated",
                    serialized_order=serialized_order,
                )
            )
        seen_layer_orders.add(serialized_order)
        constraints, constraint_order_gap = _parse_ordered_constraints(raw_layer)
        order_gap = order_gap or constraint_order_gap
        if constraint_order_gap:
            gaps.append(f"{GAP}:constraint-order:{raw_layer.get('name', index)}")
            diagnostics.append(
                warning(
                    "rigging.serialized_order.constraint_missing",
                    "constraint lacks explicit serialized_order",
                    layer=raw_layer.get("name", index),
                )
            )
        else:
            diagnostics.append(
                info(
                    "rigging.serialized_order.accepted",
                    "serialized layer and constraint order preserved",
                    layer=raw_layer.get("name", index),
                    layer_order=serialized_order,
                    constraint_count=len(constraints),
                )
            )
        layers.append(
            RigLayerManifest(
                name=str(raw_layer.get("name", f"layer-{index}")),
                serialized_order=serialized_order,
                constraints=constraints,
                evidence_ids=_as_ids(raw_layer.get("evidence_ids", raw_layer.get("evidence"))),
                active=raw_layer.get("active"),
            )
        )

    for layer in layers:
        seen: set[int] = set()
        for constraint in layer.constraints:
            if constraint.serialized_order in seen:
                order_gap = True
                gaps.append(f"{GAP}:duplicate-constraint-order:{layer.name}:{constraint.serialized_order}")
                diagnostics.append(
                    warning(
                        "rigging.serialized_order.duplicate",
                        "constraint serialized_order is duplicated",
                        layer=layer.name,
                        serialized_order=constraint.serialized_order,
                    )
                )
            seen.add(constraint.serialized_order)
            if constraint.static_candidate_order or constraint.job_io:
                gaps.append(f"{GAP}:job-io-is-not-execution-order:{constraint.name}")
                diagnostics.append(
                    warning(
                        "rigging.execution_order.candidate_gap",
                        "Job I/O or static candidate order retained without promotion",
                        constraint=constraint.name,
                    )
                )
            if constraint.unknown_fields:
                diagnostics.append(
                    warning(
                        "rigging.field.unknown",
                        "unknown constraint fields retained as untyped data",
                        constraint=constraint.name,
                        fields=list(constraint.unknown_fields),
                    )
                )

    for component in components:
        if component.unknown_fields:
            diagnostics.append(
                warning(
                    "rigging.field.unknown",
                    "unknown runtime component fields retained as untyped data",
                    component=component.name,
                    fields=list(component.unknown_fields),
                )
            )

    if order_gap:
        gaps.append(f"{GAP}:serialized-order-incomplete")

    # The graph construction module can use explicit list order, while every
    # character-specific HG runtime module remains gated by the missing contracts.
    graph_gaps = tuple(gaps) if schema != SCHEMA or "serialized-order" not in available or order_gap else ()
    modules: dict[str, RuntimeModule] = {
        "rig_builder_graph": _module(
            "rig_builder_graph", ("serialized-order",), available, graph_gaps
        ),
        "hg_ik_prepare_effectors": _module(
            "hg_ik_prepare_effectors",
            (
                "serialized-order",
                "serialized-field",
                "binder-contract",
                "animation-stream-abi",
                "prefab-instance-order",
                "float-property-binding",
            ),
            available,
        ),
        "hg_prepare_ik_effector": _module(
            "hg_prepare_ik_effector",
            (
                "serialized-order",
                "serialized-field",
                "binder-contract",
                "animation-stream-abi",
                "prefab-instance-order",
                "float-property-binding",
            ),
            available,
        ),
        "hg_two_bone_ik": _module(
            "hg_two_bone_ik",
            (
                "serialized-order",
                "serialized-field",
                "binder-contract",
                "animation-stream-abi",
                "prefab-instance-order",
                "float-property-binding",
            ),
            available,
        ),
        "biped_ik": _module(
            "biped_ik",
            (
                "serialized-order", "serialized-field", "prefab-instance-order",
                "binder-contract", "animation-stream-abi", "float-property-binding",
            ),
            available,
        ),
        "foot_lock": _module(
            "foot_lock",
            (
                "serialized-order",
                "serialized-field",
                "prefab-instance-order",
                "binder-contract",
                "animation-stream-abi",
                "float-property-binding",
            ),
            available,
        ),
    }
    # Module gate gaps are first-class manifest gaps as well as module-local
    # reasons, so serialization never hides a disabled dependency.
    for module in modules.values():
        gaps.extend(module.gaps)
    # Explicitly retain supplied relations as observations/inputs. They never
    # populate execution_order.
    relations: list[Mapping[str, Any]] = []
    for relation in raw.get("job_io_relations", raw.get("job_io", [])):
        if isinstance(relation, Mapping):
            relations.append(dict(relation))
    if relations:
        gaps.append(f"{GAP}:job-io-relations-retained-without-order")
        diagnostics.append(
            warning(
                "rigging.execution_order.job_io_gap",
                "Job I/O relations retained without creating execution order",
                relation_count=len(relations),
            )
        )

    unknown_ids = {
        evidence_id
        for layer in layers
        for evidence_id in layer.evidence_ids
        if evidence_id not in by_id
    }
    for layer in layers:
        unknown_ids.update(
            evidence_id
            for constraint in layer.constraints
            for evidence_id in constraint.evidence_ids
            if evidence_id not in by_id
        )
    gaps.extend(f"{GAP}:unknown-evidence-id:{item}" for item in sorted(unknown_ids))
    for evidence_id in sorted(unknown_ids):
        diagnostics.append(
            warning(
                "rigging.evidence.unknown_id",
                "manifest references an unknown evidence id",
                evidence_id=evidence_id,
            )
        )
    for gap in dict.fromkeys(gaps):
        diagnostics.append(
            warning("rigging.gap.retained", "GAP retained in manifest", gap=gap)
        )
    for name, module in modules.items():
        if module.enabled:
            diagnostics.append(
                info("rigging.module.enabled", "runtime module enabled", module=name)
            )
        else:
            diagnostics.append(
                warning(
                    "rigging.module.disabled",
                    "runtime module disabled by evidence gate",
                    module=name,
                    gaps=list(module.gaps),
                )
            )
        diagnostics.append(
            info(
                "rigging.parse.completed",
                "rigging graph parse completed",
                layer_count=len(layers),
                component_count=len(components),
                gap_count=len(dict.fromkeys(gaps)),
            )
    )
    return RiggingGraphManifest(
        schema=schema,
        character=raw.get("character"),
        layers=tuple(layers),
        evidence=evidence,
        modules=modules,
        gaps=tuple(dict.fromkeys(gaps)),
        execution_order=None,
        job_io_relations=tuple(relations),
        diagnostics=tuple(diagnostics),
        components=components,
    )


load_rigging_graph_manifest = parse_rigging_graph


def dump_rigging_graph_manifest(manifest: RiggingGraphManifest, destination: str | Path) -> None:
    Path(destination).write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
