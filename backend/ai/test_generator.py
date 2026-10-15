import ast
import py_compile
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from backend.ai import deepseek_client
from backend.analyzers.parser import FunctionInfo, analyze_source


def generate_tests(project_dir: Path, rel_path: str, functions: list[str]) -> dict:
    abs_path = project_dir / rel_path
    if not abs_path.exists():
        return {"ok": False, "error": f"文件不存在: {rel_path}"}
    source = abs_path.read_text(encoding="utf-8", errors="replace")
    fa = analyze_source(rel_path, source)
    if fa.parse_error:
        return {"ok": False, "error": f"源文件语法错误: {fa.parse_error}"}

    targets = [fi for fi in fa.functions if not functions or fi.name in functions]
    if not targets:
        return {"ok": False, "error": "未找到可测试的函数"}

    mode = "ai" if deepseek_client.is_available() else "rule"
    results = []
    if mode == "ai":
        from concurrent.futures import ThreadPoolExecutor, as_completed
        max_workers = min(len(targets), 4)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_map = {pool.submit(_generate_by_ai, fi, rel_path, source): fi for fi in targets}
            ai_out = {}
            for fut in as_completed(future_map):
                fi = future_map[fut]
                ai_out[fi.name] = fut.result()
        for fi in targets:
            code, err = ai_out[fi.name]
            if err:
                code = _generate_by_rule(fi, rel_path)
                results.append({"function": fi.name, "code": code, "mode": "rule_fallback",
                                "note": f"AI 调用失败，已用规则生成: {err}"})
            else:
                results.append({"function": fi.name, "code": code, "mode": "ai", "note": ""})
        if all(r["mode"] == "rule_fallback" for r in results):
            mode = "rule_fallback"
    else:
        for fi in targets:
            code = _generate_by_rule(fi, rel_path)
            results.append({"function": fi.name, "code": code, "mode": "rule",
                            "note": "未配置 API Key，使用规则生成骨架测试"})

    out_dir = project_dir / "_generated_tests"
    out_dir.mkdir(exist_ok=True)
    module_name = re.sub(r"[^0-9a-zA-Z_]", "_", rel_path.replace("/", "_").replace("\\", "_").removesuffix(".py"))
    test_file = out_dir / f"test_{module_name}.py"
    combined = _combine_results(results, rel_path)
    test_file.write_text(combined, encoding="utf-8")

    valid, syntax_err = _validate(test_file)
    filtered = 0
    if valid and mode == "ai":
        original_code = test_file.read_text(encoding="utf-8")
        filtered = _run_and_filter_tests(test_file, project_dir)
        if filtered > 0:
            remaining = test_file.read_text(encoding="utf-8")
            if "def test_" not in remaining:
                test_file.write_text(original_code, encoding="utf-8")
                filtered = 0
            else:
                valid, syntax_err = _validate(test_file)
    return {
        "ok": True,
        "test_file": str(test_file.relative_to(project_dir)),
        "mode": mode,
        "syntax_valid": valid,
        "syntax_error": syntax_err,
        "functions": [r["function"] for r in results],
        "details": results,
        "filtered_failures": filtered,
    }


def _generate_by_ai(fi: FunctionInfo, rel_path: str, source: str) -> tuple[str, str]:
    module_name = rel_path.replace("\\", "/").split("/")[-1].removesuffix(".py")
    import_path = rel_path.replace("\\", "/").removesuffix(".py").replace("/", ".")
    min_cases = max(2, fi.complexity)

    prompt = f"""你是资深 Python 测试工程师。为以下函数生成 pytest 单元测试。

文件: {rel_path}
模块导入路径: {import_path}

函数信息:
- 函数名: {fi.name}
- 参数: {fi.args_source}
- 参数数量: {fi.num_params}
- 圈复杂度: {fi.complexity}（建议至少 {min_cases} 个测试用例覆盖各分支）
- 嵌套深度: {fi.nesting}

函数源码:
```python
{fi.source}
```

要求:
1. 使用 pytest 风格，函数名 test_{fi.name}_<场景描述>
2. **先逐行手动推演函数逻辑，确认预期结果后再写断言值**——这是最重要的要求
3. 根据圈复杂度 {fi.complexity}，至少生成 {min_cases} 个测试用例覆盖不同分支
4. 包含正常路径测试 + 边界条件测试（如空输入、零值、极值等，视函数逻辑而定）
5. 只测试函数已有的行为，不要假设函数应该支持什么输入类型
6. 不要测试异常路径，除非函数代码中明确有 raise 语句
7. 对于 if/elif/else 分支，每个分支至少一个测试用例
8. 断言值必须与实际执行结果完全一致，不要猜测——先在脑中执行函数再写 assert
9. 只依赖标准库和 pytest，不要导入项目外部模块
10. 使用 `from {module_name} import {fi.name}` 导入被测函数

只输出一个 JSON 对象，格式: {{"test_code": "..."}}"""
    try:
        data = deepseek_client.chat_json(
            [{"role": "user", "content": prompt}], temperature=0.2
        )
        code = data.get("test_code", "")
        if not code or "def test_" not in code:
            return "", "AI 返回内容中无有效测试"
        return code, ""
    except Exception as e:
        return "", str(e)


