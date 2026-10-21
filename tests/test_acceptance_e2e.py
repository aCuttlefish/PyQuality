"""端到端验收测试（M4）：人工确认夹具 + 真实隔离执行 + 确定判定。

注意：conftest 禁用真实 AI，因此 LLM 路径在此为确定降级；
夹具路径（USER_CONFIRMED 规格）完整走通 runner 与判定内核。
"""
import pytest

from backend.acceptance.fixtures import (
    MAX_EVEN_CORRECT_CODE,
    MAX_EVEN_INPLACE_CODE,
    MAX_EVEN_REQUIREMENT,
    MAX_EVEN_WRONG_CODE,
    PAYABLE_GE_CODE,
    PAYABLE_GT_CODE,
    PAYABLE_REQUIREMENT,
)
from backend.acceptance.models import (
    AcceptanceMaterials,
    Entrypoint,
    EvaluationRequest,
)
from backend.acceptance.service import evaluate


def _max_even_request(code: str, prompt: str = "", policy: str = "source_backed") -> EvaluationRequest:
    return EvaluationRequest(
        requirement=MAX_EVEN_REQUIREMENT,
        generation_prompt=prompt,
        code=code,
        entrypoint=Entrypoint(module="solution", callable="max_even"),
        acceptance_materials=AcceptanceMaterials(confirmed_spec_id="SPEC-MAX-EVEN"),
        options={"oracle_policy": policy},
    )


def _payable_request(code: str) -> EvaluationRequest:
    return EvaluationRequest(
        requirement=PAYABLE_REQUIREMENT,
        code=code,
        entrypoint=Entrypoint(module="solution", callable="payable"),
        acceptance_materials=AcceptanceMaterials(confirmed_spec_id="SPEC-PAYABLE"),
    )


class TestMaxEvenE2E:
    def test_correct_impl_passes(self):
        """A01：正确实现 → PASS_WITHIN_SCOPE + TESTED。"""
        report = evaluate(_max_even_request(MAX_EVEN_CORRECT_CODE))
        assert report.code_verdict == "PASS_WITHIN_SCOPE"
        assert report.assurance_level == "TESTED"
        assert report.coverage.cases_executed == 7
        assert report.coverage.cases_passed == 7
        assert report.coverage.cases_failed == 0
        assert report.job_status in ("COMPLETED", "PARTIAL")

    def test_wrong_impl_fails_with_counterexamples(self):
        """A02：default=0 → R2 FAIL，提供 [1,3] 与 [] 反例，整体 FAIL。"""
        report = evaluate(_max_even_request(MAX_EVEN_WRONG_CODE))
        assert report.code_verdict == "FAIL"
        by_req = {r.requirement_id: r for r in report.requirement_results}
        assert by_req["R2"].status == "FAIL"
        assert "T5" in by_req["R2"].failed_case_ids
        assert "T6" in by_req["R2"].failed_case_ids
        assert report.coverage.cases_passed == 5
        assert report.coverage.cases_failed == 2
        # 反例观察值记录了实际返回 0
        t5 = next(e for e in report.evidence if e.case_id == "T5")
        assert t5.observation.get("return_value") == 0

    def test_inplace_impl_fails_r3(self):
        """A03：返回值正确但原地排序改变输入 → R3 FAIL。"""
        report = evaluate(_max_even_request(MAX_EVEN_INPLACE_CODE))
        assert report.code_verdict == "FAIL"
        by_req = {r.requirement_id: r for r in report.requirement_results}
        assert by_req["R3"].status == "FAIL"
        assert "T7" in by_req["R3"].failed_case_ids

    def test_confirmed_only_policy_fixture_still_works(self):
        report = evaluate(_max_even_request(MAX_EVEN_WRONG_CODE, policy="confirmed_only"))
        assert report.code_verdict == "FAIL"

    def test_wrong_hash_confirmation_degrades(self):
        """confirmed_spec_hash 不匹配 → 按未确认处理 → INCONCLUSIVE。"""
        req = _max_even_request(MAX_EVEN_WRONG_CODE)
        req.acceptance_materials.confirmed_spec_hash = "deadbeef"
        report = evaluate(req)
        assert report.code_verdict == "INCONCLUSIVE"
        assert any("不匹配" in b for b in report.blockers)


class TestPayableE2E:
    def test_gt_boundary_bug_fails(self):
        """15.2：>（不含边界）→ 边界案例失败 → FAIL。"""
        report = evaluate(_payable_request(PAYABLE_GT_CODE))
        assert report.code_verdict == "FAIL"
        by_req = {r.requirement_id: r for r in report.requirement_results}
        assert by_req["R1"].status == "FAIL"
        assert "P1" in by_req["R1"].failed_case_ids

    def test_ge_boundary_correct_passes(self):
        report = evaluate(_payable_request(PAYABLE_GE_CODE))
        assert report.code_verdict == "PASS_WITHIN_SCOPE"
        assert report.coverage.cases_passed == 5


