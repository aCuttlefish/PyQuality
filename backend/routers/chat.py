import json
import re
import subprocess
import sys
import difflib
import shutil
import time

from fastapi import APIRouter
from pydantic import BaseModel

from backend import database
from backend.ai import advisor, deepseek_client, fixer, test_generator
from backend.config import UPLOAD_DIR
from backend.logger import get_logger
from backend.routers.analysis import _build_analysis, _read_sources

logger = get_logger("chat")
router = APIRouter(prefix="/api", tags=["chat"])

PYTHON_SUFFIX = ".py"

COMMANDS = {
    "help": "help", "h": "help",
    "projects": "projects", "list": "projects",
    "use": "use", "switch": "use",
    "files": "files", "ls": "files",
    "analyze": "analyze", "analysis": "analyze",
    "smells": "smells", "smell": "smells",
    "score": "score", "readability": "score",
    "security": "security", "sec": "security",
    "deps": "deps", "dependencies": "deps",
    "deadcode": "deadcode", "dead": "deadcode",
    "funcs": "funcs", "functions": "funcs",
    "config": "config", "thresholds": "config",
    "history": "history", "trend": "history",
    "export": "export", "report": "export",
    "sample": "sample", "demo": "sample",
    "compare": "compare", "diff": "compare",
    "snippet": "snippet", "code": "snippet",
    "dashboard": "dashboard", "dash": "dashboard",
    "rename": "rename", "mv": "rename",
    "delete": "delete", "rm": "delete", "remove": "delete",
    "cicd": "cicd", "ci": "cicd", "github": "cicd",
    "tree": "tree", "filetree": "tree",
    "ignore": "ignore", "pyqualityignore": "ignore",
    "search": "search", "grep": "search", "find": "search",
    "doc": "doc", "docs": "doc", "docstring": "doc",
    "refactor": "refactor", "restructure": "refactor",
    "type": "type", "types": "type", "annotations": "type",
    "dup": "dup", "duplicate": "dup", "duplication": "dup",
    "perf": "perf", "performance": "perf", "hotspot": "perf",
    "tests": "tests", "test": "tests",
    "fix": "fix", "repair": "fix",
    "advice": "advice", "suggest": "advice",
    "summary": "summary", "overview": "summary",
}

KEYWORD_MAP = [
    ("分析", "analyze"), ("analyze", "analyze"),
    ("坏味", "smells"), ("smell", "smells"),
    ("评分", "score"), ("可读性", "score"), ("readability", "score"),
    ("测试", "tests"), ("test", "tests"),
    ("修复", "fix"), ("repair", "fix"),
    ("建议", "advice"), ("改进", "advice"), ("advice", "advice"),
    ("安全", "security"), ("security", "security"),
    ("依赖", "deps"), ("depend", "deps"),
    ("文件", "files"), ("file", "files"),
    ("帮助", "help"), ("help", "help"),
    ("项目", "projects"), ("project", "projects"),
    ("概览", "summary"), ("总结", "summary"),
    ("对比", "compare"), ("比较", "compare"), ("批量", "analyze"),
    ("片段", "snippet"), ("仪表盘", "dashboard"), ("概览全局", "dashboard"),
]


class ChatBody(BaseModel):
    message: str
    project_id: str = ""


@router.post("/chat")
def chat(body: ChatBody):
    msg = body.message.strip()
    pid = body.project_id
    cmd, arg = _parse_intent(msg)
    logger.info("chat cmd=%s arg=%s pid=%s", cmd, arg, pid)

    if cmd == "help":
        return {"reply": _help_text(), "project_id": pid}
    if cmd == "projects":
        return {"reply": _format_projects(arg), "project_id": pid}
    if cmd == "use":
        return _use_project(pid, arg)
    if cmd == "sample":
        return _do_sample()
    if cmd == "analyze" and arg.lower() == "all":
        return {"reply": _do_analyze_all(), "project_id": pid}
    if cmd == "snippet":
        return _do_snippet(arg)
    if cmd == "dashboard":
        return {"reply": _do_dashboard(), "project_id": pid}
    if cmd == "config":
        return {"reply": _format_config(arg), "project_id": pid}
    if cmd == "cicd":
        return {"reply": _do_cicd(arg), "project_id": pid}

    if not pid:
        return {"reply": "⚠ 请先选择项目。输入 `/projects` 查看列表，`/use <id>` 选择项目。\n\n或点击右上角上传项目。", "project_id": pid}
    project = database.get_project(pid)
    if not project:
        return {"reply": "⚠ 项目不存在，可能已删除。输入 `/projects` 查看列表。", "project_id": ""}

    if cmd == "files":
        return {"reply": _format_files(pid), "project_id": pid}
    if cmd == "tree":
        return {"reply": _format_tree(pid), "project_id": pid}
    if cmd == "ignore":
        return {"reply": _do_ignore(pid, arg), "project_id": pid}
    if cmd == "search":
        return {"reply": _do_search(pid, arg), "project_id": pid}
    if cmd == "doc":
        return {"reply": _format_doc(pid), "project_id": pid}
    if cmd == "refactor":
        return {"reply": _do_refactor(pid), "project_id": pid}
    if cmd == "type":
        return {"reply": _format_type_hints(pid), "project_id": pid}
    if cmd == "dup":
        return {"reply": _format_dup(pid), "project_id": pid}
    if cmd == "perf":
        return {"reply": _format_perf(pid), "project_id": pid}
    if cmd == "summary":
        return {"reply": _do_analyze(pid, project["name"], summary_only=True), "project_id": pid}
    if cmd == "analyze":

        return {"reply": _do_analyze(pid, project["name"]), "project_id": pid}
    if cmd == "smells":
        return {"reply": _format_smells(pid), "project_id": pid}
    if cmd == "score":
        return {"reply": _format_score(pid), "project_id": pid}
    if cmd == "security":
        return {"reply": _format_security(pid), "project_id": pid}
    if cmd == "deps":
        return {"reply": _format_deps(pid), "project_id": pid}
    if cmd == "tests":
        return {"reply": _do_tests(pid, arg), "project_id": pid}
    if cmd == "fix":
        return {"reply": _do_fix(pid, arg), "project_id": pid}
    if cmd == "advice":
        return {"reply": _do_advice(pid, arg), "project_id": pid}
    if cmd == "deadcode":
        return {"reply": _format_deadcode(pid), "project_id": pid}
    if cmd == "funcs":
        return {"reply": _format_funcs(pid), "project_id": pid}

    if cmd == "history":
        return {"reply": _format_history(pid), "project_id": pid}
    if cmd == "export":
        return {"reply": _do_export(pid, arg), "project_id": pid}
    if cmd == "compare":
        return {"reply": _do_compare(pid, arg), "project_id": pid}
    if cmd == "rename":
        return _do_rename(pid, arg)
    if cmd == "delete":
        return _do_delete(pid, arg)

    return {"reply": f"未识别的指令：`{msg}`\n\n输入 `/help` 查看可用命令。", "project_id": pid}


