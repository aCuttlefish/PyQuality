"""可编辑验收标准与显式用户确认。确认记录持久化，绑定需求和入口，独立于代码。"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from pydantic import Field, StrictBool, model_validator

from backend.config import BASE_DIR
from backend.acceptance import hashing, review, spec_extractor, verdict
from backend.acceptance.checks import validate_plan_structure
from backend.acceptance.models import (
    CanonicalSpec, ContractSpec, Entrypoint, EvaluationRequest, RequirementItem,
    StrictModel, TestPlan,
)

STORE_DIR = BASE_DIR / "data" / "acceptance_standards"


class StandardConfirmation(StrictModel):
    requirement: str = Field(min_length=1, max_length=20000)
    entrypoint: Entrypoint
    spec: CanonicalSpec
    plan: TestPlan
    scope_note: str = Field(min_length=5, max_length=1000)
    confirmed: StrictBool
    case_scope_confirmed: StrictBool = False

    @model_validator(mode="after")
    def _explicit_confirmation(self):
        if self.confirmed is not True:
            raise ValueError("请先检查需求、测试输入与期望结果，再明确确认验收标准")
        return self


def normalize(text: str) -> str:
    return "".join(text.split())


def prepare(request: EvaluationRequest) -> dict:
    # 导入在函数内，避免服务与标准模块的循环依赖。
    from backend.acceptance.service import _locate_entrypoint
    entrypoint, entry_note = _locate_entrypoint(request)
    issues = [entry_note] if entry_note else []
    result = spec_extractor.extract_spec(request.requirement, entrypoint)
    spec = result.spec
    plan = TestPlan()
    if spec is None:
        issues.append(result.error or "模型不可用：可手动填写测试案例后确认")
        spec = CanonicalSpec(
            spec_id="SPEC-DRAFT", requirement_text_digest=request.requirement,
            requirements=[RequirementItem(
                id="R1", statement=request.requirement, origin="EXPLICIT",
                source_quote=request.requirement, acceptance_intent="用户确认的固定案例检查",
            )],
        )
        plan.contracts = [ContractSpec(
            contract_id="K_R1", requirement_ids=["R1"], description="固定输入输出验收",
            relation_to_requirement="EQUIVALENT",
            relation_basis="用户逐项确认固定案例；结论仅覆盖这些案例及其声明范围",
            oracle_origin="MODEL_HYPOTHESIS",
        )]
    else:
        planned = review.build_plan(spec, request.acceptance_materials.trusted_examples)
        if planned.plan is not None:
            plan = planned.plan
            extraction_questions = list(spec.unresolved_questions)
            checked = review.review_spec_and_plan(spec, plan, request.requirement)
            review.apply_review(spec, plan, checked)
            # 审查的改进意见单独显示；不把“可补充覆盖”等建议升级为需求歧义。
            # 提取阶段及需求本身的真实未决问题仍然阻止确认。
            spec.unresolved_questions = extraction_questions
            issues.extend(checked.blocking_issues)
            issues.extend(
                f"契约 {c.contract_id} 尚未获认可，请检查或修订后确认"
                for c in plan.contracts if c.oracle_review != "ACCEPTED_FOR_TESTING"
            )
        else:
            issues.append(planned.error)
        issues.extend(spec.unresolved_questions)
    return {
        "ok": True, "requirement": request.requirement,
        "entrypoint": entrypoint.model_dump() if entrypoint else None,
        "spec": spec.model_dump(), "plan": plan.model_dump(),
        "issues": list(dict.fromkeys(i for i in issues if i)),
        "scope_note": "本轮仅验证已确认的固定测试案例；不保证未测试输入与输入域外行为。",
    }


def confirm(body: StandardConfirmation) -> dict:
    spec = body.spec.model_copy(deep=True)
    plan = body.plan.model_copy(deep=True)
    if len(spec.requirements) > 20 or len(plan.cases) > 40 or len(plan.contracts) > 40:
        raise ValueError("最多支持 20 项需求、40 个契约及 40 个测试案例")
    if len(body.model_dump_json().encode("utf-8")) > 262144:
        raise ValueError("验收标准超过 256 KiB")
    if not any(r.mandatory for r in spec.requirements):
        raise ValueError("至少需要一项必要需求")
    if spec.unresolved_questions or any(
        r.mandatory and (r.origin == "UNCLEAR" or r.unresolved_questions)
        for r in spec.requirements
    ):
        raise ValueError("请先澄清未决问题并修订需求，再确认标准")
    for r in spec.requirements:
        if r.source_quote and normalize(r.source_quote) not in normalize(body.requirement):
            raise ValueError(f"需求 {r.id} 的原文引用不在当前需求中")
    errors = validate_plan_structure(spec, plan)
    if errors:
        raise ValueError("；".join(errors[:5]))
    if any(c.input_domain_status != "IN_SCOPE" for c in plan.cases):
        raise ValueError("确认前必须明确所有案例的合法输入范围")
    key = "STD-" + uuid.uuid4().hex
    spec.spec_id = key
    spec.requirement_text_digest = body.requirement
    spec.interpretation_status = "USER_CONFIRMED"
    spec.limitations = [body.scope_note]
    for contract in plan.contracts:
        # 只有显式确认端点可以产生此身份；模型输出不会进入这个函数。
        contract.oracle_origin = "USER_CONFIRMED_RULE"
        contract.oracle_review = "ACCEPTED_FOR_TESTING"
        contract.interpretation_status = "USER_CONFIRMED"
    if body.case_scope_confirmed:
        # 操作者可以明确选择“以固定案例为标准”。完整返回值/异常可在指定输入上
        # 定义验收结果；ORDERED 等部分性质单独通过仍不足以验收功能。
        full_kinds = {"RETURN_EQUALS", "RETURN_IS_NONE", "RAISES"}
        for r in spec.requirements:
            pass_ids = {c.contract_id for c in plan.contracts if r.id in c.requirement_ids
                        and c.relation_to_requirement in ("SUFFICIENT", "EQUIVALENT")}
            if any(r.id in c.requirement_ids and c.contract_id in pass_ids for c in plan.cases):
                continue
            complete = [c for c in plan.cases if r.id in c.requirement_ids
                        and (c.assertion.kind in full_kinds or (
                            r.kind == "SIDE_EFFECT" and c.assertion.kind == "INPUT_UNCHANGED"))]
            if not complete:
                if r.mandatory:
                    raise ValueError(f"{r.id} 只有部分性质检查，请补充完整期望输出或异常案例")
                continue
            cid = f"K_USER_SCOPE_{len(plan.contracts) + 1}"
            while any(c.contract_id == cid for c in plan.contracts):
                cid += "_1"
            # 不改写原契约的关系标签；保留原始案例，补一个明确的案例范围契约。
            plan.contracts.append(ContractSpec(
                contract_id=cid, requirement_ids=[r.id],
                description=f"用户认可的固定案例范围：{r.statement}",
                relation_to_requirement="EQUIVALENT",
                relation_basis="用户显式选择以这些固定输入的完整预期输出为本轮标准；未测试输入不作结论",
                oracle_origin="USER_CONFIRMED_RULE", oracle_review="ACCEPTED_FOR_TESTING",
                interpretation_status="USER_CONFIRMED", coverage_note=body.scope_note,
            ))
            for case in complete:
                # 一个案例同时属于多条需求时保留原案例；新增每条需求的范围检查。
                if len(case.requirement_ids) > 1:
                    copy = case.model_copy(deep=True)
                    copy.case_id = f"{case.case_id}_SCOPE_{len(plan.cases) + 1}"
                    copy.requirement_ids = [r.id]
                    copy.contract_id = cid
                    plan.cases.append(copy)
                else:
                    case.contract_id = cid
    if len(plan.cases) > 40 or len(plan.contracts) > 40:
        raise ValueError("确认后的范围检查超过 40 个案例或契约，请合并重复需求归属")
    if not verdict.spec_is_ready(spec, "confirmed_only", plan):
        raise ValueError("每项必要需求都需要充分/等价契约及案例；仅 ORDERED 等部分性质不能支持整体通过")
    for r in spec.requirements:
        pass_contracts = {c.contract_id for c in plan.contracts
                          if r.id in c.requirement_ids
                          and c.relation_to_requirement in ("SUFFICIENT", "EQUIVALENT")}
        if r.mandatory and not any(
            r.id in c.requirement_ids and c.contract_id in pass_contracts for c in plan.cases
        ):
            raise ValueError(f"必要需求 {r.id} 缺少充分/等价契约对应的测试案例")
    hashing.bind_spec(spec)
    hashing.bind_plan(plan, spec)
    record = {
        "confirmed_spec_id": key, "confirmed_spec_hash": spec.spec_hash,
        "confirmed_plan_hash": plan.plan_hash, "confirmed_at": time.time(),
        "requirement": body.requirement, "entrypoint": body.entrypoint.model_dump(),
        "scope_note": body.scope_note, "spec": spec.model_dump(), "plan": plan.model_dump(),
        "case_scope_confirmed": body.case_scope_confirmed,
    }
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    # UUID + 排他创建使每次修订生成新记录，不能静默覆盖旧标准。
    with (STORE_DIR / f"{key}.json").open("x", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, allow_nan=False)
    return {"ok": True, **record}


def load(key: str, requirement: str, entrypoint: Entrypoint | None, expected_hash: str = "") -> tuple[CanonicalSpec, TestPlan]:
    if not re.fullmatch(r"STD-[0-9a-f]{32}", key):
        raise ValueError("未知确认标准 ID")
    path = STORE_DIR / f"{key}.json"
    if not path.exists():
        raise ValueError("确认记录不存在，请重新准备并确认标准")
    record = json.loads(path.read_text(encoding="utf-8"))
    if normalize(record["requirement"]) != normalize(requirement):
        raise ValueError("需求已修改，旧确认标准不能复用，请重新确认")
    if entrypoint is None or record["entrypoint"] != entrypoint.model_dump():
        raise ValueError("函数入口已修改，旧确认标准不能复用，请重新确认")
    spec = CanonicalSpec.model_validate(record["spec"])
    plan = TestPlan.model_validate(record["plan"])
    if (hashing.spec_hash(spec) != record["confirmed_spec_hash"]
        or hashing.plan_hash(plan) != record["confirmed_plan_hash"]
        or (expected_hash and expected_hash != spec.spec_hash)):
        raise ValueError("确认标准摘要不匹配，拒绝复用")
    return spec, plan
