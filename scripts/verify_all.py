"""核心功能综合验证脚本 — 验证所有分析器、AI能力、报告格式、对话交互。"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from backend.main import app
from backend.analyzers.parser import analyze_source

from backend.analyzers.smells import detect_smells
from backend.analyzers.readability import score_readability
from backend.analyzers.security import detect_security
from backend.analyzers.performance import detect_performance
from backend.analyzers.dead_code import analyze_dead_code
from backend.analyzers.dependencies import analyze_dependencies
from backend.analyzers.duplication import analyze_duplication
from backend.analyzers.type_hints import analyze_type_hints
from backend.analyzers.docstrings import analyze_docstrings
from backend.ai import deepseek_client, test_generator, fixer, advisor

SAMPLE = (ROOT / "samples" / "demo_project" / "grades.py").read_text(encoding="utf-8")

passed = 0
failed = 0
results = []


def check(name, ok, detail=""):
    global passed, failed
    mark = "✅" if ok else "❌"
    results.append(f"  {mark} {name}" + (f" — {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def section(title):
    results.append(f"\n{'='*60}")
    results.append(f"  {title}")
    results.append(f"{'='*60}")


# ============================================================
# 1. 分析器验证
# ============================================================
section("1. 分析器验证（11个）")

fa = analyze_source("grades.py", SAMPLE)

# 1.1 parser
check("parser: 解析4个函数", len(fa.functions) == 4, f"实际{len(fa.functions)}个: {[f.name for f in fa.functions]}")
check("parser: 无语法错误", not fa.parse_error, f"parse_error={repr(fa.parse_error)}")
check("parser: 总行数53", fa.total_lines == 53, f"实际{fa.total_lines}")

# 1.2 complexity
funcs = {f.name: f for f in fa.functions}
check("complexity: process_grades复杂度最高",
      funcs["process_grades"].complexity >= funcs["calculate_average"].complexity,
      f"process_grades={funcs['process_grades'].complexity}, calculate_average={funcs['calculate_average'].complexity}")
check("complexity: process_grades嵌套深", funcs["process_grades"].nesting >= 4,
      f"nesting={funcs['process_grades'].nesting}")

# 1.3 smells
smells = detect_smells([fa], {"grades.py": SAMPLE})
smell_types = {s["type"] for s in smells}
check("smells: 检测到bad_naming(findStudent)", "bad_naming" in smell_types)
check("smells: 检测到missing_docstring", "missing_docstring" in smell_types)
check("smells: 检测到broad_except", "broad_except" in smell_types)
check("smells: 检测到global_variable", "global_variable" in smell_types)
check("smells: 检测到deep_nesting", "deep_nesting" in smell_types)
check("smells: 检测到long_params", "long_params" in smell_types)
check(f"smells: 共{len(smells)}个坏味", len(smells) >= 7, f"类型: {sorted(smell_types)}")

# 1.4 readability
rd = score_readability([fa])
check("readability: 评分0-100", 0 <= rd["total"] <= 100, f"total={rd['total']}")
check("readability: 有等级", rd["grade"] in ("A", "B", "C", "D", "F"), f"grade={rd['grade']}")
check("readability: 有分项", len(rd["breakdown"]) > 0, f"{len(rd['breakdown'])}项")

# 1.5 security
sec = detect_security("grades.py", SAMPLE)
check("security: 示例无安全问题", len(sec) == 0, f"发现{len(sec)}个")

# 1.6 performance
perf = detect_performance("grades.py", SAMPLE)
check("performance: 检测完成", isinstance(perf, list), f"发现{len(perf)}个性能问题")

# 1.7 dead_code
dc = analyze_dead_code({"grades.py": SAMPLE})
check("dead_code: 有统计", "stats" in dc, f"stats={dc.get('stats', {})}")

# 1.8 dependencies
deps = analyze_dependencies({"grades.py": SAMPLE})
check("dependencies: 有统计", "stats" in deps, f"stats={deps.get('stats', {})}")

# 1.9 duplication
dup = analyze_duplication({"grades.py": SAMPLE})
check("duplication: 有统计", "stats" in dup, f"stats={dup.get('stats', {})}")

# 1.10 type_hints
th = analyze_type_hints({"grades.py": SAMPLE})
check("type_hints: 覆盖率<100%(示例缺注解)", th["stats"]["coverage"] < 100, f"coverage={th['stats']['coverage']}%")

# 1.11 docstrings
ds = analyze_docstrings({"grades.py": SAMPLE})
check("docstrings: 有统计", "stats" in ds, f"stats={ds.get('stats', {})}")


# ============================================================
# 2. 端到端API验证
# ============================================================
section("2. 端到端API验证")

client = TestClient(app)

# 2.1 健康检查
r = client.get("/api/health")
check("health: 服务正常", r.status_code == 200 and r.json()["ok"])

# 2.2 上传示例项目
r = client.post("/api/projects/sample")
check("upload: 创建示例项目", r.status_code == 200 and r.json()["ok"], f"status={r.status_code}")
pid = r.json().get("project", {}).get("id", "")
check("upload: 获得项目ID", bool(pid), f"pid={pid}")

# 2.3 分析项目
r = client.post(f"/api/projects/{pid}/analyze")
check("analyze: 分析成功", r.status_code == 200 and r.json()["ok"], f"status={r.status_code}")
analysis = r.json().get("result", {})
check("analyze: 有统计信息", "stats" in analysis, f"stats={analysis.get('stats', {})}")
check("analyze: 检测到坏味", len(analysis.get("smells", [])) >= 7,
      f"{len(analysis.get('smells', []))}个坏味")
check("analyze: 有可读性评分", "readability" in analysis)
check("analyze: 有函数列表", len(analysis.get("functions", [])) == 4,
      f"{len(analysis.get('functions', []))}个函数")

# 2.4 AI状态
r = client.get("/api/ai/status")
check("ai/status: 返回状态", r.status_code == 200)
ai_ok = r.json().get("available", False)
check("ai/status: AI可用", ai_ok, f"available={ai_ok}")


# ============================================================
# 3. AI能力验证
# ============================================================
section("3. AI能力验证（3个）")

import tempfile
tmp_dir = Path(tempfile.mkdtemp())
(tmp_dir / "grades.py").write_text(SAMPLE, encoding="utf-8")

# 3.1 测试生成
t0 = time.time()
r_tg = test_generator.generate_tests(tmp_dir, "grades.py", [])
tg_time = time.time() - t0
check("test_generator: 生成成功", r_tg["ok"], f"mode={r_tg.get('mode')}")
check("test_generator: 语法有效", r_tg.get("syntax_valid", False))
check("test_generator: 覆盖4个函数", len(r_tg.get("functions", [])) == 4,
      f"functions={r_tg.get('functions', [])}")
test_file = tmp_dir / r_tg["test_file"]
check("test_generator: 文件已创建", test_file.exists())
if test_file.exists():
    test_code = test_file.read_text(encoding="utf-8")
    check("test_generator: 包含test_函数", "def test_" in test_code)
    check("test_generator: 包含assert", "assert" in test_code)

# 3.2 代码修复
t0 = time.time()
smells_for_fix = [s for s in smells if s["file"] == "grades.py"]
r_fix = fixer.fix_code("grades.py", SAMPLE, smells_for_fix)
fix_time = time.time() - t0
check("fixer: 修复成功", r_fix["ok"], f"mode={r_fix.get('mode')}")
if r_fix["ok"] and r_fix["mode"] == "ai":
    fixed = r_fix["fixed_code"]
    import ast as _ast
    try:
        _ast.parse(fixed)
        check("fixer: 修复后语法正确", True)
    except SyntaxError:
        check("fixer: 修复后语法正确", False)
    check("fixer: 有diff_stats", "diff_stats" in r_fix, f"diff_stats={r_fix.get('diff_stats')}")
    fa_fixed = analyze_source("grades.py", fixed)
    smells_fixed = detect_smells([fa_fixed], {"grades.py": fixed})
    n_before = len(smells_for_fix)
    n_after = len([s for s in smells_fixed if s["file"] == "grades.py"])
    check("fixer: 坏味减少", n_after < n_before, f"修复前{n_before} → 修复后{n_after}")

# 3.3 改进建议
t0 = time.time()
r_adv = advisor.generate_advice("grades.py", SAMPLE, smells_for_fix)
adv_time = time.time() - t0
check("advisor: 生成成功", r_adv["ok"], f"mode={r_adv.get('mode')}")
check("advisor: 有建议内容", bool(r_adv.get("advice", "")))
check("advisor: 有建议条目", len(r_adv.get("items", [])) > 0,
      f"{len(r_adv.get('items', []))}条建议")


# ============================================================
# 4. 报告格式验证
# ============================================================
section("4. 报告格式验证（4种）")

# 4.1 Markdown
r = client.get(f"/api/projects/{pid}/report?format=markdown")
check("report(md): 200", r.status_code == 200, f"status={r.status_code}")
check("report(md): 含标题", "# 代码质量报告" in r.text)
check("report(md): 含坏味", "代码坏味" in r.text)

# 4.2 JSON
r = client.get(f"/api/projects/{pid}/report?format=json")
check("report(json): 200", r.status_code == 200)
try:
    j = r.json()
    check("report(json): 有效JSON", "stats" in j)
except Exception:
    check("report(json): 有效JSON", False)

# 4.3 SARIF
r = client.get(f"/api/projects/{pid}/report?format=sarif")
check("report(sarif): 200", r.status_code == 200)
try:
    s = r.json()
    check("report(sarif): SARIF格式", s.get("version") == "2.1.0" and "runs" in s)
except Exception:
    check("report(sarif): SARIF格式", False)

# 4.4 HTML
r = client.get(f"/api/projects/{pid}/report?format=html")
check("report(html): 200", r.status_code == 200)
check("report(html): 含DOCTYPE", "<!DOCTYPE html>" in r.text)
check("report(html): 含标题", "代码质量报告" in r.text)


# ============================================================
# 5. 对话交互验证
# ============================================================
section("5. 对话交互验证")

# 5.1 分析请求
r = client.post("/api/chat", json={"message": "分析", "project_id": pid})
check("chat: 分析请求", r.status_code == 200 and bool(r.json().get("reply", "")),
      f"status={r.status_code}")

# 5.2 生成测试请求
r = client.post("/api/chat", json={"message": "生成测试", "project_id": pid})
check("chat: 生成测试请求", r.status_code == 200 and bool(r.json().get("reply", "")),
      f"status={r.status_code}")

# 5.3 修复建议请求
r = client.post("/api/chat", json={"message": "修复", "project_id": pid})
check("chat: 修复请求", r.status_code == 200 and bool(r.json().get("reply", "")),
      f"status={r.status_code}")

# 5.4 改进建议请求
r = client.post("/api/chat", json={"message": "改进建议", "project_id": pid})
check("chat: 改进建议请求", r.status_code == 200 and bool(r.json().get("reply", "")),
      f"status={r.status_code}")

# 5.5 帮助请求
r = client.post("/api/chat", json={"message": "帮助"})
check("chat: 帮助请求", r.status_code == 200 and bool(r.json().get("reply", "")),
      f"status={r.status_code}")


# ============================================================
# 6. 其他功能验证
# ============================================================
section("6. 其他功能验证")

# 6.1 获取分析历史
r = client.get(f"/api/projects/{pid}/history")
check("history: 获取历史", r.status_code == 200 and r.json().get("ok", False))

# 6.2 获取缓存分析
r = client.get(f"/api/projects/{pid}/analysis")
check("cached: 获取缓存分析", r.status_code == 200 and r.json().get("ok", False))

# 6.3 单文件分析
r = client.post(f"/api/projects/{pid}/analyze-file", json={"file": "grades.py"})
check("analyze-file: 单文件分析", r.status_code == 200 and r.json().get("ok", False))

# 6.4 项目列表
r = client.get("/api/projects")
check("projects: 项目列表", r.status_code == 200)

# 6.5 配置
r = client.get("/api/config")
check("config: 获取配置", r.status_code == 200)

# 6.6 AI测试运行
r = client.post(f"/api/projects/{pid}/run-tests", json={"file": "grades.py"})
check("run-tests: 运行测试", r.status_code == 200)


# ============================================================
# 汇总
# ============================================================
section("验证汇总")

total = passed + failed
results.append(f"\n  总计: {total} 项")
results.append(f"  通过: {passed} 项 ✅")
results.append(f"  失败: {failed} 项 ❌")
results.append(f"  通过率: {round(passed/total*100, 1)}%")
results.append(f"\n  AI耗时: 测试生成{tg_time:.1f}s, 修复{fix_time:.1f}s, 建议{adv_time:.1f}s")

print("\n".join(results))
print()
sys.exit(0 if failed == 0 else 1)