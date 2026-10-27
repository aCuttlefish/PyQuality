"""隔离执行器（M3，方案第 9 章）。

P0 修复（v4.1）：
- 结果协议严格校验：案例集合必须与计划一一对应，重复/缺失/多余
  case_id 均触发协议错误，整份结果不得用于正常业务判定。
- 区分合法 Python None（return_value 键存在且为 null）与字段缺失。
- 非白名单执行状态不进入正常断言路径。
- 非 JSON 原生类型（tuple/set/对象）不做静默转换，标记序列化错误。

执行安全边界（P0-7）：
- 默认优先 Docker 容器隔离（非特权、无网络、只读根、资源限额）。
- 无 Docker 时动态执行 BLOCKED，整体按规则 INCONCLUSIVE；
  不回退宿主执行后仍宣称安全隔离。
- PYQ_ACCEPTANCE_ALLOW_HOST=1 为显式开发豁免，报告如实标注
  HOST_SUBPROCESS_DEV（仅限本地开发/测试，不是安全边界）。
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from backend.acceptance.checks import case_needs_snapshot, evaluate_assertion
from backend.acceptance.models import (
    CheckCase,
    Entrypoint,
    Evidence,
)

HARNESS_TEMPLATE = r'''
import json
import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MAX_OUTPUT_BYTES = 262144

def is_json_native(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return True
    if isinstance(v, list):
        return all(is_json_native(x) for x in v)
    if isinstance(v, dict):
        return all(isinstance(k, str) and is_json_native(x) for k, x in v.items())
    return False  # tuple/set/复杂对象不做静默转换

def dump_limited(obj):
    if not is_json_native(obj):
        raise ValueError("non-json-native type: %s" % type(obj).__name__)
    s = json.dumps(obj, ensure_ascii=False, allow_nan=False)
    if len(s.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ValueError("observation too large")
    return s

def snapshot(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    import copy
    return copy.deepcopy(value)

def _results_path():
    out_dir = os.environ.get("PYQ_RESULTS_DIR")
    if out_dir:
        return os.path.join(out_dir, "results.json")
    return "results.json"

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
        json.dump(results, open(_results_path(), "w", encoding="utf-8"), ensure_ascii=False)
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
        json.dump(results, open(_results_path(), "w", encoding="utf-8"), ensure_ascii=False)
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
            # 正常返回：return_value 键一定存在（可为合法 null）
            record["return_value"] = json.loads(dump_limited(ret))
        except Exception as e:
            record["return_serialization_error"] = (
                "return value not JSON-native: %s" % str(e)[:200]
            )
        record["status"] = "OK"
        results.append(record)
    try:
        json.dump(results, open(_results_path(), "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        with open("results-error.txt", "w", encoding="utf-8") as f:
            f.write(str(e)[:500])

def _after(args, kwargs):
    out = {"arg:%d" % i: snapshot(a) for i, a in enumerate(args)}
    out.update({"kwarg:%s" % k: snapshot(v) for k, v in kwargs.items()})
    return out

if __name__ == "__main__":
    main()
'''

RUNNER_VERSION = "acceptance-runner/1.1"

# harness 结果状态白名单（其余视为协议损坏）
HARNESS_STATUS_WHITELIST = {"OK", "TARGET_EXCEPTION", "IMPORT_ERROR", "HARNESS_ERROR"}

DOCKER_IMAGE = "python:3.10-slim"
DOCKER_TIMEOUT_EXTRA_S = 20


class ExecutionBlocked(Exception):
    """动态执行被阻断（无合格隔离环境且未启用开发豁免）。"""


class ExecutionBackend:
    def __init__(self, name: str, available: bool, detail: str = ""):
        self.name = name
        self.available = available
        self.detail = detail


_DOCKER_PROBE_CACHE: Optional[ExecutionBackend] = None


def _probe_docker() -> ExecutionBackend:
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return ExecutionBackend("DOCKER", True, f"server={proc.stdout.strip()}")
        return ExecutionBackend("DOCKER", False, f"docker info rc={proc.returncode}")
    except FileNotFoundError:
        return ExecutionBackend("DOCKER", False, "docker 未安装")
    except subprocess.TimeoutExpired:
        return ExecutionBackend("DOCKER", False, "docker daemon 不可达（超时）")
    except Exception as e:
        return ExecutionBackend("DOCKER", False, str(e)[:120])


def detect_execution_backend() -> ExecutionBackend:
    """执行后端检测：显式豁免 → Docker → BLOCKED。

    默认不把不可信用户代码交给宿主普通子进程执行（P0-7）。
    """
    global _DOCKER_PROBE_CACHE
    if os.environ.get("PYQ_ACCEPTANCE_ALLOW_HOST") == "1":
        return ExecutionBackend("HOST_SUBPROCESS_DEV", True, "显式开发豁免（非安全边界）")
    if os.environ.get("PYQ_ACCEPTANCE_FORCE_DOCKER") == "1":
        _DOCKER_PROBE_CACHE = _DOCKER_PROBE_CACHE or _probe_docker()
        return _DOCKER_PROBE_CACHE
    _DOCKER_PROBE_CACHE = _DOCKER_PROBE_CACHE or _probe_docker()
    if _DOCKER_PROBE_CACHE.available:
        return _DOCKER_PROBE_CACHE
    return ExecutionBackend(
        "BLOCKED",
        False,
        f"无合格隔离执行环境（{_DOCKER_PROBE_CACHE.detail}），动态验收阻断；"
        "如需本地开发豁免可设置 PYQ_ACCEPTANCE_ALLOW_HOST=1",
    )


def reset_backend_cache() -> None:
    global _DOCKER_PROBE_CACHE
    _DOCKER_PROBE_CACHE = None


def runtime_fingerprint(backend: str = "") -> str:
    backend = backend or detect_execution_backend().name
    return (
        f"{RUNNER_VERSION} python={platform.python_version()} "
        f"platform={platform.platform()} isolation={backend}"
    )


def _docker_bootstrap() -> str:
    """容器内引导：从只读输入区复制到可写区执行，结果写输出卷。"""
    return (
        "import shutil, subprocess, sys, os\n"
        "shutil.copytree('/input', '/tmp/work')\n"
        "os.chdir('/tmp/work')\n"
        "rc = subprocess.call([sys.executable, '-I', 'harness.py'])\n"
        "if os.path.exists('results.json'):\n"
        "    shutil.copy('results.json', '/output/results.json')\n"
        "sys.exit(rc)\n"
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
    artifact_dir: Optional[Path] = None,
) -> tuple[list[Evidence], list[str]]:
    """在受限环境中执行固定案例，返回 (证据列表, 运行日志)。

    证据只记录观察值；断言评估在父进程由 checks.evaluate_assertion 完成。
    无合格隔离环境时抛出 ExecutionBlocked（调用方按 BLOCKED 处理）。
    artifact_dir 提供时，原始 results.json 保存到稳定任务工件目录（P1）。
    """
    backend = detect_execution_backend()
    if not backend.available:
        raise ExecutionBlocked(backend.detail)

    tmp = Path(tempfile.mkdtemp(prefix="pyq_accept_"))
    results_dir = Path(tempfile.mkdtemp(prefix="pyq_accept_res_"))
    logs: list[str] = [f"backend={backend.name}"]
    evidence: list[Evidence] = []
    fingerprint = runtime_fingerprint(backend.name)
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

        try:
            if backend.name == "DOCKER":
                cmd = [
                    "docker", "run", "--rm",
                    "--network", "none",
                    "--read-only",
                    "--tmpfs", "/tmp:rw,nosuid,size=64m",
                    "--cpus", "1",
                    "--memory", "512m",
                    "--pids-limit", "64",
                    "--security-opt", "no-new-privileges",
                    "--cap-drop", "ALL",
                    "-v", f"{tmp.resolve()}:/input:ro",
                    "-v", f"{results_dir.resolve()}:/output:rw",
                    "-w", "/input",
                    DOCKER_IMAGE,
                    "python", "-I", "-c",
                    _docker_bootstrap(),
                ]
                proc = subprocess.run(
                    cmd, capture_output=True, text=True,
                    timeout=total_timeout_s + DOCKER_TIMEOUT_EXTRA_S,
                )
            else:
                from backend.config import build_sandbox_env

                env = build_sandbox_env(tmp)
                env["PYTHONIOENCODING"] = "utf-8"
                env["PYQ_RESULTS_DIR"] = str(results_dir)
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
        except subprocess.TimeoutExpired:
            # 超时：终止相关进程并清理（子进程已被 subprocess.run 终止），全部案例标 TIMEOUT
            logs.append(f"RUNNER_TIMEOUT after {total_timeout_s}s")
            for case in cases:
                evidence.append(Evidence(
                    kind="EXECUTED_CASE", producer=RUNNER_VERSION,
                    code_hash=code_hash_value, spec_hash=spec_hash_value,
                    plan_hash=plan_hash_value,
                    runtime_fingerprint=fingerprint,
                    case_id=case.case_id, requirement_ids=case.requirement_ids,
                    phase="RUNNER", observation={}, status="TIMEOUT",
                    artifact_refs=[str(artifact_dir / "runner-timeout.log")] if artifact_dir else [],
                ))
            if logs and artifact_dir:
                try:
                    (artifact_dir / "runner-timeout.log").write_text(
                        "\n".join(logs), encoding="utf-8"
                    )
                except OSError:
                    pass
            return evidence, logs

        results_path = results_dir / "results.json"
        if artifact_dir is not None and results_path.exists():
            try:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(results_path, artifact_dir / "evidence-results.json")
            except OSError:
                logs.append("artifact persistence failed")
        protocol_error = False
        raw_results: Any = None
        if not results_path.exists():
            logs.append("results.json missing (corrupted output)")
            protocol_error = True
        else:
            try:
                raw_results = json.loads(results_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                logs.append("results.json is not valid JSON")
                protocol_error = True
            if not isinstance(raw_results, list):
                logs.append("results.json is not a list")
                protocol_error = True

        # 协议校验：case_id 唯一 + 集合与计划一一对应 + 状态白名单（P0-6）
        by_case: dict[str, dict[str, Any]] = {}
        if raw_results is not None:
            seen_ids: set[str] = set()
            for item in raw_results:
                if not isinstance(item, dict) or not isinstance(item.get("case_id"), str):
                    protocol_error = True
                    logs.append("result item invalid (non-dict or bad case_id)")
                    continue
                cid = item["case_id"]
                if cid in seen_ids:
                    protocol_error = True
                    logs.append(f"duplicate case_id in results: {cid}")
                    continue
                seen_ids.add(cid)
                if item.get("status") not in HARNESS_STATUS_WHITELIST:
                    protocol_error = True
                    logs.append(f"unknown harness status: {item.get('status')!r}")
                    continue
                by_case[cid] = item
            expected_ids = {c.case_id for c in cases}
            if seen_ids != expected_ids:
                protocol_error = True
                logs.append(
                    f"protocol mismatch: expected {sorted(expected_ids)} got {sorted(seen_ids)}"
                )

        if protocol_error:
            # 协议异常：全部案例 ENV_ERROR，不得产生虚假 PASS/FAIL（P0-6）
            for case in cases:
                evidence.append(Evidence(
                    kind="EXECUTED_CASE", producer=RUNNER_VERSION,
                    code_hash=code_hash_value, spec_hash=spec_hash_value,
                    plan_hash=plan_hash_value,
                    runtime_fingerprint=fingerprint,
                    case_id=case.case_id, requirement_ids=case.requirement_ids,
                    phase="RUNNER",
                    observation={"protocol_error": "results protocol validation failed"},
                    status="ENV_ERROR",
                    artifact_refs=[str(artifact_dir / "evidence-results.json")] if artifact_dir else [str(results_path)],
                ))
            return evidence, logs

        for case in cases:
            item = by_case[case.case_id]
            if item["status"] == "IMPORT_ERROR":
                status = "ENV_ERROR"
                observation = {
                    "exception_type": item.get("exception_type", "ImportError"),
                    "exception_message": item.get("exception_message", ""),
                }
            else:
                observation = _extract_observation(item)
                if item["status"] == "HARNESS_ERROR":
                    status = "HARNESS_ERROR"
                elif item["status"] == "OK" and (
                    "return_value" not in item
                    and "return_serialization_error" not in item
                ):
                    # 正常返回记录必须含 return_value 或 return_serialization_error；
                    # 两者皆缺 = 协议损坏，不能当作合法 None（P0-6）。
                    # TARGET_EXCEPTION 记录只有异常观察值，不要求 return_value。
                    status = "HARNESS_ERROR"
                    observation["protocol_error"] = "missing return_value field"
                else:
                    check = evaluate_assertion(case.assertion, observation)
                    status = check.status
                    if check.detail:
                        observation["check_detail"] = check.detail
            evidence.append(Evidence(
                kind="EXECUTED_CASE", producer=RUNNER_VERSION,
                code_hash=code_hash_value, spec_hash=spec_hash_value,
                plan_hash=plan_hash_value,
                runtime_fingerprint=fingerprint,
                case_id=case.case_id, requirement_ids=case.requirement_ids,
                phase="ASSERT", observation=observation, status=status,
                artifact_refs=[str(artifact_dir / "evidence-results.json")] if artifact_dir else [str(results_path)],
                duration_ms=item.get("duration_ms"),
            ))
        return evidence, logs
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(results_dir, ignore_errors=True)


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