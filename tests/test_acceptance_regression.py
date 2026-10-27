"""v4.1 P0/P1 修复的回归测试（任务第五节 14 项 + B1/B2/B3 + 安全边界）。

新增测试在修复前可重现对应缺陷，修复后验证缺陷消除。
涉及 LLM 的部分为明确标注的 mock（仅验证接口与校验逻辑）；
执行链路为真实子进程执行（conftest 显式开发豁免）。
"""
import json
from pathlib import Path

import pytest

from backend.acceptance import hashing, llm_provider, runner, verdict as verdict_mod
from backend.acceptance.checks import evaluate_assertion
from backend.acceptance.fixtures import (
    MAX_EVEN_CORRECT_CODE,
    MAX_EVEN_REQUIREMENT,
    MAX_EVEN_WRONG_CODE,
    max_even_plan,
    max_even_spec,
)
from backend.acceptance.models import (
    AcceptanceMaterials,
    ArgTarget,
    CanonicalSpec,
    CheckCase,
    ContractSpec,
    Entrypoint,
    Evidence,
    EvaluationRequest,
    InputDomainClause,
    OrderedAssertion,
    RequirementItem,
    ReturnEqualsAssertion,
    ReturnIsNoneAssertion,
    SameMultisetAssertion,
    SupportingFile,
)
from backend.acceptance.models import TestPlan as TestPlanModel
from backend.acceptance.review import ReviewResult, apply_review, review_spec_and_plan
from backend.acceptance.service import evaluate


# ---------- 公共构造 ----------

def _max_even_req(code: str, requirement: str = MAX_EVEN_REQUIREMENT,
                  policy: str = "source_backed") -> EvaluationRequest:
    return EvaluationRequest(
        requirement=requirement,
        generation_prompt="",
        code=code,
        entrypoint=Entrypoint(module="solution", callable="max_even"),
        acceptance_materials=AcceptanceMaterials(confirmed_spec_id="SPEC-MAX-EVEN"),
        options={"oracle_policy": policy},
    )


def _sort_spec() -> CanonicalSpec:
    """B2 场景：完整升序排序需求（保留所有元素及重复次数）。"""
    return CanonicalSpec(
        spec_id="SPEC-SORT",
        interpretation_status="USER_CONFIRMED",
        requirement_text_digest="将整数列表升序排序，并保留所有元素及其重复次数。",
        requirements=[
            RequirementItem(
                id="R1", statement="升序排序并保留所有元素及其重复次数",
                kind="FUNCTIONAL", mandatory=True, origin="EXPLICIT",
                source_quote="升序排序，并保留所有元素及其重复次数",
            ),
        ],
        input_domain=[InputDomainClause(description="整数列表")],
    )


def _ordered_only_plan() -> TestPlanModel:
    """不完整计划：仅 ORDERED ASC（单一必要性质）。"""
    contracts = [
        ContractSpec(
            contract_id="K_R1_ORDERED", requirement_ids=["R1"],
            description="返回列表升序", representation="ORDERED",
            relation_to_requirement="NECESSARY",
            relation_basis="升序是排序需求的必要条件",
            oracle_origin="RULE_DERIVATION", oracle_review="ACCEPTED_FOR_TESTING",
            interpretation_status="USER_CONFIRMED",
        ),
    ]
    cases = [
        CheckCase(
            case_id="S1", contract_id="K_R1_ORDERED", requirement_ids=["R1"],
            category="NORMAL", args=[[3, 1, 2]],
            assertion=OrderedAssertion(kind="ORDERED", direction="ASC"),
            expected_basis="升序必要条件",
        ),
    ]
    return TestPlanModel(plan_id="PLAN-SORT-A", revision=1, contracts=contracts, cases=cases)


