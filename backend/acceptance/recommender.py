"""代码改进建议（M2，方案第 11 章）。

每条建议关联 finding、requirement_ids、evidence_ids；
已确认缺陷优先；LLM 提出的潜在线索保留待验证状态。
验证状态由系统填入，模型无权自报已验证。
"""
from __future__ import annotations

import json
import uuid

from backend.acceptance import llm_provider
from backend.acceptance.models import (
    CanonicalSpec,
    CodeSuggestion,
    EvaluationRequest,
    Evidence,
    RequirementResult,
    TestPlan,
)
from backend.logger import get_logger

logger = get_logger("recommender")

SUGGEST_TASK = """根据固定规格、后端 verdict、确认缺陷和真实证据解释结果。
每条建议关联 finding_id、requirement_id 和已有 evidence_id。
不把环境阻塞写成业务缺陷，不把待验证风险写成已确认缺陷。
给出最小必要修改与相应回归检查。
分析主文件及 supporting_files 中的实际源码。location 的文件和行号须从
source_code_with_line_numbers 或 supporting_files[].numbered_content 逐项核对，不能猜测行号。
checked_cases 包含本轮已执行案例的输入、断言和实际观察值；修复建议必须同时
考虑已通过的边界案例，不能为修正一个失败案例而破坏其他案例。
finding_id 必须对应 failed_cases 中的 case_id；输入、期望和实际值最终由系统填入。
仅在任务明确要求时生成候选代码，保留接口与合法输入范围。
不输出或修改验证状态，不声称候选已经执行。

输出 JSON 结构：
{
  "suggestions": [{
    "requirement_ids": ["R2"],
    "finding_id": "T5",
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
    evidence: list[Evidence] | None = None,
) -> list[CodeSuggestion]:
    """生成代码建议。LLM 不可用时用确定规则模板（不伪造 LLM 分析）。"""
    facts = _failure_facts(plan, requirement_results, evidence or [])
    fallback = _suggest_by_rules(spec, plan, requirement_results, evidence_by_case)
    for suggestion in fallback:
        fact = facts.get(suggestion.finding_id)
        if fact:
            _fill_facts(suggestion, fact)
    if llm_provider.is_available():
        got = _suggest_by_llm(request, spec, plan, requirement_results, code_verdict, facts, evidence or [])
        if got is not None:
            covered = {s.finding_id for s in got if s.category == "CORRECTNESS_FIX"}
            return got + [s for s in fallback if s.finding_id not in covered]
    return fallback


def _failure_facts(plan, requirement_results, evidence) -> dict:
    """输入、断言、观察值只从本轮计划和真实失败证据填入。"""
    out = {}
    for rr in requirement_results:
        if rr.status != "FAIL":
            continue
        for case in plan.cases:
            if case.case_id not in rr.failed_case_ids or rr.requirement_id not in case.requirement_ids:
                continue
            ev = next((e for e in evidence if e.case_id == case.case_id
                       and e.evidence_id in rr.evidence_ids
                       and rr.requirement_id in e.requirement_ids
                       and e.status in ("ASSERTION_FAILED", "TARGET_EXCEPTION")), None)
            if ev is None:
                continue
            fact = out.setdefault(case.case_id, {
                "case_id": case.case_id, "requirement_ids": [], "evidence_ids": [ev.evidence_id],
                "args": case.args, "kwargs": case.kwargs,
                "assertion": case.assertion.model_dump(), "expected_basis": case.expected_basis,
                "observation": ev.observation,
            })
            fact["requirement_ids"].append(rr.requirement_id)
    return out


def _fill_facts(suggestion, fact):
    suggestion.finding_id = fact["case_id"]
    suggestion.requirement_ids = fact["requirement_ids"]
    suggestion.evidence_ids = fact["evidence_ids"]
    suggestion.trigger_condition = json.dumps({"args": fact["args"], "kwargs": fact["kwargs"]}, ensure_ascii=False)
    assertion = fact["assertion"]
    expected = assertion.get("expected") if assertion["kind"] == "RETURN_EQUALS" else assertion
    suggestion.expected = json.dumps(expected, ensure_ascii=False)
    suggestion.actual = json.dumps(fact["observation"], ensure_ascii=False)
    suggestion.regression_check = f"复用已确认标准，重跑 {fact['case_id']} 及全部固定案例"


def _suggest_by_llm(
    request: EvaluationRequest,
    spec: CanonicalSpec,
    plan: TestPlan,
    requirement_results: list[RequirementResult],
    code_verdict: str,
    facts: dict,
    evidence: list[Evidence],
) -> list[CodeSuggestion] | None:
    failed_reqs = [rr for rr in requirement_results if rr.status == "FAIL"]
    # 交互脚本常由适配器调用；建议需要看到实际被测辅助文件，不能只分析适配器。
    supporting_sources = []
    remaining = 8000
    for file in request.supporting_files:
        if remaining <= 0:
            break
        content = file.content[:remaining]
        supporting_sources.append({"path": file.path, "content": content,
                                   "numbered_content": "\n".join(f"{i}: {line}" for i, line in enumerate(content.splitlines(), 1)),
                                   "truncated": len(content) < len(file.content)})
        remaining -= len(content)
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
        "source_code_with_line_numbers": "\n".join(
            f"{i}: {line}" for i, line in enumerate(request.code[:8000].splitlines(), 1)
        ),
        "supporting_files": supporting_sources,
        "failed_cases": list(facts.values()),
        "checked_cases": [
            {**case.model_dump(), "status":ev.status, "observation":ev.observation}
            for case in plan.cases
            for ev in evidence
            if ev.case_id == case.case_id and ev.kind == "EXECUTED_CASE"
        ],
        "entrypoint": request.entrypoint.model_dump() if request.entrypoint else None,
    }
    try:
        data = llm_provider.generate_structured(SUGGEST_TASK, payload, temperature=0.2)
    except llm_provider.ProviderUnavailable as e:
        logger.warning("suggestion LLM unavailable: %s", e)
        return None

    data = llm_provider.strip_forbidden_fields(data)
    known_reqs = {r.id for r in spec.requirements}
    valid_ev = {ev for f in facts.values() for ev in f["evidence_ids"]}
    out: list[CodeSuggestion] = []
    for i, s in enumerate(data.get("suggestions") or [], 1):
        if not isinstance(s, dict):
            continue
        rids = [str(r) for r in (s.get("requirement_ids") or []) if str(r) in known_reqs]
        evids = [str(e) for e in (s.get("evidence_ids") or []) if str(e) in valid_ev]
        category = s.get("category")
        if category not in ("CORRECTNESS_FIX", "POTENTIAL_RISK", "PERFORMANCE", "READABILITY"):
            category = "POTENTIAL_RISK"
        # 证据必须属于同一失败案例及所声明需求，不能挪用通过案例的证据。
        fact = next((f for f in facts.values() if set(evids) & set(f["evidence_ids"])
                     and set(rids) & set(f["requirement_ids"])), None)
        pending_note = ""
        if category == "CORRECTNESS_FIX" and fact is None:
            category = "POTENTIAL_RISK"
            pending_note = "（待验证：无执行证据支持）"
        suggestion = CodeSuggestion(
            suggestion_id=f"SUG-{uuid.uuid4().hex[:8]}",
            finding_id="",
            requirement_ids=rids,
            evidence_ids=evids,
            category=category,
            location=str(s.get("location") or "")[:200],
            trigger_condition=str(s.get("trigger_condition") or "")[:300],
            expected=str(s.get("expected") or "")[:300],
            actual=str(s.get("actual") or "")[:300],
            explanation=str(s.get("explanation") or "")[:800] + pending_note,
            fix=str(s.get("fix") or "")[:1000],
            regression_check=str(s.get("regression_check") or "")[:500],
            mode="LLM",
            validation_status="PENDING" if fact is None else "SYSTEM_FILLED",
        )
        if category == "CORRECTNESS_FIX" and fact:
            _fill_facts(suggestion, fact)
        out.append(suggestion)
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
