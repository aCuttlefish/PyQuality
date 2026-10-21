"""人工确认夹具（M3，方案 15.1 / 15.2）。

确定性夹具直接注入人工确认的规格和固定 TestPlan，
用于验证 runner 与判定内核，不要求真实 LLM 生成。
"""
from __future__ import annotations

from backend.acceptance.models import (
    AllItemsMatchAssertion,
    CanonicalSpec,
    CheckCase,
    ContractSpec,
    InputDomainClause,
    InputUnchangedAssertion,
    OrderedAssertion,
    RequirementItem,
    ReturnEqualsAssertion,
    ReturnIsNoneAssertion,
    TestPlan,
)

MAX_EVEN_REQUIREMENT = (
    "实现 max_even(nums)。输入整数列表，返回其中最大的偶数；"
    "不存在偶数时返回 None；不得修改输入列表。"
)

MAX_EVEN_WRONG_CODE = (
    "def max_even(nums):\n"
    "    return max((x for x in nums if x % 2 == 0), default=0)\n"
)

MAX_EVEN_CORRECT_CODE = (
    "def max_even(nums):\n"
    "    return max((x for x in nums if x % 2 == 0), default=None)\n"
)

MAX_EVEN_INPLACE_CODE = (
    "def max_even(nums):\n"
    "    nums.sort(reverse=True)\n"
    "    for x in nums:\n"
    "        if x % 2 == 0:\n"
    "            return x\n"
    "    return None\n"
)


def max_even_spec() -> CanonicalSpec:
    return CanonicalSpec(
        spec_id="SPEC-MAX-EVEN",
        interpretation_status="USER_CONFIRMED",
        requirement_text_digest="max_even 人工确认夹具（15.1）",
        requirements=[
            RequirementItem(
                id="R1", statement="返回输入列表中最大的偶数",
                kind="FUNCTIONAL", mandatory=True, origin="EXPLICIT",
                source_quote="返回其中最大的偶数",
                acceptance_intent="正常场景返回值正确",
            ),
            RequirementItem(
                id="R2", statement="不存在偶数时返回 None",
                kind="FUNCTIONAL", mandatory=True, origin="EXPLICIT",
                source_quote="不存在偶数时返回 None",
                acceptance_intent="无偶数输入的返回值要求",
            ),
            RequirementItem(
                id="R3", statement="不得修改输入列表",
                kind="SIDE_EFFECT", mandatory=True, origin="EXPLICIT",
                source_quote="不得修改输入列表",
                acceptance_intent="调用前后输入内容不变",
            ),
        ],
        input_domain=[
            InputDomainClause(description="整数列表（可含负数、零、重复值；可为空列表）"),
        ],
        technical_constraints=["入口: solution.max_even(nums)"],
        limitations=["不检测瞬时写入（先修改再恢复）行为"],
    )


def max_even_plan() -> TestPlan:
    contracts = [
        ContractSpec(
            contract_id="K_R1", requirement_ids=["R1"],
            description="最大偶数返回值", input_domain_ref="整数列表",
            representation="RETURN_EQUALS",
            relation_to_requirement="EQUIVALENT",
            relation_basis="R1 的完整输入输出关系在声明域内等价",
            oracle_origin="USER_CONFIRMED_RULE", oracle_review="ACCEPTED_FOR_TESTING",
            interpretation_status="USER_CONFIRMED",
        ),
        ContractSpec(
            contract_id="K_R2", requirement_ids=["R2"],
            description="无偶数返回 None", input_domain_ref="整数列表",
            representation="RETURN_IS_NONE",
            relation_to_requirement="EQUIVALENT",
            relation_basis="R2 唯一确定无偶数分支的返回值",
            oracle_origin="USER_CONFIRMED_RULE", oracle_review="ACCEPTED_FOR_TESTING",
            interpretation_status="USER_CONFIRMED",
        ),
        ContractSpec(
            contract_id="K_R3", requirement_ids=["R3"],
            description="输入不变", input_domain_ref="整数列表",
            representation="INPUT_UNCHANGED",
            relation_to_requirement="NECESSARY",
            relation_basis="R3 直接要求的副作用约束",
            oracle_origin="USER_CONFIRMED_RULE", oracle_review="ACCEPTED_FOR_TESTING",
            interpretation_status="USER_CONFIRMED",
        ),
    ]
    cases = [
        CheckCase(
            case_id="T1", contract_id="K_R1", requirement_ids=["R1"], category="NORMAL",
            args=[[1, 8, 3, 4]], assertion=ReturnEqualsAssertion(kind="RETURN_EQUALS", expected=8),
            expected_basis="R1：8 是 [1,8,3,4] 中最大偶数",
        ),
        CheckCase(
            case_id="T2", contract_id="K_R1", requirement_ids=["R1"], category="NEGATIVE",
            args=[[-6, -2, -3]], assertion=ReturnEqualsAssertion(kind="RETURN_EQUALS", expected=-2),
            expected_basis="R1：-2 是 [-6,-2,-3] 中最大偶数",
        ),
        CheckCase(
            case_id="T3", contract_id="K_R1", requirement_ids=["R1"], category="ZERO",
            args=[[0, 1]], assertion=ReturnEqualsAssertion(kind="RETURN_EQUALS", expected=0),
            expected_basis="R1：0 是偶数且为 [0,1] 中最大偶数",
        ),
        CheckCase(
            case_id="T4", contract_id="K_R1", requirement_ids=["R1"], category="DUPLICATE",
            args=[[4, 2, 6]], assertion=ReturnEqualsAssertion(kind="RETURN_EQUALS", expected=6),
            expected_basis="R1：6 是 [4,2,6] 中最大偶数",
        ),
        CheckCase(
            case_id="T5", contract_id="K_R2", requirement_ids=["R2"], category="NO_MATCH",
            args=[[1, 3]], assertion=ReturnIsNoneAssertion(kind="RETURN_IS_NONE"),
            expected_basis="R2：[1,3] 无偶数返回 None",
        ),
        CheckCase(
            case_id="T6", contract_id="K_R2", requirement_ids=["R2"], category="EMPTY",
            args=[[]], assertion=ReturnIsNoneAssertion(kind="RETURN_IS_NONE"),
            expected_basis="R2：空列表无偶数返回 None",
        ),
        CheckCase(
            case_id="T7", contract_id="K_R3", requirement_ids=["R3"], category="SIDE_EFFECT",
            args=[[4, 1, 8, 3]],
            assertion=InputUnchangedAssertion(
                kind="INPUT_UNCHANGED",
                targets=[{"kind": "ARG", "index": 0}],
            ),
            expected_basis="R3：调用后列表内容与调用前相同",
        ),
    ]
    return TestPlan(
        plan_id="PLAN-MAX-EVEN", revision=1, contracts=contracts, cases=cases,
        coverage_notes=["R1/R2 由固定返回值检查覆盖；R3 由输入快照对比覆盖"],
    )


