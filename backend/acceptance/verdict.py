"""判定内核（M1，方案第 8 章）。

最终 verdict 由确定规则生成。模型不能创建执行证据、伪造用户确认，
或修改验收标准使代码通过。本模块不执行任何模型调用。
"""
from __future__ import annotations

from backend.acceptance.models import (
    CanonicalSpec,
    CheckCase,
    ContractSpec,
    Evidence,
    OraclePolicy,
    RequirementStatus,
    TestPlan,
)


def aggregate_verdict(required_items: list[dict], *, spec_ready: bool) -> str:
    """方案 8.3 的确定聚合规则，逐字实现。"""
    if any(item["status"] == "FAIL" for item in required_items):
        return "FAIL"
    if not spec_ready or not required_items:
        return "INCONCLUSIVE"
    if any(item["status"] != "PASS_WITHIN_SCOPE" for item in required_items):
        return "INCONCLUSIVE"
    return "PASS_WITHIN_SCOPE"


def _oracle_passes(contract: ContractSpec, policy: OraclePolicy) -> bool:
    """按 oracle_policy 判断该规则的检查能否进入工程验收。"""
    if contract.oracle_review != "ACCEPTED_FOR_TESTING":
        return False
    if policy == "source_backed":
        return contract.oracle_origin in (
            "USER_EXAMPLE", "USER_CONFIRMED_RULE", "APPROVED_REFERENCE", "RULE_DERIVATION",
        )
    # confirmed_only：只有用户提供或确认过的规约能支持最终验收
    return contract.oracle_origin in (
        "USER_EXAMPLE", "USER_CONFIRMED_RULE", "APPROVED_REFERENCE",
    )


def _relation_supports_fail(contract: ContractSpec) -> bool:
    """用于拒绝代码的规约必须是需求的必要条件或等价条件。"""
    return contract.relation_to_requirement in ("NECESSARY", "EQUIVALENT")


def _relation_supports_pass(contract: ContractSpec) -> bool:
    """支持 PASS 的规则同样必须满足策略；充分条件可支持对应需求。"""
    return contract.relation_to_requirement in ("NECESSARY", "SUFFICIENT", "EQUIVALENT")


class VerdictInput:
    """判定内核输入：由后端组装，模型无权填写。"""

    def __init__(
        self,
        spec: CanonicalSpec,
        plan: TestPlan,
        evidence: list[Evidence],
        current_code_hash: str,
        current_spec_hash: str,
        current_plan_hash: str,
        policy: OraclePolicy,
    ):
        self.spec = spec
        self.plan = plan
        self.evidence = evidence
        self.code_hash = current_code_hash
        self.spec_hash = current_spec_hash
        self.plan_hash = current_plan_hash
        self.policy = policy

    def _hashes_match(self, ev: Evidence, contract: ContractSpec | None) -> bool:
        if ev.kind != "EXECUTED_CASE":
            return True
        if ev.code_hash and ev.code_hash != self.code_hash:
            return False
        if ev.spec_hash and ev.spec_hash != self.spec_hash:
            return False
        if ev.plan_hash and ev.plan_hash != self.plan_hash:
            return False
        return True


