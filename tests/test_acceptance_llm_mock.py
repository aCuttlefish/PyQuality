"""LLM 路径测试（M2）。

⚠ 本文件全部使用 mock —— 仅验证接口、校验与异常分支，
不冒充真实模型能力。真实模型端到端见手动验证记录。
"""
import pytest

from backend.acceptance import llm_provider, spec_extractor
from backend.acceptance.models import (
    Entrypoint,
    EvaluationRequest,
)


def _fake_generate(payload_result):
    """构造 mock generate_structured：固定返回给定 JSON。"""

    def fake(task, payload, **kwargs):
        if isinstance(payload_result, Exception):
            raise payload_result
        return payload_result

    return fake


class TestProviderUnavailable:
    def test_no_key_raises(self):
        """无密钥 → ProviderUnavailable（调用方降级）。"""
        with pytest.raises(llm_provider.ProviderUnavailable):
            llm_provider.generate_structured("t", {})


class TestForbiddenFields:
    def test_model_claiming_verdict_rejected(self, monkeypatch):
        """A21：模型自报 code_verdict → 整个候选被拒绝。"""
        monkeypatch.setattr(
            llm_provider, "is_available", lambda: True
        )
        monkeypatch.setattr(
            llm_provider.deepseek_client, "chat_json",
            lambda msgs, temperature=0.3: {
                "requirements": [], "code_verdict": "PASS_WITHIN_SCOPE",
            },
        )
        with pytest.raises(llm_provider.ProviderUnavailable, match="受保护字段"):
            llm_provider.generate_structured("t", {})

    def test_model_claiming_verified_rejected(self, monkeypatch):
        monkeypatch.setattr(llm_provider, "is_available", lambda: True)
        monkeypatch.setattr(
            llm_provider.deepseek_client, "chat_json",
            lambda msgs, temperature=0.3: {"verified": True},
        )
        with pytest.raises(llm_provider.ProviderUnavailable):
            llm_provider.generate_structured("t", {})

    def test_strip_forbidden_recursive(self):
        data = {
            "ok": 1,
            "nested": {"verified": True, "keep": 2},
            "list": [{"evidence": [], "x": 1}],
        }
        out = llm_provider.strip_forbidden_fields(data)
        assert "ok" in out
        assert "verified" not in out["nested"]
        assert "evidence" not in out["list"][0]


class TestSpecExtractorMock:
    """mock 模型返回 → 验证 source_quote 程序校验。"""

    REQ = "实现 max_even(nums)。输入整数列表，返回其中最大的偶数；不存在偶数时返回 None。"

    def test_valid_extraction(self, monkeypatch):
        monkeypatch.setattr(llm_provider, "is_available", lambda: True)
        monkeypatch.setattr(
            llm_provider.deepseek_client, "chat_json",
            lambda msgs, temperature=0.3: {
                "requirements": [
                    {
                        "id": "R1", "statement": "返回最大偶数", "origin": "EXPLICIT",
                        "source_quote": "返回其中最大的偶数",
                    },
                    {
                        "id": "R2", "statement": "无偶数返回 None", "origin": "EXPLICIT",
                        "source_quote": "不存在偶数时返回 None",
                    },
                ],
                "input_domain": [
                    {"description": "整数列表", "source_quote": "输入整数列表", "origin": "EXPLICIT"}
                ],
                "technical_constraints": ["入口 solution.max_even"],
                "unresolved_questions": [],
            },
        )
        result = spec_extractor.extract_spec(self.REQ, Entrypoint(module="solution", callable="max_even"))
        assert result.mode == "LLM"
        assert result.spec is not None
        assert len(result.spec.requirements) == 2
        assert result.spec.interpretation_status == "UNRESOLVED"

    def test_forged_quote_rejected(self, monkeypatch):
        """A21：模型伪造不在原文中的 source_quote → 该条被拒绝。"""
        monkeypatch.setattr(llm_provider, "is_available", lambda: True)
        monkeypatch.setattr(
            llm_provider.deepseek_client, "chat_json",
            lambda msgs, temperature=0.3: {
                "requirements": [
                    {
                        "id": "R1", "statement": "应缓存结果", "origin": "EXPLICIT",
                        "source_quote": "结果必须缓存以提高性能",  # 不在 R 原文中
                    },
                ],
            },
        )
        result = spec_extractor.extract_spec(self.REQ, None)
        assert result.spec is None
        assert "未通过校验" in result.error or result.mode == "UNAVAILABLE"

    def test_all_rejected_returns_unavailable(self, monkeypatch):
        monkeypatch.setattr(llm_provider, "is_available", lambda: True)
        monkeypatch.setattr(
            llm_provider.deepseek_client, "chat_json",
            lambda msgs, temperature=0.3: {"requirements": "not-a-list"},
        )
        result = spec_extractor.extract_spec(self.REQ, None)
        assert result.mode == "UNAVAILABLE"

    def test_llm_error_degrades(self, monkeypatch):
        from backend.ai.deepseek_client import DeepSeekError

        monkeypatch.setattr(llm_provider, "is_available", lambda: True)
        monkeypatch.setattr(
            llm_provider.deepseek_client, "chat_json",
            lambda msgs, temperature=0.3: (_ for _ in ()).throw(DeepSeekError("timeout")),
        )
        result = spec_extractor.extract_spec(self.REQ, None)
        assert result.mode == "UNAVAILABLE"
        assert "timeout" in result.error


class TestRequestHash:
    def test_different_prompt_different_hash(self):
        r1 = EvaluationRequest(requirement="r", generation_prompt="p1", code="x=1")
        r2 = EvaluationRequest(requirement="r", generation_prompt="p2", code="x=1")
        from backend.acceptance import hashing
        assert hashing.request_hash(r1) != hashing.request_hash(r2)

    def test_same_request_same_hash(self):
        r1 = EvaluationRequest(requirement="r", code="x=1")
        r2 = EvaluationRequest(requirement="r", code="x=1")
        from backend.acceptance import hashing
        assert hashing.request_hash(r1) == hashing.request_hash(r2)