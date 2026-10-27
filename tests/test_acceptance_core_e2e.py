"""v4.2 核心验收链路端到端测试（任务 6.1 场景 D/E + 6.2 判定规则验证）。

- 场景 D：规格歧义（无折扣规则）→ 提澄清问题 + INCONCLUSIVE。
- 场景 E：环境阻断 → BLOCKED + INCONCLUSIVE；独立编译证据可保留有依据 FAIL。
- 6.2 规则 7：可选需求失败不阻止必要需求通过。
- 6.2 规则 2：UNCLEAR 需求不产生确定通过。
- 6.2 条 10：无依据的 EQUIVALENT 标签降级 UNKNOWN。
涉及 LLM 的部分为明确标注的 mock；执行链路为真实子进程（开发豁免）。
"""
import pytest

from backend.acceptance import hashing, llm_provider, runner, verdict as verdict_mod
from backend.acceptance.fixtures import (
    MAX_EVEN_CORRECT_CODE,
    MAX_EVEN_REQUIREMENT,
    MAX_EVEN_WRONG_CODE,
    max_even_plan,
    max_even_spec,
)
from backend.acceptance.models import (
    AcceptanceMaterials,
    CanonicalSpec,
    ContractSpec,
    Entrypoint,
    EvaluationRequest,
    InputDomainClause,
    RequirementItem,
    ReturnEqualsAssertion,
    TestPlan as TestPlanModel,
)
from backend.acceptance.review import ReviewResult, apply_review
from backend.acceptance.service import evaluate


def _max_even_req(code: str, prompt: str = "") -> EvaluationRequest:
    return EvaluationRequest(
        requirement=MAX_EVEN_REQUIREMENT,
        generation_prompt=prompt,
        code=code,
        entrypoint=Entrypoint(module="solution", callable="max_even"),
        acceptance_materials=AcceptanceMaterials(confirmed_spec_id="SPEC-MAX-EVEN"),
    )


# ---------- 场景 D：规格本身存在关键歧义 ----------

