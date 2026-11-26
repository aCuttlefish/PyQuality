import ast

SUGGESTIONS = {
    "nested_loop": "评估是否可优化为单层循环或使用 itertools.product，避免 O(n²)",
    "string_concat_in_loop": "改用列表收集后 ''.join() 拼接，避免反复创建字符串",
    "range_len_loop": "改用 for item in sequence 或 for i, item in enumerate(sequence)",
    "loop_in_range_len": "内层 range(len()) 配合外层循环形成 O(n²) 索引访问，建议直接迭代",
}


def detect_performance(path: str, source: str) -> list[dict]:
    issues: list[dict] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return issues
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _scan_function(node, path, issues)
    return issues


def _scan_function(func, path: str, issues: list[dict]) -> None:
    for node in ast.walk(func):
        if isinstance(node, (ast.For, ast.While)):
            _check_nested_loops(node, path, issues)
            _check_string_concat(node, path, issues)
            _check_range_len(node, path, issues)


def _check_nested_loops(loop, path: str, issues: list[dict]) -> None:
    for child in ast.walk(loop):
        if child is loop:
            continue
        if isinstance(child, (ast.For, ast.While)):
            issues.append(_issue("nested_loop", "medium", path, child.lineno,
                                 "嵌套循环，可能产生 O(n²) 复杂度"))
            return


def _check_string_concat(loop, path: str, issues: list[dict]) -> None:
    for child in ast.walk(loop):
        if isinstance(child, ast.AugAssign) and isinstance(child.op, ast.Add):
            if isinstance(child.target, ast.Name):
                if _involves_string(child.value):
                    issues.append(_issue("string_concat_in_loop", "medium", path, child.lineno,
                                         "循环内使用 += 拼接字符串，性能较差"))
                    return


def _check_range_len(loop, path: str, issues: list[dict]) -> None:
    if not isinstance(loop, ast.For):
        return
    if _is_range_len(loop.iter):
        issues.append(_issue("range_len_loop", "low", path, loop.lineno,
                             "使用 range(len(x)) 迭代，建议直接迭代或用 enumerate"))


def _involves_string(node) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("str", "format"):
        return True
    return False


def _is_range_len(node) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not (isinstance(node.func, ast.Name) and node.func.id == "range"):
        return False
    if not node.args:
        return False
    arg = node.args[0]
    return isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "len"


def _issue(type_, severity, file, line, message) -> dict:
    return {"type": type_, "severity": severity, "file": file, "line": line,
            "message": message, "suggestion": SUGGESTIONS.get(type_, "")}