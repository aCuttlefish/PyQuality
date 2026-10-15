"""AI 输出验收测试 — 对应 docs/ai_acceptance_criteria.md 中的 A-E 维度。"""
import ast
import json
import py_compile
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

from backend.ai import advisor, deepseek_client, fixer, test_generator
from backend.analyzers.parser import analyze_source
from backend.analyzers.smells import detect_smells

SAMPLE_CODE = textwrap.dedent("""\
    def calculate_average(grades):
        total = 0
        for g in grades:
            total = total + g
        if len(grades) == 0:
            return 0
        return total / len(grades)

    def findStudent(students, name):
        for s in students:
            if s == name:
                return True
        return False
""")

SMELLY_CODE = textwrap.dedent("""\
    def bad_function(a, b, c, d, e, f, g):
        result = 0
        for i in range(a):
            for j in range(b):
                for k in range(c):
                    if i > 0:
                        if j > 0:
                            if k > 0:
                                result = result + i + j + k
        try:
            result = result / 0
        except:
            pass
        return result
""")


@pytest.fixture
def project_dir(tmp_path):
    (tmp_path / "mod.py").write_text(SAMPLE_CODE, encoding="utf-8")
    (tmp_path / "smelly.py").write_text(SMELLY_CODE, encoding="utf-8")
    return tmp_path


@pytest.fixture
def smells_for_smelly():
    fa = analyze_source("smelly.py", SMELLY_CODE)
    smells = detect_smells([fa], {"smelly.py": SMELLY_CODE})
    return [s for s in smells if s["file"] == "smelly.py"]


def _run_pytest_collect(test_file: Path) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "--collect-only", "-q"],
        capture_output=True, text=True, timeout=15, cwd=str(test_file.parent),
    )
    return result.returncode == 0, result.stderr + result.stdout


def _run_pytest_execute(test_file: Path) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-q", "--tb=short"],
        capture_output=True, text=True, timeout=30, cwd=str(test_file.parent),
    )
    has_import_error = "ImportError" in result.stderr or "ModuleNotFoundError" in result.stderr
    has_collection_error = "ERROR" in result.stdout and "collected 0 items" in result.stdout
    return not has_import_error and not has_collection_error, result.stdout + result.stderr


class TestAStructuralValidity:
    """A 维度：结构合法性"""

    def test_A1_test_syntax_valid(self, project_dir):
        r = test_generator.generate_tests(project_dir, "mod.py", [])
        assert r["ok"]
        assert r["syntax_valid"] is True, f"语法错误: {r.get('syntax_error')}"

    def test_A2_fix_syntax_valid(self, smells_for_smelly):
        r = fixer.fix_code("smelly.py", SMELLY_CODE, smells_for_smelly)
        if r["mode"] == "ai":
            v = fixer.validate_fixed(SMELLY_CODE, r["fixed_code"])
            assert v["valid"] is True, f"修复后语法错误: {v.get('error')}"

    def test_A3_json_format(self, monkeypatch, project_dir):
        monkeypatch.setattr(deepseek_client, "is_available", lambda: True)
        monkeypatch.setattr(deepseek_client, "chat_json", lambda *a, **kw: {"test_code": "def test_foo():\n    assert True\n"})
        r = test_generator.generate_tests(project_dir, "mod.py", ["calculate_average"])
        assert r["ok"]
        assert r["mode"] == "ai"

    def test_A4_advice_nonempty_markdown(self, smells_for_smelly):
        r = advisor.generate_advice("smelly.py", SMELLY_CODE, smells_for_smelly)
        assert r["ok"]
        assert r["advice"]
        assert "#" in r["advice"] or "-" in r["advice"]


