from collections import Counter, defaultdict
from difflib import SequenceMatcher

from backend.analyzers.parser import FileAnalysis
from backend.config import SMELL_THRESHOLDS

SUGGESTIONS = {
    "long_function": "将函数拆分为多个职责单一的小函数",
    "long_params": "引入参数对象或数据类，减少参数数量",
    "deep_nesting": "使用卫语句提前返回，或提取嵌套逻辑为独立函数",
    "god_class": "按职责将类拆分为多个小类",
    "magic_number": "将魔法数字提取为具名常量",
    "broad_except": "捕获具体异常类型，避免吞掉所有错误",
    "unused_import": "删除未使用的导入",
    "unused_variable": "删除未使用的变量或添加必要的使用逻辑",
    "global_variable": "将全局变量封装到类或函数参数中",
    "bad_naming": "遵循 PEP 8：函数/变量用 snake_case，类用 PascalCase，避免单字母命名",
    "long_file": "按功能拆分模块",
    "missing_docstring": "为函数/类添加 docstring 说明用途和参数",
    "long_line": "拆分过长代码行，保持每行不超过 100 字符",
    "duplicate_code": "将重复代码提取为公共函数",
}


def _add(smells, type_, severity, file, line, message):
    smells.append({
        "type": type_,
        "severity": severity,
        "file": file,
        "line": line,
        "message": message,
        "suggestion": SUGGESTIONS.get(type_, ""),
    })


def detect_smells(analyses: list[FileAnalysis], sources: dict[str, str]) -> list[dict]:
    smells: list[dict] = []
    t = SMELL_THRESHOLDS
    for fa in analyses:
        if fa.parse_error:
            _add(smells, "syntax_error", "high", fa.path, 0,
                 f"语法错误: {fa.parse_error}")
            continue
        for fi in fa.functions:
            length = fi.end_line - fi.line + 1
            if length > t["long_function_lines"]:
                _add(smells, "long_function", "medium", fa.path, fi.line,
                     f"函数 {fi.name} 过长 ({length} 行，阈值 {t['long_function_lines']})")
            if fi.num_params > t["long_params"]:
                _add(smells, "long_params", "medium", fa.path, fi.line,
                     f"函数 {fi.name} 参数过多 ({fi.num_params} 个，阈值 {t['long_params']})")
            if fi.nesting > t["deep_nesting"]:
                _add(smells, "deep_nesting", "medium", fa.path, fi.line,
                     f"函数 {fi.name} 嵌套过深 ({fi.nesting} 层，阈值 {t['deep_nesting']})")
            if not fi.has_docstring:
                _add(smells, "missing_docstring", "low", fa.path, fi.line,
                     f"函数 {fi.name} 缺少 docstring")
            if _is_bad_function_name(fi.name):
                _add(smells, "bad_naming", "low", fa.path, fi.line,
                     f"函数名 {fi.name} 不符合 snake_case 规范")
        for ci in fa.classes:
            length = ci.end_line - ci.line + 1
            if ci.num_methods > t["god_class_methods"] or length > t["god_class_lines"]:
                _add(smells, "god_class", "high", fa.path, ci.line,
                     f"类 {ci.name} 过大 ({ci.num_methods} 个方法, {length} 行)")
            if not ci.has_docstring:
                _add(smells, "missing_docstring", "low", fa.path, ci.line,
                     f"类 {ci.name} 缺少 docstring")
        if fa.total_lines > t["long_file_lines"]:
            _add(smells, "long_file", "medium", fa.path, 1,
                 f"文件过长 ({fa.total_lines} 行，阈值 {t['long_file_lines']})")
        for name, lineno in fa.global_assigns:
            if not name.startswith("_") and name not in ("__all__",):
                _add(smells, "global_variable", "low", fa.path, lineno,
                     f"模块级全局变量赋值: {name}")
        counter = Counter(abs(v) for v, _ in fa.numeric_consts)
        for value, count in counter.items():
            if value in (0, 1, 2, 100, 1000):
                continue
            if count >= t["magic_number_repeat"]:
                _add(smells, "magic_number", "low", fa.path, 0,
                     f"魔法数字 {value} 出现 {count} 次")
        for lineno, etype in fa.except_handlers:
            if etype == "bare":
                _add(smells, "broad_except", "high", fa.path, lineno,
                     "裸 except 捕获所有异常")
            elif etype in ("Exception", "BaseException"):
                _add(smells, "broad_except", "medium", fa.path, lineno,
                     f"过宽异常捕获: except {etype}")
        for name, lineno in fa.names_assigned.items():
            if _is_unused_local(name, fa):
                _add(smells, "unused_variable", "low", fa.path, lineno,
                     f"变量 {name} 可能未使用")
        used_imports = _filter_used_imports(fa)
        for imp, bound in zip(fa.imports, fa.import_bounds):
            if bound == "*":
                continue
            if bound not in used_imports:
                _add(smells, "unused_import", "low", fa.path, 1,
                     f"未使用的导入: {imp}")
        for lineno in _find_long_lines(sources.get(fa.path, "")):
            _add(smells, "long_line", "low", fa.path, lineno,
                 "代码行超过 100 字符")
    _detect_duplicates(smells, analyses, sources)
    return smells


def _is_bad_function_name(name: str) -> bool:
    if name.startswith("__") and name.endswith("__"):
        return False
    if len(name) == 1:
        return True
    return name != name.lower() and "_" not in name and not name.startswith("test")


def _is_unused_local(name: str, fa: FileAnalysis) -> bool:
    if name.startswith("_") or len(name) <= 1:
        return False
    if name in ("self", "cls", "i", "j", "k"):
        return False
    return name not in fa.names_used


def _filter_used_imports(fa: FileAnalysis) -> set[str]:
    used = set()
    for name in fa.names_used:
        used.add(name)
        parts = name.split(".")
        if parts:
            used.add(parts[0])
    return used


def _find_long_lines(source: str) -> list[int]:
    result = []
    for i, ln in enumerate(source.splitlines(), 1):
        if len(ln) > SMELL_THRESHOLDS["long_line_chars"] and ln.strip() and not ln.strip().startswith("#"):
            result.append(i)
    return result


def _detect_duplicates(smells, analyses, sources) -> None:
    t = SMELL_THRESHOLDS
    blocks = []
    for fa in analyses:
        source = sources.get(fa.path, "")
        lines = source.splitlines()
        i = 0
        while i + t["duplicate_block_lines"] <= len(lines):
            block = tuple(ln.strip() for ln in lines[i:i + t["duplicate_block_lines"]])
            if any(block) and not all(not b or b.startswith("#") for b in block):
                blocks.append((fa.path, i + 1, block))
            i += 1
    seen = set()
    for idx, (path1, line1, b1) in enumerate(blocks):
        for path2, line2, b2 in blocks[idx + 1:]:
            if path1 == path2 and abs(line1 - line2) < t["duplicate_block_lines"]:
                continue
            key = (path1, path2, line1, line2)
            if key in seen:
                continue
            ratio = SequenceMatcher(None, "\n".join(b1), "\n".join(b2)).ratio()
            if ratio >= 0.85:
                seen.add(key)
                _add(smells, "duplicate_code", "medium", path1, line1,
                     f"与 {path2}:{line2} 存在重复代码块 ({t['duplicate_block_lines']} 行, 相似度 {ratio:.0%})")