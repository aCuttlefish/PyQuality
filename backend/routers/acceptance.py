"""验收 API（M4，方案 13.1）。

POST /api/acceptance/evaluate — 同步评估（受 60s 超时保护）。
代码不合格是评估结果（verdict=FAIL），不是 HTTP 500；
请求格式错误与系统运行失败分别处理。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from backend.acceptance.models import EvaluationReport, EvaluationRequest
from backend.acceptance.service import evaluate
from backend.logger import get_logger

logger = get_logger("acceptance_api")
router = APIRouter(prefix="/api/acceptance", tags=["acceptance"])


class EvaluateBody(BaseModel):
    requirement: str
    generation_prompt: str = ""
    code: str
    supporting_files: list[dict] | None = None
    entrypoint: dict | None = None
    generation_context: dict | None = None
    acceptance_materials: dict | None = None
    options: dict | None = None


@router.post("/evaluate")
def evaluate_endpoint(body: EvaluateBody):
    payload = body.model_dump(exclude_none=True)
    try:
        request = EvaluationRequest(**payload)
    except ValidationError as e:
        raise HTTPException(422, f"请求格式错误: {e.errors()[:3]}")
    try:
        report: EvaluationReport = evaluate(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("acceptance evaluate failed")
        raise HTTPException(500, f"评估系统运行失败: {e}")
    return {"ok": True, "report": report.model_dump()}


@router.get("/fixtures")
def list_fixtures():
    """人工确认夹具清单（confirmed_only 策略的最小输入路径）。"""
    return {
        "ok": True,
        "fixtures": [
            {
                "confirmed_spec_id": "SPEC-MAX-EVEN",
                "description": "max_even：最大偶数 / 无偶数返回 None / 不修改输入",
            },
            {
                "confirmed_spec_id": "SPEC-PAYABLE",
                "description": "payable：满 10000 分（含）优惠 2000 分一次",
            },
        ],
    }