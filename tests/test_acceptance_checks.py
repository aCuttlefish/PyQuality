"""固定检查模板测试（M3）：7 种模板的断言评估纯函数。"""
import pytest

from backend.acceptance.checks import evaluate_assertion
from backend.acceptance.models import (
    AllItemsMatchAssertion,
    ArgTarget,
    InputUnchangedAssertion,
    OrderedAssertion,
    PredicateSpec,
    RaisesAssertion,
    ReturnEqualsAssertion,
    ReturnIsNoneAssertion,
    SameMultisetAssertion,
)


def obs(**kw):
    base = {"return_value": None, "exception_type": "", "exception_message": ""}
    base.update(kw)
    return base


class TestReturnEquals:
    def test_equal_pass(self):
        r = evaluate_assertion(
            ReturnEqualsAssertion(kind="RETURN_EQUALS", expected=8),
            obs(return_value=8),
        )
        assert r.passed

    def test_inequal_fail(self):
        r = evaluate_assertion(
            ReturnEqualsAssertion(kind="RETURN_EQUALS", expected=None),
            obs(return_value=0),
        )
        assert r.status == "ASSERTION_FAILED"

    def test_no_type_coercion(self):
        """bool 与 int 不做类型强制转换。"""
        r = evaluate_assertion(
            ReturnEqualsAssertion(kind="RETURN_EQUALS", expected=1),
            obs(return_value=True),
        )
        assert r.status == "ASSERTION_FAILED"

    def test_exception_is_target_exception(self):
        r = evaluate_assertion(
            ReturnEqualsAssertion(kind="RETURN_EQUALS", expected=1),
            obs(exception_type="ValueError", exception_message="bad"),
        )
        assert r.status == "TARGET_EXCEPTION"

    def test_unserializable_return(self):
        r = evaluate_assertion(
            ReturnEqualsAssertion(kind="RETURN_EQUALS", expected=1),
            obs(return_serialization_error="not serializable"),
        )
        assert r.status == "HARNESS_ERROR"


class TestReturnIsNone:
    def test_none_pass(self):
        assert evaluate_assertion(
            ReturnIsNoneAssertion(kind="RETURN_IS_NONE"), obs(return_value=None)
        ).passed

    def test_zero_fail(self):
        r = evaluate_assertion(
            ReturnIsNoneAssertion(kind="RETURN_IS_NONE"), obs(return_value=0)
        )
        assert r.status == "ASSERTION_FAILED"


class TestRaises:
    def test_right_exception(self):
        assert evaluate_assertion(
            RaisesAssertion(kind="RAISES", exception_type="ValueError"),
            obs(exception_type="ValueError", exception_message="x"),
        ).passed

    def test_wrong_exception(self):
        r = evaluate_assertion(
            RaisesAssertion(kind="RAISES", exception_type="ValueError"),
            obs(exception_type="TypeError"),
        )
        assert r.status == "ASSERTION_FAILED"

    def test_no_exception(self):
        r = evaluate_assertion(
            RaisesAssertion(kind="RAISES", exception_type="ValueError"),
            obs(return_value=0),
        )
        assert r.status == "ASSERTION_FAILED"

    def test_message_filter(self):
        r = evaluate_assertion(
            RaisesAssertion(kind="RAISES", exception_type="ValueError", message_contains="amount"),
            obs(exception_type="ValueError", exception_message="wrong input"),
        )
        assert r.status == "ASSERTION_FAILED"


class TestInputUnchanged:
    def _assertion(self):
        return InputUnchangedAssertion(
            kind="INPUT_UNCHANGED", targets=[ArgTarget(kind="ARG", index=0)]
        )

    def test_unchanged_pass(self):
        r = evaluate_assertion(
            self._assertion(),
            obs(args_before={"arg:0": [1, 2]}, args_after={"arg:0": [1, 2]}),
        )
        assert r.passed

    def test_mutated_fail(self):
        r = evaluate_assertion(
            self._assertion(),
            obs(args_before={"arg:0": [4, 1, 8]}, args_after={"arg:0": [8, 4, 1]}),
        )
        assert r.status == "ASSERTION_FAILED"

    def test_kwarg_target(self):
        a = InputUnchangedAssertion(
            kind="INPUT_UNCHANGED", targets=[ArgTarget(kind="KWARG", name="items")]
        )
        r = evaluate_assertion(
            a,
            obs(args_before={"kwarg:items": [1]}, args_after={"kwarg:items": []}),
        )
        assert r.status == "ASSERTION_FAILED"