def _parse_intent(msg: str) -> tuple[str, str]:
    if msg.startswith("/"):
        parts = msg[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        return COMMANDS.get(cmd, "unknown"), arg
    msg_lower = msg.lower()
    for kw, cmd in KEYWORD_MAP:
        if kw in msg_lower:
            return cmd, ""
    return "unknown", ""


def _help_text() -> str:
    return """## 🤖 PyQuality 命令帮助

### 项目管理
- `/projects [关键词]` — 列出/搜索项目
- `/sample` — 加载内置示例项目
- `/use <id>` — 切换到指定项目
- `/files` — 列出当前项目文件
- `/tree` — 显示项目文件树
- `/ignore [add|del <pattern>]` — 管理忽略规则
- `/search <关键词>` — 在项目代码中搜索
- `/doc` — 文档覆盖详情（缺少 docstring 列表）
- `/type` — 类型注解详情（缺少注解列表）
- `/dup` — 重复代码详情
- `/perf` — 性能热点详情
- `/refactor` — 重构优先级建议
- `/rename <名称>` — 重命名当前项目
- `/delete confirm` — 删除当前项目
- `/dashboard` — 全局仪表盘（跨项目统计概览）
- `/snippet <代码>` — 直接分析一段 Python 代码

### 代码分析
- `/analyze` — 执行完整分析（11 类分析器，尊重 .pyqualityignore）
- `/analyze all` — 批量分析所有项目并排名
- `/summary` — 查看分析概览
- `/smells` — 查看代码坏味
- `/score` — 查看可读性评分 + 项目健康度
- `/security` — 查看安全问题
- `/deps` — 查看依赖关系
- `/deadcode` — 查看死代码检测
- `/funcs` — 查看函数复杂度
- `/compare <id>` — 对比当前项目与另一项目

### AI 助手
- `/tests [文件]` — 生成 pytest 测试用例
- `/tests all` — 批量为所有文件生成测试
- `/fix [文件]` — AI 修复代码
- `/fix all` — 批量修复所有有坏味的文件
- `/fix apply [文件]` — 修复并写入文件（自动备份）
- `/advice [文件]` — 生成改进建议
- `/advice all` — 批量为所有文件生成建议

### 其他
- `/config` — 查看分析阈值
- `/config set <key> <value>` — 修改阈值（持久化）
- `/config reset` — 恢复默认阈值
- `/history` — 查看分析历史趋势
- `/export <markdown|json|sarif|html>` — 导出报告
- `/cicd <github|gitlab>` — 生成 CI/CD 配置
- `/projects <关键词>` — 搜索项目

### 自然语言
直接输入「分析」「坏味」「评分」「测试」「修复」「建议」等关键词即可。

输入 `/help` 随时查看此帮助。"""


def _format_projects(keyword: str = "") -> str:
    projects = database.list_projects()
    if not projects:
        return "📋 暂无项目。请上传 Python 项目（.zip 或 .py 文件）后开始。"
    if keyword:
        kw = keyword.lower()
        filtered = [p for p in projects if kw in p["name"].lower() or kw in p["id"].lower()]
        if not filtered:
            return f"📋 未找到匹配「{keyword}」的项目。\n\n输入 `/projects` 查看全部。"
        projects = filtered
    lines = ["## 📋 项目列表\n"]
    if keyword:
        lines.append(f"搜索「{keyword}」— {len(projects)} 个结果\n")
    for p in projects:
        badge = f" `{p.get('score')}·{p.get('grade')}`" if p.get("grade") else ""
        lines.append(f"- **{p['name']}**{badge} — `{p['id']}` ({p['file_count']} 文件)")
        if p.get("last_analysis"):
            lines.append(f"  上次分析: {p['last_analysis']}")
    lines.append("\n使用 `/use <id>` 切换项目。")
    return "\n".join(lines)


def _use_project(cur_pid: str, arg: str) -> dict:
    if not arg:
        return {"reply": "⚠ 用法: `/use <项目ID>`\n\n输入 `/projects` 查看项目列表。", "project_id": cur_pid}
    project = database.get_project(arg)
    if not project:
        return {"reply": f"⚠ 项目 `{arg}` 不存在。输入 `/projects` 查看列表。", "project_id": cur_pid}
    badge = f"，评分 {project.get('score')}·{project.get('grade')}" if project.get("grade") else ""
    return {"reply": f"✅ 已切换到项目「**{project['name']}**」\n\n- ID: `{project['id']}`\n- 文件数: {project['file_count']}{badge}\n\n输入 `/analyze` 开始分析。", "project_id": arg}


def _format_files(pid: str) -> str:
    files = database.list_files(pid)
    py_files = [f for f in files if f["rel_path"].endswith(PYTHON_SUFFIX)]
    if not py_files:
        return "📁 当前项目无 Python 文件。"
    lines = [f"## 📁 文件列表（{len(py_files)} 个 Python 文件）\n"]
    for f in py_files:
        size_kb = f["size"] / 1024
        lines.append(f"- `{f['rel_path']}` ({size_kb:.1f} KB)")
    lines.append("\n使用 `/tests <文件名>` 对指定文件生成测试。")
    return "\n".join(lines)


def _format_tree(pid: str) -> str:
    files = database.list_files(pid)
    if not files:
        return "📁 项目中没有文件。"
    tree: dict = {}
    for f in files:
        parts = f["rel_path"].replace("\\", "/").split("/")
        node = tree
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = f["size"]
    lines = ["## 📁 项目文件树\n```\n."]
    def _render(node, prefix=""):
        items = sorted(node.items())
        for i, (k, v) in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "
            if isinstance(v, dict):
                lines.append(f"{prefix}{connector}{k}/")
                _render(v, prefix + ("    " if is_last else "│   "))
            else:
                size_str = f" ({v} B)" if v < 1024 else f" ({v // 1024} KB)"
                lines.append(f"{prefix}{connector}{k}{size_str}")
    _render(tree)
    lines.append("```")
    py_count = sum(1 for f in files if f["rel_path"].endswith(PYTHON_SUFFIX))
    lines.append(f"\n共 {len(files)} 文件（{py_count} Python）")
    return "\n".join(lines)


def _do_ignore(pid: str, arg: str) -> str:
    ignore_file = UPLOAD_DIR / pid / ".pyqualityignore"
    if not arg:
        if ignore_file.exists():
            content = ignore_file.read_text(encoding="utf-8").strip()
            return f"## 📋 .pyqualityignore\n\n```\n{content}\n```\n\n用法: `/ignore add <pattern>` 添加规则，`/ignore del <pattern>` 删除规则"
        return "## 📋 .pyqualityignore\n\n暂无忽略规则。\n\n用法: `/ignore add <pattern>` 添加规则（fnmatch 语法，如 `tests/*` `*_pb2.py`）"
    parts = arg.split(maxsplit=1)
    action = parts[0].lower()
    if action == "add" and len(parts) == 2:
        pattern = parts[1].strip()
        existing = ignore_file.read_text(encoding="utf-8").splitlines() if ignore_file.exists() else []
        if pattern in existing:
            return f"⚠ 规则 `{pattern}` 已存在。"
        existing.append(pattern)
        ignore_file.write_text("\n".join(existing) + "\n", encoding="utf-8")
        return f"✅ 已添加忽略规则 `{pattern}`\n\n下次 `/analyze` 将跳过匹配的文件。"
    if action == "del" and len(parts) == 2:
        pattern = parts[1].strip()
        if not ignore_file.exists():
            return "⚠ 暂无忽略规则。"
        existing = ignore_file.read_text(encoding="utf-8").splitlines()
        if pattern not in existing:
            return f"⚠ 规则 `{pattern}` 不存在。"
        existing.remove(pattern)
        ignore_file.write_text("\n".join(existing) + "\n", encoding="utf-8")
        return f"✅ 已删除忽略规则 `{pattern}`"
    return "⚠ 用法:\n- `/ignore` — 查看规则\n- `/ignore add <pattern>` — 添加规则\n- `/ignore del <pattern>` — 删除规则"


def _do_search(pid: str, arg: str) -> str:
    if not arg:
        return "⚠ 用法: `/search <关键词>`\n\n在项目所有 Python 文件中搜索关键词。"
    files = database.list_files(pid)
    py_files = [f["rel_path"] for f in files if f["rel_path"].endswith(PYTHON_SUFFIX)]
    if not py_files:
        return "⚠ 项目中没有 Python 文件。"
    kw = arg.lower()
    lines = [f"## 🔍 搜索「{arg}」\n"]
    total_matches = 0
    for file in py_files:
        abs_path = database.get_file_abs_path(pid, file)
        if abs_path is None:
            continue
        content = abs_path.read_text(encoding="utf-8", errors="replace")
        matches = []
        for i, line in enumerate(content.splitlines(), 1):
            if kw in line.lower():
                matches.append((i, line.strip()))
        if matches:
            total_matches += len(matches)
            lines.append(f"### `{file}` ({len(matches)} 匹配)")
            for lineno, text in matches[:10]:
                lines.append(f"- `{lineno}`: `{text[:120]}`")
            if len(matches) > 10:
                lines.append(f"- ...还有 {len(matches) - 10} 个匹配")
    if total_matches == 0:
        lines.append("未找到匹配。")
    else:
        lines.append(f"\n**共 {total_matches} 处匹配**")
    return "\n".join(lines)


def _format_doc(pid: str) -> str:
    result = _get_cached_analysis(pid)
    if not result:
        return "⚠ 尚未分析，请先输入 `/analyze`。"
    ds = result.get("docstrings", {})
    st = ds.get("stats", {})
    missing = ds.get("missing", [])
    lines = [f"## 📝 文档覆盖详情\n"]
    lines.append(f"**覆盖率:** 模块 {st.get('module_coverage', 0)}%  类 {st.get('class_coverage', 0)}%  函数 {st.get('function_coverage', 0)}%  总体 {st.get('overall', 0)}%\n")
    if not missing:
        lines.append("✅ 所有模块/类/函数都有 docstring。")
        return "\n".join(lines)
    by_file = {}
    for m in missing:
        by_file.setdefault(m["file"], []).append(m)
    lines.append(f"### 缺少 docstring（{len(missing)} 项）\n")
    for file in sorted(by_file):
        items = by_file[file]
        lines.append(f"**`{file}`** ({len(items)} 项)")
        for m in items:
            kind_emoji = {"module": "📦", "class": "🏷️", "function": "🔧"}.get(m["kind"], "⚪")
            lines.append(f"- {kind_emoji} `{m['line']}` **{m['name']}** ({m['kind']})")
        lines.append("")
    lines.append("💡 输入 `/advice` 让 AI 补充文档字符串。")
    return "\n".join(lines)


def _do_refactor(pid: str) -> str:
    result = _get_cached_analysis(pid)
    if not result:
        return "⚠ 尚未分析，请先输入 `/analyze`。"
    funcs = result.get("functions", [])
    smells = result.get("smells", [])
    rd = result["readability"]
    items = []
    for f in funcs:
        if f["bucket"] in ("high", "critical"):
            items.append({
                "priority": "🔴 高" if f["bucket"] == "critical" else "🟠 中",
                "file": f["file"],
                "line": f["line"],
                "issue": f"复杂度 {f['complexity']}（{f['bucket']}）",
                "action": "拆分函数，降低圈复杂度",
            })
    smell_actions = {
        "long_function": "拆分为多个小函数",
        "deep_nesting": "提取条件为早返回或独立函数",
        "long_params": "使用参数对象/关键字参数",
        "god_class": "拆分为多个职责单一的类",
        "duplicate_code": "提取公共逻辑为独立函数",
        "magic_number": "提取为命名常量",
    }
    for s in smells:
        if s["severity"] in ("high", "medium"):
            action = smell_actions.get(s["type"], "参考坏味建议修复")
            items.append({
                "priority": "🔴 高" if s["severity"] == "high" else "🟡 中",
                "file": s["file"],
                "line": s["line"],
                "issue": f"{s['type']}: {s['message']}",
                "action": action,
            })
    if not items:
        return "✅ 未发现需要重构的高优先级问题。代码结构良好。"
    items.sort(key=lambda x: (0 if "高" in x["priority"] else 1, x["file"], x["line"]))
    lines = [f"## 🔧 重构优先级（{len(items)} 项）\n"]
    lines.append("| 优先级 | 位置 | 问题 | 建议操作 |")
    lines.append("|--------|------|------|----------|")
    for item in items[:20]:
        lines.append(f"| {item['priority']} | `{item['file']}:{item['line']}` | {item['issue']} | {item['action']} |")
    if len(items) > 20:
        lines.append(f"\n...还有 {len(items) - 20} 项")
    lines.append(f"\n💡 输入 `/fix all` 让 AI 自动修复，或 `/advice` 获取详细建议。")
    return "\n".join(lines)


def _format_type_hints(pid: str) -> str:
    result = _get_cached_analysis(pid)
    if not result:
        return "⚠ 尚未分析，请先输入 `/analyze`。"
    th = result.get("type_hints", {})
    st = th.get("stats", {})
    missing = th.get("missing", [])
    lines = [f"## 🏷️ 类型注解详情\n"]
    lines.append(f"**覆盖率:** {st.get('coverage', 0)}%  已注解: {st.get('annotated', 0)}  缺少: {st.get('missing', 0)}\n")
    if not missing:
        lines.append("✅ 所有函数都有完整的类型注解。")
        return "\n".join(lines)
    by_file = {}
    for m in missing:
        by_file.setdefault(m["file"], []).append(m)
    lines.append(f"### 缺少类型注解（{len(missing)} 项）\n")
    for file in sorted(by_file):
        items = by_file[file]
        lines.append(f"**`{file}`** ({len(items)} 项)")
        for m in items:
            kind_label = {"both": "参数+返回值", "params": "参数", "return": "返回值"}.get(m["kind"], m["kind"])
            lines.append(f"- `{m['line']}` **{m['name']}** — 缺少 {kind_label}")
        lines.append("")
    lines.append("💡 输入 `/advice` 让 AI 添加类型注解。")
    return "\n".join(lines)


def _format_dup(pid: str) -> str:
    result = _get_cached_analysis(pid)
    if not result:
        return "⚠ 尚未分析，请先输入 `/analyze`。"
    dup = result.get("duplication", {})
    st = dup.get("stats", {})
    duplicates = dup.get("duplicates", [])
    lines = [f"## 📋 重复代码详情\n"]
    lines.append(f"**重复率:** {st.get('rate', 0)}%  重复函数组: {st.get('duplicate_groups', 0)}  总函数: {st.get('total_functions', 0)}\n")
    if not duplicates:
        lines.append("✅ 未检测到重复代码。")
        return "\n".join(lines)
    for i, group in enumerate(duplicates[:10], 1):
        lines.append(f"### 重复组 {i}")
        if isinstance(group, dict):
            for key in ("functions", "members", "items"):
                if key in group:
                    for member in group[key]:
                        if isinstance(member, dict):
                            lines.append(f"- `{member.get('file', '?')}:{member.get('line', '?')}` **{member.get('name', '?')}**")
                        else:
                            lines.append(f"- {member}")
                    break
            if "similarity" in group:
                lines.append(f"  相似度: {group['similarity']}%\n")
        else:
            lines.append(f"- {group}")
        lines.append("")
    if len(duplicates) > 10:
        lines.append(f"...还有 {len(duplicates) - 10} 组重复")
    lines.append("💡 输入 `/refactor` 查看重构建议。")
    return "\n".join(lines)


def _format_perf(pid: str) -> str:
    result = _get_cached_analysis(pid)
    if not result:
        return "⚠ 尚未分析，请先输入 `/analyze`。"
    perf = result.get("performance", [])
    if not perf:
        return "✅ 未检测到性能热点。"
    sev_order = {"high": 0, "medium": 1, "low": 2}
    sorted_perf = sorted(perf, key=lambda p: (sev_order.get(p["severity"], 9), p["file"], p["line"]))
    sev_emoji = {"high": "🔴", "medium": "🟡", "low": "🔵"}
    type_counts = {}
    for p in perf:
        type_counts[p["type"]] = type_counts.get(p["type"], 0) + 1
    lines = [f"## ⚡ 性能热点详情（{len(perf)} 项）\n"]
    lines.append("**类型分布:** " + "  ".join(f"`{t}`×{c}" for t, c in sorted(type_counts.items(), key=lambda x: x[1], reverse=True)) + "\n")
    for p in sorted_perf:
        emoji = sev_emoji.get(p["severity"], "⚪")
        lines.append(f"- {emoji} `{p['file']}:{p['line']}` **{p['type']}** — {p['message']}")
        if p.get("suggestion"):
            lines.append(f"  💡 {p['suggestion']}")
    lines.append("\n💡 输入 `/advice` 获取优化建议。")
    return "\n".join(lines)


def _get_cached_analysis(pid: str) -> dict | None:
    cached = database.get_analysis(pid)
    if not cached:
        return None
    try:
        return json.loads(cached)
    except json.JSONDecodeError:
        return None


def _ensure_analysis(pid: str, name: str) -> dict | str:
    result = _get_cached_analysis(pid)
    if result:
        return result
    return _run_analysis(pid, name)


def _run_analysis(pid: str, name: str) -> dict | str:
    files = database.list_files(pid)
    py_files = [f["rel_path"] for f in files if f["rel_path"].endswith(PYTHON_SUFFIX)]
    if not py_files:
        return "⚠ 项目中没有 Python 文件。"
    from backend.routers.analysis import _load_ignore_patterns, _is_ignored
    patterns = _load_ignore_patterns(pid)
    if patterns:
        py_files = [p for p in py_files if not _is_ignored(p, patterns)]
    sources = _read_sources(pid, py_files)
    if not sources:
        return "⚠ 无法读取项目文件。"
    result = _build_analysis(pid, name, sources)
    database.save_analysis(pid, json.dumps(result, ensure_ascii=False))
    from backend.routers.analysis import _analysis_summary
    database.save_analysis_history(pid, _analysis_summary(result))
    return result


def _bar(score: float, max_score: float = 100, width: int = 20) -> str:
    filled = int(score / max_score * width)
    return "█" * filled + "░" * (width - filled)


def _do_analyze(pid: str, name: str, summary_only: bool = False) -> str:
    result = _run_analysis(pid, name)
    if isinstance(result, str):
        return result
    s = result["stats"]
    rd = result["readability"]
    sec = result.get("security", [])
    deps = result.get("dependencies", {}).get("stats", {})
    th = result.get("type_hints", {}).get("stats", {})
    ds = result.get("docstrings", {}).get("stats", {})
    dup = result.get("duplication", {}).get("stats", {})
    perf = result.get("performance", [])

    lines = [
        f"## 🔍 分析完成 — {name}\n",
        f"**可读性评分: {rd['total']}/100 (等级 {rd['grade']})**",
        f"`{_bar(rd['total'])}` {rd['total']:.1f}/100\n",
        "### 概览",
        f"- 文件: **{s['total_files']}**  行数: **{s['total_lines']}**  函数: **{s['total_functions']}**  类: **{s['total_classes']}**",
        f"- 平均圈复杂度: **{s['avg_complexity']}**  注释率: **{s['comment_ratio']:.1%}**",
        f"- 坏味: **{len(result['smells'])}**  安全: **{len(sec)}**  循环依赖: **{deps.get('cycle_count', 0)}**",
        f"- 类型提示: **{th.get('coverage', 0)}%**  文档覆盖: **{ds.get('overall', 0)}%**  重复率: **{dup.get('rate', 0)}%**  性能热点: **{len(perf)}**",
    ]
    sev_counts = {"high": 0, "medium": 0, "low": 0}
    for sm in result["smells"]:
        sev_counts[sm["severity"]] = sev_counts.get(sm["severity"], 0) + 1
    if result["smells"]:
        lines.append(f"\n**坏味分布:** 🔴 {sev_counts['high']} high  🟡 {sev_counts['medium']} medium  🔵 {sev_counts['low']} low")
    if summary_only:
        lines.append("\n" + _smart_recommendations(result))
        lines.append("\n输入 `/smells` `/security` `/score` 等查看详情。")
        return "\n".join(lines)

    lines.append("\n### 可读性分项")
    for b in rd["breakdown"]:
        lines.append(f"- {b['metric']}: `{_bar(b['score'])}` **{b['score']}** ({b['detail']})")

    lines.append(f"\n### 代码坏味（{len(result['smells'])}）")
    for sm in result["smells"][:15]:
        lines.append(f"- [{sm['severity']}] `{sm['file']}:{sm['line']}` **{sm['type']}** — {sm['message']}")
    if len(result["smells"]) > 15:
        lines.append(f"- ...还有 {len(result['smells']) - 15} 条")

    if sec:
        lines.append(f"\n### 安全问题（{len(sec)}）")
        for issue in sec[:10]:
            lines.append(f"- [{issue['severity']}] `{issue['file']}:{issue['line']}` **{issue['type']}** — {issue['message']}")

    lines.append("\n" + _smart_recommendations(result))
    return "\n".join(lines)


def _smart_recommendations(result: dict) -> str:
    smells = result.get("smells", [])
    sec = result.get("security", [])
    rd = result["readability"]
    deps = result.get("dependencies", {}).get("stats", {})
    th = result.get("type_hints", {}).get("stats", {})
    ds = result.get("docstrings", {}).get("stats", {})
    perf = result.get("performance", [])
    high_smells = sum(1 for s in smells if s["severity"] == "high")
    recs = []
    if high_smells > 0:
        recs.append(f"🔴 检测到 **{high_smells}** 个高严重度坏味 → 输入 `/fix` 让 AI 自动修复")
    if sec:
        recs.append(f"🟡 检测到 **{len(sec)}** 个安全问题 → 输入 `/security` 查看详情，`/fix` 修复")
    if rd["total"] < 60:
        recs.append(f"📉 可读性仅 **{rd['total']:.0f}**/100 → 输入 `/advice` 获取改进建议")
    if th.get("coverage", 0) < 50:
        recs.append(f"🏷️ 类型提示覆盖仅 **{th.get('coverage', 0)}%** → 输入 `/advice` 添加类型注解")
    if ds.get("overall", 0) < 40:
        recs.append(f"📝 文档覆盖仅 **{ds.get('overall', 0)}%** → 输入 `/advice` 补充文档字符串")
    if deps.get("cycle_count", 0) > 0:
        recs.append(f"🔄 检测到 **{deps.get('cycle_count', 0)}** 个循环依赖 → 输入 `/deps` 查看依赖图")
    if len(perf) > 0:
        recs.append(f"⚡ 检测到 **{len(perf)}** 个性能热点 → 输入 `/advice` 优化建议")
    if not recs:
        recs.append("✅ 代码质量良好！建议输入 `/tests` 生成测试用例，`/export html` 导出报告")
    return "**💡 智能推荐:**\n" + "\n".join(f"- {r}" for r in recs)


def _format_smells(pid: str) -> str:
    result = _get_cached_analysis(pid)
    if not result:
        return "⚠ 尚未分析，请先输入 `/analyze`。"
    smells = result["smells"]
    if not smells:
        return "✅ 未检测到代码坏味。"
    sev_order = {"high": 0, "medium": 1, "low": 2}
    sorted_smells = sorted(smells, key=lambda s: (sev_order.get(s["severity"], 9), s["file"], s["line"]))
    sev_emoji = {"high": "🔴", "medium": "🟡", "low": "🔵"}
    sev_counts = {"high": 0, "medium": 0, "low": 0}
    type_counts = {}
    for s in smells:
        sev_counts[s["severity"]] = sev_counts.get(s["severity"], 0) + 1
        type_counts[s["type"]] = type_counts.get(s["type"], 0) + 1
    lines = [f"## 代码坏味（{len(smells)}）\n"]
    lines.append("**严重度分布:** " + "  ".join(f"{sev_emoji[k]} {sev_counts[k]}" for k in ["high", "medium", "low"] if sev_counts[k] > 0))
    top_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    lines.append("**坏味类型:** " + "  ".join(f"`{t}`×{c}" for t, c in top_types) + "\n")
    for s in sorted_smells:
        emoji = sev_emoji.get(s["severity"], "⚪")
        lines.append(f"- {emoji} `{s['file']}:{s['line']}` **{s['type']}** — {s['message']}")
        if s.get("suggestion"):
            lines.append(f"  💡 {s['suggestion']}")
    if sev_counts["high"] > 0:
        lines.append(f"\n💡 {sev_counts['high']} 个高严重度坏味 → 输入 `/fix` 让 AI 自动修复")
    return "\n".join(lines)


def _calc_health(result: dict) -> tuple[float, str, dict]:
    rd = result["readability"]
    smells = result.get("smells", [])
    sec = result.get("security", [])
    sev_w = {"high": 10, "medium": 5, "low": 2}
    smell_w = {"high": 5, "medium": 3, "low": 1}
    sec_deduct = sum(sev_w.get(s["severity"], 1) for s in sec)
    smell_deduct = sum(smell_w.get(s["severity"], 1) for s in smells)
    health = max(0, rd["total"] - sec_deduct - smell_deduct)
    grade = "A" if health >= 90 else "B" if health >= 80 else "C" if health >= 70 else "D" if health >= 60 else "E"
    detail = {"readability": rd["total"], "sec_deduct": sec_deduct, "smell_deduct": smell_deduct,
              "smell_count": len(smells), "sec_count": len(sec)}
    return health, grade, detail


def _format_score(pid: str) -> str:
    result = _get_cached_analysis(pid)
    if not result:
        return "⚠ 尚未分析，请先输入 `/analyze`。"
    rd = result["readability"]
    health, health_grade, hd = _calc_health(result)

    lines = [
        f"## 📊 项目健康度: **{health:.1f}/100** (等级 **{health_grade}**)",
        f"`{_bar(health)}` {health:.1f}/100\n",
        f"**计算方式**: 可读性 {rd['total']:.1f} − 安全扣分 {hd['sec_deduct']} − 坏味扣分 {hd['smell_deduct']} = {health:.1f}\n",
        f"### 可读性评分: **{rd['total']}/100** (等级 **{rd['grade']}**)\n",
    ]
    for b in rd["breakdown"]:
        lines.append(f"- {b['metric']}: `{_bar(b['score'])}` **{b['score']}** ({b['detail']})")
    return "\n".join(lines)


def _format_security(pid: str) -> str:
    result = _get_cached_analysis(pid)
    if not result:
        return "⚠ 尚未分析，请先输入 `/analyze`。"
    sec = result.get("security", [])
    if not sec:
        return "✅ 未发现安全问题。"
    lines = [f"## 安全问题（{len(sec)}）\n"]
    for issue in sec:
        lines.append(f"- [{issue['severity']}] `{issue['file']}:{issue['line']}` **{issue['type']}** — {issue['message']}")
        if issue.get("suggestion"):
            lines.append(f"  💡 {issue['suggestion']}")
    return "\n".join(lines)


def _format_deps(pid: str) -> str:
    result = _get_cached_analysis(pid)
    if not result:
        return "⚠ 尚未分析，请先输入 `/analyze`。"
    deps = result.get("dependencies", {})
    st = deps.get("stats", {})
    lines = ["## 依赖关系\n", f"- 模块: **{st.get('module_count', 0)}**  依赖边: **{st.get('edge_count', 0)}**  循环: **{st.get('cycle_count', 0)}**  最大深度: **{st.get('max_depth', 0)}**"]
    cycles = deps.get("cycles", [])
    if cycles:
        lines.append("\n### ⚠ 循环依赖")
        for c in cycles[:5]:
            lines.append(f"- {' → '.join(c)}")
    else:
        lines.append("\n✅ 无循环依赖。")
    return "\n".join(lines)


def _first_py_file(pid: str) -> str:
    files = database.list_files(pid)
    py_files = [f["rel_path"] for f in files if f["rel_path"].endswith(PYTHON_SUFFIX)]
    return py_files[0] if py_files else ""


def _do_tests(pid: str, file_arg: str) -> str:
    if file_arg.lower() == "all":
        return _do_tests_all(pid)
    file = file_arg or _first_py_file(pid)
    if not file:
        return "⚠ 未找到 Python 文件。"
    project_dir = UPLOAD_DIR / pid
    result = test_generator.generate_tests(project_dir, file, [])
    if not result.get("ok"):
        return f"⚠ 测试生成失败: {result.get('error', '未知错误')}"
    lines = [f"## 测试用例生成完成\n", f"- 文件: `{file}`", f"- 模式: {result['mode']}", f"- 函数: {', '.join(result['functions'])}", f"- 语法校验: {'✅ 通过' if result['syntax_valid'] else '⚠ 未通过'}\n"]
    for d in result["details"]:
        if d.get("note"):
            lines.append(f"> {d['note']}\n")
        lines.append(f"### {d['function']}\n```python\n{d['code']}\n```")
    return "\n".join(lines)


def _do_tests_all(pid: str) -> str:
    files = database.list_files(pid)
    py_files = [f["rel_path"] for f in files if f["rel_path"].endswith(PYTHON_SUFFIX)]
    if not py_files:
        return "⚠ 未找到 Python 文件。"
    project_dir = UPLOAD_DIR / pid
    lines = [f"## 🧪 批量测试生成（{len(py_files)} 个文件）\n"]
    success = 0
    failed = 0
    total_funcs = 0
    for file in py_files:
        result = test_generator.generate_tests(project_dir, file, [])
        if not result.get("ok"):
            lines.append(f"- ❌ `{file}` 失败: {result.get('error', '')}")
            failed += 1
            continue
        funcs = result.get("functions", [])
        total_funcs += len(funcs)
        lines.append(f"- ✅ `{file}` — {len(funcs)} 函数 — 模式: {result['mode']}")
        success += 1
    lines.append(f"\n**汇总:** ✅ {success} 成功  ❌ {failed} 失败  共 {total_funcs} 函数")
    if success > 0:
        lines.append("\n> 输入 `/tests <文件>` 查看具体测试代码。")
    return "\n".join(lines)


def _do_fix(pid: str, file_arg: str) -> str:
    apply = False
    parts = file_arg.split()
    apply_keywords = {"apply", "--apply", "-a", "写入", "应用"}
    apply = any(p.lower() in apply_keywords for p in parts)
    file_arg = " ".join(p for p in parts if p.lower() not in apply_keywords)

    if file_arg.lower() == "all":
        return _do_fix_all(pid, apply)

    file = file_arg or _first_py_file(pid)
    if not file:
        return "⚠ 未找到 Python 文件。"
    abs_path = database.get_file_abs_path(pid, file)
    if abs_path is None:
        return f"⚠ 文件 `{file}` 不存在。"
    source = abs_path.read_text(encoding="utf-8", errors="replace")
    analysis = _get_cached_analysis(pid)
    smells = analysis.get("smells", []) if analysis else []
    result = fixer.fix_code(file, source, smells)
    if not result.get("ok"):
        return f"⚠ AI 修复失败: {result.get('error', '未知错误')}"
    fixed_code = result["fixed_code"]
    validation = fixer.validate_fixed(source, fixed_code)
    lines = [f"## AI 修复完成\n", f"- 文件: `{file}`", f"- 校验: {'✅ 通过' if validation.get('valid') else '⚠ 失败'}"]
    if validation.get("warning"):
        lines.append(f"- 提示: {validation['warning']}")
    diff_stats = result.get("diff_stats")
    if diff_stats:
        lines.append(f"- 修改统计: +{diff_stats['added']} 行 -{diff_stats['removed']} 行")
    if result.get("warning"):
        lines.append(f"- 注意: {result['warning']}")
    lines.append(f"\n### 修复说明\n{result.get('explanation', '')}")

    diff_lines = list(difflib.unified_diff(
        source.splitlines(keepends=True), fixed_code.splitlines(keepends=True),
        fromfile=f"{file} (原)", tofile=f"{file} (修复后)", n=2,
    ))
    if diff_lines:
        diff_text = "".join(diff_lines)
        lines.append(f"\n### 修改对比 (diff)\n```diff\n{diff_text}\n```")

    behavior = _verify_behavior(pid, file, abs_path, fixed_code)
    if behavior:
        lines.append(f"\n### 行为等价性验证\n{behavior}")

    if apply and validation.get("valid"):
        backup_path = abs_path.with_suffix(abs_path.suffix + f".bak.{int(time.time())}")
        shutil.copy2(abs_path, backup_path)
        abs_path.write_text(fixed_code, encoding="utf-8")
        lines.append(f"\n✅ **已写入文件** `{file}`（原文件备份: `{backup_path.name}`）")
        lines.append(f"\n> 输入 `/analyze` 重新分析，或 `/tests` 生成测试验证。")
    elif apply:
        lines.append(f"\n⚠ 修复校验未通过，未写入文件。请检查 diff 后手动应用。")
    else:
        lines.append(f"\n> 输入 `/fix apply {file}` 可将修复写入文件（自动备份原文件）。")

    lines.append(f"\n### 修复后完整代码\n```python\n{fixed_code}\n```")
    return "\n".join(lines)


def _do_fix_all(pid: str, apply: bool) -> str:
    analysis = _get_cached_analysis(pid)
    if not analysis:
        return "⚠ 尚未分析，请先输入 `/analyze`。"
    smells = analysis.get("smells", [])
    if not smells:
        return "✅ 未检测到代码坏味，无需修复。"
    smelly_files = sorted(set(s["file"] for s in smells))
    lines = [f"## 🔧 批量 AI 修复（{len(smelly_files)} 个文件）\n"]
    success = 0
    failed = 0
    for file in smelly_files:
        abs_path = database.get_file_abs_path(pid, file)
        if abs_path is None:
            lines.append(f"- ⚠ `{file}` 文件不存在，跳过")
            failed += 1
            continue
        source = abs_path.read_text(encoding="utf-8", errors="replace")
        result = fixer.fix_code(file, source, smells)
        if not result.get("ok"):
            lines.append(f"- ❌ `{file}` 修复失败: {result.get('error', '')}")
            failed += 1
            continue
        fixed_code = result["fixed_code"]
        validation = fixer.validate_fixed(source, fixed_code)
        if not validation.get("valid"):
            lines.append(f"- ⚠ `{file}` 校验未通过: {validation.get('warning', '')}")
            failed += 1
            continue
        if apply:
            backup_path = abs_path.with_suffix(abs_path.suffix + f".bak.{int(time.time())}")
            shutil.copy2(abs_path, backup_path)
            abs_path.write_text(fixed_code, encoding="utf-8")
            stats = result.get("diff_stats", {})
            stat_str = f" (+{stats.get('added', 0)} -{stats.get('removed', 0)})" if stats else ""
            lines.append(f"- ✅ `{file}` 已修复并写入{stat_str}（备份: `{backup_path.name}`）")
        else:
            lines.append(f"- ✅ `{file}` 修复成功（输入 `/fix apply {file}` 写入）")
        success += 1
    lines.append(f"\n**汇总:** ✅ {success} 成功  ❌ {failed} 失败  共 {len(smelly_files)} 文件")
    if apply and success > 0:
        lines.append("\n> 输入 `/analyze` 重新分析修复后的代码。")
    elif success > 0:
        lines.append("\n> 输入 `/fix all apply` 将所有修复写入文件。")
    return "\n".join(lines)


def _verify_behavior(pid: str, file: str, abs_path, fixed_code: str) -> str:
    test_dir = UPLOAD_DIR / pid / "_generated_tests"
    if not test_dir.exists():
        return ""
    test_files = list(test_dir.glob("test_*.py"))
    if not test_files:
        return ""
    original = abs_path.read_text(encoding="utf-8", errors="replace")
    try:
        abs_path.write_text(fixed_code, encoding="utf-8")
        results = []
        for tf in test_files:
            r = subprocess.run(
                [sys.executable, "-m", "pytest", str(tf), "--tb=no", "-q"],
                capture_output=True, text=True, timeout=20, cwd=str(UPLOAD_DIR / pid),
            )
            out = r.stdout + r.stderr
            passed = re.search(r"(\d+)\s+passed", out)
            failed = re.search(r"(\d+)\s+failed", out)
            p = int(passed.group(1)) if passed else 0
            f = int(failed.group(1)) if failed else 0
            results.append((tf.name, p, f))
    finally:
        abs_path.write_text(original, encoding="utf-8")
    total_passed = sum(p for _, p, _ in results)
    total_failed = sum(f for _, _, f in results)
    if total_failed == 0:
        return f"✅ 修复后 {total_passed} 个测试全部通过，行为等价。"
    return f"⚠ 修复后 {total_passed} passed, {total_failed} failed，可能改变了函数行为。"


def _do_advice(pid: str, file_arg: str) -> str:
    if file_arg.lower() == "all":
        return _do_advice_all(pid)
    file = file_arg or _first_py_file(pid)
    if not file:
        return "⚠ 未找到 Python 文件。"
    abs_path = database.get_file_abs_path(pid, file)
    if abs_path is None:
        return f"⚠ 文件 `{file}` 不存在。"
    source = abs_path.read_text(encoding="utf-8", errors="replace")
    analysis = _get_cached_analysis(pid)
    smells = analysis.get("smells", []) if analysis else []
    result = advisor.generate_advice(file, source, smells)
    mode_label = {"ai": "DeepSeek AI", "rule": "规则引擎", "rule_fallback": "规则引擎（AI 失败降级）", "none": "无坏味"}.get(result.get("mode"), "")
    lines = [f"## 改进建议\n", f"- 文件: `{file}`", f"- 模式: {mode_label}\n"]
    lines.append(result.get("advice", ""))
    return "\n".join(lines)


def _do_advice_all(pid: str) -> str:
    files = database.list_files(pid)
    py_files = [f["rel_path"] for f in files if f["rel_path"].endswith(PYTHON_SUFFIX)]
    if not py_files:
        return "⚠ 未找到 Python 文件。"
    analysis = _get_cached_analysis(pid)
    smells = analysis.get("smells", []) if analysis else []
    lines = [f"## 💡 批量改进建议（{len(py_files)} 个文件）\n"]
    success = 0
    failed = 0
    for file in py_files:
        abs_path = database.get_file_abs_path(pid, file)
        if abs_path is None:
            lines.append(f"- ⚠ `{file}` 文件不存在，跳过")
            failed += 1
            continue
        source = abs_path.read_text(encoding="utf-8", errors="replace")
        result = advisor.generate_advice(file, source, smells)
        if not result.get("advice"):
            lines.append(f"- ⚠ `{file}` 无建议")
            failed += 1
            continue
        mode_label = {"ai": "AI", "rule": "规则", "rule_fallback": "规则(降级)", "none": "无坏味"}.get(result.get("mode"), "")
        lines.append(f"### `{file}` ({mode_label})\n")
        lines.append(result["advice"] + "\n")
        success += 1
    lines.append(f"**汇总:** ✅ {success} 成功  ⚠ {failed} 无建议  共 {len(py_files)} 文件")
    return "\n".join(lines)


def _format_deadcode(pid: str) -> str:
    result = _get_cached_analysis(pid)
    if not result:
        return "⚠ 尚未分析，请先输入 `/analyze`。"
    dc = result.get("dead_code", {})
    st = dc.get("stats", {})
    items = dc.get("dead_code", [])
    lines = [f"## 死代码检测（死代码率 {st.get('dead_rate', 0)}%）\n", f"- 定义总数: **{st.get('total_definitions', 0)}**  疑似死代码: **{st.get('dead_count', 0)}**\n"]
    if not items:
        lines.append("✅ 未发现死代码。")
    else:
        for d in items[:20]:
            lines.append(f"- [{d['kind']}] `{d['file']}:{d['line']}` **{d['name']}** — {d['message']}")
        if len(items) > 20:
            lines.append(f"- ...还有 {len(items) - 20} 条")
    return "\n".join(lines)


def _format_funcs(pid: str) -> str:
    result = _get_cached_analysis(pid)
    if not result:
        return "⚠ 尚未分析，请先输入 `/analyze`。"
    funcs = result.get("functions", [])
    if not funcs:
        return "无函数。"
    sorted_funcs = sorted(funcs, key=lambda f: f["complexity"], reverse=True)
    bucket_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}
    bucket_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for f in funcs:
        bucket_counts[f["bucket"]] = bucket_counts.get(f["bucket"], 0) + 1
    max_cx = max(f["complexity"] for f in funcs) or 1
    lines = [f"## 🔥 函数复杂度热力图（{len(funcs)} 个函数）\n"]
    lines.append(f"**分布:** " + "  ".join(f"{bucket_emoji[b]} {bucket_counts[b]}" for b in ["critical", "high", "medium", "low"] if bucket_counts[b] > 0))
    lines.append(f"**最大复杂度:** {max_cx}  **平均:** {sum(f['complexity'] for f in funcs) / len(funcs):.1f}\n")
    lines.append("| 复杂度 | 函数 | 位置 | 长度 | 嵌套 |")
    lines.append("|--------|------|------|------|------|")
    for f in sorted_funcs[:25]:
        emoji = bucket_emoji.get(f["bucket"], "⚪")
        bar = _bar(f["complexity"], max_score=max_cx, width=10)
        lines.append(f"| {emoji} {f['complexity']} `{bar}` | **{f['name']}** | `{f['file']}:{f['line']}` | {f['length']} | {f['nesting']} |")
    if len(funcs) > 25:
        lines.append(f"\n...还有 {len(funcs) - 25} 个函数（已按复杂度降序排列）")
    critical = bucket_counts["critical"] + bucket_counts["high"]
    if critical > 0:
        lines.append(f"\n💡 **{critical}** 个高复杂度函数建议重构 → 输入 `/advice` 获取建议")
    return "\n".join(lines)


