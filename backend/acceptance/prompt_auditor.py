"""提示词诊断与优化（M2，方案第 10 章）。

P 有问题不意味着 C 必然有问题；P 表达正确也不意味着 C 一定正确。
LLM 模式做完整映射/冲突/改写；离线规则模式只做确定性文本映射
（source_quote 出现检测），不改写、不编造冲突，如实标注降级。
"""
from __future__ import annotations

from backend.acceptance import llm_provider
from backend.acceptance.models import (
    CanonicalSpec,
    EvaluationRequest,
    ExtraRequirement,
    PromptChange,
    PromptMapping,
    PromptReport,
)
from backend.logger import get_logger

logger = get_logger("prompt_auditor")

AUDIT_TASK = """对照 canonical_spec 检查 generation_prompt。
按 requirement_id 输出覆盖、上下文覆盖、可见遗漏、冲突或歧义。
原生成上下文已包含 R 时，不因 P 没复述 R 而判定遗漏。
未知上下文使用"可见提示词中未体现"的措辞。
改写只修正有依据的问题，并逐项列出变化。
不根据代码结果推断提示词错误的因果关系。
不声称改写已经提升生成成功率。

映射状态枚举：
- COVERED: P 明确表达了要求
- COVERED_BY_CONTEXT: 已知原生成上下文包含被引用的完整要求
- MISSING_FROM_VISIBLE_PROMPT: 当前可见 P 未体现；是否为真实遗漏取决于上下文
- CONFLICT: P 与 R 明确冲突
- AMBIGUOUS: R 明确但 P 表述有歧义
- UNKNOWN: R 或生成上下文不足

输出 JSON 结构：
{
  "mappings": [{
    "requirement_id": "R1",
    "status": "COVERED|COVERED_BY_CONTEXT|MISSING_FROM_VISIBLE_PROMPT|CONFLICT|AMBIGUOUS|UNKNOWN",
    "requirement_quote": "来自 R 的原文",
    "prompt_quote": "来自 P 的原文证据（可为空）",
    "explanation": "..."
  }],
  "extra_requirements": [{
    "content": "P 中的额外要求", "kind": "BUSINESS|TECHNICAL",
    "needs_user_confirmation": true
  }],
  "optimized_prompt": "改进后的完整提示词",
  "changes": [{
    "before": "...", "after": "...", "requirement_id": "R1", "reason": "..."
  }],
  "unresolved_questions": ["..."]
}"""


def audit_prompt(request: EvaluationRequest, spec: CanonicalSpec) -> PromptReport:
    """提示词诊断主入口。"""
    if llm_provider.is_available():
        report = _audit_by_llm(request, spec)
        if report is not None:
            return report
    return _audit_by_rules(request, spec)


def _audit_by_llm(request: EvaluationRequest, spec: CanonicalSpec) -> PromptReport | None:
    gc = request.generation_context
    payload = {
        "canonical_spec": {
            "requirements": [r.model_dump() for r in spec.requirements],
        },
        "generation_prompt": request.generation_prompt,
        "generation_context": {
            "is_complete": gc.is_complete,
            "requirements_also_visible": gc.requirements_also_visible,
            "additional_messages": gc.additional_messages[:5],
        },
    }
    try:
        data = llm_provider.generate_structured(AUDIT_TASK, payload, temperature=0.2)
    except llm_provider.ProviderUnavailable as e:
        logger.warning("prompt audit LLM unavailable: %s", e)
        return None

    data = llm_provider.strip_forbidden_fields(data)
    known_ids = {r.id for r in spec.requirements}
    mappings: list[PromptMapping] = []
    for m in (data.get("mappings") or []):
        if not isinstance(m, dict):
            continue
        rid = str(m.get("requirement_id") or "")
        if rid not in known_ids:
            continue
        status = m.get("status")
        if status not in (
            "COVERED", "COVERED_BY_CONTEXT", "MISSING_FROM_VISIBLE_PROMPT",
            "CONFLICT", "AMBIGUOUS", "UNKNOWN",
        ):
            continue
        mappings.append(PromptMapping(
            requirement_id=rid, status=status,
            requirement_quote=str(m.get("requirement_quote") or "")[:300],
            prompt_quote=str(m.get("prompt_quote") or "")[:300],
            explanation=str(m.get("explanation") or "")[:500],
        ))

    changes: list[PromptChange] = []
    for c in (data.get("changes") or []):
        if not isinstance(c, dict):
            continue
        rid = str(c.get("requirement_id") or "")
        if rid not in known_ids:
            continue
        changes.append(PromptChange(
            before=str(c.get("before") or "")[:500],
            after=str(c.get("after") or "")[:500],
            requirement_id=rid,
            reason=str(c.get("reason") or "")[:500],
        ))

    extras: list[ExtraRequirement] = []
    for e in (data.get("extra_requirements") or []):
        if not isinstance(e, dict):
            continue
        extras.append(ExtraRequirement(
            content=str(e.get("content") or "")[:300],
            kind=e.get("kind") if e.get("kind") in ("BUSINESS", "TECHNICAL") else "TECHNICAL",
            needs_user_confirmation=bool(e.get("needs_user_confirmation", True)),
        ))

    return PromptReport(
        mappings=mappings,
        extra_requirements=extras,
        optimized_prompt=str(data.get("optimized_prompt") or request.generation_prompt),
        changes=changes,
        unresolved_questions=[str(q) for q in (data.get("unresolved_questions") or [])][:10],
        mode="LLM",
    )