class TestBFunctionalUsability:
    """B 维度：功能可用性"""

    def test_B1_pytest_collectable(self, project_dir):
        r = test_generator.generate_tests(project_dir, "mod.py", [])
        test_file = project_dir / r["test_file"]
        ok, output = _run_pytest_collect(test_file)
        assert ok, f"pytest 收集失败:\n{output}"

    def test_B2_pytest_executable(self, project_dir):
        r = test_generator.generate_tests(project_dir, "mod.py", [])
        test_file = project_dir / r["test_file"]
        ok, output = _run_pytest_execute(test_file)
        assert ok, f"pytest 执行有 import/collection error:\n{output}"

    def test_B3_fix_compilable(self, monkeypatch, smells_for_smelly):
        monkeypatch.setattr(deepseek_client, "is_available", lambda: True)
        fixed_code = SMELLY_CODE.replace("except:", "except ZeroDivisionError:")
        monkeypatch.setattr(deepseek_client, "chat_json", lambda *a, **kw: {
            "fixed_code": fixed_code,
            "explanation": "收窄异常捕获",
            "changes": [{"line": 10, "type": "broad_except", "desc": "except: -> except ZeroDivisionError:"}],
        })
        r = fixer.fix_code("smelly.py", SMELLY_CODE, smells_for_smelly)
        assert r["ok"]
        compile(r["fixed_code"], "<test>", "exec")

    def test_B4_fix_preserves_signatures(self, monkeypatch, smells_for_smelly):
        monkeypatch.setattr(deepseek_client, "is_available", lambda: True)
        fixed_code = SMELLY_CODE.replace("except:", "except ZeroDivisionError:")
        monkeypatch.setattr(deepseek_client, "chat_json", lambda *a, **kw: {
            "fixed_code": fixed_code, "explanation": "修复", "changes": [],
        })
        r = fixer.fix_code("smelly.py", SMELLY_CODE, smells_for_smelly)
        v = fixer.validate_fixed(SMELLY_CODE, r["fixed_code"])
        assert v["valid"] is True
        assert "warning" not in v or "bad_function" not in v.get("warning", "")

    def test_B5_fix_compile_exec(self, monkeypatch, smells_for_smelly):
        monkeypatch.setattr(deepseek_client, "is_available", lambda: True)
        fixed_code = SMELLY_CODE.replace("except:", "except ZeroDivisionError:")
        monkeypatch.setattr(deepseek_client, "chat_json", lambda *a, **kw: {
            "fixed_code": fixed_code, "explanation": "修复", "changes": [],
        })
        r = fixer.fix_code("smelly.py", SMELLY_CODE, smells_for_smelly)
        compile(r["fixed_code"], "<test>", "exec")