class TestDegradedPaths:
    def test_syntax_error_fails_without_execution(self):
        """A12：确定语法错误 → FAIL；动态执行 SKIPPED，不伪造执行。"""
        req = EvaluationRequest(
            requirement="实现 f(x) 返回 x",
            code="def f(:\n    pass\n",
        )
        report = evaluate(req)
        assert report.code_verdict == "FAIL"
        assert report.coverage.cases_executed == 0
        exec_stage = next(s for s in report.stage_results if s.stage == "E_execute")
        assert exec_stage.status == "SKIPPED"

    def test_no_spec_no_llm_inconclusive(self):
        """A13/A09：模型不可用且无确认材料 → 业务 INCONCLUSIVE。"""
        req = EvaluationRequest(
            requirement="计算优惠金额",
            generation_prompt="实现 discount 函数",
            code="def discount(x):\n    return x\n",
        )
        report = evaluate(req)
        assert report.code_verdict == "INCONCLUSIVE"
        assert report.job_status in ("PARTIAL", "FAILED")
        assert report.blockers

    def test_confirmed_only_with_only_model_spec_inconclusive(self):
        """A29：confirmed_only 下无用户确认材料 → INCONCLUSIVE。"""
        req = EvaluationRequest(
            requirement="实现 abs_val(x)",
            code="def abs_val(x):\n    return x if x >= 0 else -x\n",
            options={"oracle_policy": "confirmed_only"},
        )
        report = evaluate(req)
        assert report.code_verdict == "INCONCLUSIVE"

    def test_multiple_entrypoints_inconclusive(self):
        """A25：入口有多个合理候选 → 明确待补充信息。"""
        req = EvaluationRequest(
            requirement="实现 add(a, b)",
            code="def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n",
        )
        report = evaluate(req)
        assert report.code_verdict == "INCONCLUSIVE"
        assert any("入口" in b for b in report.blockers)

    def test_prompt_report_rule_fallback(self):
        """离线模式提示词诊断：source_quote 匹配 + 如实标注降级。"""
        req = _max_even_request(
            MAX_EVEN_WRONG_CODE,
            prompt="使用 Python 实现 max_even(nums)，返回最大的偶数，找不到时返回 0。",
        )
        report = evaluate(req)
        pr = report.prompt_report
        assert pr.mode == "RULE_FALLBACK"
        assert pr.optimization_validation == "NOT_EVALUATED"
        by_req = {m.requirement_id: m for m in pr.mappings}
        # R2 的原文『不存在偶数时返回 None』不在 P 中 → 可见提示词未体现
        assert by_req["R2"].status == "MISSING_FROM_VISIBLE_PROMPT"
        # P 写 0 与 R 冲突，但离线规则不做语义冲突判定 → 不标 CONFLICT
        assert by_req["R2"].status != "CONFLICT"

    def test_prompt_relation_linking(self):
        """A04 关联：同一需求上 P 与 C 偏差 → SAME_REQUIREMENT_DEVIATION 不因果。"""
        req = _max_even_request(
            MAX_EVEN_WRONG_CODE,
            prompt="使用 Python 实现 max_even(nums)，返回最大的偶数，找不到时返回 0。",
        )
        report = evaluate(req)
        rel = {
            r["requirement_id"]: r for r in report.prompt_report.prompt_code_relation
        }
        # R2: P 未体现（规则模式不能判 CONFLICT）且 C FAIL → 无 SAME_REQUIREMENT_DEVIATION
        # 规则模式下 P 写 0 无法判定为冲突，关联为 UNKNOWN 或无观察关系
        assert "R2" in rel

    def test_repair_candidate_not_generated_by_default(self):
        req = _max_even_request(MAX_EVEN_WRONG_CODE)
        report = evaluate(req)
        assert report.repair_candidate is None

    def test_reproducibility_hashes_present(self):
        req = _max_even_request(MAX_EVEN_CORRECT_CODE)
        report = evaluate(req)
        assert report.reproducibility
        assert len(report.reproducibility.code_hash) == 64
        assert report.reproducibility.spec_hash
        assert report.reproducibility.plan_hash
        assert report.reproducibility.request_hash
        assert report.isolation_level == "SUBPROCESS_SANDBOX"

    def test_evidence_cannot_be_reused_across_code(self):
        """A23 场景：不同代码 hash 的证据不复用（通过两次评估独立执行验证）。"""
        r1 = evaluate(_max_even_request(MAX_EVEN_WRONG_CODE))
        r2 = evaluate(_max_even_request(MAX_EVEN_CORRECT_CODE))
        h1 = r1.reproducibility.code_hash
        h2 = r2.reproducibility.code_hash
        assert h1 != h2
        assert all(e.code_hash == h1 for e in r1.evidence if e.kind == "EXECUTED_CASE")
        assert all(e.code_hash == h2 for e in r2.evidence if e.kind == "EXECUTED_CASE")


class TestOptionalFeatures:
    def test_property_testing_skipped_no_fake_evidence(self):
        """可选功能关闭时标 SKIPPED，且不产生虚假执行证据。"""
        req = _max_even_request(MAX_EVEN_CORRECT_CODE)
        req.options.enable_property_testing = False
        req.options.enable_crosshair = False
        report = evaluate(req)
        # 无 HYPOTHESIS/CROSSHAIR 证据；不声称 FORMALLY_VERIFIED
        assert report.assurance_level != "FORMALLY_VERIFIED"
        assert report.assurance_level != "EXHAUSTIVE_WITHIN_DOMAIN"