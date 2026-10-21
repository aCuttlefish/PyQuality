"""判定内核纯函数测试（M1，方案 8.2/8.3/15.3）。

使用人工确认夹具做确定性测试；不依赖任何模型调用。
"""
import pytest

from backend.acceptance import hashing
from backend.acceptance.fixtures import max_even_plan, max_even_spec
from backend.acceptance.models import Evidence
from backend.acceptance.verdict import (
    VerdictInput,
    aggregate_verdict,
    assurance_for,
    compile_evidence_gate,
    spec_is_ready,
)


def _mk_input(spec, plan, evidence, policy="source_backed"):
    return VerdictInput(
        spec, plan, evidence,
        current_code_hash="ch", current_spec_hash=spec.spec_hash,
        current_plan_hash=plan.plan_hash, policy=policy,
    )


def _bind(spec, plan):
    hashing.bind_spec(spec)
    hashing.bind_plan(plan, spec)
    return spec, plan


def _run_requirements(vi, spec, plan):
    from backend.acceptance.verdict import evaluate_requirement
    cases_by_req = {}
    for c in plan.cases:
        for rid in c.requirement_ids:
            cases_by_req.setdefault(rid, []).append(c)
    contracts = {c.contract_id: c for c in plan.contracts}
    out = {}
    for r in spec.requirements:
        st, eids, fids, notes = evaluate_requirement(r.id, vi, cases_by_req, contracts)
        out[r.id] = st
    return out


class TestAggregateVerdict:
    def test_any_fail_wins(self):
        assert aggregate_verdict(
            [{"status": "PASS_WITHIN_SCOPE"}, {"status": "FAIL"}], spec_ready=True
        ) == "FAIL"

    def test_not_spec_ready_inconclusive(self):
        assert aggregate_verdict(
            [{"status": "PASS_WITHIN_SCOPE"}], spec_ready=False
        ) == "INCONCLUSIVE"

    def test_empty_items_inconclusive(self):
        assert aggregate_verdict([], spec_ready=True) == "INCONCLUSIVE"

    def test_unknown_blocks_pass(self):
        assert aggregate_verdict(
            [{"status": "PASS_WITHIN_SCOPE"}, {"status": "UNKNOWN"}], spec_ready=True
        ) == "INCONCLUSIVE"

    def test_all_pass(self):
        assert aggregate_verdict(
            [{"status": "PASS_WITHIN_SCOPE"}] * 3, spec_ready=True
        ) == "PASS_WITHIN_SCOPE"

    def test_fail_with_unknown(self):
        # A30：有效必要条件被违反，其他必要项尚未知 → 整体 FAIL
        assert aggregate_verdict(
            [{"status": "FAIL"}, {"status": "UNKNOWN"}], spec_ready=True
        ) == "FAIL"


class TestFixtureSpecReady:
    def test_user_confirmed_fixture_source_backed(self):
        spec, plan = _bind(max_even_spec(), max_even_plan())
        assert spec_is_ready(spec, "source_backed", plan) is True

    def test_user_confirmed_fixture_confirmed_only(self):
        spec, plan = _bind(max_even_spec(), max_even_plan())
        assert spec_is_ready(spec, "confirmed_only", plan) is True

    def test_unresolved_spec_not_ready(self):
        spec, plan = _bind(max_even_spec(), max_even_plan())
        spec.interpretation_status = "UNRESOLVED"
        assert spec_is_ready(spec, "source_backed", plan) is False

    def test_auto_reviewed_passes_source_backed_but_not_confirmed_only(self):
        spec, plan = _bind(max_even_spec(), max_even_plan())
        spec.interpretation_status = "AUTO_REVIEWED"
        assert spec_is_ready(spec, "source_backed", plan) is True
        # A29：confirmed_only 下只有模型推导 oracle → 不满足
        assert spec_is_ready(spec, "confirmed_only", plan) is False


class TestEvidenceGate:
    def test_hash_mismatch_rejects_reuse(self):
        """A23：代码/spec hash 与证据不匹配时拒绝复用证据。"""
        spec, plan = _bind(max_even_spec(), max_even_plan())
        ev = Evidence(
            kind="EXECUTED_CASE", producer="t", phase="ASSERT",
            code_hash="DIFFERENT", spec_hash=spec.spec_hash,
            plan_hash=plan.plan_hash, case_id="T5", status="ASSERTION_FAILED",
        )
        vi = _mk_input(spec, plan, [ev])
        statuses = _run_requirements(vi, spec, plan)
        # 证据被拒绝复用 → 不能据此外 R2 FAIL
        assert statuses["R2"] == "UNKNOWN"

    def test_matching_hash_used(self):
        spec, plan = _bind(max_even_spec(), max_even_plan())
        ev = Evidence(
            kind="EXECUTED_CASE", producer="t", phase="ASSERT",
            code_hash="ch", spec_hash=spec.spec_hash,
            plan_hash=plan.plan_hash, case_id="T5",
            status="ASSERTION_FAILED", requirement_ids=["R2"],
        )
        vi = _mk_input(spec, plan, [ev])
        statuses = _run_requirements(vi, spec, plan)
        # 方案 8.2：一条符合门槛的确认反例即可支持 FAIL（无需全部案例执行）
        assert statuses["R2"] == "FAIL"

    def test_pending_oracle_not_accepted(self):
        """A19：PENDING oracle 与代码结果冲突 → 保留待确认，不形成确定 FAIL。"""
        spec, plan = _bind(max_even_spec(), max_even_plan())
        for c in plan.contracts:
            c.oracle_review = "PENDING"
        evs = [
            Evidence(
                kind="EXECUTED_CASE", producer="t", phase="ASSERT",
                code_hash="ch", spec_hash=spec.spec_hash, plan_hash=plan.plan_hash,
                case_id=cid, status="ASSERTION_FAILED", requirement_ids=["R2"],
            )
            for cid in ("T5", "T6")
        ]
        vi = _mk_input(spec, plan, evs)
        statuses = _run_requirements(vi, spec, plan)
        assert statuses["R2"] == "UNKNOWN"


class TestCompileGate:
    def test_compile_fail_detected(self):
        ev = Evidence(
            kind="STATIC_FACT", producer="compile_check", phase="COMPILE",
            code_hash="ch", status="ASSERTION_FAILED",
            observation={"error": "line 1: invalid syntax"},
        )
        failed, evs = compile_evidence_gate([ev], "ch")
        assert failed is True

    def test_compile_pass_not_fail(self):
        ev = Evidence(
            kind="STATIC_FACT", producer="compile_check", phase="COMPILE",
            code_hash="ch", status="PASSED",
        )
        failed, _ = compile_evidence_gate([ev], "ch")
        assert failed is False

    def test_compile_fail_with_stale_hash_ignored(self):
        ev = Evidence(
            kind="STATIC_FACT", producer="compile_check", phase="COMPILE",
            code_hash="OLD", status="ASSERTION_FAILED",
        )
        failed, _ = compile_evidence_gate([ev], "ch")
        assert failed is False


class TestAssurance:
    def test_all_pass_tested(self):
        assert assurance_for(["PASS_WITHIN_SCOPE"] * 3) == "TESTED"

    def test_any_fail_none(self):
        assert assurance_for(["PASS_WITHIN_SCOPE", "FAIL"]) == "NONE"

    def test_unknown_none(self):
        assert assurance_for(["UNKNOWN"]) == "NONE"

    def test_empty_none(self):
        assert assurance_for([]) == "NONE"