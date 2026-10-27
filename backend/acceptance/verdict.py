"""判定内核（M1，方案第 8 章）。

最终 verdict 由确定规则生成。模型不能创建执行证据、伪造用户确认，
或修改验收标准使代码通过。本模块不执行任何模型调用。

P0 修复（v4.1）：
- 必要条件通过不能独立支持需求整体通过；只有 SUFFICIENT/EQUIVALENT
  契约在适用范围内全部执行通过，才可支持 PASS_WITHIN_SCOPE（8.2）。
- 执行证据三个 hash 必须非空且严格相等，缺失即拒绝（不得当成匹配）。
- 案例与契约的需求归属不一致时，该案例不得支持判定。
- spec_is_ready：必要需求必须有 SUFFICIENT/EQUIVALENT 契约覆盖，
  仅有 NECESSARY 检查不足以支撑整体验收。
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
    """支持整体通过的规则：充分条件可支持对应需求；必要条件不能单独支持。"""
    return contract.relation_to_requirement in ("SUFFICIENT", "EQUIVALENT")


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

    def _hashes_match(self, ev: Evidence) -> bool:
        """执行证据 hash 必须非空且严格相等（P0-4）。

        独立编译事实（STATIC_FACT）按 TECH_COMPILE 规则只绑定源码 hash。
        """
        if ev.kind != "EXECUTED_CASE":
            if ev.code_hash:
                return ev.code_hash == self.code_hash
            return False
        if not ev.code_hash or not ev.spec_hash or not ev.plan_hash:
            return False
        return (
            ev.code_hash == self.code_hash
            and ev.spec_hash == self.spec_hash
            and ev.plan_hash == self.plan_hash
        )


def _case_requirement_consistent(case: CheckCase, contract: ContractSpec) -> bool:
    """案例的需求归属必须是契约需求归属的子集（AC-07）。"""
    return set(case.requirement_ids).issubset(set(contract.requirement_ids))


def evaluate_requirement(
    req_id: str,
    vi: VerdictInput,
    cases_by_req: dict[str, list[CheckCase]],
    contracts: dict[str, ContractSpec],
) -> tuple[RequirementStatus, list[str], list[str], list[str]]:
    """按方案 8.2 计算单条需求状态，返回 (status, evidence_ids, failed_case_ids, notes)。

    - 确认失败（合法反例，门槛满足）→ FAIL。
    - 只有 NECESSARY 检查通过（无 SUFFICIENT/EQUIVALENT 覆盖）→ UNKNOWN
      （整体行为覆盖不足，不能判整体通过）。
    - 存在 SUFFICIENT/EQUIVALENT 覆盖且全部认可案例执行通过 → PASS_WITHIN_SCOPE。
    """
    cases = cases_by_req.get(req_id, [])
    ev_by_case: dict[str, list[Evidence]] = {}
    for ev in vi.evidence:
        if ev.case_id:
            ev_by_case.setdefault(ev.case_id, []).append(ev)

    confirmed_failures: list[CheckCase] = []
    executed_accepted: list[CheckCase] = []
    pass_capable: bool = False  # 存在支持整体通过的契约（SUFFICIENT/EQUIVALENT）
    notes: list[str] = []

    for case in cases:
        contract = contracts.get(case.contract_id)
        if contract is None:
            notes.append(f"{case.case_id}: 引用了不存在的 contract {case.contract_id}")
            continue
        if not _case_requirement_consistent(case, contract):
            notes.append(
                f"{case.case_id}: 案例需求归属 {case.requirement_ids} 与契约 "
                f"{contract.contract_id} 归属 {contract.requirement_ids} 不一致"
            )
            continue
        if case.input_domain_status != "IN_SCOPE":
            notes.append(f"{case.case_id}: 输入不在已确认合法范围内，不参与判定")
            continue
        if not _oracle_passes(contract, vi.policy):
            notes.append(f"{case.case_id}: oracle 未通过当前策略 ({contract.oracle_review}/{contract.oracle_origin})")
            continue
        if _relation_supports_pass(contract):
            pass_capable = True

        evs = [e for e in ev_by_case.get(case.case_id, []) if e.kind == "EXECUTED_CASE"]
        if not evs:
            notes.append(f"{case.case_id}: 未执行")
            continue

        usable = [e for e in evs if vi._hashes_match(e)]
        dropped = len(evs) - len(usable)
        if dropped:
            notes.append(f"{case.case_id}: {dropped} 条证据因 hash 缺失或不匹配被拒绝复用")
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
        else:
            notes.append(f"{case.case_id}: 未知执行状态 {representative.status}，不形成业务结论")

    evidence_ids: list[str] = []
    for case in confirmed_failures + executed_accepted:
        evidence_ids.extend(e.evidence_id for e in ev_by_case.get(case.case_id, []))

    if confirmed_failures:
        return "FAIL", evidence_ids, [c.case_id for c in confirmed_failures], notes

    # 认可范围内的案例集合（归属一致 + 合法输入 + oracle 通过）
    accepted_scope = [
        c for c in cases
        if c.input_domain_status == "IN_SCOPE"
        and c.contract_id in contracts
        and _oracle_passes(contracts[c.contract_id], vi.policy)
        and _case_requirement_consistent(c, contracts[c.contract_id])
    ]
    all_executed_and_passed = (
        accepted_scope
        and len(executed_accepted) == len(accepted_scope)
        and all(
            any(
                e.status == "PASSED"
                for e in ev_by_case.get(c.case_id, [])
                if vi._hashes_match(e)
            )
            for c in accepted_scope
        )
    )

    if not cases:
        return "UNKNOWN", evidence_ids, [], notes + ["该需求没有任何检查案例"]

    if all_executed_and_passed:
        if pass_capable:
            return "PASS_WITHIN_SCOPE", evidence_ids, [], notes
        # 仅必要条件通过：不足以支持整体验收（P0-2，方案 8.2）
        return "UNKNOWN", evidence_ids, [], notes + [
            "仅必要条件检查通过，缺少支持整体通过的充分/等价规约"
        ]

    # 计划不完整、关键检查未执行或只有部分性质被检查
    return "UNKNOWN", evidence_ids, [], notes


def compile_evidence_gate(
    evidence: list[Evidence],
    current_code_hash: str,
) -> tuple[bool, list[Evidence]]:
    """TECH_COMPILE：确定的语法/编译错误可直接构成不可运行证据。

    code_hash 必须非空且与当前代码严格相等（P0-4）。
    """
    compile_fails = [
        e for e in evidence
        if e.kind == "STATIC_FACT" and e.phase == "COMPILE"
        and e.status in ("ASSERTION_FAILED", "ENV_ERROR")
        and bool(e.code_hash) and e.code_hash == current_code_hash
    ]
    return bool(compile_fails), compile_fails


def spec_is_ready(spec: CanonicalSpec, policy: OraclePolicy, plan: TestPlan) -> bool:
    """spec_ready：已得到符合当前策略的真实业务验收规格与计划。

    - 必要需求必须全部被 SUFFICIENT/EQUIVALENT 契约覆盖
      （仅 NECESSARY 检查不足以支撑整体验收，P0-2）。
    - 每条必要需求都有至少一个认可案例（无案例 → 无法通过）。
    """
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
    covered_by_pass_capable = {
        rid for c in accepted
        if _relation_supports_pass(c) for rid in c.requirement_ids
    }
    if not mandatory_ids.issubset(covered_by_pass_capable):
        return False
    # 每条必要需求至少有一个认可案例
    cases_by_req: dict[str, int] = {}
    accepted_contract_ids = {c.contract_id for c in accepted}
    for case in plan.cases:
        if case.contract_id in accepted_contract_ids and case.input_domain_status == "IN_SCOPE":
            for rid in case.requirement_ids:
                cases_by_req[rid] = cases_by_req.get(rid, 0) + 1
    if not all(rid in cases_by_req for rid in mandatory_ids):
        return False
    return True


def assurance_for(statuses: list[RequirementStatus]) -> str:
    """MVP 只产生 NONE 或 TESTED 的肯定保证等级。"""
    if statuses and all(s == "PASS_WITHIN_SCOPE" for s in statuses):
        return "TESTED"
    return "NONE"