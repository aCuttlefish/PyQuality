"""代码改进建议（M2，方案第 11 章）。

每条建议关联 finding、requirement_ids、evidence_ids；
已确认缺陷优先；LLM 提出的潜在线索保留待验证状态。
验证状态由系统填入，模型无权自报已验证。
"""
from __future__ import annotations

import uuid

from backend.acceptance import llm_provider
from backend.acceptance.models import (
    CanonicalSpec,
    CodeSuggestion,
    EvaluationRequest,
    RequirementResult,
    TestPlan,
)
from backend.logger import get_logger

logger = get_logger("recommender")

SUGGEST_TASK = """根据固定规格、后端 verdict、确认缺陷和真实证据解释结果。
每条建议关联 finding_id、requirement_id 和已有 evidence_id。
不把环境阻塞写成业务缺陷，不把待验证风险写成已确认缺陷。
给出最小必要修改与相应回归检查。
仅在任务明确要求时生成候选代码，保留接口与合法输入范围。
不输出或修改验证状态，不声称候选已经执行。

输出 JSON 结构：
{
  "suggestions": [{
    "requirement_ids": ["R2"],
    "evidence_ids": ["EV-xxx"],
    "category": "CORRECTNESS_FIX|POTENTIAL_RISK|PERFORMANCE|READABILITY",
    "location": "solution.py:2",
    "trigger_condition": "[1,3] 或空列表输入",
    "expected": "None",
    "actual": "0",
    "explanation": "...",
    "fix": "...",
    "regression_check": "重跑 T5/T6"
  }]
}"""


def build_suggestions(
    request: EvaluationRequest,
    spec: CanonicalSpec,
    plan: TestPlan,
    requirement_results: list[RequirementResult],
    evidence_by_case: dict[str, str],
    code_verdict: str,
) -> list[CodeSuggestion]:
    """生成代码建议。LLM 不可用时用确定规则模板（不伪造 LLM 分析）。"""
    if llm_provider.is_available():
        got = _suggest_by_llm(request, spec, plan, requirement_results, code_verdict)
        if got is not None:
            return got
    return _suggest_by_rules(spec, plan, requirement_results, evidence_by_case)


def _suggest_by_llm(
    request: EvaluationRequest,
    spec: CanonicalSpec,
    plan: TestPlan,
    requirement_results: list[RequirementResult],
    code_verdict: str,
) -> list[CodeSuggestion] | None:
    failed_reqs = [rr for rr in requirement_results if rr.status == "FAIL"]
    payload = {
        "canonical_spec": {"requirements": [r.model_dump() for r in spec.requirements]},
        "verdict": code_verdict,
        "confirmed_defects": [
            {
                "requirement_id": rr.requirement_id,
                "statement": rr.statement,
                "failed_case_ids": rr.failed_case_ids,
                "evidence_ids": rr.evidence_ids[:5],
            }
            for rr in failed_reqs
        ],
        "source_code": request.code[:8000],
        "entrypoint": request.entrypoint.model_dump() if request.entrypoint else None,
    }
    try:
        data = llm_provider.generate_structured(SUGGEST_TASK, payload, temperature=0.2)
    except llm_provider.ProviderUnavailable as e:
        logger.warning("suggestion LLM unavailable: %s", e)
        return None

    data = llm_provider.strip_forbidden_fields(data)
    known_reqs = {r.id for r in spec.requirements}
    valid_ev = {ev for rr in requirement_results for ev in rr.evidence_ids}
    out: list[CodeSuggestion] = []
    for i, s in enumerate(data.get("suggestions") or [], 1):
        if not isinstance(s, dict):
            continue
        rids = [str(r) for r in (s.get("requirement_ids") or []) if str(r) in known_reqs]
        evids = [str(e) for e in (s.get("evidence_ids") or []) if str(e) in valid_ev]
        category = s.get("category")
        if category not in ("CORRECTNESS_FIX", "POTENTIAL_RISK", "PERFORMANCE", "READABILITY"):
            category = "POTENTIAL_RISK"
        out.append(CodeSuggestion(
            suggestion_id=f"SUG-{uuid.uuid4().hex[:8]}",
            finding_id="",
            requirement_ids=rids,
            evidence_ids=evids,
            category=category,
            location=str(s.get("location") or "")[:200],
            trigger_condition=str(s.get("trigger_condition") or "")[:300],
            expected=str(s.get("expected") or "")[:300],
            actual=str(s.get("actual") or "")[:300],
            explanation=str(s.get("explanation") or "")[:800],
            fix=str(s.get("fix") or "")[:1000],
            regression_check=str(s.get("regression_check") or "")[:500],
            mode="LLM",
        ))
    return out


def _suggest_by_rules(
    spec: CanonicalSpec,
    plan: TestPlan,
    requirement_results: list[RequirementResult],
    evidence_by_case: dict[str, str],
) -> list[CodeSuggestion]:
    """离线确定规则：基于已确认缺陷的证据生成模板化建议。"""
    out: list[CodeSuggestion] = []
    stmt_by_req = {r.id: r.statement for r in spec.requirements}
    case_by_id = {c.case_id: c for c in plan.cases}
    for rr in requirement_results:
        if rr.status != "FAIL":
            continue
        for case_id in rr.failed_case_ids[:3]:
            case = case_by_id.get(case_id)
            if case is None:
                continue
            obs = evidence_by_case.get(case_id, "")
            out.append(CodeSuggestion(
                suggestion_id=f"SUG-{uuid.uuid4().hex[:8]}",
                finding_id=case_id,
                requirement_ids=[rr.requirement_id],
                evidence_ids=rr.evidence_ids[:5],
                category="CORRECTNESS_FIX",
                location=(
                    f"{request_module(case)}:{rr.requirement_id}"
                ),
                trigger_condition=f"输入 {case.args!r}",
                expected=case.expected_basis or stmt_by_req.get(rr.requirement_id, ""),
                actual=_short_obs(obs),
                explanation=(
                    f"已确认缺陷：需求「{stmt_by_req.get(rr.requirement_id, rr.requirement_id)}」"
                    f"在案例 {case_id} 上失败"
                ),
                fix=f"修改实现使 {case_id} 通过：{case.expected_basis}",
                regression_check=f"重跑固定案例 {case_id}",
                mode="RULE_FALLBACK",
            ))
        if not rr.failed_case_ids:
            out.append(CodeSuggestion(
                suggestion_id=f"SUG-{uuid.uuid4().hex[:8]}",
                requirement_ids=[rr.requirement_id],
                evidence_ids=rr.evidence_ids[:5],
                category="CORRECTNESS_FIX",
                explanation=(
                    f"已确认缺陷：需求「{stmt_by_req.get(rr.requirement_id, '')}」"
                    "存在违反证据"
                ),
                fix="对照需求与失败证据修正实现",
                regression_check="重跑完整固定测试计划",
                mode="RULE_FALLBACK",
            ))
    return out


def request_module(case) -> str:
    return "solution.py"


def _short_obs(observation_str: str) -> str:
    return observation_str[:200]