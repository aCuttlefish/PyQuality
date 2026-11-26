import ast


def compute_complexity(node: ast.AST) -> int:
    complexity = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.While, ast.AsyncFor)):
            complexity += 1
        elif isinstance(child, ast.ExceptHandler):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += max(len(child.values) - 1, 0)
        elif isinstance(child, (ast.IfExp, ast.Assert)):
            complexity += 1
        elif isinstance(child, ast.comprehension):
            complexity += 1 + len(child.ifs)
        elif isinstance(child, ast.Match):
            complexity += max(len(child.cases) - 1, 0)
    return complexity


def compute_nesting(node: ast.AST) -> int:
    max_depth = 0

    def visit(n: ast.AST, depth: int) -> None:
        nonlocal max_depth
        if isinstance(
            n,
            (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.AsyncFor, ast.AsyncWith, ast.Match),
        ):
            depth += 1
            max_depth = max(max_depth, depth)
        for child in ast.iter_child_nodes(n):
            visit(child, depth)

    visit(node, 0)
    return max_depth