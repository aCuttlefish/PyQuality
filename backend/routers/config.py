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
    new_thresholds = dict(config.SMELL_THRESHOLDS)
    if body.smell_thresholds is not None:
        for k, v in body.smell_thresholds.items():
            if k not in config.SMELL_THRESHOLDS:
                raise HTTPException(400, f"未知坏味阈值: {k}")
            if not isinstance(v, (int, float)) or v <= 0:
                raise HTTPException(400, f"阈值 {k} 必须为正数")
            new_thresholds[k] = v

    new_weights = dict(config.READABILITY_WEIGHTS)
    if body.readability_weights is not None:
        for k, v in body.readability_weights.items():
            if k not in config.READABILITY_WEIGHTS:
                raise HTTPException(400, f"未知可读性权重: {k}")
            if not isinstance(v, (int, float)) or v < 0:
                raise HTTPException(400, f"权重 {k} 必须为非负数")
            new_weights[k] = v
    if sum(new_weights.values()) == 0:
        raise HTTPException(400, "可读性权重总和必须大于 0")

    new_th = config.TYPE_HINTS_MIN_COVERAGE
    if body.type_hints_min_coverage is not None:
        new_th = body.type_hints_min_coverage
    new_ds = config.DOCSTRING_MIN_COVERAGE
    if body.docstring_min_coverage is not None:
        new_ds = body.docstring_min_coverage
    new_dup = config.DUPLICATION_MIN_LINES
    if body.duplication_min_lines is not None:
        if body.duplication_min_lines < 1:
            raise HTTPException(400, "duplication_min_lines 必须 >= 1")
        new_dup = body.duplication_min_lines

    config.SMELL_THRESHOLDS.clear()
    config.SMELL_THRESHOLDS.update(new_thresholds)
    config.READABILITY_WEIGHTS.clear()
    config.READABILITY_WEIGHTS.update(new_weights)
    config.TYPE_HINTS_MIN_COVERAGE = new_th
    config.DOCSTRING_MIN_COVERAGE = new_ds
    config.DUPLICATION_MIN_LINES = new_dup

    try:
        config.save_user_config()
    except Exception as e:
        logger.exception("保存配置失败")
        raise HTTPException(500, f"保存配置失败: {e}")
    logger.info("分析阈值已更新")
    return {"ok": True, "config": get_config()}