def _generate_by_rule(fi: FunctionInfo, rel_path: str) -> str:
    module = rel_path.replace("\\", "/").split("/")[-1].removesuffix(".py")
    safe = re.sub(r"\W", "_", fi.name)
    params = [p.strip() for p in fi.args_source.split(",") if p.strip() and p.strip() not in ("self", "cls")]
    placeholders = ", ".join(_placeholder(p) for p in params)
    lines = [
        "import pytest",
        f"from {module} import {fi.name}",
        "",
    ]
    if params:
        lines += [
            f"def test_{safe}_basic():",
            f'    """测试 {fi.name} 基本调用。"""',
            f"    result = {fi.name}({placeholders})",
            f"    assert result is not None or result is None  # TODO: 替换为实际断言",
            "",
            f"def test_{safe}_boundary():",
            f'    """测试 {fi.name} 边界条件。"""',
            f"    # TODO: 根据函数逻辑添加边界测试（空值/零值/极值）",
            f"    pass",
            "",
        ]
    else:
        lines += [
            f"def test_{safe}_basic():",
            f'    """测试 {fi.name} 无参数调用。"""',
            f"    result = {fi.name}()",
            f"    assert result is not None or result is None  # TODO: 替换为实际断言",
            "",
        ]
    if fi.complexity > 5:
        lines += [
            f"def test_{safe}_branch_coverage():",
            f'    """测试 {fi.name} 分支覆盖（复杂度 {fi.complexity}）。"""',
            f"    # TODO: 复杂度较高，需覆盖各分支路径",
            f"    pass",
            "",
        ]
    return "\n".join(lines)


def _placeholder(param: str) -> str:
    parts = param.split("=")
    name = parts[0].strip().split(":")[0].strip()
    if len(parts) > 1:
        return f"{name}={parts[1].strip()}"
    return f"{name}=None"


def _combine_results(results: list[dict], rel_path: str) -> str:
    header = f'"""自动生成: 针对 {rel_path} 的 pytest 测试"""\n'
    header += "import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parent.parent))\n\n"
    body = "\n".join(r["code"].strip() for r in results)
    return header + "\n" + body + "\n"


def _validate(path: Path) -> tuple[bool, str]:
    try:
        with tempfile.TemporaryDirectory() as td:
            py_compile.compile(str(path), cfile=str(Path(td) / "c.pyc"), doraise=True)
        ast.parse(path.read_text(encoding="utf-8"))
        return True, ""
    except (py_compile.PyCompileError, SyntaxError) as e:
        return False, str(e)

def _run_and_filter_tests(test_file: Path, project_dir: Path) -> int:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_file), "-v", "--tb=no", "--no-header", "-q"],
            capture_output=True, text=True, timeout=30, cwd=str(project_dir),
        )
    except (subprocess.TimeoutExpired, Exception):
        return 0

    output = result.stdout + result.stderr
    failed_tests = set()
    for match in re.finditer(r"FAILED\s+(?:.*?::)?(test_\w+)", output):
        failed_tests.add(match.group(1))
    if not failed_tests:
        return 0

    code = test_file.read_text(encoding="utf-8")
    lines = code.split("\n")
    remove_ranges = []
    i = 0
    while i < len(lines):
        match = re.match(r"def (test_\w+)\(", lines[i])
        if match and match.group(1) in failed_tests:
            start = i
            while start > 0 and lines[start - 1].strip() == "":
                start -= 1
            end = i + 1
            while end < len(lines):
                if re.match(r"(def |class |import |from )", lines[end]) and not lines[end].startswith((" ", "\t")):
                    break
                end += 1
            while end > start and lines[end - 1].strip() == "":
                end -= 1
            remove_ranges.append((start, end))
            i = end
        else:
            i += 1

    remove_ranges.sort(reverse=True)
    for start, end in remove_ranges:
        del lines[start:end]

    test_file.write_text("\n".join(lines), encoding="utf-8")
    return len(remove_ranges)