def evaluate_requirement(
    req_id: str,
    vi: VerdictInput,
    cases_by_req: dict[str, list[CheckCase]],
    contracts: dict[str, ContractSpec],
) -> tuple[RequirementStatus, list[str], list[str], list[str]]:
    """按方案 8.2 计算单条需求状态，返回 (status, evidence_ids, failed_case_ids, notes)。"""
    cases = cases_by_req.get(req_id, [])
    ev_by_case: dict[str, list[Evidence]] = {}
    for ev in vi.evidence:
        if ev.case_id:
            ev_by_case.setdefault(ev.case_id, []).append(ev)

    confirmed_failures: list[CheckCase] = []
    executed_accepted: list[CheckCase] = []
    notes: list[str] = []

    for case in cases:
        contract = contracts.get(case.contract_id)
        if contract is None:
            notes.append(f"{case.case_id}: 引用了不存在的 contract {case.contract_id}")
            continue
        if case.input_domain_status != "IN_SCOPE":
            notes.append(f"{case.case_id}: 输入不在已确认合法范围内，不参与判定")
            continue
        if not _oracle_passes(contract, vi.policy):
            notes.append(f"{case.case_id}: oracle 未通过当前策略 ({contract.oracle_review}/{contract.oracle_origin})")
            continue

        evs = [e for e in ev_by_case.get(case.case_id, []) if e.kind == "EXECUTED_CASE"]
        if not evs:
            notes.append(f"{case.case_id}: 未执行")
            continue

        usable = [e for e in evs if vi._hashes_match(e, contract)]
        dropped = len(evs) - len(usable)
        if dropped:
            notes.append(f"{case.case_id}: {dropped} 条证据因版本不匹配被拒绝复用")
        if not usable:
            continue

        representative = usable[-1]
        if representative.status == "ASSERTION_FAILED":
            # 证据门槛（8.1）：输入合法、调用正确、失败来自目标行为、版本一致
            if _relation_supports_fail(contract):
                confirmed_failures.append(case)
            else:
                notes.append(
                    f"{case.case_id}: 失败但规则为 {contract.relation_to_requirement}，"
                    "不足以支持违反需求"
                )
        elif representative.status == "PASSED":
            executed_accepted.append(case)
        elif representative.status == "TARGET_EXCEPTION":
            if _relation_supports_fail(contract):
                confirmed_failures.append(case)
            else:
                notes.append(f"{case.case_id}: 目标异常，规则关系不足以判定")
        elif representative.status in ("HARNESS_ERROR", "ENV_ERROR", "TIMEOUT", "NOT_RUN", "SKIPPED"):
            notes.append(f"{case.case_id}: {representative.status}，不形成业务结论")

    evidence_ids: list[str] = []
    for case in confirmed_failures + executed_accepted:
        evidence_ids.extend(e.evidence_id for e in ev_by_case.get(case.case_id, []))

    if confirmed_failures:
        return "FAIL", evidence_ids, [c.case_id for c in confirmed_failures], notes

    accepted_scope = [
        c for c in cases
        if c.input_domain_status == "IN_SCOPE"
        and _oracle_passes(contracts[c.contract_id], vi.policy)
    ]
    if cases and accepted_scope and len(executed_accepted) == len(accepted_scope):
        return "PASS_WITHIN_SCOPE", evidence_ids, [], notes

    # 计划不完整、关键检查未执行或只有部分性质被检查
    return "UNKNOWN", evidence_ids, [], notes


def compile_evidence_gate(
    evidence: list[Evidence],
    current_code_hash: str,
) -> tuple[bool, list[Evidence]]:
    """TECH_COMPILE：确定的语法/编译错误可直接构成不可运行证据。"""
    compile_fails = [
        e for e in evidence
        if e.kind == "STATIC_FACT" and e.phase == "COMPILE"
        and e.status in ("ASSERTION_FAILED", "ENV_ERROR")
        and (not e.code_hash or e.code_hash == current_code_hash)
    ]
    return bool(compile_fails), compile_fails


def spec_is_ready(spec: CanonicalSpec, policy: OraclePolicy, plan: TestPlan) -> bool:
    """spec_ready：已得到符合当前策略的真实业务验收规格与计划。"""
    if not spec.requirements:
        return False
    if policy == "confirmed_only":
        if spec.interpretation_status != "USER_CONFIRMED":
            return False
    else:
        if spec.interpretation_status not in ("USER_CONFIRMED", "AUTO_REVIEWED"):
            return False
    accepted = [c for c in plan.contracts if _oracle_passes(c, policy)]
    if not accepted:
        return False
    mandatory_ids = {r.id for r in spec.requirements if r.mandatory}
    covered = {rid for c in accepted for rid in c.requirement_ids}
    return mandatory_ids.issubset(covered)


def assurance_for(statuses: list[RequirementStatus]) -> str:
    """MVP 只产生 NONE 或 TESTED 的肯定保证等级。"""
    if statuses and all(s == "PASS_WITHIN_SCOPE" for s in statuses):
        return "TESTED"
    return "NONE"