import ast
from collections import defaultdict


def analyze_dependencies(files: dict[str, str]) -> dict:
    modules: dict[str, str] = {}
    edges: list[dict] = []
    internal_modules: set[str] = set()

    for rel_path in files:
        stem = rel_path.replace("\\", "/").removesuffix(".py")
        if stem.endswith("/__init__"):
            stem = stem.removesuffix("/__init__")
        internal_modules.add(stem)
        internal_modules.add(stem.split("/")[-1])

    for rel_path, source in files.items():
        stem = rel_path.replace("\\", "/").removesuffix(".py")
        if stem.endswith("/__init__"):
            stem = stem.removesuffix("/__init__")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = _resolve(alias.name, internal_modules, rel_path)
                    if target:
                        edges.append({"from": rel_path, "to": target, "kind": "import", "line": node.lineno})
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                level = node.level or 0
                target = _resolve_relative(module, level, rel_path, internal_modules) if level else _resolve(module, internal_modules, rel_path)
                if target:
                    edges.append({"from": rel_path, "to": target, "kind": "from", "line": node.lineno})

    graph = defaultdict(list)
    for e in edges:
        graph[e["from"]].append(e["to"])
    cycles = _find_cycles(graph)

    in_degree = defaultdict(int)
    nodes = set(files.keys())
    for e in edges:
        nodes.add(e["from"])
        nodes.add(e["to"])
        in_degree[e["to"]] += 1
    for n in nodes:
        in_degree.setdefault(n, 0)

    return {
        "nodes": sorted(nodes),
        "edges": edges,
        "cycles": cycles,
        "stats": {
            "module_count": len(nodes),
            "edge_count": len(edges),
            "cycle_count": len(cycles),
            "max_depth": _max_depth(graph),
        },
    }


def _resolve(name: str, internal: set[str], rel_path: str) -> str | None:
    if name in internal:
        return name if name.endswith(".py") else f"{name}.py"
    top = name.split(".")[0]
    if top in internal:
        return f"{top}.py"
    return None


def _resolve_relative(module: str, level: int, rel_path: str, internal: set[str]) -> str | None:
    parts = rel_path.replace("\\", "/").split("/")
    base = parts[:-1]
    if level > 1 and len(base) >= level - 1:
        base = base[: -(level - 1)]
    candidate = "/".join(base + ([module] if module else []))
    if candidate in internal or candidate + "/__init__" in internal:
        return f"{candidate}.py"
    return None


def _find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    cycles: list[list[str]] = []
    seen_cycle: set[frozenset] = set()

    def dfs(node: str, path: list[str], visited: set[str]):
        for nxt in graph.get(node, []):
            if nxt in path:
                idx = path.index(nxt)
                cyc = path[idx:] + [nxt]
                key = frozenset(cyc)
                if key not in seen_cycle:
                    seen_cycle.add(key)
                    cycles.append(cyc)
                continue
            if nxt in visited:
                continue
            visited.add(nxt)
            dfs(nxt, path + [nxt], visited)

    for start in graph:
        dfs(start, [start], {start})
    return cycles[:20]


def _max_depth(graph: dict[str, list[str]]) -> int:
    memo: dict[str, int] = {}

    def depth(node: str, stack: set[str]) -> int:
        if node in memo:
            return memo[node]
        if node in stack:
            return 0
        stack.add(node)
        best = 0
        for nxt in graph.get(node, []):
            best = max(best, 1 + depth(nxt, stack))
        stack.discard(node)
        memo[node] = best
        return best

    return max((depth(n, set()) for n in graph), default=0)