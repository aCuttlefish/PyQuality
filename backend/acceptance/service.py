"""验收服务编排（M4，方案第 7 章端到端工作流）。

evaluate(request, configuration) -> EvaluationReport
核心服务独立于 HTTP、CLI 和 UI。判定、规格冻结、版本更新按依赖顺序执行。
"""
from __future__ import annotations

import time

from backend.acceptance import (
    hashing,
    llm_provider,
    prompt_auditor,
    recommender,
    review as review_mod,
    runner,
    spec_extractor,
    verdict as verdict_mod,
)
from backend.acceptance.fixtures import (

    max_even_plan,
    max_even_spec,
    payable_plan,
    payable_spec,
)
from backend.acceptance.models import (
    CanonicalSpec,
    CodeVerdict,
    CoverageSummary,
    Entrypoint,
    EvaluationReport,
    EvaluationRequest,
    Evidence,
    EvidenceStatus,
    PromptReport,
    ReproducibilityInfo,
    RequirementResult,
    StageResult,
    TestPlan,
)
from backend.logger import get_logger

logger = get_logger("acceptance_service")

TECH_RULE_VERSION = "tech-rules/1.0"



def _locate_entrypoint(request: EvaluationRequest) -> tuple[Entrypoint | None, str]:
    """入口定位：显式指定优先；否则 AST 静态定位；多候选记录歧义。"""
    if request.entrypoint:
        return request.entrypoint, ""
    import ast
    try:
        tree = ast.parse(request.code)
    except SyntaxError:
        return None, "代码有语法错误，无法静态定位入口"
    funcs = [
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not n.name.startswith("_")
    ]
    if len(funcs) == 1:
        return Entrypoint(module="solution", callable=funcs[0]), ""
    if not funcs:
        return None, "代码中未找到公开函数入口"
    return None, f"存在多个合理入口候选: {funcs}，需显式指定 entrypoint"


