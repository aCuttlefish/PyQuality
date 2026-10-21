"""验收数据契约测试（M1）：结构校验、引用校验、预算与安全约束。"""
import pytest
from pydantic import ValidationError

from backend.acceptance.models import (
    AcceptanceMaterials,
    CheckCase,
    ContractSpec,
    Entrypoint,
    EvaluationRequest,
    RaisesAssertion,
    RequirementItem,
    SupportingFile,
)


class TestEntrypoint:
    def test_valid(self):
        e = Entrypoint(module="solution", callable="max_even")
        assert e.module == "solution"

    def test_reject_path_traversal_module(self):
        with pytest.raises(ValidationError):
            Entrypoint(module="..evil", callable="f")

    def test_reject_bad_module(self):
        with pytest.raises(ValidationError):
            Entrypoint(module="1bad", callable="f")


class TestSupportingFile:
    def test_reject_absolute(self):
        with pytest.raises(ValidationError):
            SupportingFile(path="/etc/passwd.py", content="x")

    def test_reject_parent_jump(self):
        with pytest.raises(ValidationError):
            SupportingFile(path="../evil.py", content="x")

    def test_reject_backslash(self):
        with pytest.raises(ValidationError):
            SupportingFile(path="a\\b.py", content="x")

    def test_reject_non_py(self):
        with pytest.raises(ValidationError):
            SupportingFile(path="data.txt", content="x")


class TestRequirementItem:
    def test_explicit_requires_quote(self):
        with pytest.raises(ValidationError):
            RequirementItem(id="R1", statement="s", origin="EXPLICIT", source_quote="")

    def test_derived_requires_basis(self):
        with pytest.raises(ValidationError):
            RequirementItem(
                id="R1", statement="s", origin="DERIVED",
                source_quote="", derivation_basis="",
            )


class TestBudget:
    def test_reject_too_many_supporting_files(self):
        files = [SupportingFile(path=f"f{i}.py", content="x") for i in range(9)]
        with pytest.raises(ValidationError, match="8"):
            EvaluationRequest(
                requirement="r", code="x=1", supporting_files=files
            )

    def test_reject_oversized_code(self):
        with pytest.raises(ValidationError):
            EvaluationRequest(requirement="r", code="x" * 262200)

    def test_reject_empty_requirement(self):
        with pytest.raises(ValidationError):
            EvaluationRequest(requirement="", code="x=1")


class TestStrictSchema:
    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            EvaluationRequest(requirement="r", code="x=1", verdict="PASS")

    def test_raises_whitelist(self):
        with pytest.raises(ValidationError):
            RaisesAssertion(kind="RAISES", exception_type="SystemExit")

    def test_raises_builtin_ok(self):
        a = RaisesAssertion(kind="RAISES", exception_type="ValueError")
        assert a.exception_type == "ValueError"


class TestCheckCase:
    def test_case_requires_assertion_kind(self):
        with pytest.raises(ValidationError):
            CheckCase(
                case_id="T1", contract_id="K", requirement_ids=["R1"],
                assertion={"kind": "NOT_A_TEMPLATE"},
            )

    def test_input_unchanged_requires_targets(self):
        with pytest.raises(ValidationError):
            CheckCase(
                case_id="T1", contract_id="K", requirement_ids=["R1"],
                assertion={"kind": "INPUT_UNCHANGED", "targets": []},
            )

    def test_ordered_identity_key_only(self):
        with pytest.raises(ValidationError):
            CheckCase(
                case_id="T1", contract_id="K", requirement_ids=["R1"],
                assertion={"kind": "ORDERED", "direction": "ASC", "key": "CUSTOM"},
            )