class TestCSemanticCorrectness:
    """C 维度：语义正确性"""

    def test_C1_test_references_target_function(self, monkeypatch, project_dir):
        monkeypatch.setattr(deepseek_client, "is_available", lambda: True)
        monkeypatch.setattr(deepseek_client, "chat_json", lambda *a, **kw: {
            "test_code": "def test_calculate_average_basic():\n    assert calculate_average([1,2,3]) == 2.0\n"
        })
        r = test_generator.generate_tests(project_dir, "mod.py", ["calculate_average"])
        combined_code = (project_dir / r["test_file"]).read_text(encoding="utf-8")
        assert "calculate_average" in combined_code

    def test_C2_test_has_meaningful_assertion(self, monkeypatch, project_dir):
        monkeypatch.setattr(deepseek_client, "is_available", lambda: True)
        monkeypatch.setattr(deepseek_client, "chat_json", lambda *a, **kw: {
            "test_code": "def test_calculate_average():\n    assert calculate_average([1,2,3]) == 2.0\n"
        })
        r = test_generator.generate_tests(project_dir, "mod.py", ["calculate_average"])
        combined_code = (project_dir / r["test_file"]).read_text(encoding="utf-8")
        lines = [l.strip() for l in combined_code.split("\n")]
        meaningful = [l for l in lines if l.startswith("assert ") and "assert True" not in l and l != "assert callable(lambda: None) or True"]
        assert len(meaningful) > 0, "所有断言都是 assert True，无有意义断言"

    def test_C3_fix_smells_not_increase(self, monkeypatch, smells_for_smelly):
        monkeypatch.setattr(deepseek_client, "is_available", lambda: True)
        fixed_code = textwrap.dedent("""\
            def bad_function(a, b, c, d, e, f, g):
                result = _compute_inner(a, b, c)
                try:
                    result = result / 0
                except ZeroDivisionError:
                    pass
                return result

            def _compute_inner(a, b, c):
                result = 0
                for i in range(a):
                    for j in range(b):
                        for k in range(c):
                            if i > 0 and j > 0 and k > 0:
                                result += i + j + k
                return result
        """)
        monkeypatch.setattr(deepseek_client, "chat_json", lambda *a, **kw: {
            "fixed_code": fixed_code, "explanation": "提取子函数+收窄异常", "changes": [],
        })
        r = fixer.fix_code("smelly.py", SMELLY_CODE, smells_for_smelly)
        assert r["ok"]
        fa_fixed = analyze_source("smelly.py", r["fixed_code"])
        smells_fixed = detect_smells([fa_fixed], {"smelly.py": r["fixed_code"]})
        assert len(smells_fixed) <= len(smells_for_smelly), f"坏味增加: {len(smells_for_smelly)} -> {len(smells_fixed)}"

    def test_C4_advice_line_matches_smells(self, smells_for_smelly):
        r = advisor.generate_advice("smelly.py", SMELLY_CODE, smells_for_smelly)
        smell_lines = {s["line"] for s in smells_for_smelly}
        for item in r["items"]:
            assert item["line"] in smell_lines, f"建议行号 {item['line']} 不在坏味行号集合 {smell_lines} 中"

    def test_C5_advice_type_is_known(self, smells_for_smelly):
        from backend.analyzers.smells import SUGGESTIONS
        known_types = set(SUGGESTIONS.keys())
        r = advisor.generate_advice("smelly.py", SMELLY_CODE, smells_for_smelly)
        for item in r["items"]:
            assert item["type"] in known_types, f"未知坏味类型: {item['type']}"

    def test_C6_advice_actionable(self, smells_for_smelly):
        r = advisor.generate_advice("smelly.py", SMELLY_CODE, smells_for_smelly)
        assert r["advice"]
        actionable_keywords = ["建议", "修改", "替换", "提取", "拆分", "收窄", "补充", "改为", "使用"]
        has_actionable = any(kw in r["advice"] for kw in actionable_keywords)
        assert has_actionable, "建议中无可操作内容"


class TestDRobustness:
    """D 维度：鲁棒性"""

    def test_D1_ai_unavailable_degrades_to_rule(self, project_dir):
        r = test_generator.generate_tests(project_dir, "mod.py", [])
        assert r["ok"]
        assert r["mode"] == "rule"

    def test_D2_ai_invalid_content_falls_back(self, monkeypatch, project_dir):
        monkeypatch.setattr(deepseek_client, "is_available", lambda: True)
        monkeypatch.setattr(deepseek_client, "chat_json", lambda *a, **kw: {"test_code": "no test here"})
        r = test_generator.generate_tests(project_dir, "mod.py", ["calculate_average"])
        assert r["ok"]
        assert r["mode"] == "rule" or "rule_fallback" in r["mode"]

    def test_D3_ai_timeout_no_crash(self, monkeypatch, project_dir):
        monkeypatch.setattr(deepseek_client, "is_available", lambda: True)
        def _timeout(*a, **kw):
            raise deepseek_client.DeepSeekError("请求超时")
        monkeypatch.setattr(deepseek_client, "chat_json", _timeout)
        r = test_generator.generate_tests(project_dir, "mod.py", ["calculate_average"])
        assert r["ok"]
        assert "rule" in r["mode"]

    def test_D4_empty_smells_returns_none(self):
        r_fix = fixer.fix_code("mod.py", SAMPLE_CODE, [])
        assert r_fix["ok"]
        assert r_fix["mode"] == "none"

        r_adv = advisor.generate_advice("mod.py", SAMPLE_CODE, [])
        assert r_adv["ok"]
        assert r_adv["mode"] == "none"

    def test_D5_source_syntax_error_returns_error(self, tmp_path):
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("def broken(:\n    pass\n", encoding="utf-8")
        r = test_generator.generate_tests(tmp_path, "bad.py", [])
        assert r["ok"] is False
        assert "error" in r