def _format_config(arg: str = "") -> str:
    from backend import config
    if arg:
        parts = arg.split(maxsplit=2)
        if parts[0] == "set" and len(parts) == 3:
            return _config_set(parts[1], parts[2])
        if parts[0] == "reset":
            return _config_reset()
        return "⚠ 用法:\n- `/config set <key> <value>` — 修改阈值\n- `/config reset` — 恢复默认\n- `/config` — 查看当前配置"
    lines = ["## 分析阈值配置\n", "**坏味阈值:**"]
    for k, v in config.SMELL_THRESHOLDS.items():
        lines.append(f"- `{k}`: {v}")
    lines.append("\n**可读性权重:**")
    for k, v in config.READABILITY_WEIGHTS.items():
        lines.append(f"- `{k}`: {v}")
    lines.append(f"\n**其他:** 重复最小行数={config.DUPLICATION_MIN_LINES}  类型提示最低覆盖={config.TYPE_HINTS_MIN_COVERAGE}%  文档最低覆盖={config.DOCSTRING_MIN_COVERAGE}%")
    lines.append("\n💡 修改: `/config set <key> <value>`  重置: `/config reset`")
    return "\n".join(lines)


_CONFIG_KEYS = {
    "long_function_lines": ("SMELL_THRESHOLDS", int),
    "long_params": ("SMELL_THRESHOLDS", int),
    "deep_nesting": ("SMELL_THRESHOLDS", int),
    "god_class_methods": ("SMELL_THRESHOLDS", int),
    "god_class_lines": ("SMELL_THRESHOLDS", int),
    "long_file_lines": ("SMELL_THRESHOLDS", int),
    "long_line_chars": ("SMELL_THRESHOLDS", int),
    "magic_number_repeat": ("SMELL_THRESHOLDS", int),
    "duplicate_block_lines": ("SMELL_THRESHOLDS", int),
    "duplicate_min_tokens": ("SMELL_THRESHOLDS", int),
    "type_hints_min_coverage": ("NUMERIC", float),
    "docstring_min_coverage": ("NUMERIC", float),
    "duplication_min_lines": ("NUMERIC", int),
}