def evaluate(request: EvaluationRequest) -> EvaluationReport:
    """端到端验收。模型不可用时按确定降级路径执行并如实报告阻塞。"""
    t0 = time.monotonic()
    report = EvaluationReport()
    stages: list[StageResult] = []
    blockers: list[str] = []
    limitations: list[str] = [
        "MVP 未对任意 Python 与任意自然语言需求提供普遍正确性证明",
        "进程级隔离：无 Docker 网络隔离与 CPU/内存限额，非完备安全边界",
        "输入不变检查不检测『先修改再恢复』的瞬时写入",
    ]

    # ---- 阶段 A：输入与基础事实 ----
    ch = hashing.code_hash(
        request.code, [(f.path, f.content) for f in request.supporting_files]
    )
    entrypoint, entry_note = _locate_entrypoint(request)

    ok, compile_msg = runner.compile_check(request.code)
    compile_evidence: list[Evidence] = []
    if not ok:
        compile_evidence.append(Evidence(
            kind="STATIC_FACT", producer="compile_check",
            code_hash=ch, runtime_fingerprint=runner.runtime_fingerprint(),
            phase="COMPILE", observation={"error": compile_msg},
            status="ASSERTION_FAILED", technical_rule_version=TECH_RULE_VERSION,
        ))
    stages.append(StageResult(
        stage="A_input_and_compile",
        status="COMPLETED" if ok else "COMPLETED",
        detail=compile_msg or "编译检查通过",
        duration_ms=(time.monotonic() - t0) * 1000,
    ))

    # ---- 阶段 B：需求与规约（人工确认夹具 or LLM 候选） ----
    spec: CanonicalSpec | None = None
    plan: TestPlan | None = None
    spec_mode = "UNAVAILABLE"
    materials = request.acceptance_materials

    if materials.confirmed_spec_id:
        key = materials.confirmed_spec_id
        if key == "SPEC-MAX-EVEN":
            spec, plan = max_even_spec(), max_even_plan()
        elif key == "SPEC-PAYABLE":
            spec, plan = payable_spec(), payable_plan()
        else:
            blockers.append(f"未知 confirmed_spec_id: {key}")
        if spec is not None:
            if materials.confirmed_spec_hash and materials.confirmed_spec_hash != hashing.spec_hash(spec):
                blockers.append("confirmed_spec_hash 与登记规格不匹配，按未确认处理")
                spec.interpretation_status = "UNRESOLVED"
                for contract in plan.contracts:
                    contract.oracle_review = "PENDING"
            spec_mode = "FIXTURE"
    elif not spec:
        extraction = spec_extractor.extract_spec(request.requirement, entrypoint)
        if extraction.spec is not None:
            spec = extraction.spec
            spec_mode = "LLM_CANDIDATE"

    if spec is None:
        if not compile_evidence:
            blockers.append("需求提取不可用（模型未配置或校验失败），业务验收无法形成规格")

    # ---- 阶段 C/D：测试计划与审查冻结 ----
    if spec is not None and plan is None:
        plan_result = review_mod.build_plan(
            spec, request.acceptance_materials.trusted_examples
        )
        if plan_result.plan is not None:
            plan = plan_result.plan
            review_result = review_mod.review_spec_and_plan(spec, plan)
            review_mod.apply_review(spec, plan, review_result)
            if review_result.mode != "LLM":
                blockers.append("规约语义审查未执行（模型不可用），候选规格保持未确认")
        else:
            blockers.append(f"测试计划生成失败: {plan_result.error}")

    if spec is not None:
        spec = hashing.bind_spec(spec)
        if plan is not None:
            plan = hashing.bind_plan(plan, spec)
        stages.append(StageResult(
            stage="B_spec", status="COMPLETED",
            detail=f"规格模式 {spec_mode}，interpretation={spec.interpretation_status}",
        ))
    else:
        stages.append(StageResult(stage="B_spec", status="BLOCKED", detail="规格不可用"))

    # ---- 阶段 E：隔离执行（与提示词审查并行数据准备） ----
    evidence: list[Evidence] = list(compile_evidence)
    executed = False
    if plan is not None and entrypoint is not None and not compile_evidence:
        evidence_exec, logs = runner.run_cases(
            request.code,
            [(f.path, f.content) for f in request.supporting_files],
            entrypoint, plan.cases, ch, plan.plan_hash, spec.spec_hash,
        )
        evidence.extend(evidence_exec)
        executed = True
        stages.append(StageResult(
            stage="E_execute", status="COMPLETED",
            detail=f"{len(evidence_exec)} 条案例证据",
        ))
    elif compile_evidence:
        stages.append(StageResult(
            stage="E_execute", status="SKIPPED",
            detail="编译失败，动态执行跳过（A12：确定语法错误不需运行时反例）",
        ))
    elif plan is None or entrypoint is None:
        stages.append(StageResult(
            stage="E_execute", status="BLOCKED",
            detail=entry_note or "无可用测试计划",
        ))
        if entry_note:
            blockers.append(f"入口定位失败: {entry_note}")
        else:
            blockers.append("无可用测试计划，动态验收未执行")

    # ---- 判定（确定规则，模型不参与） ----
    requirement_results: list[RequirementResult] = []
    if spec is not None and plan is not None:
        vi = verdict_mod.VerdictInput(
            spec, plan, evidence, ch, spec.spec_hash, plan.plan_hash,
            request.options.oracle_policy,
        )
        cases_by_req: dict[str, list] = {}
        for c in plan.cases:
            for rid in c.requirement_ids:
                cases_by_req.setdefault(rid, []).append(c)
        contracts = {c.contract_id: c for c in plan.contracts}
        for r in spec.requirements:
            st, eids, fids, notes = verdict_mod.evaluate_requirement(
                r.id, vi, cases_by_req, contracts
            )
            requirement_results.append(RequirementResult(
                requirement_id=r.id, statement=r.statement, status=st,
                evidence_ids=eids, failed_case_ids=fids,
                explanation="; ".join(notes[:3]),
            ))

    # TECH_COMPILE 聚合
    compile_failed, _ = verdict_mod.compile_evidence_gate(evidence, ch)
    required_items = [{"status": rr.status} for rr in requirement_results]
    spec_ready = (
        spec is not None and plan is not None
        and verdict_mod.spec_is_ready(spec, request.options.oracle_policy, plan)
    )
    if compile_failed:
        required_items.append({"status": "FAIL"})
    verdict: CodeVerdict = verdict_mod.aggregate_verdict(required_items, spec_ready=spec_ready)

    # ---- 阶段 F：提示词诊断 + 建议 + 报告 ----
    prompt_report = PromptReport()
    if spec is not None:
        prompt_report = prompt_auditor.audit_prompt(request, spec)
        prompt_report.prompt_code_relation = prompt_auditor.relate_prompt_to_code(
            spec, prompt_report, requirement_results
        )
    stages.append(StageResult(
        stage="F_prompt_audit", status="COMPLETED",
        detail=f"mode={prompt_report.mode}",
    ))

    evidence_by_case: dict[str, str] = {}
    for ev in evidence:
        if ev.case_id:
            detail = ev.observation.get("check_detail") or ev.observation.get(
                "exception_message", ""
            ) or str(ev.observation.get("return_value", ""))
            evidence_by_case[ev.case_id] = f"{ev.status}: {detail}"

    suggestions: list = []
    if spec is not None and plan is not None:
        suggestions = recommender.build_suggestions(
            request, spec, plan, requirement_results, evidence_by_case, verdict
        )
    stages.append(StageResult(
        stage="F_suggestions",
        status="COMPLETED",
        detail=f"{len(suggestions)} 条建议",
    ))

    # ---- 汇总 ----
    coverage = CoverageSummary(
        mandatory_requirements=sum(
            1 for r in spec.requirements if r.mandatory
        ) if spec else 0,
        requirements_checked=len(requirement_results),
        cases_planned=len(plan.cases) if plan else 0,
        cases_executed=sum(1 for e in evidence if e.kind == "EXECUTED_CASE"),
        cases_passed=sum(
            1 for e in evidence
            if e.kind == "EXECUTED_CASE" and e.status == "PASSED"
        ),
        cases_failed=sum(
            1 for e in evidence
            if e.kind == "EXECUTED_CASE" and e.status == "ASSERTION_FAILED"
        ),
    )

    llm_blocked = not llm_provider.is_available()
    if llm_blocked:
        blockers.append("模型服务不可用：需求提取/语义审查/LLM 建议走确定降级路径")

    has_partial_work = (
        verdict != "INCONCLUSIVE"
        or bool(prompt_report.mappings)
        or bool(compile_evidence)
    )
    if not executed and spec is None and not has_partial_work:
        job_status = "FAILED"
    elif blockers:
        job_status = "PARTIAL"
    else:
        job_status = "COMPLETED"

    report.job_status = job_status
    report.code_verdict = verdict
    report.assurance_level = verdict_mod.assurance_for(
        [rr.status for rr in requirement_results]
    )
    report.spec_interpretation = spec.interpretation_status if spec else "UNRESOLVED"
    report.summary = _build_summary(
        verdict, requirement_results, compile_msg, spec_mode, entry_note
    )
    report.requirement_results = requirement_results
    report.prompt_report = prompt_report
    report.code_suggestions = suggestions
    report.evidence = evidence
    report.coverage = coverage
    report.blockers = blockers
    report.limitations = limitations
    report.stage_results = stages
    report.reproducibility = ReproducibilityInfo(
        code_hash=ch,
        spec_hash=spec.spec_hash if spec else "",
        plan_hash=plan.plan_hash if plan else "",
        runtime_fingerprint=runner.runtime_fingerprint(),
        request_hash=hashing.request_hash(request),
    )
    report.isolation_level = "SUBPROCESS_SANDBOX"
    return report


def _build_summary(
    verdict: str,
    requirement_results: list[RequirementResult],
    compile_msg: str,
    spec_mode: str,
    entry_note: str,
) -> str:
    if compile_msg:
        return f"代码存在确定的语法/编译错误（{compile_msg}），按当前需求解读判定 FAIL。"
    failed = [rr for rr in requirement_results if rr.status == "FAIL"]
    unknown = [rr for rr in requirement_results if rr.status == "UNKNOWN"]
    if verdict == "FAIL" and failed:
        parts = [f"需求「{rr.statement}」违反（{', '.join(rr.failed_case_ids)}）" for rr in failed]
        return "按当前需求解读，" + "；".join(parts) + "。"
    if verdict == "PASS_WITHIN_SCOPE":
        return "按当前需求解读，本轮检查通过（范围内已认可检查全部执行且通过）。"
    reasons = []
    if entry_note:
        reasons.append(f"入口定位失败: {entry_note}")
    if unknown:
        reasons.append(f"{len(unknown)} 项需求未能形成确定结论")
    if not requirement_results:
        reasons.append("未形成有效验收规格或计划")
    return "按当前需求解读，本轮无法判定（" + "；".join(reasons) + "）。"