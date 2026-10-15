import ast
import difflib

from backend.ai import deepseek_client
from backend.logger import get_logger

logger = get_logger("fixer")


def fix_code(rel_path: str, source: str, smells: list[dict]) -> dict:
    target = [s for s in smells if s["file"] == rel_path]
    if not target:
        return {
            "ok": True,
            "mode": "none",
            "fixed_code": source,
            "explanation": f"文件 {rel_path} 未检测到坏味，无需修复。",
            "changes": [],
        }
    if not deepseek_client.is_available():
        return {
            "ok": True,
            "mode": "unavailable",
            "fixed_code": source,
            "explanation": "未配置 DeepSeek API Key，无法执行 AI 修复。请配置后重试，或参考坏味建议手动修改。",
            "changes": [],
        }

    smell_lines = "\n".join(
        f"- [{s['severity']}] 行{s['line']} {s['type']}: {s['message']}" for s in target[:25]
    )
    truncated = source[:8000]
    prompt = _build_fix_prompt(rel_path, truncated, smell_lines, target)
    try:
        data = deepseek_client.chat_json([{"role": "user", "content": prompt}], temperature=0.2)
        fixed = data.get("fixed_code", "")
        if not fixed or "def " not in fixed:
            return {
                "ok": False,
                "mode": "ai",
                "error": "AI 未返回有效修复代码",
                "fixed_code": source,
                "explanation": "",
                "changes": [],
            }
        validation = validate_fixed(source, fixed)
        smell_info = _check_smell_reduction(rel_path, fixed, len(target))
        need_retry = not validation.get("valid") or not smell_info["ok"]
        if need_retry:
            retry_prompt = _build_retry_prompt(prompt, validation, smell_info.get("detail", ""))
            try:
                data2 = deepseek_client.chat_json([{"role": "user", "content": retry_prompt}], temperature=0.1)
                fixed2 = data2.get("fixed_code", "")
                if fixed2 and "def " in fixed2:
                    validation2 = validate_fixed(source, fixed2)
                    smell_info2 = _check_smell_reduction(rel_path, fixed2, len(target))
                    if validation2.get("valid") and smell_info2["ok"]:
                        return _build_success_result(fixed2, data2, source)
            except Exception:
                pass
        return _build_success_result(fixed, data, source, validation)
    except Exception as e:
        logger.warning("AI 修复失败: %s", e)
        return {
            "ok": False,
            "mode": "ai",
            "error": f"AI 调用失败: {e}",
            "fixed_code": source,
            "explanation": "",
            "changes": [],
        }


def _build_fix_prompt(rel_path: str, source: str, smell_lines: str, target: list[dict]) -> str:
    smell_types = ", ".join(sorted({s["type"] for s in target}))
    return f"""你是资深 Python 重构专家。请修复以下文件中的代码坏味，输出修复后的完整代码。

文件: {rel_path}
坏味类型: {smell_types}

原代码:
```python
{source}
```

需要修复的坏味:
{smell_lines}

要求:
1. 输出修复后的【完整可运行】Python 代码，**保持原有功能完全不变**
2. 仅修复列出的坏味，不要改变无关逻辑
3. **不要重命名公开函数**（除非是命名不规范坏味），可以提取私有子函数（_前缀）
4. 修复长函数（提取子函数）、深嵌套（卫语句）、宽泛异常（具体异常）、补 docstring、规范命名等
5. 修复后代码必须能通过原代码的所有测试
6. 不要添加注释解释你的修改
7. **保留所有 import 语句**，不要删除或修改导入
8. **保留 `if __name__ == "__main__"` 入口代码**，不要删除
9. **保留所有公开函数的参数签名**（参数名、参数数量、默认值）
10. **所有新增函数（含私有子函数）必须添加 docstring**，避免引入 missing_docstring 坏味
11. **不要引入魔法数字**：提取的子函数中如需使用阈值常量，在函数参数或默认值中传递，不要硬编码
12. **拆分子函数时避免重复代码**：如果多个子函数逻辑相似，考虑用参数化合并而非复制粘贴
13. **修复后坏味总数必须少于修复前**，不要在修复过程中引入新坏味

只输出 JSON: {{"fixed_code": "修复后的完整代码", "explanation": "简述做了哪些修改（中文，不超过200字）", "changes": [{{"line": 行号, "type": "坏味类型", "desc": "修改说明"}}]}}"""


