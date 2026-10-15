import ast
from dataclasses import dataclass, field


@dataclass
class FunctionInfo:
    name: str
    line: int
    end_line: int
    num_params: int
    complexity: int
    nesting: int
    has_docstring: bool
    source: str
    args_source: str
    is_method: bool = False


@dataclass
class ClassInfo:
    name: str
    line: int
    end_line: int
    num_methods: int
    has_docstring: bool
    source: str


@dataclass
class FileAnalysis:
    path: str
    total_lines: int
    code_lines: int
    comment_lines: int
    blank_lines: int
    long_lines: int
    imports: list[str] = field(default_factory=list)
    import_bounds: list[str] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    global_assigns: list[tuple[str, int]] = field(default_factory=list)
    parse_error: str = ""
    names_used: set[str] = field(default_factory=set)
    names_assigned: dict[str, int] = field(default_factory=dict)
    numeric_consts: list[tuple[int | float, int]] = field(default_factory=list)
    except_handlers: list[tuple[int, str]] = field(default_factory=list)


def analyze_source(path: str, source: str) -> FileAnalysis:
    fa = FileAnalysis(path=path, total_lines=0, code_lines=0, comment_lines=0,
                      blank_lines=0, long_lines=0)
    lines = source.splitlines()
    fa.total_lines = len(lines)
    in_docstring = False
    doc_delims = ('"""', "'''")
    for ln in lines:
        stripped = ln.strip()
        if in_docstring:
            fa.comment_lines += 1
            if any(d in ln for d in doc_delims):
                in_docstring = False
            continue
        if not stripped:
            fa.blank_lines += 1
            continue
        if stripped.startswith("#"):
            fa.comment_lines += 1
            continue
        fa.code_lines += 1
        if len(ln) > 100:
            fa.long_lines += 1
        for d in doc_delims:
            if stripped.startswith(d):
                in_docstring = True
                fa.comment_lines += 1
                break
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        fa.parse_error = f"line {e.lineno}: {e.msg}"
        return fa

    module_src = source
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                fa.imports.append(alias.name)
                fa.import_bounds.append(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                fa.imports.append(f"{module}.{alias.name}" if module else alias.name)
                fa.import_bounds.append(alias.asname or alias.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            fa.numeric_consts.append((node.value, node.lineno))
        elif isinstance(node, ast.ExceptHandler):
            if node.type is None:
                fa.except_handlers.append((node.lineno, "bare"))
            else:
                fa.except_handlers.append((node.lineno, ast.unparse(node.type)))

    for name, lineno in _collect_names(tree):
        fa.names_used.add(name)

    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            else:
                targets = [node.target]
            for t in targets:
                for sub in ast.walk(t):
                    if isinstance(sub, ast.Name):
                        fa.global_assigns.append((sub.id, node.lineno))
                        fa.names_assigned.setdefault(sub.id, node.lineno)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fi = _parse_function(node, module_src, is_method=False)
            fa.functions.append(fi)
        elif isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append(_parse_function(item, module_src, is_method=True))
            fa.functions.extend(methods)
            fa.classes.append(
                ClassInfo(
                    name=node.name,
                    line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    num_methods=len(methods),
                    has_docstring=ast.get_docstring(node) is not None,
                    source=ast.get_source_segment(module_src, node) or "",
                )
            )
    return fa


def _parse_function(node, module_src: str, is_method: bool) -> FunctionInfo:
    from backend.analyzers.complexity import compute_complexity, compute_nesting

    args = list(node.args.posonlyargs) + list(node.args.args)
    if node.args.vararg:
        args.append(node.args.vararg)
    args += list(node.args.kwonlyargs)
    if node.args.kwarg:
        args.append(node.args.kwarg)
    args_source = ", ".join(a.arg for a in args)
    return FunctionInfo(
        name=node.name,
        line=node.lineno,
        end_line=node.end_lineno or node.lineno,
        num_params=len(args),
        complexity=compute_complexity(node),
        nesting=compute_nesting(node),
        has_docstring=ast.get_docstring(node) is not None,
        source=ast.get_source_segment(module_src, node) or "",
        args_source=args_source,
        is_method=is_method,
    )


def _collect_names(tree: ast.AST) -> list[tuple[str, int]]:
    results = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Load, ast.Del)):
            results.append((node.id, node.lineno))
        elif isinstance(node, ast.Attribute):
            results.append((node.attr, node.lineno))
    return results