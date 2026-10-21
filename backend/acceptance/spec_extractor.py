"""需求提取（M2，方案 12.3 阶段 B）。

仅根据 requirements_text 和明确提供的技术要求提取验收项；
不从 C 的当前实现倒推用户想要的行为。
LLM 输出的 source_quote 必须确实来自 R（程序校验，A21 防伪造）。
"""
from __future__ import annotations

from typing import Optional

from backend.acceptance import llm_provider
from backend.acceptance.models import (
    CanonicalSpec,
    CheckCase,
    Entrypoint,
    RequirementItem,
    RequirementOrigin,
    TestPlan,
)
from backend.logger import get_logger

logger = get_logger("spec_extractor")

EXTRACT_TASK = """仅根据 requirements_text 和明确提供的技术要求提取验收项。
将输入域、返回值、分支、边界、异常、副作用等拆为可检查的要求。
每条区分 EXPLICIT、DERIVED、UNCLEAR，并保留原文与推导依据。
不参考当前实现来补全业务规则。
需求没有要求的防御性处理只可列为可选建议。
输出 requirements、input_domain、technical_constraints、
unresolved_questions 以及建议的输入类别。

输出 JSON 结构：
{
  "requirements": [{
    "id": "R1", "statement": "...", "kind": "FUNCTIONAL|EXCEPTION|SIDE_EFFECT|INTERFACE|CONSTRAINT",
    "mandatory": true, "origin": "EXPLICIT|DERIVED|UNCLEAR",
    "source_quote": "必须逐字来自 requirements_text 的原文片段",
    "acceptance_intent": "...", "unresolved_questions": [],
    "derivation_basis": "origin 为 DERIVED 时必填"
  }],
  "input_domain": [{"description": "...", "source_quote": "...", "origin": "EXPLICIT"}],
  "technical_constraints": ["..."],
  "unresolved_questions": ["..."],
  "suggested_categories": ["EMPTY", "BOUNDARY", "NEGATIVE"]
}"""


class SpecExtractionResult:
    def __init__(self, spec: Optional[CanonicalSpec], mode: str, error: str = ""):
        self.spec = spec
        self.mode = mode  # LLM | UNAVAILABLE
        self.error = error


def extract_spec(requirement: str, entrypoint: Optional[Entrypoint]) -> SpecExtractionResult:
    """从 R 提取候选规格。LLM 不可用时返回 None（业务验收将 INCONCLUSIVE）。"""
    payload = {
        "requirements_text": requirement,
        "technical_requirements": (
            [{"module": entrypoint.module, "callable": entrypoint.callable}]
            if entrypoint else []
        ),
    }
    try:
        data = llm_provider.generate_structured(EXTRACT_TASK, payload)
    except llm_provider.ProviderUnavailable as e:
        return SpecExtractionResult(None, "UNAVAILABLE", str(e))

    data = llm_provider.strip_forbidden_fields(data)
    reqs_raw = data.get("requirements") or []
    if not isinstance(reqs_raw, list) or not reqs_raw:
        return SpecExtractionResult(None, "UNAVAILABLE", "模型未返回有效需求列表")

    requirements: list[RequirementItem] = []
    quote_errors: list[str] = []
    for i, r in enumerate(reqs_raw, 1):
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id") or f"R{i}")
        quote = str(r.get("source_quote") or "")
        origin = r.get("origin") or "UNCLEAR"
        if origin == "EXPLICIT" and quote and not _quote_in_text(quote, requirement):
            # source_quote 必须确实来自 R，否则拒绝该条（防伪造）
            quote_errors.append(f"{rid}: source_quote 不在需求原文中")
            continue
        if origin == "EXPLICIT" and not quote:
            origin = "UNCLEAR"
        try:
            requirements.append(RequirementItem(
                id=rid,
                statement=str(r.get("statement") or "")[:500],
                kind=r.get("kind") or "FUNCTIONAL",
                mandatory=bool(r.get("mandatory", True)),
                origin=origin,
                source_quote=quote,
                acceptance_intent=str(r.get("acceptance_intent") or "")[:300],
                unresolved_questions=[str(q) for q in (r.get("unresolved_questions") or [])][:5],
                derivation_basis=str(r.get("derivation_basis") or "")[:500],
            ))
        except Exception as e:
            quote_errors.append(f"{rid}: 结构校验失败 {e}")

    if not requirements:
        return SpecExtractionResult(
            None, "UNAVAILABLE", "全部需求条目未通过校验: " + "; ".join(quote_errors[:3])
        )

    spec = CanonicalSpec(
        spec_id="SPEC-AUTO",
        interpretation_status="UNRESOLVED",
        requirements=requirements[:20],
        input_domain=_clauses(data.get("input_domain"), requirement),
        technical_constraints=[str(c) for c in (data.get("technical_constraints") or [])][:10],
        unresolved_questions=(
            [str(q) for q in (data.get("unresolved_questions") or [])][:10] + quote_errors
        ),
        limitations=["LLM 提取的候选规格，未经语义审查时不得进入验收"],
    )
    return SpecExtractionResult(spec, "LLM", "")


def _clauses(raw, requirement: str) -> list:
    from backend.acceptance.models import InputDomainClause
    out = []
    for d in (raw or [])[:8]:
        if not isinstance(d, dict):
            continue
        quote = str(d.get("source_quote") or "")
        if quote and not _quote_in_text(quote, requirement):
            continue
        try:
            out.append(InputDomainClause(
                description=str(d.get("description") or "")[:300],
                source_quote=quote,
                origin=d.get("origin") or "EXPLICIT",
            ))
        except Exception:
            continue
    return out


def _quote_in_text(quote: str, text: str) -> bool:
    """原文引用校验：规范化空白后子串匹配。"""
    norm = lambda s: "".join(s.split())
    return norm(quote) in norm(text)


def plan_from_llm_tasks(spec: CanonicalSpec, plan: TestPlan) -> list[str]:
    """对 LLM 生成的计划做引用与预期来源校验（复用固定校验器）。"""
    from backend.acceptance.checks import validate_plan_structure
    return validate_plan_structure(spec, plan)