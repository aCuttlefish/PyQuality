"""验收 CLI（M4，方案 13.1）。

用法:
  python -m backend.acceptance.cli evaluate --request request.json [--out report.json]
  python -m backend.acceptance.cli demo max_even-wrong|max_even-correct|payable-gt|payable-ge
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pyquality-acceptance")
    sub = parser.add_subparsers(dest="command", required=True)

    p_eval = sub.add_parser("evaluate", help="从 JSON 文件读取 R/P/C 并评估")
    p_eval.add_argument("--request", required=True, help="EvaluationRequest JSON 文件路径")
    p_eval.add_argument("--out", default="", help="报告输出 JSON 路径（默认打印到 stdout）")

    p_demo = sub.add_parser("demo", help="运行内置人工确认夹具演示（真实执行）")
    p_demo.add_argument("case", choices=["max_even-wrong", "max_even-correct", "payable-gt", "payable-ge"])

    args = parser.parse_args(argv)
    if args.command == "evaluate":
        return _cmd_evaluate(args)
    if args.command == "demo":
        return _cmd_demo(args)
    return 2


def _cmd_evaluate(args) -> int:
    from backend.acceptance.models import EvaluationRequest
    from backend.acceptance.service import evaluate

    path = Path(args.request)
    if not path.exists():
        print(f"错误: 请求文件不存在 {path}", file=sys.stderr)
        return 2
    try:
        request = EvaluationRequest(**json.loads(path.read_text(encoding="utf-8")))
    except Exception as e:
        print(f"错误: 请求格式无效: {e}", file=sys.stderr)
        return 2
    report = evaluate(request)
    data = report.model_dump()
    if args.out:
        Path(args.out).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"报告已写入 {args.out}")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    print(
        f"\nverdict={report.code_verdict} assurance={report.assurance_level} "
        f"job={report.job_status}",
        file=sys.stderr,
    )
    return 0


def _cmd_demo(args) -> int:
    from backend.acceptance.fixtures import (
        MAX_EVEN_CORRECT_CODE,
        MAX_EVEN_INPLACE_CODE,
        MAX_EVEN_REQUIREMENT,
        MAX_EVEN_WRONG_CODE,
        PAYABLE_GE_CODE,
        PAYABLE_GT_CODE,
        PAYABLE_REQUIREMENT,
    )
    from backend.acceptance.models import AcceptanceMaterials, Entrypoint, EvaluationRequest
    from backend.acceptance.service import evaluate

    table = {
        "max_even-wrong": (MAX_EVEN_REQUIREMENT, MAX_EVEN_WRONG_CODE, "SPEC-MAX-EVEN", "max_even"),
        "max_even-correct": (MAX_EVEN_REQUIREMENT, MAX_EVEN_CORRECT_CODE, "SPEC-MAX-EVEN", "max_even"),
        "payable-gt": (PAYABLE_REQUIREMENT, PAYABLE_GT_CODE, "SPEC-PAYABLE", "payable"),
        "payable-ge": (PAYABLE_REQUIREMENT, PAYABLE_GE_CODE, "SPEC-PAYABLE", "payable"),
    }
    req_text, code, spec_id, callable_name = table[args.case]
    request = EvaluationRequest(
        requirement=req_text,
        generation_prompt="",
        code=code,
        entrypoint=Entrypoint(module="solution", callable=callable_name),
        acceptance_materials=AcceptanceMaterials(confirmed_spec_id=spec_id),
    )
    report = evaluate(request)
    cov = report.coverage
    print(f"场景: {args.case}")
    print(f"verdict: {report.code_verdict}  assurance: {report.assurance_level}")
    print(f"案例: {cov.cases_passed} 通过 / {cov.cases_failed} 失败 / {cov.cases_executed} 执行")
    for rr in report.requirement_results:
        line = f"  {rr.requirement_id}: {rr.status}"
        if rr.failed_case_ids:
            line += f"（失败案例: {', '.join(rr.failed_case_ids)}）"
        print(line)
    print(f"阻塞: {report.blockers or '无'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())