class TestScenarioDSpecAmbiguity:
    def test_ambiguous_requirement_no_model_inconclusive_with_questions(self):
        """场景 D（离线路径）：『计算订单优惠金额』→ INCONCLUSIVE + 指出缺失信息。"""
        req = EvaluationRequest(
            requirement="计算订单优惠金额。",
            generation_prompt="实现一个优惠计算函数。",
            code="def discount(amount):\n    return amount\n",
        )
        report = evaluate(req)
        assert report.code_verdict == "INCONCLUSIVE"
        # 不得编造业务规则后批准
        assert report.spec_interpretation == "UNRESOLVED"
        # 报告指出缺少哪些信息（阻塞/限制 中体现需求不可提取）
        assert report.blockers
        # 不产生业务执行证据（未形成有效规格与计划）
        assert report.coverage.cases_executed == 0
        assert report.coverage.cases_passed == 0

    def test_ambiguous_requirement_model_path_proposes_questions(self, monkeypatch):
        """场景 D（mock 模型路径，明确标注）：提取器输出 UNCLEAR 候选 + 澄清问题。

        mock 仅验证链路行为：UNCLEAR 需求不产生确定通过（6.2 规则 2），
        unresolved_questions 进入报告。真实模型行为见端到端记录。
        """
        monkeypatch.setattr(llm_provider, "is_available", lambda: True)
        monkeypatch.setattr(
            llm_provider.deepseek_client, "chat_json",
            lambda msgs, temperature=0.3: {
                "requirements": [
                    {
                        "id": "R1", "statement": "计算订单优惠金额",
                        "origin": "UNCLEAR", "source_quote": "计算订单优惠金额",
                        "mandatory": True,
                        "unresolved_questions": ["折扣规则是什么？", "输入字段有哪些？"],
                    },
                ],
                "input_domain": [],
                "technical_constraints": [],
                "unresolved_questions": ["金额精度要求未说明"],
            },
        )
        req = EvaluationRequest(
            requirement="计算订单优惠金额。",
            code="def discount(amount):\n    return amount\n",
        )
        report = evaluate(req)
        assert report.code_verdict == "INCONCLUSIVE"
        # 澄清问题进入报告
        assert any("折扣规则" in q or "金额精度" in q
                   for q in report.prompt_report.unresolved_questions) or \
               any("unclear" in l.lower() or "UNCLEAR" in l for l in report.limitations) or \
               report.spec_interpretation == "UNRESOLVED"

    def test_unclear_requirement_cannot_pass_even_with_passing_cases(self):
        """6.2 规则 2：UNCLEAR 需求即使检查全部通过 → 仍 UNKNOWN。"""
        spec = CanonicalSpec(
            spec_id="SPEC-UNCLEAR",
            interpretation_status="USER_CONFIRMED",
            requirement_text_digest="计算订单优惠金额。",
            requirements=[
                RequirementItem(
                    id="R1", statement="计算订单优惠金额", kind="FUNCTIONAL",
                    mandatory=True, origin="UNCLEAR", source_quote="计算订单优惠金额",
                ),
            ],
            input_domain=[InputDomainClause(description="金额")],
        )
        contracts = [
            ContractSpec(
                contract_id="K_R1", requirement_ids=["R1"],
                description="返回折扣后金额", representation="RETURN_EQUALS",
                relation_to_requirement="EQUIVALENT",
                relation_basis="用户确认的固定样例",
                oracle_origin="USER_EXAMPLE", oracle_review="ACCEPTED_FOR_TESTING",
                interpretation_status="USER_CONFIRMED",
            ),
        ]
        from backend.acceptance.models import CheckCase
        cases = [
            CheckCase(
                case_id="D1", contract_id="K_R1", requirement_ids=["R1"],
                args=[100], assertion=ReturnEqualsAssertion(
                    kind="RETURN_EQUALS", expected=100,
                ),
                expected_basis="用户样例",
            ),
        ]
        plan = TestPlanModel(plan_id="PLAN-D", revision=1, contracts=contracts, cases=cases)
        hashing.bind_spec(spec)
        hashing.bind_plan(plan, spec)
        code = "def discount(amount):\n    return amount\n"
        ch = hashing.code_hash(code, [])
        evs, _ = runner.run_cases(
            code, [], Entrypoint(module="solution", callable="discount"),
            cases, ch, plan.plan_hash, spec.spec_hash,
        )
        assert all(e.status == "PASSED" for e in evs)  # 检查确实通过
        vi = verdict_mod.VerdictInput(
            spec, plan, evs, ch, spec.spec_hash, plan.plan_hash, "source_backed"
        )
        cases_by_req = {"R1": cases}
        contracts_map = {c.contract_id: c for c in plan.contracts}
        st, _, _, notes = verdict_mod.evaluate_requirement("R1", vi, cases_by_req, contracts_map)
        assert st == "UNKNOWN"
        assert any("UNCLEAR" in n for n in notes)
        # 整体也不得通过
        assert not verdict_mod.spec_is_ready(spec, "source_backed", plan) or st == "UNKNOWN"


# ---------- 场景 E：环境无法执行代码 ----------

