"""最终用户流程回归：自定义标准→确认→真实执行→证据建议→同标准复评。"""
import json
import subprocess

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.acceptance import llm_provider, recommender, runner, standards
from backend.acceptance.checks import evaluate_assertion
from backend.acceptance.environment import inspect_environment
from backend.acceptance.models import (
    CanonicalSpec, CheckCase, ContractSpec, Entrypoint, EvaluationRequest,
    RequirementItem, ReturnMatchesAssertion, ReturnTypeAssertion,
)
from backend.acceptance.models import TestPlan as Plan
from backend.acceptance.service import evaluate
from backend.main import app


@pytest.fixture(autouse=True)
def isolated_standards(tmp_path, monkeypatch):
    monkeypatch.setattr(standards, "STORE_DIR", tmp_path / "standards")


def confirmation():
    requirement = "实现 add(a, b)，返回两个整数相加的结果。"
    return standards.StandardConfirmation(
        requirement=requirement, entrypoint=Entrypoint(callable="add"),
        scope_note="仅验证本轮确认的固定输入输出案例，不保证未测试输入。",
        confirmed=True,
        spec=CanonicalSpec(spec_id="DRAFT", requirements=[RequirementItem(
            id="R1", statement="返回两个整数之和", source_quote="返回两个整数相加的结果",
            origin="EXPLICIT",
        )]),
        plan=Plan(contracts=[ContractSpec(
            contract_id="K1", requirement_ids=["R1"], description="相加结果",
            relation_to_requirement="EQUIVALENT",
            relation_basis="用户确认的固定输入输出检查", oracle_origin="MODEL_HYPOTHESIS",
        )], cases=[CheckCase(
            case_id=f"T{i}", contract_id="K1", requirement_ids=["R1"], args=args,
            assertion={"kind":"RETURN_EQUALS", "expected":expected},
            expected_basis="根据整数加法独立计算",
        ) for i, (args, expected) in enumerate([([2,3],5),([-4,1],-3),([0,0],0)], 1)]),
    )


def request_for(record, code="def add(a, b):\n    return a + b\n", **overrides):
    return EvaluationRequest(
        requirement=overrides.pop("requirement", record["requirement"]),
        code=code, entrypoint=record["entrypoint"],
        acceptance_materials={
            "confirmed_spec_id":record["confirmed_spec_id"],
            "confirmed_spec_hash":record["confirmed_spec_hash"],
        }, options={"oracle_policy":"confirmed_only"}, **overrides,
    )


def test_custom_standard_wrong_then_correct_with_identical_checks():
    record = standards.confirm(confirmation())
    wrong = evaluate(request_for(record, "def add(a, b):\n    return a - b\n"))
    correct = evaluate(request_for(record))
    assert wrong.code_verdict == "FAIL"
    assert (wrong.coverage.cases_passed, wrong.coverage.cases_failed) == (1, 2)
    assert correct.code_verdict == "PASS_WITHIN_SCOPE"
    assert correct.spec_interpretation == "USER_CONFIRMED"
    assert correct.coverage.cases_passed == correct.coverage.cases_planned == 3
    assert wrong.reproducibility.plan_hash == correct.reproducibility.plan_hash
    assert wrong.reproducibility.spec_hash == correct.reproducibility.spec_hash
    assert wrong.reproducibility.code_hash != correct.reproducibility.code_hash
    assert standards.load(record["confirmed_spec_id"], record["requirement"], Entrypoint(callable="add"))
    assert any("不保证未测试输入" in l for l in correct.limitations)


@pytest.mark.parametrize("expected_exception", [False, True])
def test_target_exception_count_matches_confirmed_assertion(expected_exception):
    """意外崩溃应计为失败；标准明确要求抛异常时应计为通过。"""
    from backend.acceptance.models import RaisesAssertion
    body = confirmation()
    if expected_exception:
        body.requirement += " a 为负数时抛出 ValueError。"
        body.spec.requirements[0].statement = body.requirement
        body.spec.requirements[0].source_quote = body.requirement
        body.plan.cases[1].assertion = RaisesAssertion(kind="RAISES", exception_type="ValueError")
    record = standards.confirm(body)
    report = evaluate(request_for(record, "def add(a, b):\n    if a < 0:\n        raise ValueError('negative')\n    return a + b\n"))
    assert report.coverage.cases_executed == 3
    assert report.coverage.cases_passed == (3 if expected_exception else 2)
    assert report.coverage.cases_failed == (0 if expected_exception else 1)
    assert report.code_verdict == ("PASS_WITHIN_SCOPE" if expected_exception else "FAIL")


