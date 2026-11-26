import ast

ENTRY_NAMES = {"main", "run", "app", "create_app", "setup", "init"}


def analyze_dead_code(files: dict[str, str]) -> dict:
    definitions = []
    used_names: set[str] = set()
    main_called: set[str] = set()

    for path, source in files.items():
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        _collect_definitions(path, tree, definitions)
        _collect_used_names(tree, used_names)
        _collect_main_calls(tree, main_called)

    used = used_names | main_called | ENTRY_NAMES
    dead = []
    for d in definitions:
        if d["name"] in used:
            continue
        if d["name"].startswith("test_"):
            continue
        if d.get("decorated"):
            continue
        if d["kind"] == "method" and d["name"].startswith("__") and d["name"].endswith("__"):
            continue
        dead.append({
            "file": d["file"],
            "name": d["name"],
            "line": d["line"],
            "kind": d["kind"],
            "message": _message(d),
            "suggestion": f"若确为未使用代码，可删除 `{d['name']}`；若被外部调用或动态引用，请添加注释说明。",
        })

    total = len(definitions)
    dead_count = len(dead)
    rate = round(dead_count / total * 100, 1) if total else 0.0
    return {
        "stats": {
            "total_definitions": total,
            "dead_count": dead_count,
            "dead_rate": rate,
        },
        "dead_code": dead,
    }


def _collect_definitions(path: str, tree: ast.Module, out: list[dict]) -> None:
    _walk_defs(path, tree.body, in_class=False, out=out)


def _walk_defs(path: str, body: list, in_class: bool, out: list[dict]) -> None:
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append({
                "file": path, "name": node.name, "line": node.lineno,
                "kind": "method" if in_class else "function",
                "decorated": bool(node.decorator_list),
            })
            _walk_defs(path, node.body, in_class=False, out=out)
        elif isinstance(node, ast.ClassDef):
            out.append({
                "file": path, "name": node.name, "line": node.lineno,
                "kind": "class", "decorated": bool(node.decorator_list),
            })
            _walk_defs(path, node.body, in_class=True, out=out)


def _collect_used_names(tree: ast.Module, out: set[str]) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                out.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                out.update(_names_in(dec))
        elif isinstance(node, ast.ClassDef):
            for base in node.bases:
                out.update(_names_in(base))


def _collect_main_calls(tree: ast.Module, out: set[str]) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_main_guard(node.test):
            for sub in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                if isinstance(sub, ast.Call):
                    out.update(_names_in(sub.func))


def _is_main_guard(test) -> bool:
    if not isinstance(test, ast.Compare):
        return False
    if not (isinstance(test.left, ast.Name) and test.left.id == "__name__"):
        return False
    for cmp in test.comparators:
        if isinstance(cmp, ast.Constant) and cmp.value == "__main__":
            return True
    return False


def _names_in(node) -> set[str]:
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            names.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            names.add(sub.attr)
    return names


def _message(d: dict) -> str:
    kind_cn = {"function": "函数", "class": "类", "method": "方法"}[d["kind"]]
    return f"{kind_cn} `{d['name']}` 在整个项目中未被引用，疑似死代码"