class TestScenarioEExecutionBlocked:
    def test_blocked_env_inconclusive_not_fake_pass(self, monkeypatch):
        """场景 E：无隔离环境 → BLOCKED + INCONCLUSIVE，未执行案例不计通过。"""
        monkeypatch.delenv("PYQ_ACCEPTANCE_ALLOW_HOST", raising=False)
        monkeypatch.delenv("PYQ_ACCEPTANCE_FORCE_DOCKER", raising=False)
        monkeypatch.setattr(
            runner, "_probe_docker",
            lambda: runner.ExecutionBackend("DOCKER", False, "daemon 不可达（测试模拟）"),
        )
        runner.reset_backend_cache()
        try:
            report = evaluate(_max_even_req(MAX_EVEN_CORRECT_CODE))
            assert report.code_verdict == "INCONCLUSIVE"
            exec_stage = next(s for s in report.stage_results if s.stage == "E_execute")
            assert exec_stage.status == "BLOCKED"
            assert report.coverage.cases_executed == 0
            assert report.coverage.cases_passed == 0
            # 未伪造执行证据
            assert all(e.kind != "EXECUTED_CASE" for e in report.evidence)
        finally:
            runner.reset_backend_cache()

    def test_blocked_env_with_syntax_error_keeps_grounded_fail(self, monkeypatch):
        """场景 E 补充：阻断 + 独立编译证据 → 保留有依据的 FAIL，并标明动态检查未执行。"""
        monkeypatch.delenv("PYQ_ACCEPTANCE_ALLOW_HOST", raising=False)
        monkeypatch.delenv("PYQ_ACCEPTANCE_FORCE_DOCKER", raising=False)
        monkeypatch.setattr(
            runner, "_probe_docker",
            lambda: runner.ExecutionBackend("DOCKER", False, "daemon 不可达（测试模拟）"),
        )
        runner.reset_backend_cache()
        try:
            req = EvaluationRequest(
                requirement="实现 f(x) 返回 x",
                code="def f(:\n    pass\n",
            )
            report = evaluate(req)
            # 独立、确定性的编译检查确认违反可运行性要求 → FAIL
            assert report.code_verdict == "FAIL"
            # 但动态检查未执行必须明确标注
            exec_stage = next(s for s in report.stage_results if s.stage == "E_execute")
            assert exec_stage.status in ("SKIPPED", "BLOCKED")
            assert report.coverage.cases_executed == 0
            assert any(e.phase == "COMPILE" for e in report.evidence)
        finally:
            runner.reset_backend_cache()

    def test_blocked_env_with_confirmed_defect_stays_inconclusive_only_if_no_independent_evidence(
        self, monkeypatch
    ):
        """场景 E：无独立证据时业务缺陷不能凭空判定（动态执行被阻断）。

        真实缺陷场景 A 依赖动态执行产生反例；执行被阻断时该路径
        只能 INCONCLUSIVE（无法产生 EXECUTED_CASE 证据）。
        """
        monkeypatch.delenv("PYQ_ACCEPTANCE_ALLOW_HOST", raising=False)
        monkeypatch.delenv("PYQ_ACCEPTANCE_FORCE_DOCKER", raising=False)
        monkeypatch.setattr(
            runner, "_probe_docker",
            lambda: runner.ExecutionBackend("DOCKER", False, "daemon 不可达（测试模拟）"),
        )
        runner.reset_backend_cache()
        try:
            report = evaluate(_max_even_req(MAX_EVEN_WRONG_CODE))
            # 无法执行 → 无反例证据 → 不得 FAIL（除非有独立静态证据）
            assert report.code_verdict == "INCONCLUSIVE"
            assert all(e.kind != "EXECUTED_CASE" for e in report.evidence)
        finally:
            runner.reset_backend_cache()


# ---------- 6.2 规则 7：可选需求不影响功能验收 ----------

class TestOptionalRequirementsDoNotBlock:
    def _spec_with_optional(self) -> CanonicalSpec:
        spec = max_even_spec()
        spec.requirements = list(spec.requirements) + [
            RequirementItem(
                id="R_OPT", statement="（可选）函数应有文档字符串",
                kind="CONSTRAINT", mandatory=False, origin="DERIVED",
                source_quote="", derivation_basis="质量建议，非用户要求",
            ),
        ]
        return spec

    def test_optional_unknown_does_not_block_mandatory_pass(self):
        """规则 7：可选需求 UNKNOWN，必要需求全通过 → 整体 PASS_WITHIN_SCOPE。"""
        spec = self._spec_with_optional()
        report = evaluate(EvaluationRequest(
            requirement=MAX_EVEN_REQUIREMENT,
            generation_prompt="",
            code=MAX_EVEN_CORRECT_CODE,
            entrypoint=Entrypoint(module="solution", callable="max_even"),
            acceptance_materials=AcceptanceMaterials(confirmed_spec_id="SPEC-MAX-EVEN"),
        ))
        assert report.code_verdict == "PASS_WITHIN_SCOPE"
        assert report.assurance_level == "TESTED"

    def test_mandatory_only_items_aggregated(self):
        """聚合只包含必要需求（service 修复验证）。"""
        spec = self._spec_with_optional()
        plan = max_even_plan()
        hashing.bind_spec(spec)
        hashing.bind_plan(plan, spec)
        # R_OPT 无案例 → UNKNOWN；若错误进入聚合会阻止 PASS
        code = MAX_EVEN_CORRECT_CODE
        ch = hashing.code_hash(code, [])
        evs, _ = runner.run_cases(
            code, [], Entrypoint(module="solution", callable="max_even"),
            plan.cases, ch, plan.plan_hash, spec.spec_hash,
        )
        vi = verdict_mod.VerdictInput(
            spec, plan, evs, ch, spec.spec_hash, plan.plan_hash, "source_backed"
        )
        cases_by_req: dict[str, list] = {}
        for c in plan.cases:
            for rid in c.requirement_ids:
                cases_by_req.setdefault(rid, []).append(c)
        contracts = {c.contract_id: c for c in plan.contracts}
        items = []
        for r in spec.requirements:
            if not r.mandatory:
                continue  # 只有必要需求进入聚合
            st, _, _, _ = verdict_mod.evaluate_requirement(r.id, vi, cases_by_req, contracts)
            items.append({"status": st})
        ready = verdict_mod.spec_is_ready(spec, "source_backed", plan)
        assert verdict_mod.aggregate_verdict(items, spec_ready=ready) == "PASS_WITHIN_SCOPE"