class TestEDegradedQuality:
    """E 维度：降级质量"""

    def test_E1_rule_test_syntax_valid(self, project_dir):
        r = test_generator.generate_tests(project_dir, "mod.py", [])
        assert r["mode"] == "rule"
        assert r["syntax_valid"] is True

    def test_E2_rule_test_pytest_collectable(self, project_dir):
        r = test_generator.generate_tests(project_dir, "mod.py", [])
        test_file = project_dir / r["test_file"]
        ok, output = _run_pytest_collect(test_file)
        assert ok, f"规则模式测试收集失败:\n{output}"

    def test_E3_rule_advice_covers_all_smells(self, smells_for_smelly):
        r = advisor.generate_advice("smelly.py", SMELLY_CODE, smells_for_smelly)
        assert r["mode"] == "rule"
        assert len(r["items"]) == len(smells_for_smelly), f"建议 {len(r['items'])} 条 != 坏味 {len(smells_for_smelly)} 条"

    def test_E4_rule_advice_sorted_by_severity(self, smells_for_smelly):
        r = advisor.generate_advice("smelly.py", SMELLY_CODE, smells_for_smelly)
        items = r["items"]
        sev_order = {"high": 0, "medium": 1, "low": 2}
        for i in range(len(items) - 1):
            cur = sev_order.get(items[i]["severity"], 3)
            nxt = sev_order.get(items[i + 1]["severity"], 3)
            assert cur <= nxt, f"建议未按严重程度排序: {items[i]['severity']} 在 {items[i+1]['severity']} 前"

class TestSignatureValidation:
    """签名校验：AI 修复不得静默改变公开函数签名。"""

    SRC = textwrap.dedent("""\
        def public_fn(a, b, c=1):
            return a + b + c

        def _private(x):
            return x
    """)

    def test_unchanged_signature_no_warning(self):
        fixed = self.SRC + "\n"
        v = fixer.validate_fixed(self.SRC, fixed)
        assert v["valid"] is True
        assert "warning" not in v

    def test_removed_parameter_flagged(self):
        fixed = self.SRC.replace("def public_fn(a, b, c=1):", "def public_fn(a, b):")
        v = fixer.validate_fixed(self.SRC, fixed)
        assert v["valid"] is True
        assert "签名变更" in v["warning"]
        assert "public_fn" in v["warning"]

    def test_renamed_parameter_flagged(self):
        fixed = self.SRC.replace("def public_fn(a, b, c=1):", "def public_fn(a, x, c=1):")
        v = fixer.validate_fixed(self.SRC, fixed)
        assert v["valid"] is True
        assert "签名变更" in v["warning"]

    def test_added_required_parameter_flagged(self):
        fixed = self.SRC.replace("def public_fn(a, b, c=1):", "def public_fn(a, b, c, d):")
        v = fixer.validate_fixed(self.SRC, fixed)
        assert v["valid"] is True
        assert "签名变更" in v["warning"]

    def test_missing_public_function_flagged(self):
        fixed = "def _private(x):\n    return x\n"
        v = fixer.validate_fixed(self.SRC, fixed)
        assert v["valid"] is False
        assert "缺少公开函数" in v["error"]

    def test_private_signature_change_not_flagged(self):
        fixed = self.SRC.replace("def _private(x):", "def _private(x, y):")
        v = fixer.validate_fixed(self.SRC, fixed)
        assert v["valid"] is True
        assert "签名变更" not in v.get("warning", "")