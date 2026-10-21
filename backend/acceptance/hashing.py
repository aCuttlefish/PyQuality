"""统一的序列化与 hash 计算（M1，方案第 14 章）。

任何规格修订、代码变化或影响结果的计划变化都需要新版本；
不能把旧版本的测试通过记录挂到新代码上。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.acceptance.models import (
    CanonicalSpec,
    ContractSpec,
    EvaluationRequest,
    TestPlan,
)


def canonical_json(obj: Any) -> str:
    """确定性 JSON 序列化：排序键、固定分隔符、ensure_ascii。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def code_hash(code: str, supporting: list[tuple[str, str]]) -> str:
    """源码包摘要：主模块 + 按固定相对路径顺序的辅助文件内容。"""
    payload = {
        "main": code,
        "supporting": [{"path": p, "content": c} for p, c in sorted(supporting)],
    }
    return digest(payload)


def request_hash(request: EvaluationRequest) -> str:
    """绑定 R、P、原生成上下文及请求选项，避免复用错误的提示词分析结果。"""
    payload = {
        "requirement": request.requirement,
        "generation_prompt": request.generation_prompt,
        "generation_context": request.generation_context.model_dump(),
        "options": request.options.model_dump(),
    }
    return digest(payload)


def spec_hash(spec: CanonicalSpec) -> str:
    """覆盖需求、输入域和已确认技术约束（不含身份字段与临时字段）。"""
    payload = {
        "requirements": [r.model_dump(exclude={"id"}, exclude_none=False) for r in spec.requirements],
        "input_domain": [d.model_dump() for d in spec.input_domain],
        "technical_constraints": spec.technical_constraints,
    }
    return digest(payload)


def plan_hash(plan: TestPlan) -> str:
    """覆盖 ContractSpec、oracle 来源与审查记录、固定 expected、案例及计划版本。"""
    payload = {
        "revision": plan.revision,
        "contracts": [
            {
                "contract_id": c.contract_id,
                "requirement_ids": c.requirement_ids,
                "relation_to_requirement": c.relation_to_requirement,
                "oracle_origin": c.oracle_origin,
                "oracle_review": c.oracle_review,
                "assertion_template": c.representation,
            }
            for c in plan.contracts
        ],
        "cases": [
            {
                "case_id": case.case_id,
                "contract_id": case.contract_id,
                "assertion": case.assertion.model_dump(),
                "args": case.args,
                "kwargs": case.kwargs,
                "input_domain_status": case.input_domain_status,
            }
            for case in plan.cases
        ],
    }
    return digest(payload)


def bind_spec(spec: CanonicalSpec) -> CanonicalSpec:
    spec.spec_hash = spec_hash(spec)
    return spec


def bind_plan(plan: TestPlan, spec: CanonicalSpec) -> TestPlan:
    h = plan_hash(plan)
    plan.plan_hash = h
    for c in plan.contracts:
        c.spec_hash = spec.spec_hash
    return plan