PAYABLE_REQUIREMENT = (
    "实现 payable(amount)。输入是非负整数，单位为分。"
    "金额达到 10000 分（含）时固定优惠 2000 分一次，否则无优惠，返回应付金额。"
)

PAYABLE_GT_CODE = (
    "def payable(amount):\n"
    "    if amount > 10000:\n"
    "        return amount - 2000\n"
    "    return amount\n"
)

PAYABLE_GE_CODE = (
    "def payable(amount):\n"
    "    if amount >= 10000:\n"
    "        return amount - 2000\n"
    "    return amount\n"
)


def payable_spec() -> CanonicalSpec:
    return CanonicalSpec(
        spec_id="SPEC-PAYABLE",
        interpretation_status="USER_CONFIRMED",
        requirement_text_digest="payable 人工确认夹具（15.2）",
        requirements=[
            RequirementItem(
                id="R1", statement="金额达到 10000 分（含）时固定优惠 2000 分一次",
                kind="FUNCTIONAL", mandatory=True, origin="EXPLICIT",
                source_quote="金额达到 10000 分（含）时固定优惠 2000 分一次",
                acceptance_intent="含边界的优惠规则",
            ),
            RequirementItem(
                id="R2", statement="未达门槛时无优惠，返回原金额",
                kind="FUNCTIONAL", mandatory=True, origin="EXPLICIT",
                source_quote="否则无优惠，返回应付金额",
                acceptance_intent="无优惠分支",
            ),
        ],
        input_domain=[
            InputDomainClause(description="非负整数（单位：分）"),
        ],
        technical_constraints=["入口: solution.payable(amount)"],
    )


def payable_plan() -> TestPlan:
    contracts = [
        ContractSpec(
            contract_id="K_P1", requirement_ids=["R1"],
            description="含门槛的优惠规则", input_domain_ref="非负整数",
            representation="RETURN_EQUALS",
            relation_to_requirement="EQUIVALENT",
            relation_basis="用户提供的固定输入输出表",
            oracle_origin="USER_EXAMPLE", oracle_review="ACCEPTED_FOR_TESTING",
            interpretation_status="USER_CONFIRMED",
        ),
        ContractSpec(
            contract_id="K_P2", requirement_ids=["R2"],
            description="无优惠分支", input_domain_ref="非负整数",
            representation="RETURN_EQUALS",
            relation_to_requirement="EQUIVALENT",
            relation_basis="用户提供的固定输入输出表",
            oracle_origin="USER_EXAMPLE", oracle_review="ACCEPTED_FOR_TESTING",
            interpretation_status="USER_CONFIRMED",
        ),
    ]
    cases = [
        CheckCase(
            case_id="P1", contract_id="K_P1", requirement_ids=["R1"], category="BOUNDARY",
            args=[10000], assertion=ReturnEqualsAssertion(kind="RETURN_EQUALS", expected=8000),
            expected_basis="R1：10000（含）触发优惠 2000",
        ),
        CheckCase(
            case_id="P2", contract_id="K_P1", requirement_ids=["R1"], category="BOUNDARY",
            args=[10001], assertion=ReturnEqualsAssertion(kind="RETURN_EQUALS", expected=8001),
            expected_basis="R1：10001 超过门槛",
        ),
        CheckCase(
            case_id="P3", contract_id="K_P1", requirement_ids=["R1"], category="NORMAL",
            args=[20000], assertion=ReturnEqualsAssertion(kind="RETURN_EQUALS", expected=18000),
            expected_basis="R1：优惠只扣一次",
        ),
        CheckCase(
            case_id="P4", contract_id="K_P2", requirement_ids=["R2"], category="BOUNDARY",
            args=[9999], assertion=ReturnEqualsAssertion(kind="RETURN_EQUALS", expected=9999),
            expected_basis="R2：9999 未达门槛无优惠",
        ),
        CheckCase(
            case_id="P5", contract_id="K_P2", requirement_ids=["R2"], category="ZERO",
            args=[0], assertion=ReturnEqualsAssertion(kind="RETURN_EQUALS", expected=0),
            expected_basis="R2：0 无优惠",
        ),
    ]
    return TestPlan(
        plan_id="PLAN-PAYABLE", revision=1, contracts=contracts, cases=cases,
        coverage_notes=["两个分支的边界值由固定输入输出表覆盖"],
    )