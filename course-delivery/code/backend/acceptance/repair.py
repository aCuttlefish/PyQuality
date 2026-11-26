"""基于失败反例的 AI 修复候选生成模块。

模型根据需求、当前代码、真实失败反例与已通过用例生成候选修复源码；
候选代码仅作为未验证草稿返回，必须交由固定标准在 Docker 容器中重新执行验收。
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import Field

from backend.acceptance import llm_provider, runner
from backend.acceptance.models import Entrypoint, StrictModel
from backend.logger import get_logger

logger = get_logger("acceptance_repair")

REPAIR_TASK = """你是 Python 代码修复助手。
请根据 requirement、current_code、failed_cases（真实执行失败的输入、期望与实际结果）以及 passed_cases（已通过的用例，绝对不能改坏），对代码做最小必要修改，使所有失败案例和已通过案例都能通过。

严格要求：
1. 保持待测函数 entrypoint 的函数名与参数签名完全不变。
2. 保留源码中原本的辅助函数和 if __name__ == "__main__" 块（如有），不要删掉无关结构。
3. 修复必须同时满足 failed_cases 和 passed_cases，不能只针对某个具体数字写死 if 特判，要从算法/边界逻辑上真正修对。
4. 只返回纯 Python 源码（不要包 ```python 代码块标记），并用 1-2 句大白话说明改了哪里。

严格按以下 JSON 格式输出：
{
  "fixed_code": "完整的修复后 Python 源码",
  "change_summary": "1-2 句大白话说明具体改了哪几行、为什么这么改"
}"""


class RepairRequest(StrictModel):
    requirement: str = Field(min_length=1, max_length=20000)
    code: str = Field(min_length=1, max_length=262144)
    entrypoint: Optional[Entrypoint] = None
    failed_cases: list[dict[str, Any]] = Field(default_factory=list)
    passed_cases: list[dict[str, Any]] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


def _strip_code_fence(src: str) -> str:
    s = (src or "").strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return s


def generate_repair(req: RepairRequest) -> dict:
    """调用大模型生成修复候选源码，并做基础语法编译校验（不代替容器动态验收）。"""
    payload = {
        "requirement": req.requirement,
        "entrypoint": req.entrypoint.model_dump() if req.entrypoint else None,
        "current_code": req.code[:16000],
        "failed_cases": req.failed_cases[:20],
        "passed_cases": req.passed_cases[:20],
        "suggestions": req.suggestions[:10],
    }
    try:
        data = llm_provider.generate_structured(REPAIR_TASK, payload, temperature=0.1)
    except llm_provider.ProviderUnavailable as e:
        raise ValueError(f"模型当前不可用，无法自动生成修复代码：{e}")

    data = llm_provider.strip_forbidden_fields(data)
    fixed_code = _strip_code_fence(str(data.get("fixed_code") or ""))
    if not fixed_code:
        raise ValueError("模型未返回有效的修复代码")

    ok, compile_msg = runner.compile_check(fixed_code)
    if not ok:
        raise ValueError(f"模型生成的修复候选存在语法错误（已拦截）：{compile_msg}")

    summary = str(data.get("change_summary") or "已根据失败反例生成修复候选代码。").strip()
    return {
        "ok": True,
        "fixed_code": fixed_code,
        "change_summary": summary,
        "validation_status": "UNVALIDATED",
    }
