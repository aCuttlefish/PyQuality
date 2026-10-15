import fnmatch
import json
import time

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from backend import config, database
from backend.analyzers.dead_code import analyze_dead_code
from backend.analyzers.dependencies import analyze_dependencies
from backend.analyzers.docstrings import analyze_docstrings
from backend.analyzers.duplication import analyze_duplication
from backend.analyzers.parser import analyze_source
from backend.analyzers.performance import detect_performance
from backend.analyzers.readability import score_readability
from backend.analyzers.security import detect_security
from backend.analyzers.smells import detect_smells
from backend.analyzers.type_hints import analyze_type_hints
from backend.config import COMPLEXITY_BUCKETS, UPLOAD_DIR
from backend.logger import get_logger

logger = get_logger("analysis")
router = APIRouter(prefix="/api/projects", tags=["analysis"])

PYTHON_SUFFIX = ".py"


class SingleFileBody(BaseModel):
    file: str


@router.post("/{pid}/analyze")
def analyze_project(pid: str):
    project = database.get_project(pid)
    if not project:
        raise HTTPException(404, "项目不存在")
    files = database.list_files(pid)
    py_files = [f["rel_path"] for f in files if f["rel_path"].endswith(PYTHON_SUFFIX)]
    if not py_files:
        raise HTTPException(400, "项目中没有 Python 文件")

    ignore_patterns = _load_ignore_patterns(pid)
    if ignore_patterns:
        py_files = [p for p in py_files if not _is_ignored(p, ignore_patterns)]
        if not py_files:
            raise HTTPException(400, "所有文件被 .pyqualityignore 忽略")

    sources = _read_sources(pid, py_files)
    if not sources:
        raise HTTPException(500, "无法读取项目文件，可能存储已损坏")
    result = _build_analysis(pid, project["name"], sources)
    database.save_analysis(pid, json.dumps(result, ensure_ascii=False))
    database.save_analysis_history(pid, _analysis_summary(result))
    logger.info("分析完成 pid=%s 文件=%d 坏味=%d", pid, len(sources), len(result["smells"]))
    return {"ok": True, "result": result}


@router.post("/{pid}/analyze-file")
def analyze_single_file(pid: str, body: SingleFileBody):
    project = database.get_project(pid)
    if not project:
        raise HTTPException(404, "项目不存在")
    abs_path = database.get_file_abs_path(pid, body.file)
    if abs_path is None or not body.file.endswith(PYTHON_SUFFIX):
        raise HTTPException(404, "文件不存在或不是 Python 文件")
    source = abs_path.read_text(encoding="utf-8", errors="replace")
    result = _build_analysis(pid, project["name"], {body.file: source})
    return {"ok": True, "result": result}


@router.get("/{pid}/analysis")
def get_cached_analysis(pid: str):
    project = database.get_project(pid)
    if not project:
        raise HTTPException(404, "项目不存在")
    cached = database.get_analysis(pid)
    if cached is None:
        return {"ok": True, "result": None}
    return {"ok": True, "result": json.loads(cached)}


@router.get("/{pid}/history")
def get_history(pid: str, limit: int = 50):
    project = database.get_project(pid)
    if not project:
        raise HTTPException(404, "项目不存在")
    history = database.list_analysis_history(pid, limit=limit)
    return {"ok": True, "history": history}


@router.get("/{pid}/report")
def export_report(pid: str, format: str = "markdown"):
    project = database.get_project(pid)
    if not project:
        raise HTTPException(404, "项目不存在")
    cached = database.get_analysis(pid)
    if cached is None:
        raise HTTPException(400, "尚未分析，请先执行分析")
    result = json.loads(cached)
    safe_name = _safe_filename(project["name"])
    if format == "json":
        return Response(
            content=json.dumps(result, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}_report.json"'},
        )
    if format == "sarif":
        return Response(
            content=json.dumps(_render_sarif(result), ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}_report.sarif"'},
        )
    if format == "html":
        return Response(
            content=_render_html_report(result),
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}_report.html"'},
        )
    md = _render_markdown_report(result)
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_report.md"'},
    )


def _safe_filename(name: str) -> str:
    import re
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", name).strip("_")
    return cleaned or "report"


