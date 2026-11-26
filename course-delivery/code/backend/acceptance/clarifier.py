"""需求多轮追问澄清模块。

在生成测试用例前，先根据用户的初始需求描述或代码生成提示词，
通过多轮问答把关键边界、排序/格式、输入域假设和函数名问清楚，
直到可以无歧义地生成固定输入输出测试用例为止。
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field

from backend.acceptance import llm_provider
from backend.acceptance.models import StrictModel
from backend.logger import get_logger

logger = get_logger("acceptance_clarifier")

CLARIFY_TASK = """你是 Python 单函数验收系统的需求澄清助手。
用户的输入可能是粗略的功能需求，也可能是他之前发给 AI 写代码的提示词。
你的目标是通过简短、直白、好回答的中文追问，帮用户把需求彻底说清楚，以便下一步直接生成准确、无歧义的固定测试用例。

请结合 initial_input、entrypoint 和历史问答 qa_history，检查以下 5 个方面是否已经清楚：
1. 函数名和参数含义（如用户尚未说明函数名，须确认一个合法的 Python 函数名）。
2. 正常情况下的输出类型、结构和排序规则（例如列表顺序、去重与否、小数精度）。
3. 关键边界情况（例如空输入、0 值、无解时返回 [] 还是 None）。
4. 非法输入处理方式（是约定调用方保证输入合法、不要求校验，还是要求抛出特定异常）。
5. 是否有不能修改原输入等副作用要求（如不涉及则无需多问）。

严格规则：
- 凡是 initial_input 或 qa_history 里已经说清楚的点，绝对不要重复再问！
- 如果关键细节还有模糊之处，设置 "ready": false，每次最多提出 2 到 4 个最关键、大白话的追问问题；每个问题尽量给出 2 到 3 个常见快捷选项（options），方便用户点选或自己填写。
- 如果以上关键细节都已经足够清楚，可以直接写出确切的固定测试用例（或者 qa_history 已经回答过关键边界且没有明显歧义），设置 "ready": true，"questions": []。
- 一致性自检（重要）：在输出 "refined_requirement" 前，必须检查所有规则之间是否存在自相矛盾（例如“不允许数字重复”与“返回全 0 列表 [0, 0]”冲突，或“m 为负返回 []”与“m 为负抛 TypeError”冲突）。若发现用户回答之间存在冲突，不得设置 ready=true，而应直接追问请用户二选一。
- 合法输入域一致性：绝对不要在合法边界问题里把“m 为负”混进示例括号；如果用户选择了“调用方保证输入合法，不要求校验”，则 refined_requirement 中绝对不要再写“m 为负时返回 []”等非法输入分支，只写合法输入域内的规则！
- 无论 ready 为 true 还是 false，都要输出 "refined_requirement"：把初始输入和所有已回答的澄清整合成一段完整、清晰、无歧义的中文需求说明（如果用户确认不需要校验非法输入，必须明确写上“调用方保证输入合法，不要求校验非法输入”）。
- 如果已知函数名，填入 "suggested_entrypoint"（纯 Python 函数名标识符，如 possibilities）。

严格按以下 JSON 格式输出：
{
  "ready": false,
  "summary": "1-2 句大白话，概括目前已搞清楚的部分和还缺什么",
  "suggested_entrypoint": "possibilities",
  "questions": [
    {
      "id": "Q1",
      "question": "简短直白的问题",
      "options": ["常见选项A", "常见选项B"]
    }
  ],
  "refined_requirement": "整合后的完整清晰需求描述"
}"""


class ClarifyTurn(StrictModel):
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=4000)


class ClarifyRequest(StrictModel):
    initial_input: str = Field(min_length=1, max_length=20000)
    input_type: Literal["requirement", "prompt"] = "requirement"
    entrypoint: Optional[str] = Field(default=None, max_length=120)
    qa_history: list[ClarifyTurn] = Field(default_factory=list)


def _valid_identifier(name: str) -> str:
    s = (name or "").strip()
    if s and s.isidentifier() and not s.startswith("__"):
        return s
    return ""


def _fallback_refined(req: ClarifyRequest) -> str:
    if not req.qa_history:
        return req.initial_input.strip()
    lines = [req.initial_input.strip(), "", "补充澄清："]
    for t in req.qa_history:
        lines.append(f"- {t.question}：{t.answer}")
    return "\n".join(lines)


def clarify(req: ClarifyRequest) -> dict:
    """分析需求是否已明确；未明确则返回追问列表，已明确则返回整理好的清晰需求。"""
    payload = {
        "input_type": req.input_type,
        "initial_input": req.initial_input,
        "entrypoint": req.entrypoint or "",
        "qa_history": [t.model_dump() for t in req.qa_history],
        "round": len(req.qa_history) + 1,
    }
    try:
        data = llm_provider.generate_structured(CLARIFY_TASK, payload, temperature=0.2)
    except llm_provider.ProviderUnavailable as e:
        logger.info("clarifier fallback (LLM unavailable): %s", e)
        return {
            "ok": True,
            "mode": "UNAVAILABLE",
            "ready": True,
            "summary": "当前未配置或暂无法连接大模型，已保留你填写的需求内容，可直接进入手动编写测试用例。",
            "suggested_entrypoint": _valid_identifier(req.entrypoint or ""),
            "questions": [],
            "refined_requirement": _fallback_refined(req),
            "error": str(e),
        }

    data = llm_provider.strip_forbidden_fields(data)
    raw_qs = data.get("questions") or []
    questions = []
    if isinstance(raw_qs, list):
        for idx, q in enumerate(raw_qs[:4], 1):
            if not isinstance(q, dict):
                continue
            qtext = str(q.get("question") or "").strip()
            if not qtext:
                continue
            opts = [str(o).strip() for o in (q.get("options") or []) if str(o).strip()][:4]
            questions.append({
                "id": str(q.get("id") or f"Q{idx}"),
                "question": qtext,
                "options": opts,
            })

    ready = bool(data.get("ready")) or len(questions) == 0
    if ready:
        questions = []

    suggested_ep = _valid_identifier(str(data.get("suggested_entrypoint") or "")) or _valid_identifier(req.entrypoint or "")
    refined = str(data.get("refined_requirement") or "").strip() or _fallback_refined(req)
    summary = str(data.get("summary") or "").strip()
    if not summary:
        summary = "需求的关键行为与边界已经明确，可以生成测试用例了。" if ready else "还有几个细节需要和你确认一下，方便生成准确的测试用例。"

    return {
        "ok": True,
        "mode": "LLM",
        "ready": ready,
        "summary": summary,
        "suggested_entrypoint": suggested_ep,
        "questions": questions,
        "refined_requirement": refined,
    }
