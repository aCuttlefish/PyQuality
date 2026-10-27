"""测试计划与规约审查（M2，方案 12.4 / 12.5 阶段 C/D）。

TestPlanner 的 expected 必须来自需求推导，不能调用待测代码取得；
SpecAndOracleReviewer 做固定结构校验 + LLM 语义审查，
语义审查通过仍归为 AUTO_REVIEWED（不是数学证明）。

P0 修复（v4.1）：
- 审查器必须收到完整原始需求 R（不是摘要）与真实断言/expected/预期依据。
- requirement_reviews 的 faithful=false 必须阻止该需求进入可验收状态。
- 必要契约被 REJECTED 时不得批准；缺失审查结果视为未通过。
- 只有全部必要需求 faithful 且其必要契约被接受时才 AUTO_REVIEWED。
"""
from __future__ import annotations

from typing import Optional

from backend.acceptance import llm_provider
from backend.acceptance.checks import validate_plan_structure
from backend.acceptance.models import (
    CanonicalSpec,
    CheckCase,
    ContractSpec,
    TestPlan,
)
from backend.logger import get_logger

logger = get_logger("review")

PLAN_TASK = """根据 candidate_spec、可信样例和入口信息设计候选测试计划。
预期结果必须来自需求、已批准参考或明确推导，不能调用待测代码取得。
优先使用固定检查模板，记录每个案例的 requirement_id、
contract_id、合法输入依据、expected_basis 和输入类别。
检查返回值、必要分支、边界以及需求明确的副作用。
识别只检查部分性质的情况，不声称样例穷尽了全部输入域。
无法确定预期时输出待确认项，不生成武断断言。

允许的 assertion kind 与字段（严格联合，禁止额外字段）：
- {"kind":"RETURN_EQUALS","expected": <JSON 值>}
- {"kind":"RETURN_IS_NONE"}
- {"kind":"RAISES","exception_type":"ValueError|TypeError|KeyError|IndexError|ZeroDivisionError|...","message_contains":""}
- {"kind":"INPUT_UNCHANGED","targets":[{"kind":"ARG","index":0}]}
- {"kind":"ALL_ITEMS_MATCH","predicate":{"op":"IS_EVEN|IS_NONNEGATIVE|IS_POSITIVE|IS_ODD|IS_NONE","value_type":"int|str|bool|float"}}
- {"kind":"ORDERED","direction":"ASC|DESC","strict":false}
- {"kind":"SAME_MULTISET","against":{"kind":"ARG","index":0}}

输出 JSON 结构：
{
  "contracts": [{
    "contract_id": "K_R1", "requirement_ids": ["R1"],
    "description": "...", "representation": "RETURN_EQUALS",
    "relation_to_requirement": "NECESSARY|SUFFICIENT|EQUIVALENT|UNKNOWN",
    "relation_basis": "...", "coverage_note": "..."
  }],
  "cases": [{
    "case_id": "T_R1_01", "contract_id": "K_R1", "requirement_ids": ["R1"],
    "category": "NORMAL|BOUNDARY|EMPTY|NEGATIVE|SIDE_EFFECT|NO_MATCH",
    "args": [<JSON 值>], "kwargs": {},
    "assertion": {...按上方模板...},
    "expected_basis": "预期值的独立来源说明", "input_domain_status": "IN_SCOPE"
  }],
  "coverage_notes": ["..."]
}"""

REVIEW_TASK = """审查 candidate_spec、候选规则与案例是否忠实于 requirements_text。
requirements_text 是用户的完整原始需求，是唯一业务依据。
逐条检查：需求来源、输入是否合法、预期推导、是否遗漏必要行为、
是否新增用户未要求的条件、是否可能被空洞实现满足。
区分规则是必要条件、充分条件、等价条件还是尚不明确。
为每项给出 ACCEPTED_FOR_TESTING、PENDING 或 REJECTED 建议及理由。
对每条需求输出 requirement_reviews，faithful 表示候选规格与案例
整体上是否忠实表达了该需求；存在遗漏、曲解或空洞覆盖时必须为 false。
你的审查是解释性审查，不是形式化证明，不输出执行结果或最终 verdict。

输出 JSON 结构：
{
  "contract_reviews": [{
    "contract_id": "K_R1",
    "oracle_review": "ACCEPTED_FOR_TESTING|PENDING|REJECTED",
    "relation_to_requirement": "NECESSARY|SUFFICIENT|EQUIVALENT|UNKNOWN",
    "reason": "..."
  }],
  "requirement_reviews": [{
    "requirement_id": "R1",
    "faithful": true, "issues": ["..."]
  }],
  "spec_level_issues": ["..."]
}"""


class PlanResult:
    def __init__(self, plan: Optional[TestPlan], mode: str, error: str = ""):
        self.plan = plan
        self.mode = mode
        self.error = error