def _load_ignore_patterns(pid: str) -> list[str]:
    ignore_file = UPLOAD_DIR / pid / ".pyqualityignore"
    if not ignore_file.exists():
        return []
    patterns = []
    for line in ignore_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _is_ignored(rel_path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(rel_path, pat):
            return True
        if "/" not in pat and fnmatch.fnmatch(rel_path.split("/")[-1], pat):
            return True
    return False


def _read_sources(pid: str, py_files: list[str]) -> dict[str, str]:
    sources = {}
    for rel in py_files:
        abs_path = database.get_file_abs_path(pid, rel)
        if abs_path is None:
            logger.warning("文件缺失 pid=%s rel=%s", pid, rel)
            continue
        try:
            sources[rel] = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning("读取文件失败 %s: %s", rel, e)
    return sources


def _build_analysis(pid: str, name: str, sources: dict[str, str]) -> dict:
    analyses = [analyze_source(rel, src) for rel, src in sources.items()]
    smells = detect_smells(analyses, sources)
    readability = score_readability(analyses)

    security_issues = []
    for rel, src in sources.items():
        security_issues.extend(detect_security(rel, src))

    dependencies = analyze_dependencies(sources)
    function_list = _function_complexity_list(analyses)
    type_hints = analyze_type_hints(sources)
    docstrings = analyze_docstrings(sources)
    performance_issues: list[dict] = []
    for rel, src in sources.items():
        performance_issues.extend(detect_performance(rel, src))
    duplication = analyze_duplication(sources, min_lines=config.DUPLICATION_MIN_LINES)
    dead_code = analyze_dead_code(sources)

    total_lines = sum(fa.total_lines for fa in analyses)
    total_functions = sum(len(fa.functions) for fa in analyses)
    total_classes = sum(len(fa.classes) for fa in analyses)
    complexities = [fi.complexity for fa in analyses for fi in fa.functions]
    avg_complexity = round(sum(complexities) / len(complexities), 2) if complexities else 0.0
    comment_ratio = round(sum(fa.comment_lines for fa in analyses) / total_lines, 4) if total_lines else 0.0

    return {
        "project_id": pid,
        "project_name": name,
        "stats": {
            "total_files": len(analyses),
            "total_lines": total_lines,
            "total_functions": total_functions,
            "total_classes": total_classes,
            "avg_complexity": avg_complexity,
            "comment_ratio": comment_ratio,
        },
        "readability": readability,
        "smells": smells,
        "security": security_issues,
        "dependencies": dependencies,
        "functions": function_list,
        "type_hints": type_hints,
        "docstrings": docstrings,
        "performance": performance_issues,
        "duplication": duplication,
        "dead_code": dead_code,
        "analyzed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _analysis_summary(result: dict) -> dict:
    s = result.get("stats", {})
    rd = result.get("readability", {})
    dc = result.get("dead_code", {}).get("stats", {})
    return {
        "total_files": s.get("total_files", 0),
        "total_lines": s.get("total_lines", 0),
        "avg_complexity": s.get("avg_complexity", 0),
        "readability_total": rd.get("total", 0),
        "readability_grade": rd.get("grade", ""),
        "smell_count": len(result.get("smells", [])),
        "security_count": len(result.get("security", [])),
        "performance_count": len(result.get("performance", [])),
        "dead_code_count": dc.get("dead_count", 0),
        "analyzed_at": result.get("analyzed_at", ""),
    }


def _function_complexity_list(analyses: list) -> list[dict]:
    items = []
    for fa in analyses:
        for fi in fa.functions:
            items.append({
                "name": fi.name,
                "file": fa.path,
                "line": fi.line,
                "complexity": fi.complexity,
                "length": fi.end_line - fi.line + 1,
                "nesting": fi.nesting,
                "bucket": _bucket(fi.complexity),
            })
    items.sort(key=lambda x: x["complexity"], reverse=True)
    return items


def _bucket(complexity: int) -> str:
    for name, (lo, hi) in COMPLEXITY_BUCKETS.items():
        if lo <= complexity <= hi:
            return name
    return "critical"


def _render_markdown_report(result: dict) -> str:
    s = result["stats"]
    rd = result["readability"]
    lines = [
        f"# 代码质量报告 - {result['project_name']}",
        f"\n> 生成时间: {result['analyzed_at']}\n",
        "## 概览",
        f"- 文件数: **{s['total_files']}**",
        f"- 总行数: **{s['total_lines']}**",
        f"- 函数数: **{s['total_functions']}**  类数: **{s['total_classes']}**",
        f"- 平均圈复杂度: **{s['avg_complexity']}**",
        f"- 注释率: **{s['comment_ratio']:.1%}**",
        f"- 可读性评分: **{rd['total']}/100** (等级 **{rd['grade']}**)\n",
        "## 可读性分项",
    ]
    for b in rd["breakdown"]:
        lines.append(f"- {b['metric']}: {b['score']} ({b['detail']})")

    lines.append(f"\n## 代码坏味 ({len(result['smells'])})")
    for sm in result["smells"][:50]:
        lines.append(f"- [{sm['severity']}] `{sm['file']}:{sm['line']}` **{sm['type']}** — {sm['message']}")
        if sm.get("suggestion"):
            lines.append(f"  - 建议: {sm['suggestion']}")

    sec = result.get("security", [])
    lines.append(f"\n## 安全问题 ({len(sec)})")
    if sec:
        for issue in sec[:50]:
            lines.append(f"- [{issue['severity']}] `{issue['file']}:{issue['line']}` **{issue['type']}** — {issue['message']}")
    else:
        lines.append("- 未发现安全问题 ✓")

    deps = result.get("dependencies", {})
    dst = deps.get("stats", {})
    lines.append(f"\n## 依赖关系")
    lines.append(f"- 模块数: {dst.get('module_count', 0)}  依赖边: {dst.get('edge_count', 0)}  循环: {dst.get('cycle_count', 0)}  最大深度: {dst.get('max_depth', 0)}")
    for cyc in deps.get("cycles", [])[:5]:
        lines.append(f"- ⚠ 循环依赖: {' -> '.join(cyc)}")

    funcs = result.get("functions", [])
    high = [f for f in funcs if f["bucket"] in ("high", "critical")]
    lines.append(f"\n## 高复杂度函数 ({len(high)})")
    for f in high[:20]:
        lines.append(f"- `{f['file']}:{f['line']}` **{f['name']}** 复杂度={f['complexity']} 长度={f['length']}行 嵌套={f['nesting']} [{f['bucket']}]")

    th = result.get("type_hints", {})
    ths = th.get("stats", {})
    lines.append(f"\n## 类型提示覆盖 ({ths.get('coverage', 0)}%)")
    lines.append(f"- 函数总数: {ths.get('total_functions', 0)}  已注解: {ths.get('annotated', 0)}  缺失: {ths.get('missing', 0)}")
    for m in th.get("missing", [])[:20]:
        lines.append(f"- `{m['file']}:{m['line']}` **{m['kind']}** — {m['message']}")

    ds = result.get("docstrings", {})
    dss = ds.get("stats", {})
    lines.append(f"\n## 文档覆盖率 (总体 {dss.get('overall', 0)}%)")
    lines.append(f"- 模块: {dss.get('module_coverage', 0)}%  类: {dss.get('class_coverage', 0)}%  函数: {dss.get('function_coverage', 0)}%  公共函数: {dss.get('public_coverage', 0)}%")
    for m in ds.get("missing", [])[:20]:
        lines.append(f"- `{m['file']}:{m['line']}` **{m['kind']}** — {m['message']}")

    perf = result.get("performance", [])
    lines.append(f"\n## 性能热点 ({len(perf)})")
    if perf:
        for p in perf[:30]:
            lines.append(f"- [{p['severity']}] `{p['file']}:{p['line']}` **{p['type']}** — {p['message']}")
    else:
        lines.append("- 未发现明显性能问题 ✓")

    dup = result.get("duplication", {})
    dus = dup.get("stats", {})
    lines.append(f"\n## 代码重复 (重复率 {dus.get('rate', 0)}%)")
    lines.append(f"- 分析函数: {dus.get('total_functions', 0)}  重复函数: {dus.get('duplicate_functions', 0)}  重复组: {dus.get('duplicate_groups', 0)}")
    for d in dup.get("duplicates", [])[:15]:
        lines.append(f"- `{d['file1']}:{d['line1']}` **{d['name1']}** ≈ `{d['file2']}:{d['line2']}` **{d['name2']}** ({d['lines']} 行)")

    dc = result.get("dead_code", {})
    dcs = dc.get("stats", {})
    lines.append(f"\n## 死代码检测 (死代码率 {dcs.get('dead_rate', 0)}%)")
    lines.append(f"- 定义总数: {dcs.get('total_definitions', 0)}  疑似死代码: {dcs.get('dead_count', 0)}")
    for d in dc.get("dead_code", [])[:30]:
        lines.append(f"- `{d['file']}:{d['line']}` **{d['kind']}** `{d['name']}` — {d['message']}")

    lines.append("\n---\n*由 PyQuality 自动生成*")
    return "\n".join(lines)

def _sarif_level(severity: str) -> str:
    s = (severity or "").lower()
    if s in ("critical", "high"):
        return "error"
    if s in ("medium", "warning"):
        return "warning"
    return "note"


def _render_sarif(result: dict) -> dict:
    results = []
    for sm in result.get("smells", []):
        results.append(_sarif_result("smell", sm))
    for issue in result.get("security", []):
        results.append(_sarif_result("security", issue))
    for p in result.get("performance", []):
        results.append(_sarif_result("performance", p))
    for d in result.get("dead_code", {}).get("dead_code", []):
        results.append(_sarif_result("dead_code", d, default_level="note"))
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "PyQuality", "version": "2.0.0"}},
            "results": results,
        }],
    }


