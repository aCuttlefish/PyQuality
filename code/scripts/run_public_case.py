"""复现公开 Copilot 辅助项目的 BMI 小数输入缺陷。

上游源码按固定提交下载并核验 Git blob；原文件不做导入改写。
--replay 关闭模型调用，使用同一组人工核对案例重新执行 Docker 验收。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

COMMIT = "dd73f1dec21bfc31c7b7a089d240104285470d7c"
BLOB = "706880ec447547fde0edb862a1a603b9fca9670e"
SOURCE_URL = f"https://github.com/Sarthak-Sidhant/week/blob/{COMMIT}/monday/fitness-calculator.py"
README_URL = f"https://github.com/Sarthak-Sidhant/week/blob/{COMMIT}/README.md"
RAW_URL = f"https://raw.githubusercontent.com/Sarthak-Sidhant/week/{COMMIT}/monday/fitness-calculator.py"
REQUIREMENT = (
    "验收公开 fitness-calculator.py 的菜单 1（BMI）：体重的单位为千克，身高的单位为米，"
    "均支持正整数和正小数输入；计算体重除以身高的平方并输出数值。"
    "测试适配器模拟交互输入并提取输出数值供断言，不替代原程序的输入转换或计算。"
    "本轮结论仅覆盖列出的六组正数输入，不覆盖其他菜单、非法输入或任何医学建议。"
)

# 原脚本作为辅助文件原样执行。注释提供给代码建议模块的两个关键源代码位置。
ADAPTER = '''"""实验测试适配器；不修改或重写上游计算逻辑。
upstream_fitness.py:35 weight=int(input("What is your weight in kg?"))
upstream_fitness.py:36 height=int(input("What is your height in meters?"))
"""
import io
from contextlib import redirect_stdout
from pathlib import Path
import runpy
from unittest.mock import patch


def calculate_bmi(weight, height):
    output = io.StringIO()
    answers = ["1", str(weight), str(height), "n"]
    with patch("builtins.input", side_effect=answers), redirect_stdout(output):
        runpy.run_path(str(Path(__file__).with_name("upstream_fitness.py")), run_name="__main__")
    for line in output.getvalue().splitlines():
        if line.startswith("Your BMI is "):
            return float(line.removeprefix("Your BMI is "))
    raise RuntimeError("Upstream program did not print a BMI value")
'''


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load_source():
    path = ROOT / "data" / "public_case_research" / "fitness-calculator.original.py"
    if not path.exists():
        request = urllib.request.Request(RAW_URL, headers={"User-Agent": "PyQuality-case-reproduction"})
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    raw = path.read_bytes()
    actual_blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if actual_blob != BLOB:
        raise RuntimeError(f"上游文件 Git blob 不一致：{actual_blob}，拒绝运行")
    return raw, raw.decode("utf-8")


def make_cases():
    pairs = [(100, 2), (80, 2), (70, 1.75), (72, 1.5), (50, 1.25), (72.5, 1)]
    cases = []
    for i, (weight, height) in enumerate(pairs, 1):
        # 使用十进制文字构造有理数，独立核对预期，不从候选实现计算 expected。
        result = Fraction(str(weight)) / Fraction(str(height)) ** 2
        cases.append({
            "case_id": f"BMI{i:02d}", "requirement_ids": ["R1"], "contract_id": "K_BMI",
            "args": [weight, height], "kwargs": {}, "input_domain_status": "IN_SCOPE",
            "assertion": {"kind": "RETURN_EQUALS", "expected": float(result)},
            "expected_basis": f"按公开源码注释声明的单位和公式独立核算：{weight} / ({height}²) = {result}",
        })
    return cases


def make_standard(cases):
    from backend.acceptance.standards import StandardConfirmation
    statement = "体重的单位为千克，身高的单位为米，均支持正整数和正小数输入；计算体重除以身高的平方并输出数值。"
    return StandardConfirmation.model_validate({
        "requirement": REQUIREMENT,
        "entrypoint": {"module": "solution", "callable": "calculate_bmi"},
        "confirmed": True, "case_scope_confirmed": True,
        "scope_note": "复现实验操作者独立核对六组输入及完整数值预期；不是上游作者的测试记录，结论仅限本轮案例。",
        "spec": {"spec_id": "PUBLIC-BMI-DRAFT", "requirements": [{
            "id": "R1", "statement": statement, "source_quote": statement,
            "origin": "EXPLICIT", "mandatory": True, "kind": "FUNCTIONAL",
        }]},
        "plan": {"plan_id": "PUBLIC-BMI-PLAN", "contracts": [{
            "contract_id": "K_BMI", "requirement_ids": ["R1"],
            "description": "六组固定输入完整预期；精确比较输出解析后的浮点值",
            "relation_to_requirement": "EQUIVALENT",
            "relation_basis": "充分性仅限声明的六组固定输入，未测试输入不作结论",
            "oracle_origin": "USER_EXAMPLE",
        }], "cases": cases},
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", action="store_true", help="关闭模型调用；新结果写入 data/public_case_replay")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    os.environ.pop("PYQ_ACCEPTANCE_ALLOW_HOST", None)
    from backend.acceptance import runner, standards, llm_provider
    from backend.acceptance.models import EvaluationRequest
    from backend.acceptance.service import evaluate
    from backend.ai import deepseek_client

    backend = runner.detect_execution_backend()
    if backend.name != "DOCKER" or not backend.available:
        raise SystemExit("需要启动 Docker Desktop；本实验不在宿主机执行上游程序")
    if args.replay:
        deepseek_client.is_available = lambda: False
    elif not llm_provider.is_available():
        raise SystemExit("初次留证需要已配置的模型服务；离线复现请使用 --replay")

    raw, original = load_source()
    weight_line = '        weight=int(input("What is your weight in kg?"))'
    height_line = '        height=int(input("What is your height in meters?"))'
    if original.count(height_line) != 1 or weight_line not in original:
        raise RuntimeError("关键源代码位置与固定提交不符")
    # 本次修复由实验操作者实施；只改菜单 1 的两处数值转换，不声称由原作者或模型生成。
    corrected = original.replace(weight_line, weight_line.replace("int(input", "float(input"), 1)
    corrected = corrected.replace(height_line, height_line.replace("int(input", "float(input"), 1)
    folder = ROOT / ("data/public_case_replay" if args.replay else "docs/public_case")
    folder.mkdir(parents=True, exist_ok=True)
    cases = make_cases()
    confirmation = standards.confirm(make_standard(cases))
    write_json(folder / "confirmation.json", confirmation)
    (folder / "adapter.py").write_text(ADAPTER, encoding="utf-8")
    provenance = {
        "repository": "https://github.com/Sarthak-Sidhant/week", "source_url": SOURCE_URL,
        "readme_url": README_URL, "commit": COMMIT, "source_commit_date": "2022-11-09T14:49:03Z",
        "git_blob": BLOB, "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_bytes": len(raw), "original_source_unmodified": True,
        "ai_provenance": "作者在 README 声明借助 GitHub Copilot 开发；无法核验每一行的具体生成者。",
        "original_prompt": "未公开；本实验留空，不据此推断原提示词的错误或缺失。",
        "dataset_url": "https://zenodo.org/records/14565942",
        "dataset_note": "公开研究数据集保存了同名源码及该仓库来源；本次小数输入功能缺陷由我们独立复现，不是论文已报告的安全缺陷。",
        "test_author": "本次 PyQuality 复现实验操作者，根据原程序菜单单位和公式独立编写",
        "repair_author": "本次复现实验操作者；将 BMI 分支的 weight/height 输入转换从 int 改为 float",
        "scope": "六组正数 BMI 输入；不代表上游全部功能通过，不验证非法输入或医学用途",
        "reproduced_at": datetime.now(timezone.utc).isoformat(),
    }
    archive_path = ROOT / "data/public_case_research/dataset.zip"
    if archive_path.exists():
        import zipfile
        with zipfile.ZipFile(archive_path) as archive:
            names = [n for n in archive.namelist() if n.endswith("/case4/fitness-calculator.py")]
            if len(names) == 1:
                snapshot = archive.read(names[0])
                provenance["dataset_source_member"] = names[0]
                provenance["dataset_snapshot_matches"] = snapshot.replace(b"\r\n", b"\n") == raw.replace(b"\r\n", b"\n")
    write_json(folder / "provenance.json", provenance)
    reports = {}
    for phase, source in (("initial", original), ("repaired", corrected)):
        request = EvaluationRequest(
            requirement=REQUIREMENT, generation_prompt="", code=ADAPTER,
            supporting_files=[{"path": "upstream_fitness.py", "content": source}],
            entrypoint={"module": "solution", "callable": "calculate_bmi"},
            generation_context={"is_complete": False, "requirements_also_visible": None,
                "additional_messages": ["上游原始提示词未公开。不得将空字段当成原提示词；只能给出后续生成代码可采用的新提示词建议。"]},
            options={"oracle_policy": "confirmed_only"},
            acceptance_materials={"confirmed_spec_id": confirmation["confirmed_spec_id"],
                "confirmed_spec_hash": confirmation["confirmed_spec_hash"]},
        )
        # 请求包含下载源码，保存在忽略目录；可提交的报告只保留证据和来源。
        cache = ROOT / "data/public_case_research"
        write_json(cache / f"{phase}_request.json", request.model_dump())
        report = evaluate(request)
        reports[phase] = report
        write_json(folder / f"{phase}_report.json", report.model_dump())
        print(json.dumps({"phase": phase, "verdict": report.code_verdict,
            "coverage": report.coverage.model_dump(), "isolation": report.isolation_level,
            "prompt_mode": report.prompt_report.mode}, ensure_ascii=False), flush=True)

    first, repaired = reports["initial"], reports["repaired"]
    same_plan = first.reproducibility.plan_hash == repaired.reproducibility.plan_hash
    source_hash_changed = first.reproducibility.code_hash != repaired.reproducibility.code_hash
    rows = []
    for case in cases:
        row = {"case_id": case["case_id"], "input": case["args"], "expected": case["assertion"]["expected"]}
        for phase, report in reports.items():
            evidence = next(e for e in report.evidence if e.case_id == case["case_id"] and e.kind == "EXECUTED_CASE")
            row[phase] = {"status": evidence.status, "observation": evidence.observation}
        rows.append(row)
    summary = {"source_url": SOURCE_URL, "same_plan": same_plan,
        "same_adapter": True, "adapter_sha256": hashlib.sha256(ADAPTER.encode()).hexdigest(),
        "source_code_hash_changed": source_hash_changed,
        "initial_verdict": first.code_verdict, "repaired_verdict": repaired.code_verdict,
        "initial": first.coverage.model_dump(), "repaired": repaired.coverage.model_dump(),
        "isolation": first.isolation_level, "cases": rows, "scope": provenance["scope"]}
    write_json(folder / "summary.json", summary)
    prompt = first.prompt_report.optimized_prompt
    (folder / "recommended_prompt.txt").write_text(
        "以下是 PyQuality 本轮提出的新提示词建议，不是上游原始提示词；本次未用它重新生成代码。\n\n" + prompt,
        encoding="utf-8",
    )
    table = "\n".join(
        f"{row['case_id']} | {row['input'][0]} kg | {row['input'][1]} m | {row['expected']} | "
        f"{row['initial']['status']} | {row['repaired']['status']}"
        for row in rows
    )
    (folder / "case_report.txt").write_text(
        f"公开项目案例：Copilot 辅助开发的 BMI 计算器拒绝小数输入\n\n"
        f"原仓库：{provenance['repository']}\n原文件（固定提交）：{SOURCE_URL}\n"
        f"AI 来源说明：{README_URL}\n源码提交时间：{provenance['source_commit_date']}\n"
        f"Git blob：{BLOB}\nSHA-256：{provenance['source_sha256']}\n\n"
        "真实性边界：作者说明项目借助 GitHub Copilot 开发；没有逐行生成日志或原始提示词。"
        "本案例可称为公开 AI 辅助项目的真实功能缺陷，不能称为已证实全部由 AI 生成的生产事故。"
        "研究数据集用于核对来源，本文的功能缺陷和测试结果由本次实验独立获得。\n\n"
        "需求来自原程序声明的单位和公式：千克 / 米²。小数身高为正常使用输入。"
        "验收标准和六个案例由本次实验操作者编写，预期使用有理数独立核算。"
        "上游源码未改动，以辅助文件原样执行；adapter.py 只模拟 input 并提取 print 的数值，"
        "既不拦截原程序的 ValueError，也不替代原始计算。\n\n"
        f"运行环境：{first.isolation_level}，隔离容器中执行；固定测试计划相同：{same_plan}\n"
        f"计划哈希：{first.reproducibility.plan_hash}\n\n"
        "案例 | 体重 | 身高 | 预期数值 | 原程序 | 修复后\n" + table + "\n\n"
        f"原程序：{first.code_verdict}，通过 {first.coverage.cases_passed}/6，"
        f"失败 {first.coverage.cases_failed}/6。四项失败均是原程序解析小数时抛出 ValueError。\n"
        "本次留存的 LLM 报告将缺陷定位到 upstream_fitness.py:35-36，建议输入转换使用 float。"
        "--replay 时建议模块降级为规则模式；请在 docs/public_case/initial_report.json 查看原始模型建议。"
        "修改由本次实验操作者实施，仅改 BMI 分支两处转换。\n"
        f"修复后：{repaired.code_verdict}，通过 {repaired.coverage.cases_passed}/6。"
        "适配器和标准未变，其他菜单尚未验收，静态质量仍有改进建议。\n\n"
        "提示词：上游原始提示词未知，不能推断缺陷由提示词遗漏造成。"
        "recommended_prompt.txt 留存本次 PyQuality 的新提示词建议；未据此重新生成代码，"
        "因此本案例不声称已验证提示词对重新生成成功率的提升。\n\n"
        "答辩表述：我们选择一个公开的 Copilot 辅助项目，保留原代码。"
        "程序在整数样例下能运行，但面对常见的小数身高就崩溃。"
        "PyQuality 用独立标准发现失败，给出带执行证据的修改建议；人工按建议修改两行后，"
        "复用同一组测试，通过数从 2/6 提升为 6/6。\n\n"
        "复现命令（在仓库根目录运行，需要 Docker）：\n"
        ".\\.venv\\Scripts\\python.exe scripts\\run_public_case.py --replay\n"
        "--replay 关闭模型调用，结果写入 data/public_case_replay，保留 docs 中本次真实模型报告。"
        "首次没有源码缓存时会下载固定提交的原文件并核验 Git blob；有缓存后可断网复现。\n",
        encoding="utf-8",
    )
    if not (same_plan and first.code_verdict == "FAIL" and first.coverage.cases_passed == 2
            and first.coverage.cases_failed == 4
            and repaired.code_verdict == "PASS_WITHIN_SCOPE" and repaired.coverage.cases_passed == 6):
        raise RuntimeError("实际结果与预期不同，已保留真实报告供检查")
    print("公开案例已完成：原样上游代码 2/6，人工两行修复后同标准 6/6。", flush=True)


if __name__ == "__main__":
    main()
