"""验收数据契约（M1）。

依据《CodeArts Python 代码验收 Agent 工程实施方案》第 6 章。
Pydantic 校验的是结构与类型约束，不证明模型解释或结论正确。
模型 proposal 类型只承载候选内容，不开放受保护身份字段。
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- 枚举（3.2 状态维度） ----

JobStatus = Literal["COMPLETED", "PARTIAL", "FAILED"]
CodeVerdict = Literal["FAIL", "PASS_WITHIN_SCOPE", "INCONCLUSIVE"]
StageStatus = Literal["COMPLETED", "BLOCKED", "FAILED", "SKIPPED"]
RequirementStatus = Literal["FAIL", "PASS_WITHIN_SCOPE", "UNKNOWN"]
InterpretationStatus = Literal["AUTO_REVIEWED", "USER_CONFIRMED", "UNRESOLVED"]
EvidenceKind = Literal[
    "STATIC_FACT", "EXECUTED_CASE", "SYMBOLIC_COUNTEREXAMPLE",
    "FORMAL_PROOF", "MODEL_REVIEW",
]
AssuranceLevel = Literal["NONE", "TESTED", "EXHAUSTIVE_WITHIN_DOMAIN", "FORMALLY_VERIFIED"]
RelationToRequirement = Literal["NECESSARY", "SUFFICIENT", "EQUIVALENT", "UNKNOWN"]
OracleOrigin = Literal[
    "USER_EXAMPLE", "USER_CONFIRMED_RULE", "APPROVED_REFERENCE",
    "RULE_DERIVATION", "MODEL_HYPOTHESIS",
]
OracleReview = Literal["ACCEPTED_FOR_TESTING", "PENDING", "REJECTED"]
EvidencePhase = Literal["COMPILE", "IMPORT", "CALL", "ASSERT", "RUNNER"]
EvidenceStatus = Literal[
    "PASSED", "ASSERTION_FAILED", "TARGET_EXCEPTION", "HARNESS_ERROR",
    "ENV_ERROR", "TIMEOUT", "NOT_RUN", "SKIPPED",
]
RequirementKind = Literal["FUNCTIONAL", "EXCEPTION", "SIDE_EFFECT", "INTERFACE", "CONSTRAINT"]
RequirementOrigin = Literal["EXPLICIT", "DERIVED", "UNCLEAR"]
OraclePolicy = Literal["source_backed", "confirmed_only"]
PromptMappingStatus = Literal[
    "COVERED", "COVERED_BY_CONTEXT", "MISSING_FROM_VISIBLE_PROMPT",
    "CONFLICT", "AMBIGUOUS", "UNKNOWN",
]
SuggestionCategory = Literal["CORRECTNESS_FIX", "POTENTIAL_RISK", "PERFORMANCE", "READABILITY"]
RepairValidationStatus = Literal[
    "NOT_GENERATED", "UNVALIDATED", "FAILED",
    "PASSED_EXISTING_CHECKS", "INCONCLUSIVE",
]


# ---- 6.1 EvaluationRequest ----

class Entrypoint(StrictModel):
    module: str = "solution"
    callable: str

    @field_validator("module")
    @classmethod
    def _valid_module(cls, v: str) -> str:
        import re
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", v or ""):
            raise ValueError(f"非法模块名: {v!r}")
        return v


class GenerationContext(StrictModel):
    is_complete: Optional[bool] = None
    requirements_also_visible: Optional[bool] = None
    additional_messages: list[str] = Field(default_factory=list)


class TrustedExample(StrictModel):
    requirement_id: str
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    assertion: dict[str, Any]


class AcceptanceMaterials(StrictModel):
    trusted_examples: list[TrustedExample] = Field(default_factory=list)
    confirmed_spec_id: Optional[str] = None
    confirmed_spec_hash: Optional[str] = None
    approved_reference_id: Optional[str] = None


class EvaluateOptions(StrictModel):
    oracle_policy: OraclePolicy = "source_backed"
    generate_repair_candidate: bool = False
    enable_property_testing: bool = False
    enable_crosshair: bool = False
    max_requirements: int = 20
    max_cases: int = 40


class SupportingFile(StrictModel):
    path: str
    content: str

    @field_validator("path")
    @classmethod
    def _safe_path(cls, v: str) -> str:
        from pathlib import PurePosixPath
        p = PurePosixPath(v)
        if p.is_absolute() or ".." in p.parts or v.startswith("/") or "\\" in v:
            raise ValueError(f"辅助文件路径不合法: {v!r}")
        if not v.endswith(".py"):
            raise ValueError(f"仅支持 .py 辅助文件: {v!r}")
        return v


MAIN_MODULE_FILENAME = "solution.py"


class EvaluationRequest(StrictModel):
    requirement: str = Field(min_length=1, max_length=20000)
    generation_prompt: str = Field(default="", max_length=20000)
    code: str = Field(min_length=1, max_length=262144)
    supporting_files: list[SupportingFile] = Field(default_factory=list)
    entrypoint: Optional[Entrypoint] = None
    generation_context: GenerationContext = Field(default_factory=GenerationContext)
    acceptance_materials: AcceptanceMaterials = Field(default_factory=AcceptanceMaterials)
    options: EvaluateOptions = Field(default_factory=EvaluateOptions)

    @model_validator(mode="after")
    def _check_budget(self) -> "EvaluationRequest":
        if len(self.supporting_files) > 8:
            raise ValueError("辅助文件超过 8 个上限")
        total = len(self.code.encode("utf-8")) + sum(
            len(f.content.encode("utf-8")) for f in self.supporting_files
        )
        if total > 262144:
            raise ValueError("源码总量超过 256 KiB 上限")
        # 主代码写入 solution.py，辅助文件不得与其冲突（P0-4）
        normalized = [f.path.replace("\\", "/").lstrip("./") for f in self.supporting_files]
        for p in normalized:
            if p == MAIN_MODULE_FILENAME or p.endswith(f"/{MAIN_MODULE_FILENAME}"):
                raise ValueError(f"辅助文件不得覆盖主代码模块 {MAIN_MODULE_FILENAME}")
        if len(set(normalized)) != len(normalized):
            raise ValueError("存在重复的辅助文件路径")
        return self


# ---- 6.2 CanonicalSpec / RequirementItem ----

class RequirementItem(StrictModel):
    id: str
    statement: str
    kind: RequirementKind = "FUNCTIONAL"
    mandatory: bool = True
    origin: RequirementOrigin
    source_quote: str
    source_start: Optional[int] = None
    source_end: Optional[int] = None
    acceptance_intent: str = ""
    unresolved_questions: list[str] = Field(default_factory=list)
    derivation_basis: str = ""

    @model_validator(mode="after")
    def _origin_rules(self) -> "RequirementItem":
        if self.origin == "EXPLICIT" and not self.source_quote:
            raise ValueError("EXPLICIT 要求必须提供原文引用")
        if self.origin == "DERIVED" and not self.derivation_basis:
            raise ValueError("DERIVED 要求必须提供推导依据")
        return self


class InputDomainClause(StrictModel):
    description: str
    source_quote: str = ""
    origin: RequirementOrigin = "EXPLICIT"


class CanonicalSpec(StrictModel):
    spec_id: str
    spec_hash: str = ""
    revision: int = 1
    interpretation_status: InterpretationStatus = "UNRESOLVED"
    requirements: list[RequirementItem] = Field(default_factory=list)
    input_domain: list[InputDomainClause] = Field(default_factory=list)
    technical_constraints: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    requirement_text_digest: str = ""


# ---- 6.3 ContractSpec 与 CheckCase ----

class ArgTarget(StrictModel):
    kind: Literal["ARG", "KWARG"]
    index: Optional[int] = None
    name: Optional[str] = None

    @model_validator(mode="after")
    def _check(self) -> "ArgTarget":
        if self.kind == "ARG" and (self.index is None or self.index < 0):
            raise ValueError("ARG 目标必须提供非负 index")
        if self.kind == "KWARG" and not self.name:
            raise ValueError("KWARG 目标必须提供 name")
        return self


class PredicateSpec(StrictModel):
    op: Literal["IS_EVEN", "IS_NONNEGATIVE", "IS_POSITIVE", "IS_ODD", "IS_NONE"]
    value_type: Literal["int", "str", "bool", "float"] = "int"


class ReturnEqualsAssertion(StrictModel):
    kind: Literal["RETURN_EQUALS"]
    expected: Any


class ReturnIsNoneAssertion(StrictModel):
    kind: Literal["RETURN_IS_NONE"]


class RaisesAssertion(StrictModel):
    kind: Literal["RAISES"]
    exception_type: str
    message_contains: str = ""

    @field_validator("exception_type")
    @classmethod
    def _builtin_exc(cls, v: str) -> str:
        allowed = {
            "ValueError", "TypeError", "KeyError", "IndexError", "ZeroDivisionError",
            "ArithmeticError", "AttributeError", "LookupError", "AssertionError",
            "NotImplementedError", "OverflowError", "StopIteration", "RuntimeError",
        }
        if v not in allowed:
            raise ValueError(f"未登记的异常类型: {v!r}")
        return v


class InputUnchangedAssertion(StrictModel):
    kind: Literal["INPUT_UNCHANGED"]
    targets: list[ArgTarget] = Field(min_length=1)


class AllItemsMatchAssertion(StrictModel):
    kind: Literal["ALL_ITEMS_MATCH"]
    predicate: PredicateSpec
    element_type: Literal["int", "str", "bool", "float"] = "int"


class OrderedAssertion(StrictModel):
    kind: Literal["ORDERED"]
    direction: Literal["ASC", "DESC"]
    strict: bool = False
    key: Literal["IDENTITY"] = "IDENTITY"


class SameMultisetAssertion(StrictModel):
    kind: Literal["SAME_MULTISET"]
    against: ArgTarget


Assertion = Union[
    ReturnEqualsAssertion, ReturnIsNoneAssertion, RaisesAssertion,
    InputUnchangedAssertion, AllItemsMatchAssertion, OrderedAssertion,
    SameMultisetAssertion,
]


class ContractSpec(StrictModel):
    contract_id: str
    requirement_ids: list[str] = Field(min_length=1)
    description: str
    input_domain_ref: str = ""
    representation: str = ""
    relation_to_requirement: RelationToRequirement = "UNKNOWN"
    relation_basis: str = ""
    oracle_origin: OracleOrigin
    oracle_review: OracleReview = "PENDING"
    interpretation_status: InterpretationStatus = "UNRESOLVED"
    spec_hash: str = ""
    coverage_note: str = ""


class CheckCase(StrictModel):
    case_id: str
    contract_id: str
    requirement_ids: list[str] = Field(min_length=1)
    category: str = ""
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    assertion: Assertion
    expected_basis: str = ""
    input_domain_status: Literal["IN_SCOPE", "OUT_OF_SCOPE", "UNKNOWN"] = "IN_SCOPE"


class TestPlan(StrictModel):
    plan_id: str = ""
    plan_hash: str = ""
    revision: int = 1
    contracts: list[ContractSpec] = Field(default_factory=list)
    cases: list[CheckCase] = Field(default_factory=list)
    coverage_notes: list[str] = Field(default_factory=list)


# ---- 6.4 Evidence ----

def new_evidence_id() -> str:
    return f"EV-{uuid.uuid4().hex[:12]}"


class Evidence(StrictModel):
    evidence_id: str = Field(default_factory=new_evidence_id)
    kind: EvidenceKind
    producer: str
    code_hash: str = ""
    spec_hash: str = ""
    plan_hash: str = ""
    runtime_fingerprint: str = ""
    case_id: str = ""
    requirement_ids: list[str] = Field(default_factory=list)
    phase: EvidencePhase
    observation: dict[str, Any] = Field(default_factory=dict)
    status: EvidenceStatus
    artifact_refs: list[str] = Field(default_factory=list)
    duration_ms: Optional[float] = None
    output_truncated: bool = False
    technical_rule_version: str = ""


# ---- 10.2 PromptReport ----

class PromptMapping(StrictModel):
    requirement_id: str
    status: PromptMappingStatus
    requirement_quote: str
    prompt_quote: str = ""
    explanation: str = ""


class ExtraRequirement(StrictModel):
    content: str
    kind: Literal["BUSINESS", "TECHNICAL"]
    needs_user_confirmation: bool = True


class PromptChange(StrictModel):
    before: str
    after: str
    requirement_id: str
    reason: str


class PromptReport(StrictModel):
    mappings: list[PromptMapping] = Field(default_factory=list)
    extra_requirements: list[ExtraRequirement] = Field(default_factory=list)
    optimized_prompt: str = ""
    changes: list[PromptChange] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    optimization_validation: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"
    mode: Literal["LLM", "RULE_FALLBACK"] = "RULE_FALLBACK"
    prompt_code_relation: list[dict[str, str]] = Field(default_factory=list)


# ---- 11 CodeSuggestion ----

class CodeSuggestion(StrictModel):
    suggestion_id: str
    finding_id: str = ""
    requirement_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    category: SuggestionCategory
    location: str = ""
    trigger_condition: str = ""
    expected: str = ""
    actual: str = ""
    explanation: str = ""
    fix: str = ""
    regression_check: str = ""
    validation_status: Literal["SYSTEM_FILLED", "PENDING"] = "SYSTEM_FILLED"
    mode: Literal["LLM", "RULE_FALLBACK"] = "RULE_FALLBACK"


class RepairCandidate(StrictModel):
    candidate_hash: str
    code: str
    validation_status: RepairValidationStatus = "UNVALIDATED"
    checks_summary: dict[str, int] = Field(default_factory=dict)


# ---- 6.5 EvaluationReport ----

class RequirementResult(StrictModel):
    requirement_id: str
    statement: str
    status: RequirementStatus
    evidence_ids: list[str] = Field(default_factory=list)
    failed_case_ids: list[str] = Field(default_factory=list)
    explanation: str = ""
    assurance: AssuranceLevel = "NONE"


class StageResult(StrictModel):
    stage: str
    status: StageStatus
    detail: str = ""
    duration_ms: Optional[float] = None


class CoverageSummary(StrictModel):
    mandatory_requirements: int = 0
    requirements_checked: int = 0
    cases_planned: int = 0
    cases_executed: int = 0
    cases_passed: int = 0
    cases_failed: int = 0


class ReproducibilityInfo(StrictModel):
    code_hash: str
    spec_hash: str
    plan_hash: str
    runtime_fingerprint: str
    request_hash: str = ""


class EvaluationReport(StrictModel):
    schema_version: str = "1.0"
    evaluation_id: str = Field(default_factory=lambda: f"EVAL-{uuid.uuid4().hex[:12]}")
    created_at: float = Field(default_factory=time.time)
    job_status: JobStatus = "COMPLETED"
    code_verdict: CodeVerdict = "INCONCLUSIVE"
    assurance_level: AssuranceLevel = "NONE"
    spec_interpretation: InterpretationStatus = "UNRESOLVED"
    summary: str = ""
    requirement_results: list[RequirementResult] = Field(default_factory=list)
    prompt_report: PromptReport = Field(default_factory=PromptReport)
    code_suggestions: list[CodeSuggestion] = Field(default_factory=list)
    repair_candidate: Optional[RepairCandidate] = None
    evidence: list[Evidence] = Field(default_factory=list)
    coverage: CoverageSummary = Field(default_factory=CoverageSummary)
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    stage_results: list[StageResult] = Field(default_factory=list)
    reproducibility: Optional[ReproducibilityInfo] = None
    isolation_level: str = ""