def test_user_can_choose_explicit_fixed_case_scope_for_complete_outputs():
    body = confirmation()
    body.plan.contracts[0].relation_to_requirement = "NECESSARY"
    body.case_scope_confirmed = True
    record = standards.confirm(body)
    assert record["case_scope_confirmed"] is True
    assert any(c["contract_id"].startswith("K_USER_SCOPE") for c in record["plan"]["contracts"])
    assert evaluate(request_for(record)).code_verdict == "PASS_WITHIN_SCOPE"
    assert evaluate(request_for(record, "def add(a,b):\n return a-b")).code_verdict == "FAIL"


def test_fixed_case_scope_does_not_approve_only_partial_properties():
    body = confirmation()
    body.case_scope_confirmed = True
    body.plan.contracts[0].relation_to_requirement = "NECESSARY"
    for case in body.plan.cases:
        case.assertion = ReturnTypeAssertion(kind="RETURN_TYPE", expected_type="int")
    with pytest.raises(ValueError, match="部分性质"):
        standards.confirm(body)


def test_confirmation_is_persisted_and_requirement_bound():
    record = standards.confirm(confirmation())
    assert (standards.STORE_DIR / (record["confirmed_spec_id"] + ".json")).exists()
    report = evaluate(request_for(record, requirement="实现整数相乘。"))
    assert report.code_verdict == "INCONCLUSIVE"
    assert report.coverage.cases_executed == 0
    assert any("需求已修改" in b for b in report.blockers)


def test_changed_entrypoint_requires_new_confirmation():
    record = standards.confirm(confirmation())
    with pytest.raises(ValueError, match="入口"):
        standards.load(record["confirmed_spec_id"], record["requirement"], Entrypoint(callable="sub"))


def test_confirmation_hash_mismatch_rejected():
    record = standards.confirm(confirmation())
    with pytest.raises(ValueError, match="摘要"):
        standards.load(record["confirmed_spec_id"], record["requirement"], Entrypoint(callable="add"), "stale")


def test_stored_plan_tampering_rejected():
    record = standards.confirm(confirmation())
    path = standards.STORE_DIR / (record["confirmed_spec_id"] + ".json")
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["plan"]["cases"][0]["assertion"]["expected"] = 999
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="摘要"):
        standards.load(record["confirmed_spec_id"], record["requirement"], Entrypoint(callable="add"))


def test_case_requirement_mapping_is_part_of_plan_hash():
    from backend.acceptance.hashing import plan_hash
    plan = confirmation().plan
    before = plan_hash(plan)
    plan.cases[0].requirement_ids = ["R2"]
    assert plan_hash(plan) != before


@pytest.mark.parametrize("path", ["C:/escape.py", "harness.py", "//server/share/escape.py"])
def test_auxiliary_paths_cannot_escape_or_replace_runner(path):
    from backend.acceptance.models import SupportingFile
    with pytest.raises(ValidationError):
        SupportingFile(path=path, content="")


@pytest.mark.parametrize("flag", [False, 1, "true"])
def test_explicit_confirmation_required(flag):
    body = confirmation().model_dump()
    body["confirmed"] = flag
    with pytest.raises(ValidationError):
        standards.StandardConfirmation(**body)


@pytest.mark.parametrize("mutation, message", [
    ("no_cases", "每项必要需求"), ("partial", "每项必要需求"),
    ("unclear", "澄清"), ("forged_quote", "原文引用"), ("duplicate", "重复"),
])
def test_invalid_standards_cannot_be_confirmed(mutation, message):
    body = confirmation()
    if mutation == "no_cases":
        body.plan.cases = []
    elif mutation == "partial":
        body.plan.contracts[0].relation_to_requirement = "NECESSARY"
    elif mutation == "unclear":
        body.spec.requirements[0].origin = "UNCLEAR"
    elif mutation == "forged_quote":
        body.spec.requirements[0].source_quote = "需求必须访问互联网"
    else:
        body.plan.cases[1].case_id = body.plan.cases[0].case_id
    with pytest.raises(ValueError, match=message):
        standards.confirm(body)


def test_prepare_without_model_remains_editable_without_fake_cases():
    result = standards.prepare(EvaluationRequest(requirement="返回两个整数之和。", code="def add(a,b):\n return a+b"))
    assert result["ok"]
    assert result["spec"]["interpretation_status"] == "UNRESOLVED"
    assert result["plan"]["cases"] == []
    assert result["issues"]


