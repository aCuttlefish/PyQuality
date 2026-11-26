import ast


def analyze_docstrings(files: dict[str, str]) -> dict:
    mod_total = mod_ok = 0
    cls_total = cls_ok = 0
    func_total = func_ok = 0
    pub_total = pub_ok = 0
    missing: list[dict] = []

    for path, source in files.items():
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        mod_total += 1
        if ast.get_docstring(tree) is not None:
            mod_ok += 1
        else:
            missing.append({"file": path, "name": path, "line": 1, "kind": "module",
                            "message": "模块缺少 docstring"})
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                cls_total += 1
                if ast.get_docstring(node) is not None:
                    cls_ok += 1
                else:
                    missing.append({"file": path, "name": node.name, "line": node.lineno,
                                    "kind": "class", "message": f"类 {node.name} 缺少 docstring"})
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("__") and node.name.endswith("__") and node.name != "__init__":
                    continue
                func_total += 1
                is_public = not node.name.startswith("_")
                if is_public:
                    pub_total += 1
                if ast.get_docstring(node) is not None:
                    func_ok += 1
                    if is_public:
                        pub_ok += 1
                else:
                    missing.append({"file": path, "name": node.name, "line": node.lineno,
                                    "kind": "function", "message": f"函数 {node.name} 缺少 docstring"})

    def pct(ok, tot):
        return round(ok / tot * 100, 1) if tot else 100.0

    overall = pct(mod_ok + cls_ok + func_ok, mod_total + cls_total + func_total)
    return {
        "stats": {
            "modules": mod_total,
            "classes": cls_total,
            "functions": func_total,
            "public_functions": pub_total,
            "module_coverage": pct(mod_ok, mod_total),
            "class_coverage": pct(cls_ok, cls_total),
            "function_coverage": pct(func_ok, func_total),
            "public_coverage": pct(pub_ok, pub_total),
            "overall": overall,
        },
        "missing": missing,
    }