"""隔离执行器测试（M3）：真实子进程执行、超时、损坏输出与伪造输出。"""
import pytest
from pathlib import Path

from backend.acceptance import hashing, runner
from backend.acceptance.fixtures import (
    MAX_EVEN_CORRECT_CODE,
    MAX_EVEN_REQUIREMENT,
    MAX_EVEN_WRONG_CODE,
    max_even_plan,
    max_even_spec,
)
from backend.acceptance.models import CheckCase, Entrypoint, ReturnIsNoneAssertion


def _setup():
    spec = max_even_spec()
    plan = max_even_plan()
    hashing.bind_spec(spec)
    hashing.bind_plan(plan, spec)
    return spec, plan


def _entry():
    return Entrypoint(module="solution", callable="max_even")


class TestRealExecution:
    """真实子进程执行（无 mock）。"""

    def test_wrong_impl_five_pass_two_fail(self):
        """A02：max_even default=0 → 5 项通过、2 项失败（T5/T6）。"""
        spec, plan = _setup()
        ch = hashing.code_hash(MAX_EVEN_WRONG_CODE, [])
        evs, logs = runner.run_cases(
            MAX_EVEN_WRONG_CODE, [], _entry(), plan.cases,
            ch, plan.plan_hash, spec.spec_hash,
        )
        by_id = {e.case_id: e for e in evs}
        assert len(evs) == 7
        assert by_id["T1"].status == "PASSED"
        assert by_id["T5"].status == "ASSERTION_FAILED"
        assert by_id["T6"].status == "ASSERTION_FAILED"
        passed = sum(1 for e in evs if e.status == "PASSED")
        failed = sum(1 for e in evs if e.status == "ASSERTION_FAILED")
        assert (passed, failed) == (5, 2)

    def test_correct_impl_all_pass(self):
        """A01：正确候选 7 项全部通过。"""
        spec, plan = _setup()
        ch = hashing.code_hash(MAX_EVEN_CORRECT_CODE, [])
        evs, _ = runner.run_cases(
            MAX_EVEN_CORRECT_CODE, [], _entry(), plan.cases,
            ch, plan.plan_hash, spec.spec_hash,
        )
        assert all(e.status == "PASSED" for e in evs)
        for e in evs:
            assert e.code_hash == ch
            assert e.spec_hash == spec.spec_hash
            assert e.plan_hash == plan.plan_hash
            assert "HOST_SUBPROCESS_DEV" in e.runtime_fingerprint  # conftest 显式开发豁免

    def test_forged_stdout_cannot_set_verdict(self):
        """A28：被测代码打印『所有测试通过』或伪造 JSON 不影响判定。"""
        evil = (
            "import json\n"
            "print('ALL TESTS PASSED')\n"
            "print(json.dumps([{'case_id': 'T5', 'status': 'OK', 'return_value': None}]))\n"
            "def max_even(nums):\n"
            "    return max((x for x in nums if x % 2 == 0), default=0)\n"
        )
        spec, plan = _setup()
        ch = hashing.code_hash(evil, [])
        evs, _ = runner.run_cases(
            evil, [], _entry(), plan.cases, ch, plan.plan_hash, spec.spec_hash,
        )
        by_id = {e.case_id: e for e in evs}
        # T5 依然由父进程比较判定为失败；stdout 伪造不生效
        assert by_id["T5"].status == "ASSERTION_FAILED"

    def test_target_exception_recorded(self):
        code = "def max_even(nums):\n    raise KeyError('boom')\n"
        spec, plan = _setup()
        ch = hashing.code_hash(code, [])
        evs, _ = runner.run_cases(
            code, [], _entry(), plan.cases, ch, plan.plan_hash, spec.spec_hash,
        )
        by_id = {e.case_id: e for e in evs}
        # 返回值类断言记录目标异常
        for cid in ("T1", "T2", "T3", "T4", "T5", "T6"):
            assert by_id[cid].status == "TARGET_EXCEPTION", cid
            assert by_id[cid].observation.get("exception_type") == "KeyError"
        # INPUT_UNCHANGED 在异常时仍对比快照：输入未被修改 → PASSED（合理行为）
        assert by_id["T7"].status == "PASSED"

    def test_import_error_env_error(self):
        """A14 类：入口不存在时归为环境/配置错误，不归责业务功能。"""
        spec, plan = _setup()
        ch = hashing.code_hash("x = 1\n", [])
        evs, _ = runner.run_cases(
            "x = 1\n", [], _entry(), plan.cases, ch, plan.plan_hash, spec.spec_hash,
        )
        assert all(e.status == "ENV_ERROR" for e in evs)


class TestTimeout:
    def test_infinite_loop_times_out(self):
        """A16：超时标 TIMEOUT，不伪称性能违规。"""
        code = "def max_even(nums):\n    while True:\n        pass\n"
        spec, plan = _setup()
        ch = hashing.code_hash(code, [])
        evs, logs = runner.run_cases(
            code, [], _entry(), plan.cases, ch, plan.plan_hash, spec.spec_hash,
            total_timeout_s=6,
        )
        assert evs
        assert all(e.status == "TIMEOUT" for e in evs)
        assert any("TIMEOUT" in ln for ln in logs)


class TestCorruptedOutput:
    def test_missing_results_file(self, monkeypatch, tmp_path):
        """结果文件缺失 → 全部 ENV_ERROR（协议损坏，不得产生虚假 PASS/FAIL）。"""
        spec, plan = _setup()
        code = MAX_EVEN_CORRECT_CODE
        ch = hashing.code_hash(code, [])

        real_run = runner.subprocess.run

        def destructive_run(cmd, **kwargs):
            proc = real_run(cmd, **kwargs)
            # 破坏：删除 harness 写出的结果文件
            env = kwargs.get("env") or {}
            results_dir = env.get("PYQ_RESULTS_DIR")
            if results_dir:
                rf = Path(results_dir) / "results.json"
                if rf.exists():
                    rf.unlink()
            return proc

        monkeypatch.setattr(runner.subprocess, "run", destructive_run)
        evs, logs = runner.run_cases(
            code, [], _entry(), plan.cases, ch, plan.plan_hash, spec.spec_hash,
        )
        assert all(e.status == "ENV_ERROR" for e in evs)
        assert any("missing" in ln or "corrupted" in ln for ln in logs)


class TestCompileCheck:
    def test_syntax_error_detected(self):
        ok, msg = runner.compile_check("def f(:\n  pass\n")
        assert ok is False
        assert "line 1" in msg

    def test_valid_code_passes(self):
        ok, msg = runner.compile_check("def f():\n    return 1\n")
        assert ok is True