def test_prepare_api_accepts_requirement_without_code():
    with TestClient(app) as client:
        resp = client.post("/api/acceptance/prepare", json={
            "requirement": "实现 add(a, b)，返回两个整数之和。",
            "entrypoint": {"module": "solution", "callable": "add"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["entrypoint"] == {"module": "solution", "callable": "add"}
        assert data["spec"]["requirements"]


def test_ordered_check_supports_lexicographic_nested_lists():
    from backend.acceptance.checks import evaluate_assertion
    from backend.acceptance.models import OrderedAssertion

    ok = evaluate_assertion(
        OrderedAssertion(kind="ORDERED", direction="ASC", strict=False),
        {"return_value": [[0, 2], [1, 1], [2, 0]]},
    )
    assert ok.status == "PASSED"
    bad = evaluate_assertion(
        OrderedAssertion(kind="ORDERED", direction="ASC", strict=False),
        {"return_value": [[2, 0], [1, 1], [0, 2]]},
    )
    assert bad.status == "ASSERTION_FAILED"


def test_clarify_api_offline_fallback():
    with TestClient(app) as client:
        resp = client.post("/api/acceptance/clarify", json={
            "initial_input": "写一个 possibilities(m, n) 函数",
            "input_type": "prompt",
            "entrypoint": "possibilities",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["mode"] == "UNAVAILABLE"
        assert data["ready"] is True
        assert data["suggested_entrypoint"] == "possibilities"


def test_clarify_api_multi_turn_with_mock_llm(monkeypatch):
    from backend.acceptance import llm_provider

    calls = []

    def fake_structured(task, payload, **kwargs):
        calls.append(payload)
        if not payload["qa_history"]:
            return {
                "ready": False,
                "summary": "还需要确认 n=0 的边界行为。",
                "suggested_entrypoint": "possibilities",
                "questions": [
                    {"id": "Q1", "question": "当 n=0 且 m>0 时应该返回什么？", "options": ["返回空列表 []", "抛出 ValueError"]},
                ],
                "refined_requirement": "实现 possibilities(m, n)...",
            }
        return {
            "ready": True,
            "summary": "需求与边界已经完全清楚。",
            "suggested_entrypoint": "possibilities",
            "questions": [],
            "refined_requirement": "实现 possibilities(m, n)，n=0 且 m>0 返回 []，调用方保证输入为非负整数。",
        }

    monkeypatch.setattr(llm_provider, "generate_structured", fake_structured)
    with TestClient(app) as client:
        r1 = client.post("/api/acceptance/clarify", json={
            "initial_input": "写一个 possibilities(m, n) 找所有和为 m 的 n 项组合",
            "input_type": "requirement",
        }).json()
        assert r1["ready"] is False
        assert len(r1["questions"]) == 1

        r2 = client.post("/api/acceptance/clarify", json={
            "initial_input": "写一个 possibilities(m, n) 找所有和为 m 的 n 项组合",
            "input_type": "requirement",
            "qa_history": [{"question": r1["questions"][0]["question"], "answer": "返回空列表 []"}],
        }).json()
        assert r2["ready"] is True
        assert r2["questions"] == []
        assert "返回 []" in r2["refined_requirement"]


def test_prepare_auto_augments_partial_only_mandatory_requirement():
    from backend.acceptance.models import (
        CanonicalSpec, CheckCase, ContractSpec, OrderedAssertion,
        RequirementItem, ReturnEqualsAssertion, TestPlan,
    )

    spec = CanonicalSpec(
        spec_id="SPEC-DRAFT",
        requirement_text_digest="返回所有组合并按字典序升序排列。",
        requirements=[
            RequirementItem(id="R1", statement="返回所有组合", origin="EXPLICIT", source_quote="返回所有组合"),
            RequirementItem(id="R2", statement="按字典序升序排列", origin="EXPLICIT", source_quote="按字典序升序排列"),
        ],
    )
    plan = TestPlan(
        contracts=[
            ContractSpec(contract_id="K_R1", requirement_ids=["R1"], description="组合", relation_to_requirement="EQUIVALENT", relation_basis="直接计算", oracle_origin="RULE_DERIVATION"),
            ContractSpec(contract_id="K_R2", requirement_ids=["R2"], description="升序", relation_to_requirement="NECESSARY", relation_basis="有序", oracle_origin="RULE_DERIVATION"),
        ],
        cases=[
            CheckCase(case_id="T1", contract_id="K_R1", requirement_ids=["R1"], args=[2, 2], assertion=ReturnEqualsAssertion(kind="RETURN_EQUALS", expected=[[0, 2], [1, 1], [2, 0]]), expected_basis="手工计算", input_domain_status="IN_SCOPE"),
            CheckCase(case_id="T2", contract_id="K_R2", requirement_ids=["R2"], args=[2, 2], assertion=OrderedAssertion(kind="ORDERED", direction="ASC", strict=False), expected_basis="按字典序升序", input_domain_status="IN_SCOPE"),
        ],
    )
    standards._ensure_complete_cases_for_partial_mandatory(spec, plan)
    body = standards.StandardConfirmation(
        requirement="返回所有组合并按字典序升序排列。",
        entrypoint=Entrypoint(callable="possibilities"),
        spec=spec,
        plan=plan,
        scope_note="仅验证已确认的固定案例。",
        confirmed=True,
        case_scope_confirmed=True,
    )
    record = standards.confirm(body)
    assert record["ok"] is True
    assert record["confirmed_spec_id"].startswith("STD-")


def test_repair_api_generates_compilable_candidate(monkeypatch):
    from backend.acceptance import llm_provider

    def fake_structured(task, payload, **kwargs):
        return {
            "fixed_code": "def add(a, b):\n    return a + b\n",
            "change_summary": "将减法改为加法。",
        }

    monkeypatch.setattr(llm_provider, "generate_structured", fake_structured)
    with TestClient(app) as client:
        resp = client.post("/api/acceptance/repair", json={
            "requirement": "返回两个整数之和",
            "code": "def add(a, b):\n    return a - b\n",
            "entrypoint": {"module": "solution", "callable": "add"},
            "failed_cases": [{"case_id": "T1", "args": [2, 3], "assertion": {"kind": "RETURN_EQUALS", "expected": 5}}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["validation_status"] == "UNVALIDATED"
        assert "return a + b" in data["fixed_code"]


def test_confirm_and_evaluate_api_end_to_end():
    with TestClient(app) as client:
        response = client.post("/api/acceptance/confirm", json=confirmation().model_dump())
        assert response.status_code == 200
        record = response.json()
        response = client.post("/api/acceptance/evaluate", json=request_for(record).model_dump())
        report = response.json()["report"]
        assert response.status_code == 200
        assert report["code_verdict"] == "PASS_WITHIN_SCOPE"
        assert report["test_plan"]["cases"][0]["args"] == [2,3]
        assert client.get("/acceptance.html").status_code == 200
        assert client.get("/static/acceptance.js").status_code == 200
        assert client.get("/api/acceptance/demos").json()["demos"]


def test_suggestions_include_real_inputs_expected_and_actual():
    record = standards.confirm(confirmation())
    report = evaluate(request_for(record, "def add(a, b):\n    return a - b\n"))
    suggestion = next(s for s in report.code_suggestions if s.finding_id == "T1")
    assert json.loads(suggestion.trigger_condition)["args"] == [2,3]
    assert json.loads(suggestion.expected) == 5
    assert json.loads(suggestion.actual)["return_value"] == -1
    assert suggestion.evidence_ids == [next(e.evidence_id for e in report.evidence if e.case_id == "T1")]


def test_model_receives_failure_facts_and_cannot_rewrite_observations(monkeypatch):
    record = standards.confirm(confirmation())
    helper = "def subtract(a, b):\n    return a - b\n"
    request = request_for(record, "from helper import subtract\ndef add(a, b):\n    return subtract(a, b)\n",
                          supporting_files=[{"path":"helper.py", "content":helper}])
    report = evaluate(request)
    ev = next(e for e in report.evidence if e.case_id == "T1")
    def fake(task, payload, **kwargs):
        assert "from helper import subtract" in payload["source_code"]
        assert payload["source_code_with_line_numbers"].startswith("1: from helper import subtract\n")
        assert payload["supporting_files"] == [{"path":"helper.py", "content":helper,
            "numbered_content":"1: def subtract(a, b):\n2:     return a - b", "truncated":False}]
        assert payload["failed_cases"][0]["args"] == [2,3]
        assert payload["failed_cases"][0]["assertion"]["expected"] == 5
        assert payload["failed_cases"][0]["observation"]["return_value"] == -1
        assert any(c["case_id"] == "T3" and c["status"] == "PASSED" for c in payload["checked_cases"])
        return {"suggestions":[{
            "category":"CORRECTNESS_FIX", "requirement_ids":["R1"], "evidence_ids":[ev.evidence_id],
            "expected":"999", "actual":"999", "trigger_condition":"伪造输入", "fix":"将减法改为加法",
        }]}
    monkeypatch.setattr(llm_provider, "is_available", lambda:True)
    monkeypatch.setattr(llm_provider, "generate_structured", fake)
    suggestions = recommender.build_suggestions(request, report.canonical_spec, report.test_plan,
        report.requirement_results, {}, report.code_verdict, evidence=report.evidence)
    suggestion = next(s for s in suggestions if s.finding_id == "T1")
    assert json.loads(suggestion.expected) == 5
    assert json.loads(suggestion.actual)["return_value"] == -1
    assert any(s.finding_id == "T2" for s in suggestions)  # 模型漏掉的缺陷由规则补全


def test_passing_evidence_cannot_be_borrowed_to_claim_defect(monkeypatch):
    record = standards.confirm(confirmation())
    request = request_for(record, "def add(a, b):\n    return a - b\n")
    report = evaluate(request)
    passed_ev = next(e for e in report.evidence if e.case_id == "T3")
    monkeypatch.setattr(llm_provider, "is_available", lambda:True)
    monkeypatch.setattr(llm_provider, "generate_structured", lambda *a, **k: {"suggestions":[{
        "category":"CORRECTNESS_FIX", "requirement_ids":["R1"], "evidence_ids":[passed_ev.evidence_id],
    }]})
    suggestions = recommender.build_suggestions(request, report.canonical_spec, report.test_plan,
        report.requirement_results, {}, report.code_verdict, evidence=report.evidence)
    assert suggestions[0].category == "POTENTIAL_RISK"
    assert suggestions[0].validation_status == "PENDING"


def test_quality_advice_in_same_report_without_hiding_function_result():
    record = standards.confirm(confirmation())
    report = evaluate(request_for(record, "def add(a, b):\n    return eval('a + b')\n"))
    assert report.code_verdict == "PASS_WITHIN_SCOPE"
    assert report.quality_report.status == "REVIEW_REQUIRED"
    assert report.usability == "REVIEW_REQUIRED"
    assert any(s.category == "POTENTIAL_RISK" and "eval" in s.explanation for s in report.code_suggestions)


@pytest.mark.parametrize("value, status", [(2,"PASSED"), (True,"ASSERTION_FAILED"), ("2","ASSERTION_FAILED")])
def test_return_type_is_strict(value, status):
    check = ReturnTypeAssertion(kind="RETURN_TYPE", expected_type="int")
    assert evaluate_assertion(check, {"return_value":value}).status == status


def test_scalar_predicate_rejects_negative_and_accepts_zero():
    check = ReturnMatchesAssertion(kind="RETURN_MATCHES", predicate={"op":"IS_NONNEGATIVE","value_type":"int"})
    assert evaluate_assertion(check, {"return_value":0}).passed
    assert evaluate_assertion(check, {"return_value":-1}).status == "ASSERTION_FAILED"


def test_environment_blockers_are_actionable(monkeypatch):
    monkeypatch.delenv("PYQ_ACCEPTANCE_ALLOW_HOST", raising=False)
    monkeypatch.setattr(runner, "_probe_docker", lambda:runner.ExecutionBackend("DOCKER",False,"daemon unavailable"))
    status = inspect_environment()
    assert status["ready_for_execution"] is False
    assert status["model_configured"] is False
    assert status["model_connection"] == "NOT_PROBED"
    assert any("Docker Desktop" in a for a in status["actions"])
    assert "DEEPSEEK_API_KEY" not in status.keys()


def test_docker_timeout_cleans_up_named_container(monkeypatch):
    monkeypatch.setattr(runner, "detect_execution_backend", lambda:runner.ExecutionBackend("DOCKER",True))
    commands = []
    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        if cmd[1] == "run":
            raise subprocess.TimeoutExpired(cmd, 1)
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    body = confirmation()
    evs, _ = runner.run_cases("def add(a,b):\n return a+b", [], body.entrypoint, body.plan.cases, "c","p","s")
    assert all(e.status == "TIMEOUT" for e in evs)
    name = commands[0][commands[0].index("--name")+1]
    assert commands[-1] == ["docker","rm","-f",name]
    assert "--user" in commands[0] and "--network" in commands[0]


def test_async_function_is_executed_not_serialized_as_coroutine():
    record = standards.confirm(confirmation())
    report = evaluate(request_for(record, "async def add(a, b):\n    return a + b\n"))
    assert report.code_verdict == "PASS_WITHIN_SCOPE"


def test_syntax_failure_always_has_compiler_backed_advice():
    report = evaluate(EvaluationRequest(requirement="实现整数相加", code="def add(:\n    pass\n"))
    assert report.code_verdict == "FAIL"
    advice = next(s for s in report.code_suggestions if s.finding_id == "TECH_COMPILE")
    assert "line 1" in advice.actual
    assert advice.evidence_ids == [next(e.evidence_id for e in report.evidence if e.phase == "COMPILE")]