def _config_set(key: str, value: str) -> str:
    from backend import config
    if key not in _CONFIG_KEYS:
        avail = ", ".join(f"`{k}`" for k in _CONFIG_KEYS)
        return f"⚠ 未知配置项 `{key}`。\n\n可用项: {avail}"
    group, cast = _CONFIG_KEYS[key]
    try:
        val = cast(float(value)) if cast is int else cast(value)
    except ValueError:
        return f"⚠ 值 `{value}` 无法转为 {cast.__name__}。"
    if group == "SMELL_THRESHOLDS":
        config.SMELL_THRESHOLDS[key] = val
    elif group == "NUMERIC":
        setattr(config, key.upper(), val)
    config.save_user_config()
    return f"✅ 已设置 `{key}` = {val}\n\n配置已持久化，输入 `/config` 查看。"


def _config_reset() -> str:
    from backend import config
    if config.CONFIG_FILE.exists():
        config.CONFIG_FILE.unlink()
    return "✅ 已删除自定义配置文件。重启服务后恢复默认阈值。"


_TREND_CHARS = "▁▂▃▄▅▆▇█"


def _trend_line(values: list[int], label: str, color: str = "") -> str:
    if not values:
        return f"{label}: 无数据"
    mx = max(values) or 1
    bars = []
    for v in values:
        idx = min(int(v / mx * 7), 7)
        bars.append(_TREND_CHARS[idx])
    trend_arrow = "↓" if values[-1] < values[0] else ("↑" if values[-1] > values[0] else "→")
    return f"{label} {color}{''.join(bars)}{color}  范围 {min(values)}–{max(values)}  趋势 {trend_arrow}"