def build_plan(spec: CanonicalSpec, trusted_examples: list) -> PlanResult:
    """从候选规格生成候选测试计划（LLM；不可用时返回 None）。"""
    payload = {
        "candidate_spec": {
            "requirements": [r.model_dump() for r in spec.requirements],
            "input_domain": [d.model_dump() for d in spec.input_domain],
            "technical_constraints": spec.technical_constraints,
        },
        "trusted_examples": [e.model_dump() for e in trusted_examples],
        "entrypoint_hint": spec.technical_constraints,
        "budget": {"max_cases": 40},
    }
    try:
        data = llm_provider.generate_structured(PLAN_TASK, payload)
    except llm_provider.ProviderUnavailable as e:
        return PlanResult(None, "UNAVAILABLE", str(e))

    data = llm_provider.strip_forbidden_fields(data)
    contracts_raw = data.get("contracts") or []
    cases_raw = data.get("cases") or []
    if not isinstance(contracts_raw, list) or not contracts_raw:
        return PlanResult(None, "UNAVAILABLE", "模型未返回契约列表")
    if not isinstance(cases_raw, list) or not cases_raw:
        return PlanResult(None, "UNAVAILABLE", "模型未返回案例列表")

    contracts: list[ContractSpec] = []
    for c in contracts_raw[:20]:
        if not isinstance(c, dict):
            continue
        try:
            contracts.append(ContractSpec(
                contract_id=str(c.get("contract_id") or ""),
                requirement_ids=[str(r) for r in (c.get("requirement_ids") or [])],
                description=str(c.get("description") or "")[:300],
                representation=str(c.get("representation") or ""),
                relation_to_requirement=c.get("relation_to_requirement") or "UNKNOWN",
                relation_basis=str(c.get("relation_basis") or "")[:500],
                oracle_origin="RULE_DERIVATION",
                oracle_review="PENDING",
                interpretation_status="UNRESOLVED",
                coverage_note=str(c.get("coverage_note") or "")[:500],
            ))
        except Exception:
            continue

    contract_ids = {c.contract_id for c in contracts}
    cases: list[CheckCase] = []
    for i, case in enumerate(cases_raw[:40], 1):
        if not isinstance(case, dict):
            continue
        assertion = case.get("assertion")
        if not isinstance(assertion, dict) or "kind" not in assertion:
            continue
        try:
            cases.append(CheckCase(
                case_id=str(case.get("case_id") or f"T_AUTO_{i:02d}"),
                contract_id=str(case.get("contract_id") or ""),
                requirement_ids=[str(r) for r in (case.get("requirement_ids") or [])],
                category=str(case.get("category") or "")[:40],
                args=case.get("args") if isinstance(case.get("args"), list) else [],
                kwargs=case.get("kwargs") if isinstance(case.get("kwargs"), dict) else {},
                assertion=assertion,
                expected_basis=str(case.get("expected_basis") or "")[:300],
                input_domain_status=case.get("input_domain_status") or "IN_SCOPE",
            ))
        except Exception:
            continue

    cases = [c for c in cases if c.contract_id in contract_ids]
    if not cases:
        return PlanResult(None, "UNAVAILABLE", "全部案例未通过模板结构校验")

    plan = TestPlan(
        plan_id="PLAN-AUTO", revision=1, contracts=contracts, cases=cases,
        coverage_notes=[str(n) for n in (data.get("coverage_notes") or [])][:10],
    )
    structural = validate_plan_structure(spec, plan)
    if structural:
        return PlanResult(None, "UNAVAILABLE", "计划结构校验失败: " + "; ".join(structural[:3]))
    return PlanResult(plan, "LLM", "")


class ReviewResult:
    def __init__(self, mode: str, error: str = ""):
        self.mode = mode
        self.error = error
        self.accepted_contracts: set[str] = set()
        self.rejected_contracts: set[str] = set()
        self.relations: dict[str, str] = {}
        self.spec_level_issues: list[str] = []
        # requirement_id -> (faithful: bool | None, issues: list[str])
        # None 表示审查器未覆盖该条需求（视为未通过）
        self.requirement_faithful: dict[str, Optional[bool]] = {}
        self.requirement_issues: dict[str, list[str]] = {}

    @property
    def blocking_issues(self) -> list[str]:
        out = list(self.spec_level_issues)
        for rid, issues in self.requirement_issues.items():
            out.extend(f"{rid}: {i}" for i in issues)
        return out