def _complete_sort_plan() -> TestPlanModel:
    """完整计划：ORDERED + SAME_MULTISET 组合覆盖完整排序语义。"""
    contracts = [
        ContractSpec(
            contract_id="K_R1_ORDERED", requirement_ids=["R1"],
            description="返回列表升序", representation="ORDERED",
            relation_to_requirement="NECESSARY",
            relation_basis="升序是排序必要条件",
            oracle_origin="RULE_DERIVATION", oracle_review="ACCEPTED_FOR_TESTING",
            interpretation_status="USER_CONFIRMED",
        ),
        ContractSpec(
            contract_id="K_R1_COMPLETE", requirement_ids=["R1"],
            description="元素与重复次数保持不变（完整性）", representation="SAME_MULTISET",
            relation_to_requirement="EQUIVALENT",
            relation_basis="ORDERED+SAME_MULTISET 组合在声明域内等价于完整排序",
            oracle_origin="RULE_DERIVATION", oracle_review="ACCEPTED_FOR_TESTING",
            interpretation_status="USER_CONFIRMED",
        ),
    ]
    cases = [
        CheckCase(
            case_id="S1", contract_id="K_R1_ORDERED", requirement_ids=["R1"],
            category="NORMAL", args=[[3, 1, 2]],
            assertion=OrderedAssertion(kind="ORDERED", direction="ASC"),
            expected_basis="升序必要条件",
        ),
        CheckCase(
            case_id="S2", contract_id="K_R1_COMPLETE", requirement_ids=["R1"],
            category="COMPLETENESS", args=[[3, 1, 2, 2]],
            assertion=SameMultisetAssertion(
                kind="SAME_MULTISET", against=ArgTarget(kind="ARG", index=0)
            ),
            expected_basis="保留所有元素及重复次数",
        ),
    ]
    return TestPlanModel(plan_id="PLAN-SORT-B", revision=1, contracts=contracts, cases=cases)


SORT_WRONG_CODE = "def sort_numbers(nums):\n    return []\n"
SORT_RIGHT_CODE = "def sort_numbers(nums):\n    return sorted(nums)\n"