def _audit_by_rules(request: EvaluationRequest, spec: CanonicalSpec) -> PromptReport:
    """离线确定性降级：只做 source_quote 文本匹配，不做语义判断。

    冲突/歧义检测需要语义理解，规则模式一律标 UNKNOWN 并说明原因，
    不编造结论。optimized_prompt 保持原 P（离线模式不具改写能力）。
    """
    p = request.generation_prompt
    gc = request.generation_context
    mappings: list[PromptMapping] = []

    def _norm(s: str) -> str:
        return "".join(s.split())

    p_norm = _norm(p)
    for r in spec.requirements:
        quote = r.source_quote or r.statement
        if not p:
            mappings.append(PromptMapping(
                requirement_id=r.id, status="UNKNOWN",
                requirement_quote=quote, explanation="未提供生成提示词 P",
            ))
            continue
        if gc.requirements_also_visible is True:
            status = "COVERED_BY_CONTEXT"
            expl = "已知原生成上下文包含完整需求；P 未复述不构成遗漏"
        elif quote and _norm(quote) in p_norm:
            status = "COVERED"
            expl = "P 中出现需求原文表述"
        elif gc.requirements_also_visible is None and gc.is_complete is None:
            status = "MISSING_FROM_VISIBLE_PROMPT"
            expl = "可见提示词中未体现该要求；生成上下文未知，不能断言模型没收到要求"
        else:
            status = "MISSING_FROM_VISIBLE_PROMPT" if not gc.requirements_also_visible else "UNKNOWN"
            expl = "可见提示词中未体现该要求"
        mappings.append(PromptMapping(
            requirement_id=r.id, status=status,
            requirement_quote=quote, explanation=expl,
        ))

    return PromptReport(
        mappings=mappings,
        extra_requirements=[],
        optimized_prompt=p,
        changes=[],
        unresolved_questions=[
            "离线规则模式：CONFLICT/AMBIGUOUS 判定与提示词改写需要模型或人工确认",
        ],
        mode="RULE_FALLBACK",
    )


def relate_prompt_to_code(
    spec: CanonicalSpec, prompt_report: PromptReport, requirement_results: list,
) -> list[dict[str, str]]:
    """10.3：由后端根据 requirement_id 关联，不写因果结论。"""
    status_by_req = {rr.requirement_id: rr.status for rr in requirement_results}
    mapping_by_req = {m.requirement_id: m.status for m in prompt_report.mappings}
    relations: list[dict[str, str]] = []
    for r in spec.requirements:
        ms = mapping_by_req.get(r.id, "UNKNOWN")
        cs = status_by_req.get(r.id, "UNKNOWN")
        if ms == "CONFLICT" and cs == "FAIL":
            rel = "SAME_REQUIREMENT_DEVIATION"
        elif ms in ("COVERED", "COVERED_BY_CONTEXT") and cs == "FAIL":
            rel = "PROMPT_COVERS_BUT_CODE_FAILS"
        elif ms in ("CONFLICT", "MISSING_FROM_VISIBLE_PROMPT") and cs == "PASS_WITHIN_SCOPE":
            rel = "PROMPT_ISSUE_BUT_CODE_PASSES"
        elif ms == "UNKNOWN" or cs == "UNKNOWN":
            rel = "UNKNOWN"
        else:
            rel = "NO_OBSERVED_RELATION"
        relations.append({
            "requirement_id": r.id,
            "prompt_status": ms,
            "code_status": cs,
            "relation": rel,
        })
    return relations