def _format_history(pid: str) -> str:
    history = database.list_analysis_history(pid, limit=20)
    if not history:
        return "暂无历史数据，先输入 `/analyze`。"
    chrono = list(reversed(history))
    smells = [h["summary"].get("smell_count", 0) for h in chrono]
    security = [h["summary"].get("security_count", 0) for h in chrono]
    dead = [h["summary"].get("dead_code_count", 0) for h in chrono]
    readability = [h["summary"].get("readability_total", 0) for h in chrono]
    lines = ["## 分析历史趋势\n"]
    lines.append("```\n" + _trend_line(smells, "坏味  ", "🔴") + "\n")
    lines.append(_trend_line(security, "安全  ", "🟡") + "\n")
    lines.append(_trend_line(dead, "死代码", "🔵") + "\n")
    lines.append(_trend_line(readability, "可读性", "🟢") + "\n```")
    lines.append(f"\n共 {len(history)} 次分析（从旧 → 新）\n")
    lines.append("| 时间 | 可读性 | 等级 | 坏味 | 安全 | 死代码 |")
    lines.append("|------|--------|------|------|------|--------|")
    for h in history:
        s = h["summary"]
        lines.append(f"| {s.get('analyzed_at', '')[-8:]} | {s.get('readability_total', 0)} | {s.get('readability_grade', '')} | {s.get('smell_count', 0)} | {s.get('security_count', 0)} | {s.get('dead_code_count', 0)} |")
    if len(chrono) >= 2:
        alerts = []
        if smells[-1] > smells[0]:
            alerts.append(f"⚠ 坏味增加 {smells[-1] - smells[0]} 个 → 输入 `/fix all` 修复")
        if readability[-1] < readability[0]:
            alerts.append(f"⚠ 可读性下降 {readability[0] - readability[-1]:.1f} 分 → 输入 `/advice all` 获取建议")
        if security[-1] > security[0]:
            alerts.append(f"⚠ 安全问题增加 {security[-1] - security[0]} 个 → 输入 `/security` 查看详情")
        if not alerts and (smells[-1] < smells[0] or readability[-1] > readability[0]):
            alerts.append("✅ 代码质量呈改善趋势，继续保持！")
        if alerts:
            lines.append("\n**趋势预警:**\n" + "\n".join(f"- {a}" for a in alerts))
    return "\n".join(lines)


