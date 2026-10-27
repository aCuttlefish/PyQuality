"""固定检查模板的断言评估（M3，方案 6.3）。

调用后由受控父流程比较结构化观察值与固定 expected；
子进程输出只是数据，不参与判定控制。
"""
from __future__ import annotations

from typing import Any

from backend.acceptance.models import (
    ArgTarget,
    Assertion,
    Evidence,
    EvidenceStatus,
    CheckCase,
)


class CheckResult:
    def __init__(self, status: EvidenceStatus, detail: str = ""):
        self.status = status
        self.detail = detail

    @property
    def passed(self) -> bool:
        return self.status == "PASSED"


def _json_equal(a: Any, b: Any) -> bool:
    """按约定的 JSON 值比较，不做类型强制转换（bool 与 1 不相等）。"""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if type(a) is not type(b):
        return False
    if isinstance(a, list):
        return len(a) == len(b) and all(_json_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return set(a.keys()) == set(b.keys()) and all(
            _json_equal(a[k], b[k]) for k in a
        )
    return a == b


def _snapshot_value(value: Any) -> Any:
    """调用前快照：JSON 深拷贝，避免原地修改使比较依据同时改变。"""
    import copy
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return copy.deepcopy(value)


def _predicate_ok(predicate: dict[str, Any], value: Any) -> tuple[bool, str]:
    op = predicate.get("op")
    vt = predicate.get("value_type", "int")
    if vt == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return False, f"元素 {value!r} 不是 int"
    elif vt == "str":
        if not isinstance(value, str):
            return False, f"元素 {value!r} 不是 str"
    elif vt == "bool":
        if not isinstance(value, bool):
            return False, f"元素 {value!r} 不是 bool"
    elif vt == "float":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False, f"元素 {value!r} 不是数值"
    checks = {
        "IS_EVEN": lambda v: isinstance(v, int) and not isinstance(v, bool) and v % 2 == 0,
        "IS_ODD": lambda v: isinstance(v, int) and not isinstance(v, bool) and v % 2 != 0,
        "IS_NONNEGATIVE": lambda v: v >= 0,
        "IS_POSITIVE": lambda v: v > 0,
        "IS_NONE": lambda v: v is None,
    }
    fn = checks.get(op)
    if fn is None:
        return False, f"不支持的 predicate: {op!r}"
    if not fn(value):
        return False, f"元素 {value!r} 不满足 {op}"
    return True, ""


def _return_value_or_error(observation: dict[str, Any]) -> tuple[str, Any]:
    """取返回值；区分合法 None、序列化失败与字段缺失（P0-6）。

    返回 ("ok", value) / ("serialize_error", msg) / ("missing", "")。
    字段缺失是协议损坏，不能当作合法 None 参与判定。
    """
    if observation.get("return_serialization_error"):
        return "serialize_error", str(observation["return_serialization_error"])
    if "return_value" not in observation:
        return "missing", ""
    return "ok", observation["return_value"]


def _exception_or_none(observation: dict[str, Any]) -> str:
    return observation.get("exception_type") or ""


def evaluate_assertion(
    assertion: Assertion,
    observation: dict[str, Any],
) -> CheckResult:
    """比较单次调用的观察值与固定断言。observation 由受控 harness 生成。"""
    kind = assertion.kind

    if kind == "RETURN_EQUALS":
        if _exception_or_none(observation):
            return CheckResult(
                "TARGET_EXCEPTION",
                f"目标抛出 {observation['exception_type']}: {observation.get('exception_message', '')[:120]}",
            )
        state, value = _return_value_or_error(observation)
        if state == "serialize_error":
            return CheckResult("HARNESS_ERROR", f"返回值无法按受限协议序列化: {value}")
        if state == "missing":
            return CheckResult("HARNESS_ERROR", "观察数据缺少 return_value 字段（协议损坏）")
        if not _json_equal(value, assertion.expected):
            return CheckResult(
                "ASSERTION_FAILED",
                f"返回值 {value!r} 不等于期望 {assertion.expected!r}",
            )
        return CheckResult("PASSED")

    if kind == "RETURN_IS_NONE":
        if _exception_or_none(observation):
            return CheckResult(
                "TARGET_EXCEPTION",
                f"目标抛出 {observation['exception_type']}: {observation.get('exception_message', '')[:120]}",
            )
        state, value = _return_value_or_error(observation)
        if state == "serialize_error":
            return CheckResult("HARNESS_ERROR", f"返回值无法按受限协议序列化: {value}")
        if state == "missing":
            return CheckResult("HARNESS_ERROR", "观察数据缺少 return_value 字段（协议损坏）")
        # 使用 is None 语义（JSON null），不通过真假值判断
        if value is not None:
            return CheckResult(
                "ASSERTION_FAILED",
                f"期望返回 None，实际 {value!r}",
            )
        return CheckResult("PASSED")

    if kind == "RAISES":
        if not observation.get("exception_type"):
            return CheckResult(
                "ASSERTION_FAILED",
                f"期望抛出 {assertion.exception_type}，实际正常返回 {observation.get('return_value')!r}",
            )
        if observation["exception_type"] != assertion.exception_type:
            return CheckResult(
                "ASSERTION_FAILED",
                f"期望 {assertion.exception_type}，实际 {observation['exception_type']}",
            )
        if assertion.message_contains and assertion.message_contains not in (
            observation.get("exception_message") or ""
        ):
            return CheckResult(
                "ASSERTION_FAILED",
                f"异常消息不含 {assertion.message_contains!r}",
            )
        return CheckResult("PASSED")

    if kind == "INPUT_UNCHANGED":
        if observation.get("exception_type"):
            # 目标异常时仍需检查是否已修改输入（先修改再抛出）
            pass
        changes = []
        for target in assertion.targets:
            before, after = _get_target_snapshots(target, observation)
            if before is None and after is None:
                changes.append(f"目标 {target.model_dump()} 无快照")
                continue
            if not _json_equal(before, after):
                changes.append(
                    f"参数 {target.model_dump()} 调用前 {before!r} 调用后 {after!r}"
                )
        if changes:
            return CheckResult("ASSERTION_FAILED", "; ".join(changes))
        return CheckResult("PASSED")

    if kind == "ALL_ITEMS_MATCH":
        if _exception_or_none(observation):
            return CheckResult(
                "TARGET_EXCEPTION",
                f"目标抛出 {observation['exception_type']}: {observation.get('exception_message', '')[:120]}",
            )
        state, ret = _return_value_or_error(observation)
        if state == "serialize_error":
            return CheckResult("HARNESS_ERROR", f"返回值无法按受限协议序列化: {ret}")
        if state == "missing":
            return CheckResult("HARNESS_ERROR", "观察数据缺少 return_value 字段（协议损坏）")
        if not isinstance(ret, list):
            return CheckResult("ASSERTION_FAILED", f"返回值不是列表: {ret!r}")
        for i, item in enumerate(ret):
            ok, why = _predicate_ok(assertion.predicate.model_dump(), item)
            if not ok:
                return CheckResult("ASSERTION_FAILED", f"索引 {i}: {why}")
        return CheckResult("PASSED")

    if kind == "ORDERED":
        if _exception_or_none(observation):
            return CheckResult(
                "TARGET_EXCEPTION",
                f"目标抛出 {observation['exception_type']}: {observation.get('exception_message', '')[:120]}",
            )
        state, ret = _return_value_or_error(observation)
        if state == "serialize_error":
            return CheckResult("HARNESS_ERROR", f"返回值无法按受限协议序列化: {ret}")
        if state == "missing":
            return CheckResult("HARNESS_ERROR", "观察数据缺少 return_value 字段（协议损坏）")
        if not isinstance(ret, list):
            return CheckResult("ASSERTION_FAILED", f"返回值不是列表: {ret!r}")
        if any(not isinstance(x, (int, float, str)) or isinstance(x, bool) for x in ret):
            return CheckResult("ASSERTION_FAILED", "列表含不可比较标量")
        asc = assertion.direction == "ASC"
        for i in range(len(ret) - 1):
            a, b = ret[i], ret[i + 1]
            if asc and (a > b or (assertion.strict and a == b)):
                return CheckResult("ASSERTION_FAILED", f"索引 {i}->{i+1}: {a!r} 与 {b!r} 非严格升序破坏")
            if not asc and (a < b or (assertion.strict and a == b)):
                return CheckResult("ASSERTION_FAILED", f"索引 {i}->{i+1}: {a!r} 与 {b!r} 非降序破坏")
        return CheckResult("PASSED")

    if kind == "SAME_MULTISET":
        if _exception_or_none(observation):
            return CheckResult(
                "TARGET_EXCEPTION",
                f"目标抛出 {observation['exception_type']}: {observation.get('exception_message', '')[:120]}",
            )
        state, ret = _return_value_or_error(observation)
        if state == "serialize_error":
            return CheckResult("HARNESS_ERROR", f"返回值无法按受限协议序列化: {ret}")
        if state == "missing":
            return CheckResult("HARNESS_ERROR", "观察数据缺少 return_value 字段（协议损坏）")
        before, _ = _get_target_snapshots(assertion.against, observation)
        if before is None:
            return CheckResult("HARNESS_ERROR", "缺少调用前快照")
        if not isinstance(ret, list) or not isinstance(before, list):
            return CheckResult("ASSERTION_FAILED", "返回值或输入快照不是列表")
        # 带类型的元素及出现次数（bool 与 int 区分）
        from collections import Counter
        def typed(v: Any) -> tuple:
            return (type(v).__name__, v)
        if Counter(typed(x) for x in ret) != Counter(typed(x) for x in before):
            return CheckResult(
                "ASSERTION_FAILED",
                f"返回 {ret!r} 与调用前输入 {before!r} 不是同一多重集",
            )
        return CheckResult("PASSED")

    return CheckResult("HARNESS_ERROR", f"未实现的检查模板: {kind!r}")


def _get_target_snapshots(
    target: ArgTarget, observation: dict[str, Any]
) -> tuple[Any, Any]:
    before_map = observation.get("args_before") or {}
    after_map = observation.get("args_after") or {}
    if target.kind == "ARG":
        key = f"arg:{target.index}"
    else:
        key = f"kwarg:{target.name}"
    return before_map.get(key), after_map.get(key)


def case_needs_snapshot(case: CheckCase) -> bool:
    """INPUT_UNCHANGED 与 SAME_MULTISET 必须使用执行前快照。"""
    return case.assertion.kind in ("INPUT_UNCHANGED", "SAME_MULTISET")


def validate_plan_structure(spec, plan) -> list[str]:
    """固定校验器（阶段 D）：结构、引用与空洞模式检查。"""
    errors: list[str] = []
    req_ids = {r.id for r in spec.requirements}
    contract_ids = {c.contract_id for c in plan.contracts}
    for c in plan.contracts:
        for rid in c.requirement_ids:
            if rid not in req_ids:
                errors.append(f"契约 {c.contract_id} 引用不存在的需求 {rid}")
        if not c.relation_basis:
            errors.append(f"契约 {c.contract_id} 缺少关系依据 relation_basis")
    seen_case_ids = set()
    for case in plan.cases:
        if case.case_id in seen_case_ids:
            errors.append(f"重复 case_id: {case.case_id}")
        seen_case_ids.add(case.case_id)
        if case.contract_id not in contract_ids:
            errors.append(f"案例 {case.case_id} 引用不存在的契约 {case.contract_id}")
        if case.assertion.kind == "RETURN_EQUALS" and not case.expected_basis:
            errors.append(f"案例 {case.case_id} 缺少 expected_basis（预期独立来源）")
        if case.input_domain_status == "OUT_OF_SCOPE":
            errors.append(f"案例 {case.case_id} 输入在范围外，不应进入验收计划")
    return errors