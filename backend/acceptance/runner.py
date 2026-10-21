"""隔离执行器（M3，方案第 9 章）。

受限子进程执行：受控 harness 脚本在任务级临时目录中导入被测代码，
观察值仅通过独立结果文件（results.json）返回；stdout/stderr 仅作日志，
父流程不从日志中解析结论。被测代码输出不能控制 verdict。

隔离级别如实报告：进程级隔离（参数列表调用、沙箱环境变量、任务临时目录、
总超时与进程终止），无 Docker 网络隔离与 CPU/内存 cgroup 限制；
该边界写入报告 limitations，不伪称完备安全隔离。
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from backend.acceptance.checks import case_needs_snapshot, evaluate_assertion
from backend.acceptance.models import (
    CheckCase,
    Entrypoint,
    Evidence,
    EvidenceStatus,
)

HARNESS_TEMPLATE = r'''
import json
import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MAX_OUTPUT_BYTES = 262144

def dump_limited(obj):
    s = json.dumps(obj, ensure_ascii=False, allow_nan=False)
    if len(s.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ValueError("observation too large")
    return s

def snapshot(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    import copy
    return copy.deepcopy(value)

def main():
    with open("cases.json", encoding="utf-8") as f:
        cases = json.load(f)
    entry = json.load(open("entry.json", encoding="utf-8"))
    results = []
    module = None
    import importlib
    try:
        module = importlib.import_module(entry["module"])
    except Exception as e:
        for case in cases:
            results.append({
                "case_id": case["case_id"],
                "status": "IMPORT_ERROR",
                "exception_type": type(e).__name__,
                "exception_message": str(e)[:500],
                "duration_ms": 0.0,
            })
        json.dump(results, open("results.json", "w", encoding="utf-8"), ensure_ascii=False)
        return

    fn = getattr(module, entry["callable"], None)
    if fn is None or not callable(fn):
        for case in cases:
            results.append({
                "case_id": case["case_id"],
                "status": "IMPORT_ERROR",
                "exception_message": "entry callable not found: %s" % entry["callable"],
                "duration_ms": 0.0,
            })
        json.dump(results, open("results.json", "w", encoding="utf-8"), ensure_ascii=False)
        return

    for case in cases:
        args = case["args"]
        kwargs = case["kwargs"]
        need_snap = case.get("snapshot", False)
        record = {"case_id": case["case_id"], "duration_ms": 0.0}
        before = None
        if need_snap:
            try:
                before = {"arg:%d" % i: snapshot(a) for i, a in enumerate(args)}
                before.update({"kwarg:%s" % k: snapshot(v) for k, v in kwargs.items()})
            except Exception as e:
                record["status"] = "HARNESS_ERROR"
                record["exception_type"] = type(e).__name__
                record["exception_message"] = "snapshot failed: %s" % str(e)[:300]
                results.append(record)
                continue
        t0 = time.monotonic()
        try:
            ret = fn(*args, **kwargs)
        except BaseException as e:
            record["duration_ms"] = (time.monotonic() - t0) * 1000.0
            record["status"] = "TARGET_EXCEPTION"
            record["exception_type"] = type(e).__name__
            record["exception_message"] = str(e)[:500]
            if need_snap:
                record["args_before"] = before
                record["args_after"] = _after(args, kwargs)
            results.append(record)
            continue
        record["duration_ms"] = (time.monotonic() - t0) * 1000.0
        if need_snap:
            record["args_before"] = before
            record["args_after"] = _after(args, kwargs)
        try:
            record["return_value"] = json.loads(dump_limited(ret))
        except Exception:
            record["return_serialization_error"] = (
                "return value not JSON-serializable: %s" % type(ret).__name__
            )
        record["status"] = "OK"
        results.append(record)
    try:
        json.dump(results, open("results.json", "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        # 结果文件写入失败时写一个错误标记文件，父进程按损坏输出处理
        with open("results-error.txt", "w", encoding="utf-8") as f:
            f.write(str(e)[:500])

def _after(args, kwargs):
    out = {"arg:%d" % i: snapshot(a) for i, a in enumerate(args)}
    out.update({"kwarg:%s" % k: snapshot(v) for k, v in kwargs.items()})
    return out

if __name__ == "__main__":
    main()
'''

RUNNER_VERSION = "acceptance-runner/1.0"


def runtime_fingerprint() -> str:
    return (
        f"{RUNNER_VERSION} python={platform.python_version()} "
        f"platform={platform.platform()} isolation=SUBPROCESS_SANDBOX"
    )


def run_cases(
    code: str,
    supporting_files: list[tuple[str, str]],
    entrypoint: Entrypoint,
    cases: list[CheckCase],
    code_hash_value: str,
    plan_hash_value: str,
    spec_hash_value: str,
    total_timeout_s: float = 30.0,
) -> tuple[list[Evidence], list[str]]:
    """在受限子进程中执行固定案例，返回 (证据列表, 运行日志)。

    证据只记录观察值；断言评估在父进程由 checks.evaluate_assertion 完成。
    """
    tmp = Path(tempfile.mkdtemp(prefix="pyq_accept_"))
    logs: list[str] = []
    evidence: list[Evidence] = []
    try:
        (tmp / "solution.py").write_text(code, encoding="utf-8")
        for rel, content in supporting_files:
            dest = tmp / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        (tmp / "harness.py").write_text(HARNESS_TEMPLATE, encoding="utf-8")
        cases_payload = []
        for case in cases:
            cases_payload.append({
                "case_id": case.case_id,
                "args": case.args,
                "kwargs": case.kwargs,
                "snapshot": case_needs_snapshot(case),
            })
        (tmp / "cases.json").write_text(
            json.dumps(cases_payload, ensure_ascii=False), encoding="utf-8"
        )
        (tmp / "entry.json").write_text(
            json.dumps({"module": entrypoint.module, "callable": entrypoint.callable}),
            encoding="utf-8",
        )

        from backend.config import build_sandbox_env

        env = build_sandbox_env(tmp)
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(tmp / "harness.py")],
                capture_output=True, text=True, timeout=total_timeout_s,
                cwd=str(tmp), env=env,
            )
            logs.append(f"exit={proc.returncode}")
            if proc.stdout:
                logs.append("stdout: " + proc.stdout[:2048])
            if proc.stderr:
                logs.append("stderr: " + proc.stderr[:2048])
        except subprocess.TimeoutExpired as e:
            logs.append(f"RUNNER_TIMEOUT after {total_timeout_s}s")
            for case in cases:
                evidence.append(Evidence(
                    kind="EXECUTED_CASE", producer=RUNNER_VERSION,
                    code_hash=code_hash_value, spec_hash=spec_hash_value,
                    plan_hash=plan_hash_value,
                    runtime_fingerprint=runtime_fingerprint(),
                    case_id=case.case_id, requirement_ids=case.requirement_ids,
                    phase="RUNNER", observation={}, status="TIMEOUT",
                    artifact_refs=[str(tmp / "harness.py")],
                ))
            return evidence, logs

        results_path = tmp / "results.json"
        if not results_path.exists():
            logs.append("results.json missing (corrupted output)")
            for case in cases:
                evidence.append(Evidence(
                    kind="EXECUTED_CASE", producer=RUNNER_VERSION,
                    code_hash=code_hash_value, spec_hash=spec_hash_value,
                    plan_hash=plan_hash_value,
                    runtime_fingerprint=runtime_fingerprint(),
                    case_id=case.case_id, requirement_ids=case.requirement_ids,
                    phase="RUNNER", observation={}, status="ENV_ERROR",
                    artifact_refs=[str(tmp / "harness.py")],
                ))
            return evidence, logs

        try:
            raw_results = json.loads(results_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raw_results = None
        if not isinstance(raw_results, list):
            logs.append("results.json is not a list")
            raw_results = None

        # 校验结果协议：case_id 必须与计划一一对应，多余/缺失都按损坏处理
        by_case: dict[str, dict[str, Any]] = {}
        if raw_results is not None:
            for item in raw_results:
                if isinstance(item, dict) and isinstance(item.get("case_id"), str):
                    by_case[item["case_id"]] = item
        expected_ids = {c.case_id for c in cases}
        received_ids = set(by_case.keys())
        if expected_ids != received_ids:
            logs.append(
                f"protocol mismatch: expected {sorted(expected_ids)} got {sorted(received_ids)}"
            )

        for case in cases:
            item = by_case.get(case.case_id)
            if item is None:
                status = "NOT_RUN"
                observation: dict[str, Any] = {}
                if raw_results is not None:
                    status = "ENV_ERROR"
                    observation = {"protocol_error": "missing case result"}
            elif item.get("status") == "IMPORT_ERROR":
                status = "ENV_ERROR"
                observation = {
                    "exception_type": item.get("exception_type", "ImportError"),
                    "exception_message": item.get("exception_message", ""),
                }
            else:
                observation = _extract_observation(item)
                check = evaluate_assertion(case.assertion, observation)
                status = check.status
                if check.detail:
                    observation["check_detail"] = check.detail
            evidence.append(Evidence(
                kind="EXECUTED_CASE", producer=RUNNER_VERSION,
                code_hash=code_hash_value, spec_hash=spec_hash_value,
                plan_hash=plan_hash_value,
                runtime_fingerprint=runtime_fingerprint(),
                case_id=case.case_id, requirement_ids=case.requirement_ids,
                phase="ASSERT", observation=observation, status=status,
                artifact_refs=[str(tmp / "results.json")],
                duration_ms=item.get("duration_ms") if item else None,
            ))
        return evidence, logs
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _extract_observation(item: dict[str, Any]) -> dict[str, Any]:
    obs: dict[str, Any] = {}
    for key in (
        "return_value", "return_serialization_error",
        "exception_type", "exception_message",
        "args_before", "args_after", "duration_ms",
    ):
        if key in item:
            obs[key] = item[key]
    return obs


def compile_check(code: str, module_name: str = "solution") -> tuple[bool, str]:
    """阶段 A 的编译事实：TECH_COMPILE（受限工具进程内完成）。"""
    try:
        compile(code, f"<{module_name}.py>", "exec")
        return True, ""
    except SyntaxError as e:
        return False, f"line {e.lineno}: {e.msg}"