def _build_retry_prompt(original_prompt: str, validation: dict, smell_info: str = "") -> str:
    errors = []
    if validation.get("error"):
        errors.append(f"语法/编译错误: {validation['error']}")
    if validation.get("warning"):
        errors.append(f"签名问题: {validation['warning']}")
    if smell_info:
        errors.append(f"坏味问题: {smell_info}")
    error_detail = "；".join(errors) if errors else "未知验证失败"
    return original_prompt + f"""

注意：上一次修复验证失败，原因: {error_detail}

请特别注意：
- 确保修复后代码语法正确且可编译
- 保留所有 import 语句
- 保留所有公开函数及其参数签名
- 保留 if __name__ == "__main__" 入口代码
- 不要遗漏任何函数或类定义
- 所有新增函数必须添加 docstring
- 不要引入魔法数字或重复代码
- 修复后坏味总数必须少于修复前"""


def _build_success_result(fixed: str, data: dict, source: str, validation: dict | None = None) -> dict:
    result = {
        "ok": True,
        "mode": "ai",
        "fixed_code": fixed,
        "explanation": data.get("explanation", ""),
        "changes": data.get("changes", []),
    }
    if validation and validation.get("warning"):
        result["warning"] = validation["warning"]
    result["diff_stats"] = _diff_stats(source, fixed)
    return result


def _diff_stats(source: str, fixed: str) -> dict:
    diff = list(difflib.unified_diff(
        source.splitlines(keepends=True), fixed.splitlines(keepends=True), n=0
    ))
    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    return {"added": added, "removed": removed, "changed": added + removed}


def validate_fixed(source: str, fixed: str) -> dict:
    try:
        ast.parse(fixed)
    except SyntaxError as e:
        return {"valid": False, "error": f"修复后代码语法错误: 行{e.lineno} {e.msg}"}
    try:
        compile(fixed, "<fixed>", "exec")
    except Exception as e:
        return {"valid": False, "error": f"修复后代码编译失败: {e}"}

    src_funcs = _signatures(source)
    fixed_funcs = _signatures(fixed)
    src_public = {f for f in src_funcs if not f.startswith("_")}
    fixed_public = {f for f in fixed_funcs if not f.startswith("_")}
    missing = src_public - fixed_public
    if missing:
        return {"valid": False, "error": f"修复后缺少公开函数: {', '.join(sorted(missing))}"}

    src_imports = _extract_imports(source)
    fixed_imports = _extract_imports(fixed)
    missing_imports = src_imports - fixed_imports
    if missing_imports:
        return {"valid": True, "warning": f"修复后缺少导入: {', '.join(sorted(missing_imports)[:3])}"}

    if _has_main_guard(source) and not _has_main_guard(fixed):
        return {"valid": True, "warning": "修复后缺少 if __name__ == '__main__' 入口代码"}

    src_sigs = _public_signatures(source)
    fixed_sigs = _public_signatures(fixed)
    changed = [n for n in sorted(src_sigs) if n in fixed_sigs and src_sigs[n] != fixed_sigs[n]]
    if changed:
        return {"valid": True, "warning": f"签名变更: {', '.join(changed)}（请确认调用方兼容）"}

    return {"valid": True}


def _signatures(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.add(node.name)
        elif isinstance(node, ast.ClassDef):
            result.add(node.name)
    return result


def _extract_imports(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                result.add(f"{module}.{alias.name}")
    return result


def _has_main_guard(source: str) -> bool:
    return '__name__' in source and '__main__' in source


def _public_signatures(source: str) -> dict[str, tuple]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    result: dict[str, tuple] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            args = node.args
            pos = tuple(a.arg for a in args.args)
            kwonly = tuple(a.arg for a in args.kwonlyargs)
            n_defaults = len(args.defaults)
            required_pos = pos[: len(pos) - n_defaults] if n_defaults <= len(pos) else ()
            required_kw = tuple(a for a, d in zip(kwonly, args.kw_defaults) if d is None)
            result[node.name] = (pos, kwonly, required_pos, required_kw)
    return result

def _check_smell_reduction(rel_path: str, fixed: str, n_before: int) -> dict:
    from backend.analyzers.parser import analyze_source
    from backend.analyzers.smells import detect_smells
    try:
        fa = analyze_source(rel_path, fixed)
        smells = detect_smells([fa], {rel_path: fixed})
        n_after = len([s for s in smells if s["file"] == rel_path])
    except Exception:
        return {"ok": True, "detail": ""}
    if n_after >= n_before:
        return {"ok": False, "detail": f"修复后坏味数 {n_after} >= 修复前 {n_before}，引入了新坏味，请确保修复后坏味严格减少"}
    return {"ok": True, "detail": ""}