import re

from backend.analyzers.parser import FileAnalysis
from backend.config import READABILITY_WEIGHTS

SNAKE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
PASCAL_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")


def score_readability(analyses: list[FileAnalysis]) -> dict:
    if not analyses:
        return {"total": 0.0, "grade": "N/A", "breakdown": []}

    all_functions = [fi for fa in analyses for fi in fa.functions]
    all_classes = [ci for fa in analyses for ci in fa.classes]
    total_lines = sum(fa.code_lines for fa in analyses) or 1

    avg_func_len = (
        sum(fi.end_line - fi.line + 1 for fi in all_functions) / len(all_functions)
        if all_functions else 0.0
    )
    avg_complexity = (
        sum(fi.complexity for fi in all_functions) / len(all_functions)
        if all_functions else 1.0
    )
    comment_ratio = sum(fa.comment_lines for fa in analyses) / total_lines
    documented = sum(1 for fi in all_functions if fi.has_docstring) + sum(
        1 for ci in all_classes if ci.has_docstring
    )
    documentable = len(all_functions) + len(all_classes)
    docstring_coverage = documented / documentable if documentable else 1.0

    naming_total = len(all_functions) + len(all_classes)
    naming_ok = 0
    for fi in all_functions:
        if _ok_function_name(fi.name):
            naming_ok += 1
    for ci in all_classes:
        if PASCAL_RE.match(ci.name):
            naming_ok += 1
    naming_quality = naming_ok / naming_total if naming_total else 1.0

    max_nesting = max((fi.nesting for fi in all_functions), default=1)
    long_line_ratio = sum(fa.long_lines for fa in analyses) / total_lines

    scores = {
        "avg_function_length": _score_func_len(avg_func_len),
        "avg_complexity": _score_complexity(avg_complexity),
        "comment_ratio": _score_comment(comment_ratio),
        "docstring_coverage": min(docstring_coverage * 100, 100),
        "naming_quality": naming_quality * 100,
        "nesting_depth": _score_nesting(max_nesting),
        "long_line_ratio": max(0.0, 100 - long_line_ratio * 500),
    }

    details = {
        "avg_function_length": f"平均函数长度 {avg_func_len:.1f} 行",
        "avg_complexity": f"平均圈复杂度 {avg_complexity:.1f}",
        "comment_ratio": f"注释率 {comment_ratio:.1%}",
        "docstring_coverage": f"文档覆盖率 {docstring_coverage:.0%}",
        "naming_quality": f"命名规范率 {naming_quality:.0%}",
        "nesting_depth": f"最大嵌套 {max_nesting} 层",
        "long_line_ratio": f"超长行占比 {long_line_ratio:.1%}",
    }

    breakdown = []
    weighted_sum = 0.0
    weight_total = 0
    for metric, weight in READABILITY_WEIGHTS.items():
        s = round(scores[metric], 1)
        breakdown.append({
            "metric": metric, "score": s, "weight": weight,
            "detail": details.get(metric, ""),
        })
        weighted_sum += s * weight
        weight_total += weight

    total = round(weighted_sum / weight_total, 1)
    return {"total": total, "grade": _grade(total), "breakdown": breakdown}


def _ok_function_name(name: str) -> bool:
    if name.startswith("__") and name.endswith("__"):
        return True
    return bool(SNAKE_RE.match(name)) and len(name) > 1


def _score_func_len(avg: float) -> float:
    if avg <= 20:
        return 100.0
    if avg >= 60:
        return 0.0
    return round(100 * (60 - avg) / 40, 1)


def _score_complexity(avg: float) -> float:
    if avg <= 5:
        return 100.0
    if avg >= 15:
        return 0.0
    return round(100 * (15 - avg) / 10, 1)


def _score_comment(ratio: float) -> float:
    if ratio < 0.05:
        return round(ratio / 0.05 * 50, 1)
    if ratio > 0.30:
        return 100.0
    return round(50 + (min(ratio, 0.30) - 0.05) / 0.25 * 50, 1)


def _score_nesting(max_depth: int) -> float:
    if max_depth <= 3:
        return 100.0
    if max_depth >= 8:
        return 0.0
    return round(100 * (8 - max_depth) / 5, 1)


def _grade(total: float) -> str:
    if total >= 85:
        return "A"
    if total >= 70:
        return "B"
    if total >= 55:
        return "C"
    if total >= 40:
        return "D"
    return "E"