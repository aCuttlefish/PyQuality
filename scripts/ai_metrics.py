"""AI 输出量化验收脚本 — 对示例项目实际运行 AI 功能，计算量化指标并生成验收报告。

运行: python scripts/ai_metrics.py
输出: docs/ai_acceptance_report.md + 控制台摘要
"""
import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.ai import advisor, deepseek_client, fixer, test_generator
from backend.analyzers.parser import analyze_source
from backend.analyzers.smells import detect_smells, SUGGESTIONS
from backend.analyzers.readability import score_readability

SAMPLE = (ROOT / "samples" / "demo_project" / "grades.py").read_text(encoding="utf-8")

THRESHOLDS = {
    "test_syntax_pass_rate": 95,
    "test_collect_pass_rate": 90,
    "test_execute_pass_rate": 50,
    "test_function_coverage": 80,
    "test_assertion_density": 0.9,
    "test_bug_detection_rate": 40,
    "fix_syntax_preserve_rate": 95,
    "fix_function_count_preserve_rate": 90,
    "fix_smell_reduction_rate": 30,
    "fix_compile_rate": 95,
    "advice_smell_coverage": 90,
    "advice_line_accuracy": 90,
    "advice_type_accuracy": 95,
    "advice_actionable_rate": 80,
}

BUG_VARIANTS = {
    "bug_minus": SAMPLE.replace("total = total + s", "total = total - s"),
    "bug_neq": SAMPLE.replace('s["id"] == id', 's["id"] != id'),
    "bug_div_weight": SAMPLE.replace("scores[subject] * weight", "scores[subject] / weight"),
}


def run_pytest(test_file: Path, cwd: Path) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "--tb=line", "-v"],
        capture_output=True, text=True, timeout=30, cwd=str(cwd),
    )
    output = result.stdout + result.stderr
    summary = re.search(r"(\d+)\s+passed", output)
    fail = re.search(r"(\d+)\s+failed", output)
    err = re.search(r"(\d+)\s+error", output)
    passed = int(summary.group(1)) if summary else 0
    failed = int(fail.group(1)) if fail else 0
    errors = int(err.group(1)) if err else 0
    return {"passed": passed, "failed": failed, "errors": errors, "output": output, "returncode": result.returncode}


def collect_pytest(test_file: Path, cwd: Path) -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "--collect-only", "-q"],
        capture_output=True, text=True, timeout=15, cwd=str(cwd),
    )
    return result.returncode == 0


def count_assertions(code: str) -> int:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            count += 1
    return count


def count_test_functions(code: str) -> int:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return 0
    return sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("test_"))