def _do_snippet(code: str) -> dict:
    if not code:
        return {"reply": "⚠ 用法: `/snippet <Python代码>`\n\n示例: `/snippet def foo(): return 42`", "project_id": ""}
    if not code.strip().startswith(("def ", "class ", "import ", "from ", "#", "@")):
        if "\n" not in code and len(code) > 3:
            pass
    import uuid
    new_pid = uuid.uuid4().hex[:12]
    target = UPLOAD_DIR / new_pid
    target.mkdir(parents=True, exist_ok=True)
    (target / "snippet.py").write_text(code, encoding="utf-8")
    records = [{"rel_path": "snippet.py", "size": len(code.encode("utf-8"))}]
    project = database.create_project("代码片段", f"snippet {new_pid}", records, pid=new_pid)
    reply = _do_analyze(new_pid, "代码片段")
    return {"reply": reply, "project_id": new_pid}


def _do_dashboard() -> str:
    projects = database.list_projects()
    if not projects:
        return "📋 暂无项目。请先上传项目或输入 `/sample` 加载示例。"
    lines = [f"## 📊 全局仪表盘（{len(projects)} 个项目）\n"]
    total_files = 0
    total_lines = 0
    total_smells = 0
    total_sec = 0
    health_list = []
    grade_dist = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0, "—": 0}
    for p in projects:
        result = _get_cached_analysis(p["id"])
        if not result:
            grade_dist["—"] += 1
            continue
        s = result["stats"]
        total_files += s["total_files"]
        total_lines += s["total_lines"]
        total_smells += len(result["smells"])
        total_sec += len(result.get("security", []))
        h, g, _ = _calc_health(result)
        health_list.append(h)
        grade_dist[g] += 1
    lines.append(f"- **总文件:** {total_files}  **总行数:** {total_lines}")
    lines.append(f"- **总坏味:** {total_smells}  **总安全问题:** {total_sec}")
    if health_list:
        avg_h = sum(health_list) / len(health_list)
        lines.append(f"- **平均健康度:** {avg_h:.1f}/100  **最高:** {max(health_list):.1f}  **最低:** {min(health_list):.1f}")
    lines.append(f"\n### 等级分布")
    grade_bar = ""
    for g in "ABCDE":
        cnt = grade_dist[g]
        grade_bar += f"{g}:{cnt} " + "█" * cnt + "  "
    lines.append(f"`{grade_bar.strip()}`")
    if grade_dist["—"] > 0:
        lines.append(f"未分析: {grade_dist['—']} 个")
    lines.append("\n使用 `/analyze all` 批量分析，`/compare <id>` 对比项目。")
    return "\n".join(lines)