class TestAllItemsMatch:
    def test_all_even_pass(self):
        r = evaluate_assertion(
            AllItemsMatchAssertion(
                kind="ALL_ITEMS_MATCH",
                predicate=PredicateSpec(op="IS_EVEN", value_type="int"),
            ),
            obs(return_value=[2, 4, 6]),
        )
        assert r.passed

    def test_odd_fail(self):
        r = evaluate_assertion(
            AllItemsMatchAssertion(
                kind="ALL_ITEMS_MATCH",
                predicate=PredicateSpec(op="IS_EVEN", value_type="int"),
            ),
            obs(return_value=[2, 3]),
        )
        assert r.status == "ASSERTION_FAILED"

    def test_non_list_fail(self):
        r = evaluate_assertion(
            AllItemsMatchAssertion(
                kind="ALL_ITEMS_MATCH",
                predicate=PredicateSpec(op="IS_EVEN", value_type="int"),
            ),
            obs(return_value=None),
        )
        assert r.status == "ASSERTION_FAILED"

    def test_type_checked(self):
        r = evaluate_assertion(
            AllItemsMatchAssertion(
                kind="ALL_ITEMS_MATCH",
                predicate=PredicateSpec(op="IS_EVEN", value_type="int"),
            ),
            obs(return_value=[2, "4"]),
        )
        assert r.status == "ASSERTION_FAILED"


class TestOrdered:
    def test_asc_pass(self):
        assert evaluate_assertion(
            OrderedAssertion(kind="ORDERED", direction="ASC"),
            obs(return_value=[1, 2, 3]),
        ).passed

    def test_desc_pass(self):
        assert evaluate_assertion(
            OrderedAssertion(kind="ORDERED", direction="DESC"),
            obs(return_value=[3, 2, 1]),
        ).passed

    def test_unordered_fail(self):
        r = evaluate_assertion(
            OrderedAssertion(kind="ORDERED", direction="ASC"),
            obs(return_value=[2, 1, 3]),
        )
        assert r.status == "ASSERTION_FAILED"

    def test_strict_rejects_equal(self):
        r = evaluate_assertion(
            OrderedAssertion(kind="ORDERED", direction="ASC", strict=True),
            obs(return_value=[1, 1, 2]),
        )
        assert r.status == "ASSERTION_FAILED"


class TestSameMultiset:
    def _assertion(self):
        return SameMultisetAssertion(
            kind="SAME_MULTISET", against=ArgTarget(kind="ARG", index=0)
        )

    def test_same_pass(self):
        r = evaluate_assertion(
            self._assertion(),
            obs(return_value=[3, 1, 2], args_before={"arg:0": [1, 2, 3]}, args_after={}),
        )
        assert r.passed

    def test_missing_element_fail(self):
        """A11：代码返回 [] 时不能通过完整性检查。"""
        r = evaluate_assertion(
            self._assertion(),
            obs(return_value=[], args_before={"arg:0": [1, 2, 3]}, args_after={}),
        )
        assert r.status == "ASSERTION_FAILED"

    def test_counts_matter(self):
        r = evaluate_assertion(
            self._assertion(),
            obs(return_value=[1, 1, 2], args_before={"arg:0": [1, 2, 2]}, args_after={}),
        )
        assert r.status == "ASSERTION_FAILED"

    def test_bool_int_distinct(self):
        r = evaluate_assertion(
            self._assertion(),
            obs(return_value=[1], args_before={"arg:0": [True]}, args_after={}),
        )
        assert r.status == "ASSERTION_FAILED"


class TestUnsupported:
    def test_unknown_template_is_harness_error(self):
        from backend.acceptance.models import Assertion
        r = evaluate_assertion(
            ReturnIsNoneAssertion(kind="RETURN_IS_NONE"), obs()
        )
        assert r.passed  # 已支持模板不受影响