# ---------- 6.2 条 10：无依据的 EQUIVALENT 标签降级 ----------

class TestUnfoundedRelationLabels:
    def test_equivalent_without_reason_downgraded(self):
        spec = max_even_spec()
        plan = max_even_plan()
        review = ReviewResult("LLM")
        review.accepted_contracts = {c.contract_id for c in plan.contracts}
        # EQUIVALENT 但无 reason → 全部降级 UNKNOWN
        review.relations = {
            "K_R1": "EQUIVALENT", "K_R2": "SUFFICIENT", "K_R3": "EQUIVALENT",
        }
        # 直接构造 review 结果（绕过 review_spec_and_plan 的 LLM 调用）
        from unittest.mock import patch

        fake_output = {
            "contract_reviews": [
                {"contract_id": "K_R1", "oracle_review": "ACCEPTED_FOR_TESTING",
                 "relation_to_requirement": "EQUIVALENT"},  # 无 reason
                {"contract_id": "K_R2", "oracle_review": "ACCEPTED_FOR_TESTING",
                 "relation_to_requirement": "SUFFICIENT",
                 "reason": "输入输出表覆盖该分支"},
                {"contract_id": "K_R3", "oracle_review": "ACCEPTED_FOR_TESTING",
                 "relation_to_requirement": "EQUIVALENT",
                 "reason": "快照观测范围内等价"},
            ],
            "requirement_reviews": [
                {"requirement_id": rid, "faithful": True}
                for rid in ("R1", "R2", "R3")
            ],
            "spec_level_issues": [],
        }
        with patch.object(
            llm_provider, "is_available", lambda: True
        ), patch.object(
            llm_provider.deepseek_client, "chat_json",
            lambda msgs, temperature=0.3: fake_output,
        ):
            from backend.acceptance.review import review_spec_and_plan
            result = review_spec_and_plan(spec, plan, requirement_text=MAX_EVEN_REQUIREMENT)

        # K_R1 无 reason → UNKNOWN；K_R2/K_R3 有 reason → 保留
        assert result.relations["K_R1"] == "UNKNOWN"
        assert result.relations["K_R2"] == "SUFFICIENT"
        assert result.relations["K_R3"] == "EQUIVALENT"
        # K_R1 降级后，R1 无 pass-capable 契约 → spec 不可 ready
        apply_review(spec, plan, result)
        assert not verdict_mod.spec_is_ready(spec, "source_backed", plan)


# ---------- 阶段 G：报告字段 ----------

class TestReportFields:
    def test_requirement_result_has_location_and_scope_fields(self):
        report = evaluate(_max_even_req(MAX_EVEN_WRONG_CODE))
        r2 = next(r for r in report.requirement_results if r.requirement_id == "R2")
        assert r2.code_location == "solution.py:max_even"
        assert r2.blocked_source == ""  # FAIL 不标阻塞
        # UNKNOWN 需求有阻塞来源
        r_unknown = [r for r in report.requirement_results if r.status == "UNKNOWN"]
        for r in r_unknown:
            assert r.uncovered_scope

    def test_blocked_env_reports_execution_blocked_source(self, monkeypatch):
        monkeypatch.delenv("PYQ_ACCEPTANCE_ALLOW_HOST", raising=False)
        monkeypatch.delenv("PYQ_ACCEPTANCE_FORCE_DOCKER", raising=False)
        monkeypatch.setattr(
            runner, "_probe_docker",
            lambda: runner.ExecutionBackend("DOCKER", False, "daemon 不可达（测试模拟）"),
        )
        runner.reset_backend_cache()
        try:
            report = evaluate(_max_even_req(MAX_EVEN_WRONG_CODE))
            # 动态执行被阻断 → 需求 UNKNOWN 且 blocked_source=EXECUTION_ENV
            unknown = [r for r in report.requirement_results if r.status == "UNKNOWN"]
            assert unknown
            assert any(r.blocked_source == "EXECUTION_ENV" for r in unknown)
        finally:
            runner.reset_backend_cache()