def _do_analyze_all() -> str:
    projects = database.list_projects()
    if not projects:
        return "📋 暂无项目。请先上传项目或输入 `/sample` 加载示例。"
    lines = [f"## 🔍 批量分析（{len(projects)} 个项目）\n"]
    lines.append("| 项目 | 文件 | 可读性 | 坏味 | 安全 | 健康度 | 等级 |")
    lines.append("|------|------|--------|------|------|--------|------|")
    ranked = []
    for p in projects:
        result = _run_analysis(p["id"], p["name"])
        if isinstance(result, str):
            lines.append(f"| **{p['name']}** | {p['file_count']} | — | — | — | — | ⚠ |")
            continue
        s = result["stats"]
        rd = result["readability"]
        health, grade, _ = _calc_health(result)
        ranked.append((p["name"], health, grade))
        lines.append(f"| **{p['name']}** | {s['total_files']} | {rd['total']:.1f} | {len(result['smells'])} | {len(result.get('security', []))} | `{_bar(health, width=10)}` {health:.0f} | {grade} |")
    if len(ranked) >= 2:
        ranked.sort(key=lambda x: x[1], reverse=True)
        lines.append(f"\n**🏆 健康度排名:** " + " > ".join(f"{n}({h:.0f}{g})" for n, h, g in ranked))
    lines.append("\n使用 `/use <id>` 选择项目查看详情，`/compare <id>` 对比两个项目。")
    return "\n".join(lines)