def get_signatures(code: str) -> set[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    sigs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            sigs.add(node.name)
    return sigs


def measure_test_generation(tmp_base: Path) -> dict:
    metrics = {}
    ai_available = deepseek_client.is_available()
    metrics["ai_available"] = ai_available

    project_dir = tmp_base / "test_gen"
    project_dir.mkdir()
    (project_dir / "grades.py").write_text(SAMPLE, encoding="utf-8")

    fa = analyze_source("grades.py", SAMPLE)
    target_functions = [fi.name for fi in fa.functions]
    metrics["target_functions"] = target_functions

    r = test_generator.generate_tests(project_dir, "grades.py", [])
    metrics["mode"] = r["mode"]
    metrics["syntax_valid"] = r.get("syntax_valid", False)

    test_file = project_dir / r["test_file"]
    test_code = test_file.read_text(encoding="utf-8")

    metrics["collect_ok"] = collect_pytest(test_file, project_dir)

    exec_result = run_pytest(test_file, project_dir)
    total = exec_result["passed"] + exec_result["failed"]
    metrics["passed"] = exec_result["passed"]
    metrics["failed"] = exec_result["failed"]
    metrics["errors"] = exec_result["errors"]
    metrics["execute_pass_rate"] = round(exec_result["passed"] / total * 100, 1) if total else 0.0

    covered = [fn for fn in target_functions if fn in test_code]
    metrics["covered_functions"] = covered
    metrics["function_coverage"] = round(len(covered) / len(target_functions) * 100, 1) if target_functions else 0.0

    n_assertions = count_assertions(test_code)
    n_tests = count_test_functions(test_code)
    metrics["n_assertions"] = n_assertions
    metrics["n_tests"] = n_tests
    metrics["assertion_density"] = round(n_assertions / n_tests, 2) if n_tests else 0.0

    detected_bugs = []
    for bug_name, bug_code in BUG_VARIANTS.items():
        bug_dir = tmp_base / f"bug_{bug_name}"
        bug_dir.mkdir()
        (bug_dir / "grades.py").write_text(bug_code, encoding="utf-8")
        shutil.copy2(test_file, bug_dir / test_file.name)
        bug_result = run_pytest(bug_dir / test_file.name, bug_dir)
        if bug_result["failed"] > 0:
            detected_bugs.append(bug_name)
    metrics["injected_bugs"] = list(BUG_VARIANTS.keys())
    metrics["detected_bugs"] = detected_bugs
    metrics["bug_detection_rate"] = round(len(detected_bugs) / len(BUG_VARIANTS) * 100, 1)

    return metrics


def measure_fix(tmp_base: Path) -> dict:
    metrics = {}
    project_dir = tmp_base / "fix"
    project_dir.mkdir()
    (project_dir / "grades.py").write_text(SAMPLE, encoding="utf-8")

    fa = analyze_source("grades.py", SAMPLE)
    smells = detect_smells([fa], {"grades.py": SAMPLE})
    smells_for_file = [s for s in smells if s["file"] == "grades.py"]
    metrics["smells_before"] = len(smells_for_file)

    r = fixer.fix_code("grades.py", SAMPLE, smells_for_file)
    metrics["mode"] = r["mode"]
    metrics["ok"] = r["ok"]

    if r["ok"] and r["mode"] == "ai":
        fixed = r["fixed_code"]
        try:
            ast.parse(fixed)
            metrics["syntax_preserved"] = True
        except SyntaxError:
            metrics["syntax_preserved"] = False

        try:
            compile(fixed, "<test>", "exec")
            metrics["compilable"] = True
        except Exception:
            metrics["compilable"] = False

        src_sigs = get_signatures(SAMPLE)
        fixed_sigs = get_signatures(fixed)
        public_before = {s for s in src_sigs if not s.startswith("_")}
        public_after = {s for s in fixed_sigs if not s.startswith("_")}
        metrics["function_count_preserved"] = len(public_after) >= len(public_before)

        fa_fixed = analyze_source("grades.py", fixed)
        smells_fixed = detect_smells([fa_fixed], {"grades.py": fixed})
        smells_after = len([s for s in smells_fixed if s["file"] == "grades.py"])
        metrics["smells_after"] = smells_after
        metrics["smell_reduction_rate"] = round(
            (metrics["smells_before"] - smells_after) / metrics["smells_before"] * 100, 1
        ) if metrics["smells_before"] else 0.0
    else:
        metrics["syntax_preserved"] = False
        metrics["compilable"] = False
        metrics["function_count_preserved"] = False
        metrics["smells_after"] = metrics["smells_before"]
        metrics["smell_reduction_rate"] = 0.0

    return metrics


def measure_advice(tmp_base: Path) -> dict:
    metrics = {}
    fa = analyze_source("grades.py", SAMPLE)
    smells = detect_smells([fa], {"grades.py": SAMPLE})
    smells_for_file = [s for s in smells if s["file"] == "grades.py"]
    metrics["total_smells"] = len(smells_for_file)

    r = advisor.generate_advice("grades.py", SAMPLE, smells_for_file)
    metrics["mode"] = r["mode"]
    metrics["advice_length"] = len(r.get("advice", ""))
    items = r.get("items", [])
    metrics["n_items"] = len(items)

    smell_lines = {s["line"] for s in smells_for_file}
    smell_types = {s["type"] for s in smells_for_file}
    line_matches = sum(1 for item in items if item.get("line") in smell_lines)
    type_matches = sum(1 for item in items if item.get("type") in smell_types)

    metrics["line_accuracy"] = round(line_matches / len(items) * 100, 1) if items else 0.0
    metrics["type_accuracy"] = round(type_matches / len(items) * 100, 1) if items else 0.0
    metrics["smell_coverage"] = round(len(items) / len(smells_for_file) * 100, 1) if smells_for_file else 0.0

    actionable_keywords = ["建议", "修改", "替换", "提取", "拆分", "收窄", "补充", "改为", "使用", "移除", "添加", "重命名"]
    actionable = sum(1 for item in items if any(kw in item.get("suggestion", "") for kw in actionable_keywords))
    metrics["actionable_rate"] = round(actionable / len(items) * 100, 1) if items else 0.0

    return metrics


def evaluate(metrics: dict) -> dict:
    results = {}
    tg = metrics["test_generation"]
    fx = metrics["fix"]
    adv = metrics["advice"]

    checks = {
        "test_syntax_pass_rate": (100.0 if tg["syntax_valid"] else 0.0, THRESHOLDS["test_syntax_pass_rate"]),
        "test_collect_pass_rate": (100.0 if tg["collect_ok"] else 0.0, THRESHOLDS["test_collect_pass_rate"]),
        "test_execute_pass_rate": (tg["execute_pass_rate"], THRESHOLDS["test_execute_pass_rate"]),
        "test_function_coverage": (tg["function_coverage"], THRESHOLDS["test_function_coverage"]),
        "test_assertion_density": (tg["assertion_density"], THRESHOLDS["test_assertion_density"]),
        "test_bug_detection_rate": (tg["bug_detection_rate"], THRESHOLDS["test_bug_detection_rate"]),
        "fix_syntax_preserve_rate": (100.0 if fx.get("syntax_preserved") else 0.0, THRESHOLDS["fix_syntax_preserve_rate"]),
        "fix_function_count_preserve_rate": (100.0 if fx.get("function_count_preserved") else 0.0, THRESHOLDS["fix_function_count_preserve_rate"]),
        "fix_smell_reduction_rate": (fx.get("smell_reduction_rate", 0.0), THRESHOLDS["fix_smell_reduction_rate"]),
        "fix_compile_rate": (100.0 if fx.get("compilable") else 0.0, THRESHOLDS["fix_compile_rate"]),
        "advice_smell_coverage": (adv["smell_coverage"], THRESHOLDS["advice_smell_coverage"]),
        "advice_line_accuracy": (adv["line_accuracy"], THRESHOLDS["advice_line_accuracy"]),
        "advice_type_accuracy": (adv["type_accuracy"], THRESHOLDS["advice_type_accuracy"]),
        "advice_actionable_rate": (adv["actionable_rate"], THRESHOLDS["advice_actionable_rate"]),
    }

    for name, (actual, threshold) in checks.items():
        passed = actual >= threshold
        results[name] = {"actual": actual, "threshold": threshold, "passed": passed}

    return results


def generate_report(metrics: dict, eval_results: dict) -> str:
    tg = metrics["test_generation"]
    fx = metrics["fix"]
    adv = metrics["advice"]
    ai_status = "✅ 已连接" if metrics["ai_available"] else "⚠ 未配置（规则模式）"

    lines = [
        "# PyQuality AI 输出量化验收报告",
        f"\n> 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"> AI 状态: {ai_status}",
        f"> 测试输入: `samples/demo_project/grades.py`（{len(tg['target_functions'])} 个函数）\n",
    ]

    passed_count = sum(1 for v in eval_results.values() if v["passed"])
    total_count = len(eval_results)
    lines.append(f"## 总览\n\n- 验收指标: **{total_count}** 项")
    lines.append(f"- 通过: **{passed_count}** 项  失败: **{total_count - passed_count}** 项")
    lines.append(f"- 通过率: **{round(passed_count / total_count * 100, 1)}%**\n")

    lines.append("## 1. 测试生成指标\n")
    lines.append(f"| 指标 | 实测值 | 阈值 | 结果 |")
    lines.append(f"| --- | --- | --- | --- |")
    for k in ["test_syntax_pass_rate", "test_collect_pass_rate", "test_execute_pass_rate", "test_function_coverage", "test_assertion_density", "test_bug_detection_rate"]:
        v = eval_results[k]
        mark = "✅" if v["passed"] else "❌"
        unit = "" if k == "test_assertion_density" else "%"
        lines.append(f"| {k} | {v['actual']}{unit} | ≥{v['threshold']}{unit} | {mark} |")
    lines.append(f"\n**详情:**")
    lines.append(f"- 目标函数: {tg['target_functions']}")
    lines.append(f"- 已覆盖: {tg['covered_functions']}")
    lines.append(f"- 测试函数数: {tg['n_tests']}, 断言数: {tg['n_assertions']}")
    lines.append(f"- pytest 结果: {tg['passed']} passed, {tg['failed']} failed, {tg['errors']} errors")
    lines.append(f"- 注入 BUG: {tg['injected_bugs']}")
    lines.append(f"- 检出 BUG: {tg['detected_bugs']}\n")

    lines.append("## 2. 代码修复指标\n")
    lines.append(f"| 指标 | 实测值 | 阈值 | 结果 |")
    lines.append(f"| --- | --- | --- | --- |")
    for k in ["fix_syntax_preserve_rate", "fix_function_count_preserve_rate", "fix_smell_reduction_rate", "fix_compile_rate"]:
        v = eval_results[k]
        mark = "✅" if v["passed"] else "❌"
        lines.append(f"| {k} | {v['actual']}% | ≥{v['threshold']}% | {mark} |")
    lines.append(f"\n**详情:**")
    lines.append(f"- 修复前坏味: {fx['smells_before']}, 修复后坏味: {fx['smells_after']}")
    lines.append(f"- 模式: {fx['mode']}\n")

    lines.append("## 3. 改进建议指标\n")
    lines.append(f"| 指标 | 实测值 | 阈值 | 结果 |")
    lines.append(f"| --- | --- | --- | --- |")
    for k in ["advice_smell_coverage", "advice_line_accuracy", "advice_type_accuracy", "advice_actionable_rate"]:
        v = eval_results[k]
        mark = "✅" if v["passed"] else "❌"
        lines.append(f"| {k} | {v['actual']}% | ≥{v['threshold']}% | {mark} |")
    lines.append(f"\n**详情:**")
    lines.append(f"- 总坏味: {adv['total_smells']}, 建议条数: {adv['n_items']}")
    lines.append(f"- 模式: {adv['mode']}\n")

    lines.append("## 4. 不达标项\n")
    failed = {k: v for k, v in eval_results.items() if not v["passed"]}
    if not failed:
        lines.append("✅ 全部指标达标。")
    else:
        for k, v in failed.items():
            unit = "" if k == "test_assertion_density" else "%"
            lines.append(f"- ❌ **{k}**: 实测 {v['actual']}{unit}，阈值 ≥{v['threshold']}{unit}")

    return "\n".join(lines)


def main():
    print("=" * 60)
    print("PyQuality AI 输出量化验收")
    print("=" * 60)

    ai_available = deepseek_client.is_available()
    print(f"\nAI 状态: {'✅ 已连接' if ai_available else '⚠ 未配置（将使用规则模式）'}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_base = Path(tmp)

        print("\n[1/3] 度量测试生成...")
        t0 = time.time()
        tg = measure_test_generation(tmp_base)
        print(f"  完成 ({time.time() - t0:.1f}s) — 模式: {tg['mode']}, 通过率: {tg['execute_pass_rate']}%, BUG检出: {tg['bug_detection_rate']}%")

        print("[2/3] 度量代码修复...")
        t0 = time.time()
        fx = measure_fix(tmp_base)
        print(f"  完成 ({time.time() - t0:.1f}s) — 模式: {fx['mode']}, 坏味消除: {fx.get('smell_reduction_rate', 0)}%")

        print("[3/3] 度量改进建议...")
        t0 = time.time()
        adv = measure_advice(tmp_base)
        print(f"  完成 ({time.time() - t0:.1f}s) — 模式: {adv['mode']}, 坏味覆盖: {adv['smell_coverage']}%")

    metrics = {"ai_available": ai_available, "test_generation": tg, "fix": fx, "advice": adv}
    eval_results = evaluate(metrics)

    report = generate_report(metrics, eval_results)
    report_path = ROOT / "docs" / "ai_acceptance_report.md"
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    print("\n" + "=" * 60)
    passed = sum(1 for v in eval_results.values() if v["passed"])
    total = len(eval_results)
    print(f"验收结果: {passed}/{total} 指标通过 ({round(passed / total * 100, 1)}%)")
    print(f"报告已保存: {report_path}")
    print("=" * 60)

    failed = {k: v for k, v in eval_results.items() if not v["passed"]}
    if failed:
        print("\n❌ 不达标项:")
        for k, v in failed.items():
            unit = "" if k == "test_assertion_density" else "%"
            print(f"  {k}: {v['actual']}{unit} < {v['threshold']}{unit}")
    else:
        print("\n✅ 全部指标达标!")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())