def review_spec_and_plan(
    spec: CanonicalSpec,
    plan: TestPlan,
    requirement_text: str = "",
) -> ReviewResult:
    """阶段 D 审查：固定校验 + LLM 语义审查。

    - requirement_text 必须是完整原始需求 R，不得用摘要替代。
    - 审查 payload 包含完整断言与 expected（不再 exclude）。
    - 语义审查成功 → 必要需求全部 faithful 且契约接受才 AUTO_REVIEWED；
    - LLM 不可用 → 保持 PENDING/UNRESOLVED（spec_ready 为 false）。
    """
    result = ReviewResult("UNAVAILABLE", "语义审查未执行（模型不可用）")
    # 原始需求 R 优先；规格中的 digest 仅作兜底（夹具路径已填充完整需求）
    raw_req = requirement_text or spec.requirement_text_digest
    payload = {
        "requirements_text": raw_req,
        "candidate_spec": {
            "requirements": [r.model_dump() for r in spec.requirements],
            "input_domain": [d.model_dump() for d in spec.input_domain],
        },
        "candidate_plan": {
            "contracts": [
                c.model_dump(exclude={"spec_hash"}) for c in plan.contracts
            ],
            # 完整断言与 expected 交给审查器（修复 exclude={"assertion"}）
            "cases": [c.model_dump() for c in plan.cases],
        },
    }
    try:
        data = llm_provider.generate_structured(REVIEW_TASK, payload, temperature=0.1)
    except llm_provider.ProviderUnavailable as e:
        result.error = f"语义审查失败: {e}"
        return result

    data = llm_provider.strip_forbidden_fields(data)
    reviews = data.get("contract_reviews") or []
    if not isinstance(reviews, list):
        result.error = "审查输出结构无效"
        return result

    known = {c.contract_id for c in plan.contracts}
    for r in reviews:
        if not isinstance(r, dict):
            continue
        cid = str(r.get("contract_id") or "")
        if cid not in known:
            continue
        review_status = r.get("oracle_review")
        if review_status in ("ACCEPTED_FOR_TESTING", "PENDING", "REJECTED"):
            if review_status == "ACCEPTED_FOR_TESTING":
                result.accepted_contracts.add(cid)
            elif review_status == "REJECTED":
                result.rejected_contracts.add(cid)
            relation = r.get("relation_to_requirement")
            reason = str(r.get("reason") or "").strip()
            if relation in ("SUFFICIENT", "EQUIVALENT") and not reason:
                # 6.2 条 10：无语义依据的充分/等价标签不得成为正确性依据 → 降级 UNKNOWN
                result.relations[cid] = "UNKNOWN"
            elif relation in ("NECESSARY", "SUFFICIENT", "EQUIVALENT", "UNKNOWN"):
                result.relations[cid] = relation

    # 处理 requirement_reviews：faithful=false 或缺失都视为未通过
    req_reviews = data.get("requirement_reviews")
    known_req_ids = {r.id for r in spec.requirements}
    if isinstance(req_reviews, list):
        for rr in req_reviews:
            if not isinstance(rr, dict):
                continue
            rid = str(rr.get("requirement_id") or "")
            if rid not in known_req_ids:
                continue
            faithful = rr.get("faithful")
            if isinstance(faithful, bool):
                result.requirement_faithful[rid] = faithful
            issues = [
                str(i) for i in (rr.get("issues") or [])[:5] if str(i).strip()
            ]
            if issues:
                result.requirement_issues[rid] = issues

    # 审查器未覆盖的必要需求 → 显式记为未通过（faithful 缺失）
    for req in spec.requirements:
        if req.id not in result.requirement_faithful:
            result.requirement_faithful[req.id] = None

    result.mode = "LLM"
    result.error = ""
    result.spec_level_issues = [
        str(i) for i in (data.get("spec_level_issues") or [])[:10]
    ]
    return result


def apply_review(spec: CanonicalSpec, plan: TestPlan, review: ReviewResult) -> None:
    """将审查结果应用到规格与计划（冻结前的最后一步）。

    - REJECTED 契约保持 REJECTED（不得进入验收）。
    - faithful=false / faithful 缺失的必要需求 → 规格 UNRESOLVED。
    - 只有全部必要需求 faithful 且必要契约被接受才 AUTO_REVIEWED。
    """
    for contract in plan.contracts:
        if review.mode == "LLM":
            if contract.contract_id in review.rejected_contracts:
                contract.oracle_review = "REJECTED"
                contract.interpretation_status = "UNRESOLVED"
            elif contract.contract_id in review.accepted_contracts:
                contract.oracle_review = "ACCEPTED_FOR_TESTING"
                contract.interpretation_status = "AUTO_REVIEWED"
                if contract.contract_id in review.relations:
                    contract.relation_to_requirement = review.relations[contract.contract_id]
            else:
                contract.oracle_review = "PENDING"
        else:
            contract.oracle_review = "PENDING"

    mandatory_ids = {r.id for r in spec.requirements if r.mandatory}
    mandatory_contracts = [
        c for c in plan.contracts if mandatory_ids & set(c.requirement_ids)
    ]

    if review.mode == "LLM":
        all_faithful = all(
            review.requirement_faithful.get(rid) is True for rid in mandatory_ids
        )
        mandatory_accepted = bool(mandatory_contracts) and all(
            c.oracle_review == "ACCEPTED_FOR_TESTING" for c in mandatory_contracts
        )
        if all_faithful and mandatory_accepted:
            spec.interpretation_status = "AUTO_REVIEWED"
        else:
            spec.interpretation_status = "UNRESOLVED"

    if review.spec_level_issues:
        spec.unresolved_questions = list(
            dict.fromkeys(spec.unresolved_questions + review.spec_level_issues)
        )
    for rid, issues in review.requirement_issues.items():
        if not issues:
            continue
        spec.unresolved_questions = list(
            dict.fromkeys(spec.unresolved_questions + [f"{rid}: {i}" for i in issues])
        )