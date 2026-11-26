"""可重复的最终效果验收。默认真实 Docker；--live-model 验证真实提示词建议。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-model", action="store_true", help="使用现有模型配置验证真实提示词诊断")
    parser.add_argument("--local-demo", action="store_true", help="显式允许可信仓库示例用宿主子进程执行")
    parser.add_argument("--out", default="data/workflow_verification")
    args = parser.parse_args()
    if args.local_demo:
        os.environ["PYQ_ACCEPTANCE_ALLOW_HOST"] = "1"
    else:
        os.environ.pop("PYQ_ACCEPTANCE_ALLOW_HOST", None)
    from backend.acceptance import llm_provider, runner, standards
    from backend.acceptance.models import CanonicalSpec, EvaluationRequest, RequirementItem
    from backend.acceptance.models import TestPlan as Plan
    from backend.acceptance.service import evaluate
    from backend.ai import deepseek_client
    if not args.live_model:
        deepseek_client.is_available = lambda: False
    elif not llm_provider.is_available():
        raise SystemExit("--live-model 需要配置 DEEPSEEK_API_KEY")
    backend = runner.detect_execution_backend()
    if not backend.available:
        raise SystemExit("动态执行不可用：" + backend.detail)
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    summaries = []
    for path in sorted((ROOT / "samples" / "acceptance").glob("*.json")):
        demo = json.loads(path.read_text(encoding="utf-8"))
        # 案例来自仓库中可复核的验收样例，不从待测代码反推期望值。
        confirmation = standards.StandardConfirmation(
            requirement=demo["requirement"], entrypoint=demo["entrypoint"],
            confirmed=True, scope_note="操作者运行验收脚本，认可仓库样例的固定案例；结论不覆盖未测试输入。",
            spec=CanonicalSpec(spec_id="DEMO", requirements=[RequirementItem(
                id="R1", statement=demo["requirement"], source_quote=demo["requirement"], origin="EXPLICIT",
            )]),
            plan=Plan.model_validate({
                "contracts":[{"contract_id":"K1","requirement_ids":["R1"],"description":"固定样例验收",
                    "relation_to_requirement":"EQUIVALENT","relation_basis":"人工核对的固定样例",
                    "oracle_origin":"USER_EXAMPLE"}],
                "cases":[{"case_id":f"T{i}","contract_id":"K1","requirement_ids":["R1"],
                    "args":e["args"],"kwargs":e.get("kwargs",{}),
                    "assertion":e.get("assertion",{"kind":"RETURN_EQUALS","expected":e.get("expected")}),
                    "expected_basis":e["note"]} for i,e in enumerate(demo["examples"],1)],
            }),
        )
        standard = standards.confirm(confirmation)
        results = {}
        for label, code in [("wrong",demo["code"]),("correct",demo["correct_code"])]:
            report = evaluate(EvaluationRequest(
                requirement=demo["requirement"], generation_prompt=demo["generation_prompt"], code=code,
                entrypoint=demo["entrypoint"], options={"oracle_policy":"confirmed_only"},
                acceptance_materials={"confirmed_spec_id":standard["confirmed_spec_id"],
                    "confirmed_spec_hash":standard["confirmed_spec_hash"]},
            ))
            (output / f"{demo['id']}_{label}.json").write_text(report.model_dump_json(indent=2),encoding="utf-8")
            expected = "FAIL" if label == "wrong" else "PASS_WITHIN_SCOPE"
            assert report.code_verdict == expected, (demo["id"],label,report.model_dump())
            if label == "wrong":
                assert any(s.category == "CORRECTNESS_FIX" and s.evidence_ids for s in report.code_suggestions)
            if args.live_model:
                assert report.prompt_report.mode == "LLM"
                assert any(m.status == "CONFLICT" for m in report.prompt_report.mappings)
                assert report.prompt_report.changes
            results[label] = report
        assert results["wrong"].reproducibility.plan_hash == results["correct"].reproducibility.plan_hash
        row = {"demo":demo["id"],"isolation":backend.name,
            "wrong":results["wrong"].coverage.model_dump(),"correct":results["correct"].coverage.model_dump(),
            "same_plan":True,"prompt_mode":results["wrong"].prompt_report.mode}
        summaries.append(row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
    (output / "summary.json").write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding="utf-8")
    print("全部最终效果场景通过。报告目录：" + str(output.resolve()))


if __name__ == "__main__":
    main()
