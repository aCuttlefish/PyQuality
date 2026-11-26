import ast

SKIP_ARGS = {"self", "cls"}


def analyze_type_hints(files: dict[str, str]) -> dict:
    total = 0
    annotated = 0
    missing: list[dict] = []
    for path, source in files.items():
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("__") and node.name.endswith("__") and node.name != "__init__":
                continue
            total += 1
            has_param = _has_annotated_params(node)
            has_return = node.returns is not None
            if has_param and has_return:
                annotated += 1
                continue
            kind = "both"
            if has_param and not has_return:
                kind = "return"
            elif has_return and not has_param:
                kind = "params"
            missing.append({
                "file": path,
                "name": node.name,
                "line": node.lineno,
                "kind": kind,
                "message": _missing_message(node.name, kind),
            })
    coverage = round(annotated / total * 100, 1) if total else 100.0
    return {
        "stats": {
            "total_functions": total,
            "annotated": annotated,
            "missing": len(missing),
            "coverage": coverage,
        },
        "missing": missing,
    }


def _has_annotated_params(node) -> bool:
    args = list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
    real = [a for a in args if a.arg not in SKIP_ARGS]
    if not real:
        return True
    return all(a.annotation is not None for a in real)


def _missing_message(name: str, kind: str) -> str:
    if kind == "return":
        return f"函数 {name} 缺少返回值类型注解"
    if kind == "params":
        return f"函数 {name} 缺少参数类型注解"
    return f"函数 {name} 缺少参数和返回值类型注解"