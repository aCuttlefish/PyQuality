import ast
import hashlib
from collections import defaultdict


def analyze_duplication(files: dict[str, str], min_lines: int = 6) -> dict:
    blocks: list[dict] = []
    by_hash: dict[str, list[int]] = defaultdict(list)

    for path, source in files.items():
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            length = (node.end_lineno or node.lineno) - node.lineno + 1
            if length < min_lines:
                continue
            norm = _normalize(node)
            digest = hashlib.md5(norm.encode()).hexdigest()
            entry = {
                "file": path,
                "name": node.name,
                "line": node.lineno,
                "length": length,
                "hash": digest,
            }
            idx = len(blocks)
            blocks.append(entry)
            by_hash[digest].append(idx)

    duplicates: list[dict] = []
    seen_pairs: set[frozenset] = set()
    for digest, indices in by_hash.items():
        if len(indices) < 2:
            continue
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                a, b = blocks[indices[i]], blocks[indices[j]]
                pair = frozenset((a["file"], a["line"], b["file"], b["line"]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                duplicates.append({
                    "file1": a["file"], "line1": a["line"], "name1": a["name"],
                    "file2": b["file"], "line2": b["line"], "name2": b["name"],
                    "lines": a["length"],
                })

    total_blocks = len(blocks)
    dup_blocks = sum(len(v) for v in by_hash.values() if len(v) >= 2)
    rate = round(dup_blocks / total_blocks * 100, 1) if total_blocks else 0.0
    duplicates.sort(key=lambda d: d["lines"], reverse=True)
    return {
        "stats": {
            "total_functions": total_blocks,
            "duplicate_functions": dup_blocks,
            "rate": rate,
            "duplicate_groups": sum(1 for v in by_hash.values() if len(v) >= 2),
        },
        "duplicates": duplicates[:50],
    }


def _normalize(node) -> str:
    parts: list[str] = []

    def walk(n, depth=0):
        if depth > 64:
            parts.append("X")
            return
        if isinstance(n, ast.Name):
            parts.append("N")
            return
        if isinstance(n, ast.Constant):
            parts.append("C")
            return
        if isinstance(n, ast.arg):
            parts.append("A")
            return
        if isinstance(n, ast.Attribute):
            parts.append("Attr")
        else:
            parts.append(type(n).__name__)
        for child in ast.iter_child_nodes(n):
            walk(child, depth + 1)

    walk(node)
    return "|".join(parts)