def _sarif_result(category: str, item: dict, default_level: str = "warning") -> dict:
    severity = item.get("severity", "")
    level = _sarif_level(severity) if severity else default_level
    return {
        "ruleId": f"{category}/{item.get('type', item.get('kind', 'issue'))}",
        "level": level,
        "message": {"text": item.get("message", "")},
        "locations": [{
            "physicalLocation": {
                "artifactLocation": {"uri": item.get("file", "")},
                "region": {"startLine": int(item.get("line", 1))},
            }
        }],
    }


def _render_html_report(result: dict) -> str:
    import html as html_lib
    s = result["stats"]
    rd = result["readability"]
    rows = []

    def issue_table(items, limit=50):
        if not items:
            return "<p class='ok'>未发现问题 ✓</p>"
        body = ""
        for it in items[:limit]:
            body += (
                f"<tr><td>{html_lib.escape(it.get('severity', ''))}</td>"
                f"<td>{html_lib.escape(it.get('type', it.get('kind', '')))}</td>"
                f"<td><code>{html_lib.escape(it.get('file', ''))}:{it.get('line', '')}</code></td>"
                f"<td>{html_lib.escape(it.get('message', ''))}</td></tr>"
            )
        return f"<table><tr><th>级别</th><th>类型</th><th>位置</th><th>说明</th></tr>{body}</table>"

    rows.append(f"<section><h2>概览</h2><div class='cards'>"
                f"<div class='card'>文件数<b>{s['total_files']}</b></div>"
                f"<div class='card'>总行数<b>{s['total_lines']}</b></div>"
                f"<div class='card'>函数<b>{s['total_functions']}</b></div>"
                f"<div class='card'>类<b>{s['total_classes']}</b></div>"
                f"<div class='card'>平均复杂度<b>{s['avg_complexity']}</b></div>"
                f"<div class='card'>可读性<b>{rd['total']}/100 ({rd['grade']})</b></div>"
                f"</div></section>")
    rows.append(f"<section><h2>代码坏味 ({len(result.get('smells', []))})</h2>{issue_table(result.get('smells', []))}</section>")
    rows.append(f"<section><h2>安全问题 ({len(result.get('security', []))})</h2>{issue_table(result.get('security', []))}</section>")
    rows.append(f"<section><h2>性能热点 ({len(result.get('performance', []))})</h2>{issue_table(result.get('performance', []))}</section>")
    dc = result.get("dead_code", {})
    rows.append(f"<section><h2>死代码 ({dc.get('stats', {}).get('dead_count', 0)})</h2>{issue_table(dc.get('dead_code', []))}</section>")

    return (
        "<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>"
        f"<title>代码质量报告 - {html_lib.escape(result['project_name'])}</title>"
        "<style>body{font-family:system-ui;background:#1e1e2e;color:#cdd6f4;margin:0;padding:24px}"
        "h1{color:#89b4fa}h2{color:#f9e2af;border-bottom:1px solid #45475a;padding-bottom:6px}"
        "section{margin-bottom:28px}.cards{display:flex;flex-wrap:wrap;gap:12px}"
        ".card{background:#313244;padding:14px 18px;border-radius:8px;min-width:120px}.card b{display:block;font-size:1.4em;color:#a6e3a1;margin-top:4px}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #45475a;padding:8px;text-align:left}"
        "th{background:#313244}code{background:#45475a;padding:2px 6px;border-radius:4px}"
        ".ok{color:#a6e3a1}</style></head><body>"
        f"<h1>代码质量报告 - {html_lib.escape(result['project_name'])}</h1>"
        f"<p>生成时间: {result.get('analyzed_at', '')}</p>"
        + "".join(rows) +
        "<p><em>由 PyQuality 自动生成</em></p></body></html>"
    )