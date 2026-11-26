from backend.ai import deepseek_client
from backend.analyzers.smells import SUGGESTIONS
from backend.config import SMELL_THRESHOLDS

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

_SMELL_FIX_EXAMPLES = {
    "long_function": "提取子函数：将长函数按职责拆分为多个 _helper 函数，主函数只做编排",
    "deep_nesting": "卫语句：将 if 嵌套改为提前返回，如 `if not x: return` 替代深层 if",
    "long_params": "参数对象：将多个参数打包为 dataclass 或 TypedDict",
    "god_class": "职责拆分：将大类按功能拆分为多个小类",
    "magic_number": "命名常量：`MAX_RETRY = 3` 替代裸数字 3",
    "broad_except": "具体异常：`except (ValueError, KeyError)` 替代 `except Exception`",
    "missing_docstring": "添加 docstring：`\"\"\"函数功能描述。\"\"\"`",
    "unused_import": "删除未使用的 import 语句",
    "unused_variable": "删除未使用的变量或加 `_` 前缀",
    "global_variable": "改为函数参数或类属性，避免全局可变状态",
    "long_line": "换行：在括号内自然换行或使用反斜杠续行",
    "long_file": "拆分模块：将大类或相关函数组提取到独立文件",
    "duplicate_code": "提取公共函数：将重复逻辑抽取为共享 helper",
    "naming_violation": "重命名：`snake_case` 函数/变量，`PascalCase` 类名",
}


def generate_advice(rel_path: str, source: str, smells: list[dict]) -> dict:
    target_smells = [s for s in smells if s["file"] == rel_path]
    if not target_smells:
        return {
            "ok": True,
            "mode": "none",
            "advice": f"文件 {rel_path} 未检测到坏味，保持现状即可。",
            "items": [],
        }
    target_smells.sort(key=lambda s: (SEVERITY_ORDER.get(s["severity"], 3), s["line"]))

    if deepseek_client.is_available():
        mode = "ai"
        advice, items, err = _advice_by_ai(rel_path, source, target_smells)
        if err:
            mode = "rule_fallback"
            advice, items = _advice_by_rule(rel_path, target_smells), _rule_items(target_smells)
    else:
        mode = "rule"
        advice, items = _advice_by_rule(rel_path, target_smells), _rule_items(target_smells)

    return {"ok": True, "mode": mode, "advice": advice, "items": items}


def _advice_by_ai(rel_path: str, source: str, smells: list[dict]) -> tuple[str, list[dict], str]:
    smell_lines = "\n".join(
        f"- [{s['severity']}] 行{s['line']} {s['type']}: {s['message']}" for s in smells[:20]
    )
    fix_hints = "\n".join(
        f"  {t}: {_SMELL_FIX_EXAMPLES.get(t, '参考坏味建议')}"
        for t in sorted({s["type"] for s in smells})
    )
    truncated = source[:6000]
    prompt = f"""你是资深 Python 代码审查专家。针对以下文件及其检测到的代码坏味，给出具体可操作的改进建议。

文件: {rel_path}
代码:
```python
{truncated}
```

检测到的坏味:
{smell_lines}

各坏味修复参考:
{fix_hints}

要求:
1. 逐条给出修复建议，按严重程度排序（high → medium → low）
2. 每条建议必须包含:
   - **问题**: 具体什么坏味，在哪一行
   - **影响**: 这个问题会导致什么后果（可读性/可维护性/性能/安全）
   - **方案**: 具体修复步骤
   - **示例**: before/after 代码对比（用 ```python 代码块```）
3. 最后给出一段整体改进总结，说明修复优先级和建议的修复顺序
4. 使用 Markdown 格式，结构清晰

只输出 JSON: {{"advice": "markdown文本", "items": [{{"line": 行号, "type": "坏味类型", "severity": "high/medium/low", "suggestion": "具体修复建议"}}]}}"""
    try:
        data = deepseek_client.chat_json([{"role": "user", "content": prompt}], temperature=0.3)
        advice = data.get("advice", "")
        items = data.get("items", [])
        if not advice:
            return "", [], "AI 返回内容为空"
        return advice, items, ""
    except Exception as e:
        return "", [], str(e)


def _advice_by_rule(rel_path: str, smells: list[dict]) -> str:
    lines = [f"# {rel_path} 改进建议", ""]
    by_sev: dict[str, list[dict]] = {"high": [], "medium": [], "low": []}
    for s in smells:
        by_sev.setdefault(s["severity"], []).append(s)
    for sev, title in (("high", "🔴 严重问题"), ("medium", "🟡 一般问题"), ("low", "🔵 轻微问题")):
        group = by_sev.get(sev, [])
        if not group:
            continue
        lines.append(f"## {title} ({len(group)})")
        for s in group:
            fix_hint = _SMELL_FIX_EXAMPLES.get(s["type"], s.get("suggestion", ""))
            lines.append(f"### 行 {s['line']} — {s['type']}")
            lines.append(f"**问题**: {s['message']}")
            lines.append(f"**方案**: {fix_hint}")
            lines.append("")
    lines.append("## 整体建议")
    types = {s["type"] for s in smells}
    priorities = []
    if "long_function" in types or "deep_nesting" in types:
        priorities.append("1. 优先重构过长/深嵌套函数（影响可读性和可维护性）")
    if "broad_except" in types:
        priorities.append("2. 收窄异常捕获范围（隐藏真实错误会导致调试困难）")
    if "magic_number" in types:
        priorities.append("3. 提取魔法数字为命名常量（提高可读性）")
    if "missing_docstring" in types:
        priorities.append("4. 补充 docstring（提升代码可维护性）")
    if "duplicate_code" in types:
        priorities.append("5. 合并重复代码为公共函数（减少维护成本）")
    if not priorities:
        priorities.append("按行号顺序逐一修复即可。")
    lines.extend(priorities)
    lines.append("")
    return "\n".join(lines)


def _rule_items(smells: list[dict]) -> list[dict]:
    return [
        {
            "line": s["line"],
            "type": s["type"],
            "severity": s["severity"],
            "suggestion": _SMELL_FIX_EXAMPLES.get(s["type"], s.get("suggestion") or SUGGESTIONS.get(s["type"], "")),
        }
        for s in smells
    ]


def smell_summary(smells: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for s in smells:
        counts[s["type"]] = counts.get(s["type"], 0) + 1
    return counts