def _do_compare(pid: str, arg: str) -> str:
    if not arg:
        projects = database.list_projects()
        if not projects:
            return "⚠ 暂无项目可对比。"
        lines = ["## 选择项目进行对比\n", "用法: `/compare <项目ID>`\n"]
        for p in projects:
            mark = " ← 当前" if p["id"] == pid else ""
            lines.append(f"- `{p['id']}` **{p['name']}**{mark}")
        return "\n".join(lines)
    other = database.get_project(arg)
    if not other:
        return f"⚠ 项目 `{arg}` 不存在。输入 `/compare` 查看项目列表。"
    current = database.get_project(pid)
    if not current:
        return "⚠ 当前项目不存在。"
    if arg == pid:
        return "⚠ 不能与自身对比，请选择另一个项目。"
    r1 = _ensure_analysis(pid, current["name"])
    r2 = _ensure_analysis(arg, other["name"])
    if isinstance(r1, str) or isinstance(r2, str):
        return "⚠ 分析失败，请先对两个项目执行 `/analyze`。"
    h1, g1, _ = _calc_health(r1)
    h2, g2, _ = _calc_health(r2)
    n1, n2 = current["name"], other["name"]

    def _row(label: str, v1, v2, fmt="{:.1f}", lower_better: bool = False) -> str:
        d = v1 - v2
        if abs(d) < 0.05:
            sym = "＝"
        elif (d > 0 and not lower_better) or (d < 0 and lower_better):
            sym = "✅"
        else:
            sym = "❌"
        return f"| {label} | {fmt.format(v1)} | {fmt.format(v2)} | {sym} {fmt.format(abs(d))} |"

    th1 = r1.get("type_hints", {}).get("stats", {}).get("coverage", 0)
    th2 = r2.get("type_hints", {}).get("stats", {}).get("coverage", 0)
    ds1 = r1.get("docstrings", {}).get("stats", {}).get("overall", 0)
    ds2 = r2.get("docstrings", {}).get("stats", {}).get("overall", 0)
    lines = [
        "## 📊 项目对比\n",
        f"| 指标 | **{n1}** | **{n2}** | 差值 |",
        "|------|------|------|------|",
        _row("可读性", r1["readability"]["total"], r2["readability"]["total"]),
        _row("健康度", h1, h2),
        _row("坏味数", len(r1["smells"]), len(r2["smells"]), "{:.0f}", True),
        _row("安全问题", len(r1.get("security", [])), len(r2.get("security", [])), "{:.0f}", True),
        _row("平均复杂度", r1["stats"]["avg_complexity"], r2["stats"]["avg_complexity"], "{:.1f}", True),
        _row("类型提示%", th1, th2, "{:.0f}"),
        _row("文档覆盖%", ds1, ds2, "{:.0f}"),
    ]
    if abs(h1 - h2) < 0.05:
        lines.append("\n**综合评价:** 两个项目健康度持平。")
    else:
        winner = n1 if h1 > h2 else n2
        lines.append(f"\n**🏆 综合评价:** {winner} 更优（健康度差 {abs(h1 - h2):.1f}）")
    return "\n".join(lines)


def _do_cicd(arg: str) -> str:
    fmt = arg or "github"
    if fmt not in ("github", "gitlab"):
        return "⚠ 格式可选: github / gitlab\n\n用法: `/cicd github`"
    if fmt == "github":
        workflow = """name: Code Quality Check

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install PyQuality
        run: |
          pip install fastapi uvicorn pydantic requests httpx pytest

      - name: Run analysis
        env:
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
        run: |
          python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
          sleep 3
          PID=$(curl -s -X POST http://127.0.0.1:8000/api/projects/upload \\
            -F "archive=@." \\
            -F "name=CI-Check" | python -c "import sys,json; print(json.load(sys.stdin)['project']['id'])")
          curl -s -X POST http://127.0.0.1:8000/api/projects/$PID/analyze
          curl -s http://127.0.0.1:8000/api/projects/$PID/report?format=sarif > quality.sarif

      - name: Upload SARIF report
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: quality.sarif

      - name: Run tests
        run: python -m pytest tests/ -q
"""
        return f"## 🔧 GitHub Actions CI/CD 配置\n\n将以下内容保存为 `.github/workflows/quality.yml`：\n\n```yaml\n{workflow}\n```\n\n**说明:**\n- 每次 push/PR 自动触发\n- 运行 PyQuality 分析并生成 SARIF 报告\n- SARIF 报告上传到 GitHub Code Scanning\n- 需要在仓库 Settings → Secrets 添加 `DEEPSEEK_API_KEY`（可选）"

    gitlab_ci = """stages:
  - quality

code_quality:
  stage: quality
  image: python:3.12
  script:
    - pip install fastapi uvicorn pydantic requests httpx pytest
    - python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
    - sleep 3
    - PID=$(curl -s -X POST http://127.0.0.1:8000/api/projects/upload -F "archive=@." -F "name=CI-Check" | python -c "import sys,json; print(json.load(sys.stdin)['project']['id'])")
    - curl -s -X POST http://127.0.0.1:8000/api/projects/$PID/analyze
    - curl -s http://127.0.0.1:8000/api/projects/$PID/report?format=json > quality-report.json
  artifacts:
    paths:
      - quality-report.json
    expire_in: 7 days
"""
    return f"## 🔧 GitLab CI 配置\n\n将以下内容保存为 `.gitlab-ci.yml`：\n\n```yaml\n{gitlab_ci}\n```\n\n**说明:**\n- 每次 push 自动触发\n- 运行 PyQuality 分析并生成 JSON 报告\n- 报告作为 artifact 保存 7 天"


def _do_rename(pid: str, arg: str) -> dict:
    if not arg:
        return {"reply": "⚠ 用法: `/rename <新名称>`", "project_id": pid}
    if len(arg) > 60:
        return {"reply": "⚠ 项目名称不能超过 60 字符。", "project_id": pid}
    if database.rename_project(pid, arg):
        return {"reply": f"✅ 项目已重命名为「**{arg}**」", "project_id": pid}
    return {"reply": "⚠ 重命名失败，项目可能不存在。", "project_id": pid}


def _do_delete(pid: str, arg: str) -> dict:
    confirm = arg.lower() in ("yes", "confirm", "确认", "y")
    if not confirm:
        project = database.get_project(pid)
        name = project["name"] if project else pid
        return {"reply": f"⚠ 确认删除项目「**{name}**」？此操作不可撤销。\n\n输入 `/delete confirm` 确认删除。", "project_id": pid}
    project = database.get_project(pid)
    name = project["name"] if project else pid
    if database.delete_project(pid):
        return {"reply": f"✅ 项目「**{name}**」已删除。", "project_id": ""}
    return {"reply": "⚠ 删除失败，项目可能不存在。", "project_id": ""}


def _do_export(pid: str, arg: str) -> str:
    fmt = arg or "markdown"
    if fmt not in ("markdown", "json", "sarif", "html"):
        return "⚠ 格式可选: markdown / json / sarif / html\n\n用法: `/export sarif`"
    return f"## 导出报告\n\n在浏览器打开以下链接下载 `{fmt}` 报告：\n\n[/api/projects/{pid}/report?format={fmt}](/api/projects/{pid}/report?format={fmt})"


def _do_sample() -> dict:
    import shutil
    import uuid
    from backend.config import BASE_DIR
    sample_dir = BASE_DIR / "samples" / "demo_project"
    if not sample_dir.exists():
        return {"reply": "⚠ 示例项目不存在", "project_id": ""}
    new_pid = uuid.uuid4().hex[:12]
    target = UPLOAD_DIR / new_pid
    target.mkdir(parents=True, exist_ok=True)
    records = []
    for src in sorted(sample_dir.rglob("*.py")):
        rel = src.relative_to(sample_dir)
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        records.append({"rel_path": str(rel).replace("\\", "/"), "size": src.stat().st_size})
    project = database.create_project("示例项目-学生成绩管理", "内置示例", records, pid=new_pid)
    return {"reply": f"✅ 已加载示例项目「**{project['name']}**」（{len(records)} 个文件）。\n\n输入 `/analyze` 开始分析。", "project_id": new_pid}