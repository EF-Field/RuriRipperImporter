"""Evidence-aware partial order for Endfield animation execution.

The graph deliberately stops at unresolved Unity/native boundaries.  It is a
contract ledger, not a pose evaluator: static reachability and callback labels
are never promoted to runtime stage semantics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
import logging

from . import diagnostics


class EdgeType(str, Enum):
    DIRECT_CALL = "direct-call"
    VTABLE = "vtable"
    SERIALIZED_ORDER = "serialized-order"
    RUNTIME_OBSERVED = "runtime-observed"
    ENGINE_GAP = "engine-gap"


# Short spelling useful to callers and kept as a public alias.
EdgeKind = EdgeType
ALLOWED_EDGE_TYPES = frozenset(item.value for item in EdgeType)


class ExecutionOrderError(ValueError):
    """Base error for malformed or contradictory contract evidence."""


class EvidenceValidationError(ExecutionOrderError):
    pass


class IllegalEvidenceUpgradeError(EvidenceValidationError):
    pass


class IdentityMismatchError(EvidenceValidationError):
    pass


class EvidenceContradictionError(EvidenceValidationError):
    pass


class CycleError(ExecutionOrderError):
    pass


class RequiredGapError(ExecutionOrderError):
    pass


class MissingRuntimeOrderError(EvidenceValidationError):
    pass


class ProbeDisabledError(ExecutionOrderError):
    pass


@dataclass(frozen=True)
class EvidenceIdentity:
    """Identity tuple used to join runtime observations.

    Static records may leave these values empty. Runtime records retain every
    value supplied by a capture; matching compares only fields present on both
    records, while :meth:`complete` is used by the R3 gate.
    """

    build_hash: str | None = None
    gameassembly_hash: str | None = None
    metadata_hash: str | None = None
    character_id: str | None = None
    action_id: str | None = None
    instance_id: str | None = None
    animator_id: str | None = None
    graph_id: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None = None, **extra: Any) -> "EvidenceIdentity":
        data = dict(value or {})
        data.update({k: v for k, v in extra.items() if v is not None})
        aliases = {"build": "build_hash", "gameassembly": "gameassembly_hash", "metadata": "metadata_hash", "character": "character_id", "action": "action_id", "instance": "instance_id", "animator": "animator_id", "graph": "graph_id"}
        for old, new in aliases.items():
            if new not in data and old in data:
                data[new] = data[old]
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: data[k] for k in fields if k in data})

    @property
    def complete(self) -> bool:
        return all((self.build_hash, self.character_id, self.action_id, self.instance_id))

    def conflicts_with(self, other: "EvidenceIdentity") -> bool:
        return any(a is not None and b is not None and a != b for a, b in zip(self.values(), other.values()))

    def compatible_with(self, other: "EvidenceIdentity") -> bool:
        return not self.conflicts_with(other)

    def values(self) -> tuple[Any, ...]:
        return tuple(getattr(self, f.name) for f in self.__dataclass_fields__.values())

    def as_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in self.__dataclass_fields__.values() if getattr(self, f.name) is not None}

    to_dict = as_dict


@dataclass(frozen=True)
class RuntimeObservation:
    node_id: str
    engine_frame: int
    qpc: int | float
    identity: EvidenceIdentity = field(default_factory=EvidenceIdentity)
    sequence: int = 0
    label: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RuntimeObservation":
        node = value.get("node_id", value.get("node", value.get("event", value.get("name"))))
        if not node:
            raise EvidenceValidationError("runtime observation requires node_id")
        frame = value.get("engine_frame", value.get("frame"))
        qpc = value.get("qpc", value.get("qpc_ticks", value.get("timestamp")))
        if frame is None or qpc is None:
            raise MissingRuntimeOrderError(f"{node}: engine_frame and QPC are required")
        ident = EvidenceIdentity.from_mapping(value.get("identity"), **{k: value.get(k) for k in EvidenceIdentity.__dataclass_fields__ if k in value})
        return cls(str(node), int(frame), float(qpc) if isinstance(qpc, float) else int(qpc), ident, int(value.get("sequence", 0)), value.get("label"), value.get("metadata", {}))

    def sort_key(self) -> tuple[int, int | float, int]:
        return (self.engine_frame, self.qpc, self.sequence)

    from_dict = from_mapping


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    edge_type: EdgeType
    source: str
    target: str
    source_ref: str | None = None
    target_ref: str | None = None
    identity: EvidenceIdentity = field(default_factory=EvidenceIdentity)
    origin: str = "artifact"
    source_observation: RuntimeObservation | None = None
    target_observation: RuntimeObservation | None = None
    engine_frame: int | None = None
    qpc: int | float | None = None
    label: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvidenceRecord":
        kind = value.get("edge_type", value.get("kind", value.get("type")))
        try:
            edge_type = EdgeType(kind)
        except (TypeError, ValueError) as exc:
            raise EvidenceValidationError(f"unsupported edge type: {kind!r}; allowed={sorted(ALLOWED_EDGE_TYPES)}") from exc
        source = value.get("source", value.get("caller", value.get("from")))
        target = value.get("target", value.get("callee", value.get("to")))
        if not source or not target:
            raise EvidenceValidationError("evidence requires source and target")
        eid = value.get("evidence_id", value.get("id"))
        if not eid:
            raise EvidenceValidationError("evidence requires evidence_id")
        identity = EvidenceIdentity.from_mapping(value.get("identity"), **{k: value.get(k) for k in EvidenceIdentity.__dataclass_fields__ if k in value})
        obs = value.get("observations")
        source_obs = value.get("source_observation")
        target_obs = value.get("target_observation")
        if obs:
            if len(obs) != 2:
                raise MissingRuntimeOrderError("runtime evidence observations must contain source and target")
            source_obs, target_obs = obs[0], obs[1]
        if isinstance(source_obs, Mapping): source_obs = RuntimeObservation.from_mapping({**source_obs, "identity": source_obs.get("identity", identity.as_dict())})
        if isinstance(target_obs, Mapping): target_obs = RuntimeObservation.from_mapping({**target_obs, "identity": target_obs.get("identity", identity.as_dict())})
        return cls(str(eid), edge_type, str(source), str(target), value.get("source_ref"), value.get("target_ref"), identity, str(value.get("origin", "artifact")), source_obs, target_obs, value.get("engine_frame"), value.get("qpc"), value.get("label"), value.get("metadata", {}))

    def validate(self) -> None:
        static_origins = {"static", "ida", "decompile", "method-index", "artifact-static"}
        if self.edge_type is EdgeType.RUNTIME_OBSERVED and self.origin.lower() in static_origins:
            raise IllegalEvidenceUpgradeError(f"{self.evidence_id}: static evidence cannot be imported as runtime-observed")
        if self.edge_type is EdgeType.RUNTIME_OBSERVED:
            stage = str(self.metadata.get("semantic_stage", "")).lower()
            label = str(self.label or self.metadata.get("label", "")).lower()
            forbidden = {"pre-ik", "post-ik", "pre_ik", "post_ik", "final-render", "final_render", "renderer-final"}
            if stage in forbidden or label in forbidden:
                raise IllegalEvidenceUpgradeError(f"{self.evidence_id}: callback/phase labels do not establish IK or renderer stage")
            if (self.source_observation is None) != (self.target_observation is None):
                raise MissingRuntimeOrderError(f"{self.evidence_id}: source and target observations must be paired")
            if self.source_observation and self.target_observation:
                if self.source_observation.identity.conflicts_with(self.target_observation.identity):
                    raise IdentityMismatchError(f"{self.evidence_id}: source and target observations have different identities")
                if self.identity.conflicts_with(self.source_observation.identity) or self.identity.conflicts_with(self.target_observation.identity):
                    raise IdentityMismatchError(f"{self.evidence_id}: observation identity differs from evidence identity")
                if self.source_observation.sort_key() >= self.target_observation.sort_key():
                    raise EvidenceContradictionError(f"{self.evidence_id}: runtime timestamps do not order source before target")
            elif self.engine_frame is None or self.qpc is None:
                raise MissingRuntimeOrderError(f"{self.evidence_id}: runtime evidence needs paired observations or engine_frame+qpc")

    from_dict = from_mapping


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    owner: str | None = None
    stage: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderEdge:
    source: str
    target: str
    edge_type: EdgeType
    evidence_ids: tuple[str, ...] = ()
    identity: EvidenceIdentity = field(default_factory=EvidenceIdentity)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return self.edge_type.value


@dataclass(frozen=True)
class RequiredGap:
    gap_id: str
    source: str
    target: str
    reason: str
    required: bool = True


@dataclass(frozen=True)
class GateResult:
    ready: bool
    issues: tuple[str, ...] = ()
    unresolved_gaps: tuple[str, ...] = ()
    probe_hooks_enabled: bool = False
    diagnostics: tuple[Mapping[str, Any], ...] = ()

    def require_ready(self) -> None:
        if not self.ready:
            raise RequiredGapError("R3 gate blocked: " + "; ".join(self.issues or self.unresolved_gaps))


def sort_runtime_events(events: Iterable[RuntimeObservation | Mapping[str, Any]], identity: EvidenceIdentity | None = None) -> list[RuntimeObservation]:
    parsed = [e if isinstance(e, RuntimeObservation) else RuntimeObservation.from_mapping(e) for e in events]
    anchor = identity
    if anchor is None and parsed:
        anchor = parsed[0].identity
    if anchor:
        for event in parsed:
            if event.identity.conflicts_with(anchor):
                raise IdentityMismatchError(f"runtime observation {event.node_id} does not match graph identity")
    parsed.sort(key=RuntimeObservation.sort_key)
    return parsed


class ExecutionOrderGraph:
    """Typed DAG ledger with mandatory unresolved native-boundary gaps."""

    def __init__(self, *, required_gaps: Iterable[RequiredGap] = (), identity: EvidenceIdentity | None = None, probe_hooks_enabled: bool = False) -> None:
        self.nodes: dict[str, GraphNode] = {}
        self.edges: list[OrderEdge] = []
        self.evidence: dict[str, EvidenceRecord] = {}
        self.required_gaps: dict[str, RequiredGap] = {g.gap_id: g for g in required_gaps if g.required}
        self.identity = identity
        self.probe_hooks_enabled = bool(probe_hooks_enabled)
        self.diagnostics: list[diagnostics.DiagnosticEvent] = []
        self._gap_edges: set[str] = set()

    def _emit_info(self, code: str, message: str, **context: Any) -> diagnostics.DiagnosticEvent:
        event = diagnostics.info(code, message, **context)
        self.diagnostics.append(event)
        return event

    def _emit_warning(self, code: str, message: str, **context: Any) -> diagnostics.DiagnosticEvent:
        event = diagnostics.warning(code, message, **context)
        self.diagnostics.append(event)
        return event

    @property
    def diagnostic_records(self) -> tuple[diagnostics.DiagnosticEvent, ...]:
        return tuple(self.diagnostics)

    @classmethod
    def contract_graph(cls, identity: EvidenceIdentity | None = None) -> "ExecutionOrderGraph":
        graph = cls(identity=identity, probe_hooks_enabled=False, required_gaps=default_required_gaps())
        for gap in default_required_gaps():
            graph.add_edge(OrderEdge(gap.source, gap.target, EdgeType.ENGINE_GAP, metadata={"gap_id": gap.gap_id, "reason": gap.reason}))
            graph._gap_edges.add(gap.gap_id)
        return graph

    def add_node(self, node: GraphNode | str, **kwargs: Any) -> GraphNode:
        item = node if isinstance(node, GraphNode) else GraphNode(str(node), **kwargs)
        existing = self.nodes.get(item.node_id)
        if existing and existing != item:
            raise EvidenceContradictionError(f"node identity collision: {item.node_id}")
        self.nodes[item.node_id] = item
        return item

    def add_edge(self, edge: OrderEdge | str, target: str | None = None, edge_type: EdgeType | str | None = None, **kwargs: Any) -> OrderEdge:
        try:
            if isinstance(edge, OrderEdge):
                try:
                    normalized_type = edge.edge_type if isinstance(edge.edge_type, EdgeType) else EdgeType(edge.edge_type)
                except (TypeError, ValueError) as exc:
                    raise EvidenceValidationError(f"unsupported edge type: {edge.edge_type!r}") from exc
                item = edge if normalized_type is edge.edge_type else OrderEdge(edge.source, edge.target, normalized_type, edge.evidence_ids, edge.identity, edge.metadata)
            else:
                if target is None or edge_type is None:
                    raise EvidenceValidationError("source, target and edge_type are required")
                try: kind = edge_type if isinstance(edge_type, EdgeType) else EdgeType(edge_type)
                except ValueError as exc: raise EvidenceValidationError(f"unsupported edge type: {edge_type!r}") from exc
                item = OrderEdge(str(edge), str(target), kind, tuple(kwargs.get("evidence_ids", ())), kwargs.get("identity", EvidenceIdentity()), kwargs.get("metadata", {}))
            if not isinstance(item.edge_type, EdgeType):
                raise EvidenceValidationError(f"unsupported edge type: {item.edge_type!r}")
        except ExecutionOrderError as exc:
            self._emit_warning("edge.rejected", str(exc), source=str(edge), target=target, requested_type=str(edge_type))
            raise
        self.add_node(item.source); self.add_node(item.target)
        if item.identity and self.identity and item.identity.conflicts_with(self.identity):
            self._emit_warning("edge.identity-mismatch", f"edge {item.source}->{item.target} identity mismatch", source=item.source, target=item.target)
            raise IdentityMismatchError(f"edge {item.source}->{item.target} identity mismatch")
        self.edges.append(item)
        if item.edge_type is EdgeType.ENGINE_GAP:
            required_gap = next((gap.gap_id for gap in self.required_gaps.values() if gap.source == item.source and gap.target == item.target), None)
            self._emit_warning(
                "engine-gap.retained",
                "execution edge remains an engine gap",
                source=item.source,
                target=item.target,
                edge_type=item.edge_type.value,
                required_gap=required_gap,
            )
        else:
            self._emit_info("edge.accepted", "typed execution edge accepted", source=item.source, target=item.target, edge_type=item.edge_type.value)
        return item

    def import_evidence(self, records: Iterable[EvidenceRecord | Mapping[str, Any]] | EvidenceRecord | Mapping[str, Any]) -> list[OrderEdge]:
        if isinstance(records, (EvidenceRecord, Mapping)): records = [records]
        added=[]
        for raw in records:
            record = raw if isinstance(raw, EvidenceRecord) else None
            try:
                record = record if record is not None else EvidenceRecord.from_mapping(raw)
                record.validate()
                if self.identity and record.identity.conflicts_with(self.identity):
                    raise IdentityMismatchError(f"evidence {record.evidence_id} identity mismatch")
            except ExecutionOrderError as exc:
                code = "evidence.identity-mismatch" if isinstance(exc, IdentityMismatchError) else "evidence.rejected"
                self._emit_warning(code, str(exc), evidence_id=getattr(record, "evidence_id", None), edge_type=getattr(record, "edge_type", None).value if getattr(record, "edge_type", None) else None)
                raise
            if record.edge_type is EdgeType.RUNTIME_OBSERVED:
                for obs in (record.source_observation, record.target_observation):
                    if obs and self.identity and obs.identity.conflicts_with(self.identity):
                        self._emit_warning("evidence.identity-mismatch", f"evidence {record.evidence_id} observation identity mismatch", evidence_id=record.evidence_id)
                        raise IdentityMismatchError(f"evidence {record.evidence_id} observation identity mismatch")
            previous = self.evidence.get(record.evidence_id)
            if previous is not None and previous != record:
                self._emit_warning("evidence.contradiction", f"evidence id collision: {record.evidence_id}", evidence_id=record.evidence_id)
                raise EvidenceContradictionError(f"evidence id collision: {record.evidence_id}")
            self.evidence[record.evidence_id] = record
            edge = OrderEdge(record.source, record.target, record.edge_type, (record.evidence_id,), record.identity, {"origin": record.origin, "label": record.label, **dict(record.metadata)})
            self.add_edge(edge); added.append(edge)
        return added

    add_evidence = import_evidence
    ingest_evidence = import_evidence

    def import_json(self, path: str | Path) -> list[OrderEdge]:
        data=json.loads(Path(path).read_text(encoding="utf-8"))
        records=data.get("evidence", data) if isinstance(data, Mapping) else data
        return self.import_evidence(records)

    def runtime_events(self, events: Iterable[RuntimeObservation | Mapping[str, Any]]) -> list[RuntimeObservation]:
        try:
            ordered = sort_runtime_events(events, self.identity)
        except ExecutionOrderError as exc:
            self._emit_warning("runtime-sort.rejected", str(exc))
            raise
        self._emit_info("runtime-sort.accepted", "runtime observations sorted by engine_frame and QPC", count=len(ordered))
        return ordered

    def topological_order(self) -> list[str]:
        adjacency: dict[str, set[str]]={n:set() for n in self.nodes}
        indegree={n:0 for n in self.nodes}
        for edge in self.edges:
            if edge.edge_type is EdgeType.ENGINE_GAP:
                continue
            if edge.target not in adjacency[edge.source]:
                adjacency[edge.source].add(edge.target); indegree[edge.target]+=1
        ready=sorted(n for n,d in indegree.items() if d==0); result=[]
        while ready:
            node=ready.pop(0); result.append(node)
            for nxt in sorted(adjacency[node]):
                indegree[nxt]-=1
                if indegree[nxt]==0: ready.append(nxt); ready.sort()
        if len(result)!=len(self.nodes):
            self._emit_warning("graph.cycle", "partial-order graph contains a cycle or contradictory order")
            raise CycleError("partial-order graph contains a cycle or contradictory order")
        return result

    def validate(self) -> tuple[str, ...]:
        issues=[]
        try: self.topological_order()
        except CycleError as exc: issues.append(str(exc))
        if self.identity and not self.identity.complete:
            issues.append("runtime identity is incomplete: build_hash, character_id, action_id and instance_id are required")
            self._emit_warning("identity.incomplete", issues[-1])
        return tuple(issues)

    def gate(self) -> GateResult:
        issues=list(self.validate())
        unresolved=[]
        for gap_id,gap in self.required_gaps.items():
            closing_types = {EdgeType.RUNTIME_OBSERVED}
            matching=[e for e in self.edges if e.source==gap.source and e.target==gap.target and e.edge_type in closing_types]
            if not matching: unresolved.append(gap_id)
        issues.extend(f"required GAP unresolved: {g}" for g in unresolved)
        if unresolved:
            self._emit_warning("gate.blocked", "required execution GAPs remain unresolved", gaps=tuple(unresolved))
        elif issues:
            self._emit_warning("gate.blocked", "execution-order gate has validation issues", issues=tuple(issues))
        else:
            self._emit_info("gate.ready", "execution-order gate passed", probe_hooks_enabled=self.probe_hooks_enabled)
        return GateResult(not issues and not unresolved, tuple(issues), tuple(unresolved), self.probe_hooks_enabled and not issues, tuple(event.to_dict() for event in self.diagnostics[-len(unresolved or issues or [1]):]))

    def enable_probe_hooks(self) -> None:
        result=self.gate()
        if not result.ready:
            self._emit_warning("probe.disabled", "probe hooks remain disabled until the R3 gate closes", unresolved_gaps=result.unresolved_gaps)
            raise ProbeDisabledError("probe hooks remain disabled until the R3 gate closes")
        self.probe_hooks_enabled=True
        self._emit_info("probe.enabled", "probe hooks enabled after the R3 gate closed")

    def as_dict(self) -> dict[str, Any]:
        gate = self.gate()
        return {"identity": self.identity.as_dict() if self.identity else {}, "probe_hooks_enabled": self.probe_hooks_enabled, "nodes": [node.__dict__ for node in self.nodes.values()], "edges": [{"source": e.source, "target": e.target, "edge_type": e.edge_type.value, "evidence_ids": list(e.evidence_ids), "identity": e.identity.as_dict(), "metadata": dict(e.metadata)} for e in self.edges], "required_gaps": [gap.__dict__ for gap in self.required_gaps.values()], "diagnostics": [event.to_dict() for event in self.diagnostics], "gate": gate.__dict__}

    manifest = as_dict

    def write_manifest(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class EvidenceImporter:
    """Small adapter for JSON/dict evidence feeds targeting one graph."""

    def __init__(self, graph: ExecutionOrderGraph) -> None:
        self.graph = graph

    def import_records(self, records: Iterable[EvidenceRecord | Mapping[str, Any]] | EvidenceRecord | Mapping[str, Any]) -> list[OrderEdge]:
        return self.graph.import_evidence(records)

    def import_json(self, path: str | Path) -> list[OrderEdge]:
        return self.graph.import_json(path)


def import_evidence(graph: ExecutionOrderGraph, records: Iterable[EvidenceRecord | Mapping[str, Any]] | EvidenceRecord | Mapping[str, Any]) -> list[OrderEdge]:
    return graph.import_evidence(records)


def load_evidence(path: str | Path, graph: ExecutionOrderGraph) -> list[OrderEdge]:
    return graph.import_json(path)


# Semantic aliases used by callers that prefer the shorter names.
PartialOrderGraph = ExecutionOrderGraph
ExecutionGraph = ExecutionOrderGraph


def default_required_gaps() -> tuple[RequiredGap, ...]:
    return (
        RequiredGap("brain-slot4", "CharacterAnimation.PreLateTick", "CharacterLimbIKBrain.Update", "vtable slot-4 target mapping is not recovered"),
        RequiredGap("animationstream-job", "AnimationScriptPlayable", "AnimationStream.ProcessAnimation", "native Job dispatch/evaluation callback is not recovered"),
        RequiredGap("renderer-consumption", "Animator pose output", "SkinnedMeshRenderer skin-matrix read", "renderer request/finish/read stage is not recovered"),
    )


def build_contract_graph(identity: EvidenceIdentity | None = None) -> ExecutionOrderGraph:
    return ExecutionOrderGraph.contract_graph(identity)
