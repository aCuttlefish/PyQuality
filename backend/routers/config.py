from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import config
from backend.logger import get_logger

logger = get_logger("config")
router = APIRouter(prefix="/api/config", tags=["config"])


class ConfigUpdate(BaseModel):
    smell_thresholds: dict | None = None
    readability_weights: dict | None = None
    type_hints_min_coverage: float | None = None
    docstring_min_coverage: float | None = None
    duplication_min_lines: int | None = None


@router.get("")
def get_config():
    return {
        "smell_thresholds": dict(config.SMELL_THRESHOLDS),
        "readability_weights": dict(config.READABILITY_WEIGHTS),
        "type_hints_min_coverage": config.TYPE_HINTS_MIN_COVERAGE,
        "docstring_min_coverage": config.DOCSTRING_MIN_COVERAGE,
        "duplication_min_lines": config.DUPLICATION_MIN_LINES,
    }


@router.put("")
def update_config(body: ConfigUpdate):
    if body.smell_thresholds is not None:
        for k, v in body.smell_thresholds.items():
            if k not in config.SMELL_THRESHOLDS:
                raise HTTPException(400, f"未知坏味阈值: {k}")
            if not isinstance(v, (int, float)) or v <= 0:
                raise HTTPException(400, f"阈值 {k} 必须为正数")
            config.SMELL_THRESHOLDS[k] = v
    if body.readability_weights is not None:
        for k, v in body.readability_weights.items():
            if k not in config.READABILITY_WEIGHTS:
                raise HTTPException(400, f"未知可读性权重: {k}")
            if not isinstance(v, (int, float)) or v < 0:
                raise HTTPException(400, f"权重 {k} 必须为非负数")
            config.READABILITY_WEIGHTS[k] = v
    if body.type_hints_min_coverage is not None:
        config.TYPE_HINTS_MIN_COVERAGE = body.type_hints_min_coverage
    if body.docstring_min_coverage is not None:
        config.DOCSTRING_MIN_COVERAGE = body.docstring_min_coverage
    if body.duplication_min_lines is not None:
        if body.duplication_min_lines < 1:
            raise HTTPException(400, "duplication_min_lines 必须 >= 1")
        config.DUPLICATION_MIN_LINES = body.duplication_min_lines
    try:
        config.save_user_config()
    except Exception as e:
        logger.exception("保存配置失败")
        raise HTTPException(500, f"保存配置失败: {e}")
    logger.info("分析阈值已更新")
    return {"ok": True, "config": get_config()}