def _run_verdict(code: str, spec: CanonicalSpec, plan: TestPlanModel) -> dict:
    """真实子进程执行 + 判定内核（不经 service 的 LLM 路径）。"""
    hashing.bind_spec(spec)
    hashing.bind_plan(plan, spec)
    ch = hashing.code_hash(code, [])
    evs, _ = runner.run_cases(
        code, [], Entrypoint(module="solution", callable="sort_numbers"),
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
    statuses = {}
    for r in spec.requirements:
        st, _, fids, _ = verdict_mod.evaluate_requirement(r.id, vi, cases_by_req, contracts)
        statuses[r.id] = st
        items.append({"status": st})
    ready = verdict_mod.spec_is_ready(spec, "source_backed", plan)
    return {
        "statuses": statuses,
        "verdict": verdict_mod.aggregate_verdict(items, spec_ready=ready),
        "evidence": evs,
    }


# ---------- AC-02 / 任务 1：faithful=false 阻止批准 ----------

class TestFaithfulReviewBlocksApproval:
    def test_faithful_false_blocks_auto_reviewed(self):
        """faithful=false 的必要需求 → 规格 UNRESOLVED，不得 AUTO_REVIEWED。"""
        spec = max_even_spec()
        plan = max_even_plan()
        review = ReviewResult("LLM")
        review.accepted_contracts = {c.contract_id for c in plan.contracts}
        review.requirement_faithful = {"R1": True, "R2": False, "R3": True}
        apply_review(spec, plan, review)
        assert spec.interpretation_status == "UNRESOLVED"
        assert not verdict_mod.spec_is_ready(spec, "source_backed", plan)

    def test_missing_faithful_blocks_approval(self):
        """审查器未覆盖的必要需求（faithful 缺失）→ 不得批准。"""
        spec = max_even_spec()
        plan = max_even_plan()
        review = ReviewResult("LLM")
        review.accepted_contracts = {c.contract_id for c in plan.contracts}
        review.requirement_faithful = {"R1": True, "R2": True}  # R3 缺失
        apply_review(spec, plan, review)
        assert spec.interpretation_status == "UNRESOLVED"

    def test_rejected_contract_blocks(self):
        """必要契约被 REJECTED → 不得进入验收。"""
        spec = max_even_spec()
        plan = max_even_plan()
        review = ReviewResult("LLM")
        review.accepted_contracts = {"K_R1", "K_R2"}
        review.rejected_contracts = {"K_R3"}
        review.requirement_faithful = {"R1": True, "R2": True, "R3": True}
        apply_review(spec, plan, review)
        by_id = {c.contract_id: c for c in plan.contracts}
        assert by_id["K_R3"].oracle_review == "REJECTED"
        assert not verdict_mod.spec_is_ready(spec, "source_backed", plan)

    def test_single_accepted_contract_not_enough(self):
        """仅一个契约被接受不足以让整个规格可验收。"""
        spec = max_even_spec()
        plan = max_even_plan()
        review = ReviewResult("LLM")
        review.accepted_contracts = {"K_R1"}
        review.requirement_faithful = {"R1": True, "R2": True, "R3": True}
        apply_review(spec, plan, review)
        assert spec.interpretation_status == "UNRESOLVED"


# ---------- AC-01 / 任务 2：审查器收到完整输入 ----------

class TestReviewerReceivesFullInputs:
    def test_review_payload_contains_full_requirement_and_assertions(self, monkeypatch):
        """mock（明确标注）：验证审查 payload 含完整 R 与真实断言。"""
        captured = {}

        def fake_chat_json(messages, temperature=0.3):
            captured["messages"] = messages
            return {
                "contract_reviews": [],
                "requirement_reviews": [],
                "spec_level_issues": [],
            }

        monkeypatch.setattr(llm_provider, "is_available", lambda: True)
        monkeypatch.setattr(
            llm_provider.deepseek_client, "chat_json", fake_chat_json
        )
        spec = max_even_spec()
        plan = max_even_plan()
        review_spec_and_plan(spec, plan, requirement_text=MAX_EVEN_REQUIREMENT)

        user_content = captured["messages"][-1]["content"]
        payload_json = user_content.split("input_data:\n", 1)[1]
        payload = json.loads(payload_json)
        # 完整原始需求（非摘要）
        assert payload["requirements_text"] == MAX_EVEN_REQUIREMENT
        # 真实断言与预期值（不再 exclude assertion）
        cases = payload["candidate_plan"]["cases"]
        t1 = next(c for c in cases if c["case_id"] == "T1")
        assert t1["assertion"]["kind"] == "RETURN_EQUALS"
        assert t1["assertion"]["expected"] == 8
        t5 = next(c for c in cases if c["case_id"] == "T5")
        assert t5["assertion"]["kind"] == "RETURN_IS_NONE"
        # 预期依据与需求 ID 映射
        assert t1["expected_basis"]
        assert t1["requirement_ids"] == ["R1"]


# ---------- AC-03 / AC-04 / 任务 3、4：局部性质不得误判整体通过 ----------

class TestPartialPropertyNoPass:
    def test_ordered_only_with_empty_return_inconclusive(self):
        """B2：仅 ORDERED 检查 + return [] → 不得 PASS_WITHIN_SCOPE。"""
        result = _run_verdict(SORT_WRONG_CODE, _sort_spec(), _ordered_only_plan())
        assert result["verdict"] == "INCONCLUSIVE"
        assert result["statuses"]["R1"] == "UNKNOWN"

    def test_complete_plan_catches_empty_return(self):
        """B2 补充：加完整性检查后识别错误实现。"""
        result = _run_verdict(SORT_WRONG_CODE, _sort_spec(), _complete_sort_plan())
        assert result["verdict"] == "FAIL"
        assert result["statuses"]["R1"] == "FAIL"

    def test_complete_plan_right_code_passes(self):
        result = _run_verdict(SORT_RIGHT_CODE, _sort_spec(), _complete_sort_plan())
        assert result["verdict"] == "PASS_WITHIN_SCOPE"

    def test_necessary_only_cannot_support_pass(self):
        """NECESSARY 检查全部通过 + 无 SUFFICIENT/EQUIVALENT → UNKNOWN。"""
        result = _run_verdict(SORT_RIGHT_CODE, _sort_spec(), _ordered_only_plan())
        assert result["statuses"]["R1"] == "UNKNOWN"
        assert result["verdict"] == "INCONCLUSIVE"

    def test_spec_ready_requires_pass_capable_coverage(self):
        """计划只有 NECESSARY 契约 → spec_is_ready 为 False。"""
        spec, plan = _sort_spec(), _ordered_only_plan()
        hashing.bind_spec(spec)
        hashing.bind_plan(plan, spec)
        assert not verdict_mod.spec_is_ready(spec, "source_backed", plan)


# ---------- AC-05 / 任务 5：确认规格与当前需求不匹配 ----------

class TestConfirmedSpecBinding:
    def test_requirement_mismatch_blocks_confirmation(self):
        """请求 R 与登记需求不一致 → 旧确认状态不复用，INCONCLUSIVE。"""
        req = _max_even_req(MAX_EVEN_WRONG_CODE, requirement="实现 max_even(nums)，返回最大偶数，找不到返回 -1。")
        report = evaluate(req)
        assert report.code_verdict == "INCONCLUSIVE"
        assert any("不一致" in b for b in report.blockers)

    def test_matching_requirement_still_works(self):
        report = evaluate(_max_even_req(MAX_EVEN_CORRECT_CODE))
        assert report.code_verdict == "PASS_WITHIN_SCOPE"

    def test_unknown_confirmed_spec_id_blocks(self):
        req = _max_even_req(MAX_EVEN_CORRECT_CODE)
        req.acceptance_materials.confirmed_spec_id = "SPEC-UNKNOWN-404"
        report = evaluate(req)
        assert report.code_verdict == "INCONCLUSIVE"
        assert any("未知 confirmed_spec_id" in b for b in report.blockers)

    def test_wrong_hash_degrades_to_inconclusive(self):
        req = _max_even_req(MAX_EVEN_WRONG_CODE)
        req.acceptance_materials.confirmed_spec_hash = "deadbeef"
        report = evaluate(req)
        assert report.code_verdict == "INCONCLUSIVE"
        assert any("hash" in b.lower() or "不匹配" in b for b in report.blockers)


# ---------- AC-06 / 任务 6、7：路径冲突与重复 ----------

class TestSupportingFileGuards:
    def test_supporting_file_overwrites_main_module_rejected(self):
        with pytest.raises(Exception, match="solution.py"):
            EvaluationRequest(
                requirement="r",
                code="def f():\n    return 1\n",
                supporting_files=[SupportingFile(path="solution.py", content="x=1")],
            )

    def test_supporting_file_nested_overwrite_rejected(self):
        with pytest.raises(Exception, match="solution.py"):
            EvaluationRequest(
                requirement="r",
                code="def f():\n    return 1\n",
                supporting_files=[SupportingFile(path="pkg/solution.py", content="x=1")],
            )

    def test_duplicate_supporting_paths_rejected(self):
        with pytest.raises(Exception, match="重复"):
            EvaluationRequest(
                requirement="r",
                code="def f():\n    return 1\n",
                supporting_files=[
                    SupportingFile(path="util.py", content="a=1"),
                    SupportingFile(path="util.py", content="a=2"),
                ],
            )

    def test_path_traversal_rejected(self):
        with pytest.raises(Exception, match="路径不合法"):
            EvaluationRequest(
                requirement="r",
                code="def f():\n    return 1\n",
                supporting_files=[SupportingFile(path="../evil.py", content="x=1")],
            )

    def test_absolute_path_rejected(self):
        with pytest.raises(Exception, match="路径不合法"):
            EvaluationRequest(
                requirement="r",
                code="def f():\n    return 1\n",
                supporting_files=[SupportingFile(path="/abs/path.py", content="x=1")],
            )


# ---------- AC-07 / 任务 8、9：hash 严格绑定与需求归属 ----------

class TestEvidenceHashBinding:
    def _fixture_bound(self):
        spec, plan = max_even_spec(), max_even_plan()
        hashing.bind_spec(spec)
        hashing.bind_plan(plan, spec)
        return spec, plan

    def test_empty_hash_rejected(self):
        """证据 hash 为空 → 不匹配（不得当成匹配）。"""
        spec, plan = self._fixture_bound()
        ev = Evidence(
            kind="EXECUTED_CASE", producer="t", phase="ASSERT",
            code_hash="", spec_hash="", plan_hash="",
            case_id="T5", status="ASSERTION_FAILED",
        )
        vi = verdict_mod.VerdictInput(spec, plan, [ev], "ch", spec.spec_hash, plan.plan_hash, "source_backed")
        assert not vi._hashes_match(ev)

    def test_missing_one_hash_rejected(self):
        spec, plan = self._fixture_bound()
        ev = Evidence(
            kind="EXECUTED_CASE", producer="t", phase="ASSERT",
            code_hash="ch", spec_hash=spec.spec_hash, plan_hash="",
            case_id="T5", status="ASSERTION_FAILED",
        )
        vi = verdict_mod.VerdictInput(spec, plan, [ev], "ch", spec.spec_hash, plan.plan_hash, "source_backed")
        assert not vi._hashes_match(ev)

    def test_stale_code_hash_rejected(self):
        spec, plan = self._fixture_bound()
        ev = Evidence(
            kind="EXECUTED_CASE", producer="t", phase="ASSERT",
            code_hash="OLD", spec_hash=spec.spec_hash, plan_hash=plan.plan_hash,
            case_id="T5", status="ASSERTION_FAILED", requirement_ids=["R2"],
        )
        vi = verdict_mod.VerdictInput(spec, plan, [ev], "ch", spec.spec_hash, plan.plan_hash, "source_backed")
        cases_by_req = {}
        for c in plan.cases:
            for rid in c.requirement_ids:
                cases_by_req.setdefault(rid, []).append(c)
        contracts = {c.contract_id: c for c in plan.contracts}
        st, _, _, _ = verdict_mod.evaluate_requirement("R2", vi, cases_by_req, contracts)
        assert st == "UNKNOWN"

    def test_case_requirement_inconsistent_with_contract(self):
        """案例需求 ID 与契约归属不一致 → 该案例不得支持需求通过。"""
        spec, plan = self._fixture_bound()
        ch = hashing.code_hash(MAX_EVEN_CORRECT_CODE, [])
        evs, _ = runner.run_cases(
            MAX_EVEN_CORRECT_CODE, [],
            Entrypoint(module="solution", callable="max_even"),
            plan.cases, ch, plan.plan_hash, spec.spec_hash,
        )
        # 篡改：R2 的全部案例（T5/T6）声明归属 R1（与其契约 K_R2 的归属不一致）
        for c in plan.cases:
            if c.case_id in ("T5", "T6"):
                c.requirement_ids = ["R1"]
        vi = verdict_mod.VerdictInput(spec, plan, evs, ch, spec.spec_hash, plan.plan_hash, "source_backed")
        cases_by_req = {}
        for c in plan.cases:
            for rid in c.requirement_ids:
                cases_by_req.setdefault(rid, []).append(c)
        contracts = {c.contract_id: c for c in plan.contracts}
        # R2 失去全部案例 → 不得因执行通过而 PASS
        st_r2, _, _, _ = verdict_mod.evaluate_requirement("R2", vi, cases_by_req, contracts)
        assert st_r2 == "UNKNOWN"
        # R1 评估中 T5/T6 因归属不一致被拒绝，并留下记录
        st_r1, _, _, notes_r1 = verdict_mod.evaluate_requirement("R1", vi, cases_by_req, contracts)
        assert any("不一致" in n for n in notes_r1)
        assert st_r1 == "PASS_WITHIN_SCOPE"  # T1-T4 归属一致且完整通过


# ---------- AC-09 / 任务 10：业务数据不被篡改 ----------

class TestBusinessDataPreserved:
    def test_business_json_with_protected_names_preserved(self):
        """合法业务返回 {"verified": True, "evidence": [1]} 不被篡改。"""
        code = (
            "def make_report():\n"
            "    return {'verified': True, 'evidence': [1]}\n"
        )
        assertion = ReturnEqualsAssertion(
            kind="RETURN_EQUALS",
            expected={"verified": True, "evidence": [1]},
        )
        spec, plan = max_even_spec(), max_even_plan()
        hashing.bind_spec(spec)
        hashing.bind_plan(plan, spec)
        case = CheckCase(
            case_id="BIZ1", contract_id="K_R1", requirement_ids=["R1"],
            args=[], assertion=assertion, expected_basis="业务数据保留语义",
        )
        ch = hashing.code_hash(code, [])
        evs, _ = runner.run_cases(
            code, [], Entrypoint(module="solution", callable="make_report"),
            [case], ch, plan.plan_hash, spec.spec_hash,
        )
        assert evs[0].status == "PASSED"
        assert evs[0].observation["return_value"] == {"verified": True, "evidence": [1]}

    def test_strip_forbidden_keeps_nested_business_data(self):
        data = {
            "cases": [
                {"assertion": {"kind": "RETURN_EQUALS",
                               "expected": {"verified": True, "evidence": [1]}}}
            ],
        }
        out = llm_provider.strip_forbidden_fields(data)
        assert out["cases"][0]["assertion"]["expected"] == {"verified": True, "evidence": [1]}


# ---------- AC-08 / 任务 11-14：执行协议严格性 ----------

class TestProtocolStrictness:
    def _run_with_tamper(self, monkeypatch, code, tamper_fn):
        spec, plan = max_even_spec(), max_even_plan()
        hashing.bind_spec(spec)
        hashing.bind_plan(plan, spec)
        ch = hashing.code_hash(code, [])
        real_run = runner.subprocess.run

        def tampering_run(cmd, **kwargs):
            proc = real_run(cmd, **kwargs)
            env = kwargs.get("env") or {}
            rd = env.get("PYQ_RESULTS_DIR")
            if rd:
                rf = Path(rd) / "results.json"
                if rf.exists():
                    tamper_fn(rf)
            return proc

        monkeypatch.setattr(runner.subprocess, "run", tampering_run)
        return runner.run_cases(
            code, [], Entrypoint(module="solution", callable="max_even"),
            plan.cases, ch, plan.plan_hash, spec.spec_hash,
        )

    def test_duplicate_case_id_protocol_error(self, monkeypatch):
        """重复 case_id → 协议错误，不得产生虚假 PASS/FAIL。"""
        def tamper(rf):
            data = json.loads(rf.read_text(encoding="utf-8"))
            data.append(dict(data[0]))  # 重复 T1
            rf.write_text(json.dumps(data), encoding="utf-8")

        evs, logs = self._run_with_tamper(monkeypatch, MAX_EVEN_CORRECT_CODE, tamper)
        assert all(e.status == "ENV_ERROR" for e in evs)
        assert any("duplicate" in ln for ln in logs)

    def test_missing_case_id_protocol_error(self, monkeypatch):
        def tamper(rf):
            data = json.loads(rf.read_text(encoding="utf-8"))
            data = [d for d in data if d["case_id"] != "T5"]
            rf.write_text(json.dumps(data), encoding="utf-8")

        evs, _ = self._run_with_tamper(monkeypatch, MAX_EVEN_CORRECT_CODE, tamper)
        assert all(e.status == "ENV_ERROR" for e in evs)

    def test_extra_case_id_protocol_error(self, monkeypatch):
        def tamper(rf):
            data = json.loads(rf.read_text(encoding="utf-8"))
            data.append({"case_id": "T_EXTRA", "status": "OK", "return_value": 1,
                         "duration_ms": 0.0})
            rf.write_text(json.dumps(data), encoding="utf-8")

        evs, _ = self._run_with_tamper(monkeypatch, MAX_EVEN_CORRECT_CODE, tamper)
        assert all(e.status == "ENV_ERROR" for e in evs)

    def test_unknown_status_protocol_error(self, monkeypatch):
        """未知执行状态 → 协议错误，不进入正常断言路径。"""
        def tamper(rf):
            data = json.loads(rf.read_text(encoding="utf-8"))
            data[0]["status"] = "EVERYTHING_PASSED"
            rf.write_text(json.dumps(data), encoding="utf-8")

        evs, logs = self._run_with_tamper(monkeypatch, MAX_EVEN_CORRECT_CODE, tamper)
        assert all(e.status == "ENV_ERROR" for e in evs)
        assert any("unknown harness status" in ln for ln in logs)

    def test_missing_return_value_not_treated_as_none(self):
        """观察数据缺 return_value → HARNESS_ERROR，不是合法 None。"""
        r = evaluate_assertion(
            ReturnIsNoneAssertion(kind="RETURN_IS_NONE"),
            {"exception_type": ""},
        )
        assert r.status == "HARNESS_ERROR"

        r2 = evaluate_assertion(
            ReturnEqualsAssertion(kind="RETURN_EQUALS", expected=None),
            {},
        )
        assert r2.status == "HARNESS_ERROR"

    def test_tuple_return_not_silently_converted(self):
        """tuple 返回值 → 序列化错误，不静默转 list 后继续判定。"""
        code = "def max_even(nums):\n    return (8, 1)\n"
        spec, plan = max_even_spec(), max_even_plan()
        hashing.bind_spec(spec)
        hashing.bind_plan(plan, spec)
        ch = hashing.code_hash(code, [])
        evs, _ = runner.run_cases(
            code, [], Entrypoint(module="solution", callable="max_even"),
            plan.cases[:1], ch, plan.plan_hash, spec.spec_hash,
        )
        assert evs[0].status == "HARNESS_ERROR"
        assert "not JSON-native" in evs[0].observation.get("return_serialization_error", "")

    def test_legitimate_none_return_passes_is_none(self):
        """合法 Python None（键存在值为 null）→ 正常判定。"""
        code = "def max_even(nums):\n    return None\n"
        spec, plan = max_even_spec(), max_even_plan()
        hashing.bind_spec(spec)
        hashing.bind_plan(plan, spec)
        ch = hashing.code_hash(code, [])
        t5 = next(c for c in plan.cases if c.case_id == "T5")
        evs, _ = runner.run_cases(
            code, [], Entrypoint(module="solution", callable="max_even"),
            [t5], ch, plan.plan_hash, spec.spec_hash,
        )
        assert evs[0].status == "PASSED"
        assert evs[0].observation["return_value"] is None


# ---------- C：执行器与安全验收 ----------

class TestExecutionSafety:
    def test_default_blocked_without_isolation(self, monkeypatch):
        """默认（无 Docker、无豁免）→ 动态执行 BLOCKED，整体 INCONCLUSIVE。"""
        monkeypatch.delenv("PYQ_ACCEPTANCE_ALLOW_HOST", raising=False)
        monkeypatch.delenv("PYQ_ACCEPTANCE_FORCE_DOCKER", raising=False)
        monkeypatch.setattr(
            runner, "_probe_docker",
            lambda: runner.ExecutionBackend("DOCKER", False, "daemon 不可达（测试模拟）"),
        )
        runner.reset_backend_cache()
        try:
            report = evaluate(_max_even_req(MAX_EVEN_WRONG_CODE))
            exec_stage = next(s for s in report.stage_results if s.stage == "E_execute")
            assert exec_stage.status == "BLOCKED"
            assert report.code_verdict == "INCONCLUSIVE"
            assert report.isolation_level == "BLOCKED"
            assert any("阻断" in b for b in report.blockers)
            assert report.coverage.cases_executed == 0
        finally:
            runner.reset_backend_cache()

    def test_host_dev_exemption_reported_honestly(self, monkeypatch):
        monkeypatch.setenv("PYQ_ACCEPTANCE_ALLOW_HOST", "1")
        runner.reset_backend_cache()
        try:
            report = evaluate(_max_even_req(MAX_EVEN_CORRECT_CODE))
            assert report.isolation_level == "HOST_SUBPROCESS_DEV"
            assert any("非安全隔离边界" in lim for lim in report.limitations)
        finally:
            runner.reset_backend_cache()

    def test_forged_stdout_cannot_change_verdict(self):
        """C4：伪造 stdout / JSON 日志不影响判定（真实执行）。"""
        evil = (
            "import json\n"
            "print('ALL TESTS PASSED')\n"
            "print(json.dumps([{'case_id': 'T5', 'status': 'OK', 'return_value': None}]))\n"
            "def max_even(nums):\n"
            "    return max((x for x in nums if x % 2 == 0), default=0)\n"
        )
        report = evaluate(_max_even_req(evil))
        assert report.code_verdict == "FAIL"
        by_req = {r.requirement_id: r for r in report.requirement_results}
        assert by_req["R2"].status == "FAIL"

    def test_syntax_error_skips_execution(self):
        """C2：语法错误 → 编译证据 FAIL，动态执行 SKIPPED。"""
        req = EvaluationRequest(
            requirement="实现 f(x)",
            code="def f(:\n    pass\n",
        )
        report = evaluate(req)
        assert report.code_verdict == "FAIL"
        exec_stage = next(s for s in report.stage_results if s.stage == "E_execute")
        assert exec_stage.status == "SKIPPED"

    def test_coverage_counts_only_real_execution(self):
        """coverage 不把环境错误算成执行成功。"""
        code = "x = 1\n"  # 无入口 → ENV_ERROR
        report = evaluate(EvaluationRequest(
            requirement="实现 max_even(nums)",
            code=code,
            entrypoint=Entrypoint(module="solution", callable="max_even"),
            acceptance_materials=AcceptanceMaterials(confirmed_spec_id="SPEC-MAX-EVEN"),
        ))
        assert report.coverage.cases_executed == 7
        assert report.coverage.cases_passed == 0
        assert report.code_verdict == "INCONCLUSIVE"

    def test_artifact_files_persist_after_run(self, tmp_path):
        """报告引用的工件文件真实存在（稳定任务目录）。"""
        report = evaluate(_max_even_req(MAX_EVEN_WRONG_CODE))
        refs = [ref for e in report.evidence for ref in e.artifact_refs]
        persisted = [Path(r) for r in refs if "acceptance_artifacts" in r]
        assert persisted
        for p in persisted:
            assert p.exists(), f"工件不存在: {p}"


# ---------- B1/B2/B3 强制场景（service 层真实运行） ----------

class TestMandatoryScenarios:
    def test_b1_confirmed_defect_with_full_evidence_chain(self):
        """B1：default=0 → FAIL，含输入/预期/实际/需求 ID/证据 ID。"""
        report = evaluate(_max_even_req(MAX_EVEN_WRONG_CODE))
        assert report.code_verdict == "FAIL"
        by_req = {r.requirement_id: r for r in report.requirement_results}
        r2 = by_req["R2"]
        assert r2.status == "FAIL"
        assert r2.failed_case_ids  # 反例案例
        assert r2.evidence_ids  # 有效证据 ID
        t5 = next(e for e in report.evidence if e.case_id == "T5")
        assert t5.observation.get("return_value") == 0  # 实际值
        assert t5.code_hash == report.reproducibility.code_hash

    def test_b2_incomplete_plan_inconclusive_then_fail_with_complete_plan(self):
        """B2：ORDERED-only → INCONCLUSIVE；补完整性检查 → 识别不合格。"""
        # service 层走夹具路径受限，用判定内核直接驱动（见 TestPartialPropertyNoPass）
        result_a = _run_verdict(SORT_WRONG_CODE, _sort_spec(), _ordered_only_plan())
        assert result_a["verdict"] == "INCONCLUSIVE"
        result_b = _run_verdict(SORT_WRONG_CODE, _sort_spec(), _complete_sort_plan())
        assert result_b["verdict"] == "FAIL"

    def test_b3_pass_within_scope_tested(self):
        """B3：认可规格 + 完整必要检查 + hash 匹配 → PASS_WITHIN_SCOPE + TESTED。"""
        report = evaluate(_max_even_req(MAX_EVEN_CORRECT_CODE))
        assert report.code_verdict == "PASS_WITHIN_SCOPE"
        assert report.assurance_level == "TESTED"
        assert report.coverage.cases_executed == report.coverage.cases_planned == 7
        assert report.coverage.cases_passed == 7
        # hash 完全匹配
        for e in report.evidence:
            if e.kind == "EXECUTED_CASE":
                assert e.code_hash == report.reproducibility.code_hash
                assert e.spec_hash == report.reproducibility.spec_hash
                assert e.plan_hash == report.reproducibility.plan_hash


# ---------- D：提示词诊断与建议验收 ----------

class TestPromptAndSuggestions:
    def test_prompt_missing_but_code_passes_not_failed(self):
        """D2：P 有遗漏但 C 满足需求 → 代码不得判不合格。"""
        req = _max_even_req(MAX_EVEN_CORRECT_CODE)
        req.generation_prompt = "实现 max_even，返回最大偶数。"  # 未提 None/不变
        report = evaluate(req)
        assert report.code_verdict == "PASS_WITHIN_SCOPE"
        pr = report.prompt_report
        by_req = {m.requirement_id: m for m in pr.mappings}
        assert by_req["R2"].status == "MISSING_FROM_VISIBLE_PROMPT"

    def test_rule_fallback_no_fake_conflict(self):
        """D4：规则降级无法判断语义冲突 → 不伪造 CONFLICT。"""
        req = _max_even_req(
            MAX_EVEN_CORRECT_CODE,
        )
        # P 与 R 语义冲突（返回 0 vs None），规则模式只能文本匹配
        req.generation_prompt = "使用 Python 实现 max_even(nums)，返回最大的偶数，找不到时返回 0。"
        report = evaluate(req)
        pr = report.prompt_report
        assert pr.mode == "RULE_FALLBACK"
        statuses = {m.requirement_id: m.status for m in pr.mappings}
        # 不得伪造 CONFLICT（无法语义判定）
        assert "CONFLICT" not in statuses.values()

    def test_optimization_validation_not_evaluated(self):
        req = _max_even_req(MAX_EVEN_CORRECT_CODE)
        req.generation_prompt = "实现 max_even。"
        report = evaluate(req)
        assert report.prompt_report.optimization_validation == "NOT_EVALUATED"

    def test_rule_suggestions_bound_to_evidence(self):
        """D6：已确认缺陷建议必须绑定真实失败证据。"""
        report = evaluate(_max_even_req(MAX_EVEN_WRONG_CODE))
        failed_ev_ids = {
            e.evidence_id for e in report.evidence
            if e.status == "ASSERTION_FAILED"
        }
        correctness = [s for s in report.code_suggestions if s.category == "CORRECTNESS_FIX"]
        assert correctness
        for s in correctness:
            assert s.evidence_ids
            assert set(s.evidence_ids) & failed_ev_ids

    def test_unimplemented_repair_candidate_reported(self):
        """请求修复候选但未实现 → 明确报告，不静默。"""
        req = _max_even_req(MAX_EVEN_WRONG_CODE)
        req.options.generate_repair_candidate = True
        report = evaluate(req)
        assert report.repair_candidate is None
        assert any("修复候选生成未实现" in lim for lim in report.limitations)
        stage = [s for s in report.stage_results if s.stage == "G_repair_candidate"]
        assert stage and stage[0].status == "SKIPPED"