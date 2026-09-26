"""Evidence-gated resource pose contracts for Endfield animation reconstruction.

This module is deliberately a data contract, not an evaluator or importer.  A field is
usable only when its source, reader, formula, and output space are all recorded.  Missing
runtime edges are represented as GAP records and gate the dependent compilation path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .diagnostics import DiagnosticEvent, info, warning

SCHEMA = "endfield.animation.runtime-contract.resource-semantics.v1"
CLOSED = "closed"
GAP = "gap"


class ContractValidationError(ValueError):
    """Raised when an evidence contract is incomplete or internally inconsistent."""


def _warn(code: str, message: str, **context: Any) -> None:
    """Keep validation warnings structured while preserving the existing exception API."""
    warning(code, message, **context)


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    kind: str
    source: str
    reader: str
    formula: str
    output_space: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.kind not in {
            "serialized-field", "direct-call", "vtable", "formula",
            "serialized-order", "runtime-observed", "engine-gap",
        }:
            _warn("INVALID_EVIDENCE_KIND", "evidence record rejected", evidence_id=self.evidence_id, kind=self.kind)
            raise ContractValidationError(f"unknown evidence kind: {self.kind}")
        if not self.evidence_id.strip():
            _warn("INVALID_EVIDENCE_ID", "evidence record rejected: id is empty")
            raise ContractValidationError("evidence_id is required")

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.evidence_id,
            "kind": self.kind,
            "source": self.source,
            "reader": self.reader,
            "formula": self.formula,
            "output_space": self.output_space,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceRecord":
        try:
            return cls(
                evidence_id=str(value.get("id", value.get("evidence_id", ""))),
                kind=str(value["kind"]), source=str(value.get("source", "")),
                reader=str(value.get("reader", "")), formula=str(value.get("formula", "")),
                output_space=str(value.get("output_space", "")), detail=str(value.get("detail", "")),
            )
        except ContractValidationError:
            raise
        except (KeyError, TypeError, AttributeError) as exc:
            _warn("INVALID_EVIDENCE_RECORD", "serialized evidence record rejected", error=str(exc))
            raise ContractValidationError("invalid serialized evidence record") from exc


@dataclass(frozen=True)
class FieldContract:
    field_id: str
    bucket: str
    source_fields: tuple[str, ...]
    reader: str
    formula: str
    output_space: str
    evidence_ids: tuple[str, ...]
    status: str = CLOSED
    notes: str = ""

    def __post_init__(self) -> None:
        if self.status not in {CLOSED, GAP}:
            _warn("INVALID_FIELD_STATUS", "field record rejected", field_id=self.field_id, status=self.status)
            raise ContractValidationError(f"invalid field status: {self.status}")
        if not self.field_id.strip() or not self.bucket.strip():
            _warn("INVALID_FIELD_ID", "field record rejected", field_id=self.field_id)
            raise ContractValidationError("field_id and bucket are required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.field_id,
            "bucket": self.bucket,
            "source_fields": list(self.source_fields),
            "reader": self.reader,
            "formula": self.formula,
            "output_space": self.output_space,
            "evidence_ids": list(self.evidence_ids),
            "status": self.status,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FieldContract":
        return cls(
            field_id=str(value.get("id", value.get("field_id", ""))),
            bucket=str(value["bucket"]),
            source_fields=tuple(str(x) for x in value.get("source_fields", ())),
            reader=str(value.get("reader", "")), formula=str(value.get("formula", "")),
            output_space=str(value.get("output_space", "")),
            evidence_ids=tuple(str(x) for x in value.get("evidence_ids", ())),
            status=str(value.get("status", CLOSED)), notes=str(value.get("notes", "")),
        )


@dataclass(frozen=True)
class GapRecord:
    gap_id: str
    area: str
    missing: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
    required: bool = True
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.gap_id,
            "area": self.area,
            "missing": list(self.missing),
            "evidence_ids": list(self.evidence_ids),
            "required": self.required,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GapRecord":
        return cls(
            gap_id=str(value.get("id", value.get("gap_id", ""))),
            area=str(value["area"]), missing=tuple(str(x) for x in value.get("missing", ())),
            evidence_ids=tuple(str(x) for x in value.get("evidence_ids", ())),
            required=bool(value.get("required", True)), reason=str(value.get("reason", "")),
        )


@dataclass(frozen=True)
class GateResult:
    module: str
    enabled: bool
    required_gap_ids: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()
    message: str = ""
    diagnostic: DiagnosticEvent | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "enabled": self.enabled,
            "required_gap_ids": list(self.required_gap_ids),
            "blocked_by": list(self.blocked_by),
            "message": self.message,
            "diagnostic": None if self.diagnostic is None else self.diagnostic.to_dict(),
        }


@dataclass
class ResourcePoseContract:
    evidence: list[EvidenceRecord] = field(default_factory=list)
    fields: list[FieldContract] = field(default_factory=list)
    gaps: list[GapRecord] = field(default_factory=list)
    schema: str = SCHEMA
    version: int = 1
    diagnostic: DiagnosticEvent | None = field(default=None, repr=False, compare=False)

    def validate(self) -> DiagnosticEvent:
        if self.schema != SCHEMA:
            _warn("INVALID_SCHEMA", "resource contract rejected: schema mismatch", schema=self.schema)
            raise ContractValidationError(f"schema mismatch: {self.schema}")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            _warn("DUPLICATE_EVIDENCE", "resource contract rejected: duplicate evidence id")
            raise ContractValidationError("duplicate evidence id")
        field_ids = [item.field_id for item in self.fields]
        if len(field_ids) != len(set(field_ids)):
            _warn("DUPLICATE_FIELD", "resource contract rejected: duplicate field id")
            raise ContractValidationError("duplicate field id")
        gap_ids = [item.gap_id for item in self.gaps]
        if len(gap_ids) != len(set(gap_ids)):
            _warn("DUPLICATE_GAP", "resource contract rejected: duplicate GAP id")
            raise ContractValidationError("duplicate gap id")
        known = set(evidence_ids)
        for item in self.fields:
            missing_evidence = set(item.evidence_ids) - known
            if missing_evidence:
                _warn("MISSING_FIELD_EVIDENCE", "field references missing evidence", field_id=item.field_id, missing=sorted(missing_evidence))
                raise ContractValidationError(
                    f"{item.field_id} references missing evidence: {sorted(missing_evidence)}"
                )
            if item.status == CLOSED:
                missing_parts = [name for name, value in (
                    ("reader", item.reader), ("formula", item.formula),
                    ("output_space", item.output_space),
                ) if not value.strip()]
                if missing_parts:
                    _warn("INCOMPLETE_CLOSED_FIELD", "closed field lacks required decision data", field_id=item.field_id, missing=missing_parts)
                    raise ContractValidationError(
                        f"closed field {item.field_id} lacks {', '.join(missing_parts)}"
                    )
                if not item.evidence_ids:
                    _warn("CLOSED_FIELD_NO_EVIDENCE", "closed field has no evidence", field_id=item.field_id)
                    raise ContractValidationError(f"closed field {item.field_id} has no evidence")
        for gap in self.gaps:
            if not gap.gap_id.strip() or not gap.area.strip() or not gap.missing:
                _warn("INCOMPLETE_GAP", "GAP record is incomplete", gap_id=gap.gap_id)
                raise ContractValidationError(f"incomplete GAP record: {gap.gap_id!r}")
            if set(gap.evidence_ids) - known:
                _warn("MISSING_GAP_EVIDENCE", "GAP references missing evidence", gap_id=gap.gap_id)
                raise ContractValidationError(f"GAP {gap.gap_id} references missing evidence")
        event = info("CONTRACT_VALIDATED", "resource contract validated", fields=len(self.fields), gaps=len(self.gaps), evidence=len(self.evidence))
        self.diagnostic = event
        return event

    def gate(self, module: str, required_gap_ids: Iterable[str] = ()) -> GateResult:
        """Return an explicit compile gate; unresolved required gaps keep a module disabled."""
        self.validate()
        requested = tuple(dict.fromkeys(str(x) for x in required_gap_ids))
        known_gaps = {item.gap_id: item for item in self.gaps}
        blocked = tuple(item for item in requested if item not in known_gaps or known_gaps[item].required)
        if blocked:
            event = warning("GATE_BLOCKED", "module disabled: required evidence GAP remains unresolved", module=module, blocked_by=list(blocked))
            return GateResult(
                module=module, enabled=False, required_gap_ids=requested, blocked_by=blocked,
                message="module disabled: required evidence GAP remains unresolved",
                diagnostic=event,
            )
        event = info("GATE_ENABLED", "module enabled: no required GAP selected", module=module)
        return GateResult(
            module=module, enabled=True, required_gap_ids=requested,
            message="module enabled: no required GAP selected",
            diagnostic=event,
        )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "version": self.version,
            "evidence": [item.to_dict() for item in self.evidence],
            "fields": [item.to_dict() for item in self.fields],
            "gaps": [item.to_dict() for item in self.gaps],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResourcePoseContract":
        if not isinstance(value, Mapping):
            _warn("INVALID_CONTRACT_DATA", "serialized resource contract must be an object")
            raise ContractValidationError("resource contract must be an object")
        result = cls(
            schema=str(value.get("schema", "")), version=int(value.get("version", 1)),
            evidence=[EvidenceRecord.from_dict(x) for x in value.get("evidence", ())],
            fields=[FieldContract.from_dict(x) for x in value.get("fields", ())],
            gaps=[GapRecord.from_dict(x) for x in value.get("gaps", ())],
        )
        result.validate()
        return result

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    @classmethod
    def loads(cls, text: str) -> "ResourcePoseContract":
        try:
            value = json.loads(text)
        except (TypeError, json.JSONDecodeError) as exc:
            _warn("LOAD_REJECTED", "resource contract JSON rejected", error=str(exc))
            raise ContractValidationError("invalid resource contract JSON") from exc
        result = cls.from_dict(value)
        result.diagnostic = info("CONTRACT_LOADED", "resource contract loaded from serialized data", fields=len(result.fields), gaps=len(result.gaps))
        return result

    def save(self, path: str | Path) -> DiagnosticEvent:
        Path(path).write_text(self.dumps(), encoding="utf-8")
        event = info("CONTRACT_SAVED", "resource contract persisted", path=str(path))
        self.diagnostic = event
        return event

    @classmethod
    def load(cls, path: str | Path) -> "ResourcePoseContract":
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            _warn("LOAD_REJECTED", "resource contract file could not be read", path=str(path), error=str(exc))
            raise ContractValidationError(f"resource contract load failed: {path}") from exc
        result = cls.loads(text)
        event = info("CONTRACT_LOADED", "resource contract loaded from file", path=str(path))
        result.diagnostic = event
        return result


def build_resource_pose_contract() -> ResourcePoseContract:
    """Build the evidence-linked R1 baseline from checked-in source/artifact anchors."""
    ev = [
        EvidenceRecord("E-SER-ACL-BUFFERS", "serialized-field",
            "tools/Ruri-RipperHook/.../EndfieldCapabilities.cs:369-555",
            "ProbeEndfieldAcl/ProbeRootAcl", "TypeTree field extraction; buffer bytes preserved",
            "serialized AnimationClip resource fields", "m_TransformBufferData, m_FloatBufferData, m_RootMotionBufferData"),
        EvidenceRecord("E-FORM-ACL-QVVF", "formula",
            "tools/Ruri-RipperHook/Source/Ruri.ACL/AclCompressedTracks.cs:65-840",
            "AclCompressedTracks.DecompressTransforms", "bit normalization, min+value*extent, quaternion W reconstruction, normalized lerp",
            "clip-local per-track Q/V/S", "QVVF header track type 12"),
        EvidenceRecord("E-FORM-ACL-FLOAT", "formula",
            "tools/Ruri-RipperHook/Source/Ruri.ACL/AclCompressedTracks.cs:680-840",
            "AclCompressedTracks.DecompressFloats", "Float1F 32-bit/raw or normalized bit value, range remap, linear interpolation",
            "clip-time scalar; binding supplies property meaning", "Float1F track type 0"),
        EvidenceRecord("E-SER-CONSTANTS", "serialized-field",
            "tools/Ruri-RipperHook/.../EndfieldCapabilities.cs:537-555",
            "ClipCurveBlob.TryBuildEndfieldAcl", "constant index consumes binding dimensions; constant supersedes sampled value",
            "binding property space", "m_ConstantIndexs/m_ConstantValues/m_DefaultIndexs"),
        EvidenceRecord("E-SER-BINDINGS", "serialized-field",
            "tools/Ruri-RipperHook/.../ClipCurveBlob.cs:330-462",
            "ClipCurveBlob.TryBuildEndfieldAcl", "Transform lists grouped by class/attribute; rotation joined to position by path; scalar order follows binding order",
            "Unity clip binding path/property space", "GenericBindings and AnimatorMuscle custom type"),
        EvidenceRecord("E-FORM-ROOT-MUSCLE", "formula",
            "tools/Ruri-RipperHook/.../RootChannelPlan.cs:3-29; AvatarMuscleReferential.cs:205-363",
            "RootChannelPlan.Bind/Read; AvatarMuscleReferential.BodyTransform",
            "fullT=RootT; rootTSimple=fullT-motionT; rootQ=inverse(motionQ)*fullQ; hips FK/mass-center solve",
            "custom Unity/C# body/hips referential", "RootT/RootQ/MotionT/MotionQ"),
        EvidenceRecord("E-FORM-MUSCLE", "formula",
            "tools/Ruri-RipperHook/.../AvatarMuscleReferential.cs:205-235,509-523",
            "AvatarMuscleReferential.BodyLocalQuats/LocalRotation",
            "angle=Sgn*m*(m>=0 ? LimitMax : -LimitMin); tangent swing-twist; PreQ*swing*inverse(PostQ)",
            "solver bone-local quaternion", "95 muscle DOF table and MuscleBone referential"),
        EvidenceRecord("E-SER-DELTAPOSE-TREE", "serialized-field",
            "artifacts/animation-chain/required-clips-export.log:81-320",
            "TypeTree animation-tree logger only", "m_DeltaPose is typed HumanPose with RootX, LookAt, GoalArray, hand-pose, DoFArray and TDoFArray children; no evaluator edge recovered",
            "unknown HumanPose/goal space", "TypeTree structure is observed; unmapped-owner diagnostics remain in the same export"),
        EvidenceRecord("E-SER-ROOT-TYPE-V02", "serialized-field",
            "docs/animation/V02_BUFFERS_MASKS.md:94-105,326-339",
            "ClipCurveBlob.TryBuildEndfieldAcl; V02 capture/analyze probes",
            "one captured sample has a 28-value root-motion prefix equal to the Float bucket; the same relation is not universal (205/479 clips have root tracks greater than float curves)",
            "decoded scalar bucket; runtime root application space unknown",
            "RootMotion=Float is a sample-level relation only; no dedicated resource consumer or general mapping is established"),
        EvidenceRecord("E-STATIC-IK-HASH-PREFIX", "serialized-field",
            "D:/Programs/blender-5.2.0-git.89ec05ff-windows64/tools/endfield_reverse/agent_reports/rigging_graph_semantics/rigging_graph_semantics.md:317-357; static_string_globals.txt; output/methods_runtime_all.csv",
            "BipedIKRigging static cctor/StringToHash and get_ikCurveHashes/get_footLockCurveHashes inventory",
            "static construction of IK and foot-lock hash arrays is observed; exact suffix arrays, AnimationStream property read, and threshold/application formula are not recovered",
            "hash/name identity only; IK goal/property output space unknown",
            "Prefixes observed: fOutFootIKWeight_ and fOutFootIKLockEnable_; this does not close float-to-property binding"),
        EvidenceRecord("E-DIRECT-IK-FLOAT-READER", "direct-call",
            "D:/Programs/blender-5.2.0-git.89ec05ff-windows64/tools/endfield_reverse/agent_reports/render_phase_boundary/render_phase_ida_decompiled.json:1447-1554; output/methods_runtime_all.csv:55661,433006",
            "IKRiggingBase.LateTick (0x5FA402C) -> IKRiggingBase._UpdateFootLockStateAndPush (0x5FA6D24) -> UnityEngine.Animator.GetFloatID (0x388C310)",
            "LateTick indexes per-limb curve-hash arrays; _UpdateFootLockStateAndPush calls Animator.GetFloatID(hash) and passes the returned scalar into _TickFootLockStateMachine. The same LateTick body reads the companion IK hash array through Animator.GetFloatID; its scalar consumer is not identified by the decompiler output.",
            "Animator float scalar consumed by FootLock state machine; IK scalar consumer/output space unresolved",
            "Runtime reader and call edge are closed for FootLock. This is not an ACL m_FloatBufferData producer edge, and exact suffix/hash values remain unresolved."),
        EvidenceRecord("E-R1E-FLOAT-TRACK-EXPORT", "serialized-field",
            "docs/animation/evidence/v02-attack01-recheck01/effective-floats.tsv; v02-capture03/effective-floats.tsv; v02-capture06/effective-floats.tsv; v02-capture07/effective-floats.tsv; v02-fixture-defaults01/effective-floats.tsv; artifacts/animation-chain/typhoea-controller-with-masks.json",
            "R1-E float-binding identity scanner",
            "754 exported scalar rows preserve bindingIndex/path/attribute/classId/customType/name identity; 39 rows carry anonymous hash_0x... labels and zero rows carry exact fOutFootIKWeight_* or fOutFootIKLockEnable_* names. Two historical property-hash logs preserve 16 CustomType=0 rows (including an unverified FootIKWeight candidate), while controller export carries zero target property names/hashes.",
            "exported AnimationClip scalar-track identity; property join unresolved",
            "Real exports contain AnimatorMuscle names and anonymous hash labels, not the BipedIK target property identity. Missing names, collisions, and unmatched rows are retained in r1_e_float_binding_ledger_2026-09-12.json."),
        EvidenceRecord("E-R1F-SER-POSE-METADATA", "serialized-field",
            "artifacts/animation-chain/required-clips-export.log:81-263, 439-481; docs/animation/evidence/runtime-contract-r1/r1_f_serialized_pose_ledger_2026-09-12.json",
            "Endfield TypeTree AnimationTree logger plus EndfieldCapabilities.LogMuscleArraySummary",
            "AnimationClip tree contains m_DeltaPose/HumanPose, m_ValueArrayDelta<ValueDelta Start/Stop>, m_ValueArrayReferencePose<float>, StartX/StopX and KeepOriginal flags. Real additive clips expose delta=2768 and reference=2768 values; the probe reads counts and reference head values.",
            "serialized MuscleClip HumanPose/reference metadata; evaluator space unresolved",
            "Field presence and serialized paths are closed; no resource caller or composition consumer is established."),
        EvidenceRecord("E-R1F-ROOT-ACL-READER", "serialized-field",
            "artifacts/animation-chain/required-clips-export.log:264-324, 439-481; D:/Programs/blender-5.2.0-git.89ec05ff-windows64/tools/Ruri-RipperHook/Source/Ruri.RipperHook/AssetRipperGameHook/Endfield/EndfieldCapabilities.cs:529-570",
            "EndfieldCapabilities.ProbeRootAcl",
            "TypeTree m_AclCompressedBuffer contains m_RootMotionBufferData as a byte vector; ProbeRootAcl selects a decoder and reports root bytes/tracks/samples. This is a diagnostic reader, not a final pose application.",
            "serialized ACL root-motion scalar bucket; runtime output space unknown",
            "Root bytes are present in real captures, while the production bridge path remains separate."),
        EvidenceRecord("E-R1F-CONVERTER-AUDIT", "direct-call",
            "D:/Programs/blender-5.2.0-git.89ec05ff-windows64/tools/Ruri-RipperHook/Source/Ruri.RipperHook/Utils/Bridge/ClipCurveBlob.cs:202-207,304-311,432-463; .../Utils/Humanoid/HumanoidClipGenericizer.cs:173-179,288-319",
            "ClipCurveBlob.Build/TryBuildEndfieldAcl; HumanoidClipGenericizer.Convert/CollectMuscleChannels",
            "TryBuildEndfieldAcl reads m_TransformBufferData and m_FloatBufferData, maps scalar bindings and constants, and does not read m_RootMotionBufferData, m_DeltaPose, m_ValueArrayDelta or m_ValueArrayReferencePose. Humanoid genericization consumes FloatCurves_C74 root/muscle attributes and KeepOriginal flags only.",
            "converter output curves; dedicated root/reference consumer absent",
            "Reader/consumer audit narrows the missing edges but provides no additive or root application formula."),
        EvidenceRecord("E-R1F-AVATAR-REFERENTIAL-READER", "serialized-field",
            "D:/Programs/blender-5.2.0-git.89ec05ff-windows64/tools/Ruri-RipperHook/Source/Ruri.RipperHook/Utils/Humanoid/AvatarRigInput.cs:45-117,174-223; .../Utils/Humanoid/AvatarMuscleReferential.cs:85-162",
            "AvatarRigInput.FromAvatar/TryCreateFromDocument -> AvatarMuscleReferential.TryCreate",
            "Avatar m_Human/m_Skeleton/m_SkeletonPose/m_AxesArray/m_HumanBoneIndex/m_HumanBoneMass are read into the referential input; this is a skeleton/muscle mapping reader, not a DeltaPose/reference-pose evaluator.",
            "Avatar skeleton referential and muscle limits",
            "Source API path is present; target Avatar object identity/payload is not joined in the clip export."),
        EvidenceRecord("E-R1G-POSE-PAYLOAD-LAYOUT", "serialized-field",
            "docs/animation/evidence/runtime-contract-r1/r1_g_pose_payload_ledger_2026-09-12.json; artifacts/animation-chain/required-clips-export.log:81-320",
            "R1-G read-only TypeTree layout indexer; EndfieldCapabilities.LogMuscleArraySummary",
            "HumanPose leaf order and vector element widths are recorded without assigning semantic counts; ValueDelta is 2x float32 and reference pose is float32. The coordinator-reported 2,056-byte DeltaPose and 4,792-byte reference payload have no standalone raw field-offset capture.",
            "serialized payload layout only; HumanPose/reference output space unknown",
            "No byte offset is promoted for the two reported payload sizes; all unresolved evaluator and additive edges remain GAP."),
        EvidenceRecord("E-R1G-ROOT-PAYLOAD-LAYOUT", "serialized-field",
            "docs/animation/evidence/runtime-contract-r1/r1_g_pose_payload_ledger_2026-09-12.json; docs/animation/evidence/v02-capture07/m_RootMotionBufferData.bin; .../raw-fields.json",
            "Ruri.ACL.AclCompressedTracks constructor; EndfieldCapabilities.ProbeRootAcl",
            "Real 11,472-byte root vector parses at offsets 0..48: wire metadata, ACL tag/version/type, 28 tracks, 301 samples, 60Hz, Float1F body offsets. These fields identify the decoder only; no root property mapping or application formula is present.",
            "decoded ACL scalar tracks; root application space unknown",
            "Layout and decoder boundary are closed; dedicated consumer/order/space remains a required GAP."),
        EvidenceRecord("E-R1G-READER-CONTRACT-AUDIT", "direct-call",
            "D:/Programs/blender-5.2.0-git.89ec05ff-windows64/tools/Ruri-RipperHook/Source/Ruri.RipperHook/AssetRipperGameHook/Endfield/EndfieldCapabilities.cs:426-550; .../Utils/Bridge/ClipCurveBlob.cs:202-311; .../Core/TypeTree/TypeTreeReadPlan.cs:96-129",
            "ProbeEndfieldAcl/LogMuscleArraySummary/ProbeRootAcl; ClipCurveBlob.TryBuildEndfieldAcl; TypeTreeReadPlan",
            "The diagnostic reader accesses MuscleClip_C74 counts and RootMotion bytes. The production bridge consumes Transform/Float buffers only, while ownerless TypeTree nodes are discarded unless captured. No HumanPose evaluator, additive composition, or root application call edge was recovered.",
            "reader boundary and discard boundary; evaluator output space unknown",
            "Reader evidence is sufficient to retain field presence and byte boundaries, not to close runtime semantics."),
        EvidenceRecord("E-R1H-CROSS-RESOURCE-JOIN", "direct-call",
            "docs/animation/evidence/runtime-contract-r1/r1_h_cross_resource_identity_ledger_2026-09-12.json; docs/animation/evidence/runtime-contract-r2/typhoea-r2g-owner-graph-ledger.json; tools/endfield_reverse/agent_reports/ik_rigging_static/ik_annotated.txt",
            "R1-H cross-resource identity indexer; IKRiggingBase.LateTick/_UpdateFootLockStateAndPush",
            "R2-G closes the same-CAB GrounderBipedIK -> BipedIK -> owner-root Animator identity, and static code closes LateTick -> _UpdateFootLockStateAndPush -> Animator.GetFloatID with hash=*(uint32*)(v8 + 4*index + 32). Clip float rows remain unjoined to this Animator/time; cctor numeric outputs and target property names are absent.",
            "Animator scalar input to FootLock state machine; final IK goal/property space unknown",
            "All 754 export rows, 39 anonymous hashes, metadata hashes, and collision/repetition records are retained; GAP is intentionally preserved."),
        EvidenceRecord("E-GAP-ROOT-CONSUMER", "engine-gap",
            "docs/animation/V02_BUFFERS_MASKS.md:94-105,326-339; GameAssembly.dll + methods_runtime_all.csv; EndfieldCapabilities.cs:531-547",
            "ProbeRootAcl; runtime method inventory only", "dedicated root ACL consumer and application sequence not recovered",
            "unknown", "m_RootMotionBufferData, rootMotionCurve setters, EnableMontageRootMotion"),
        EvidenceRecord("E-GAP-HUMANPOSE", "engine-gap",
            "methods_runtime_all.csv (HumanPoseHandler methods); artifacts/animation-chain/required-clips-export.log:81-320",
            "method presence inventory; no clip caller", "resource-to-HumanPose/DeltaPose/reference-pose call chain not recovered",
            "unknown", "HumanPoseHandler.GetHumanPose exists; serialized m_DeltaPose tree exists but is not joined to clip buffers"),
        EvidenceRecord("E-GAP-ADDITIVE", "engine-gap",
            "docs/.../typhoea-controller-with-masks.json; controller graph", "controller parser only",
            "blendMode=1 is observed; reference pose/time and exact composition are not recovered",
            "unknown", "A_actor_typhoea_idle_loop_additive and additive layers"),
        EvidenceRecord("E-GAP-MASKS", "engine-gap",
            "EndfieldCapabilities.cs:537-552; controller graph bodyMask words", "byte/word probe only",
            "serialized mask bit/lane map to evaluator channels not recovered", "unknown", "m_TransformSubTrackMasks and BodyMask.Word0/1/2"),
        EvidenceRecord("E-GAP-FLOAT-PROPERTY", "engine-gap",
            "methods_runtime_all.csv (BipedIKRigging/FootLockData); render_phase_boundary/render_phase_ida_decompiled.json:1447-1554",
            "runtime hash reader is found, but no ACL float producer edge or exact IK scalar consumer is joined",
            "FootLock receives Animator.GetFloatID(hash) and enters its state machine; ACL binding, exact hash suffixes, IK scalar use, and final goal/property space remain unresolved",
            "FootLock state-machine input scalar only; IK goal/property output space unknown",
            "The direct runtime reader evidence narrows the gap but does not close the R1 float-property contract."),
    ]
    fields = [
        FieldContract("transform.qvvf", "transform", ("m_TransformBufferData",),
            "AclDecompressor/AclCompressedTracks.DecompressTransforms",
            "QVVF subtracks: identity, constant, or animated bit/range decode then interpolation",
            "clip-local per-track Q/V/S", ("E-SER-ACL-BUFFERS", "E-FORM-ACL-QVVF", "E-SER-BINDINGS")),
        FieldContract("float.float1f", "float", ("m_FloatBufferData",),
            "AclFloatDecompressor/AclCompressedTracks.DecompressFloats",
            "Float1F range/bit decode and linear interpolation",
            "clip-time scalar; property meaning is binding-defined", ("E-SER-ACL-BUFFERS", "E-FORM-ACL-FLOAT", "E-SER-BINDINGS")),
        FieldContract("float.constants", "float", ("m_ConstantIndexs", "m_ConstantValues", "m_DefaultIndexs"),
            "ClipCurveBlob.TryBuildEndfieldAcl",
            "indexed constants consume Transform dimensions 3/4 or scalar dimension 1 and override samples",
            "binding-declared property space", ("E-SER-CONSTANTS", "E-SER-BINDINGS")),
        FieldContract("root.float.channels", "root", ("RootT", "RootQ", "MotionT", "MotionQ"),
            "RootChannelPlan + AvatarMuscleReferential.BodyTransform",
            "full root split from motion; hips transform solved from provisional FK and mass center",
            "custom Unity/C# body/hips referential", ("E-FORM-ROOT-MUSCLE", "E-SER-BINDINGS")),
        FieldContract("muscle.avatar.referential", "muscle", ("AnimatorMuscle", "95 muscle DOF"),
            "AvatarMuscleReferential.BodyLocalQuats",
            "signed muscle limits to tangent swing-twist quaternion with PreQ/PostQ",
            "solver bone-local quaternion", ("E-FORM-MUSCLE", "E-SER-BINDINGS")),
    ]
    gaps = [
        GapRecord("gap.root.dedicated-consumer", "dedicated root ACL", ("reader", "formula", "output_space", "application_order"), ("E-SER-ROOT-TYPE-V02", "E-R1F-ROOT-ACL-READER", "E-R1G-ROOT-PAYLOAD-LAYOUT", "E-R1G-READER-CONTRACT-AUDIT", "E-R1F-CONVERTER-AUDIT", "E-GAP-ROOT-CONSUMER"), reason="RootMotion bytes and a decoder header/layout are present; no dedicated application consumer/order/space is joined."),
        GapRecord("gap.humanpose-delta-reference", "HumanPose/DeltaPose/reference pose", ("resource caller", "delta formula", "reference pose/time", "output_space"), ("E-SER-DELTAPOSE-TREE", "E-R1F-SER-POSE-METADATA", "E-R1G-POSE-PAYLOAD-LAYOUT", "E-R1G-READER-CONTRACT-AUDIT", "E-R1F-CONVERTER-AUDIT", "E-GAP-HUMANPOSE"), reason="HumanPose field order and reported payload sizes are recorded, but raw field offsets, evaluator caller, delta formula, reference time and output space are still missing."),
        GapRecord("gap.additive-reference", "additive composition", ("reference pose", "reference time", "composition formula", "output_space"), ("E-R1F-SER-POSE-METADATA", "E-R1G-POSE-PAYLOAD-LAYOUT", "E-R1G-READER-CONTRACT-AUDIT", "E-R1F-CONVERTER-AUDIT", "E-GAP-ADDITIVE"), reason="Additive clips carry nonzero ValueArrayReferencePose and its float layout is recorded; resource-to-layer composition consumer, time and output space are absent."),
        GapRecord("gap.serialized-mask-semantics", "ConstantMask/SubTrackMask/BodyMask", ("bit lane map", "runtime reader", "composition formula", "output_space"), ("E-R1G-READER-CONTRACT-AUDIT", "E-GAP-MASKS")),
        GapRecord("gap.float-property-binding", "Float to IK/FootLock/runtime properties", ("ACL producer binding", "exact hash/name binding", "IK scalar consumer", "threshold/application formula", "goal/property space"), ("E-STATIC-IK-HASH-PREFIX", "E-DIRECT-IK-FLOAT-READER", "E-R1E-FLOAT-TRACK-EXPORT", "E-R1G-READER-CONTRACT-AUDIT", "E-R1H-CROSS-RESOURCE-JOIN", "E-GAP-FLOAT-PROPERTY")),
    ]
    result = ResourcePoseContract(evidence=ev, fields=fields, gaps=gaps)
    result.validate()
    return result


def gate_module(contract: ResourcePoseContract, module: str, required_gap_ids: Iterable[str]) -> dict[str, Any]:
    """JSON-compatible gate helper used by downstream compilers."""
    return contract.gate(module, required_gap_ids).to_dict()


def compile_resource_module(contract: ResourcePoseContract, module: str, required_gap_ids: Iterable[str]) -> dict[str, Any]:
    """Return a compile decision; gated modules have no fallback payload."""
    result = contract.gate(module, required_gap_ids)
    diagnostic = result.diagnostic.to_dict() if result.diagnostic else None
    if not result.enabled:
        return {"status": "disabled", "gate": result.to_dict(), "operations": [], "diagnostic": diagnostic}
    return {"status": "ready", "gate": result.to_dict(), "operations": ["resource-fields-only"], "diagnostic": diagnostic}
