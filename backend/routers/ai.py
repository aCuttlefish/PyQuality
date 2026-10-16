import os
import re
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import database
from backend.ai import advisor, deepseek_client, fixer, test_generator
from backend.config import TEST_SANDBOX, UPLOAD_DIR
from backend.errors import AIUnavailableError, AppError
from backend.logger import get_logger

logger = get_logger("ai")
router = APIRouter(prefix="/api", tags=["ai"])


class GenerateRequest(BaseModel):
    file: str
    functions: list[str] = []


class AdviceBody(BaseModel):
    file: str


class FixBody(BaseModel):
    file: str
    apply: bool = False
    candidate_id: str = ""


class RunBody(BaseModel):
    test_file: str = ""


@router.get("/ai/status")
def ai_status():
    return {
        "ok": True,
        "available": deepseek_client.is_available(),
        "model": "deepseek-chat",
    }


@router.post("/projects/{pid}/generate-tests")
def generate_tests(pid: str, body: GenerateRequest):
    if not database.get_project(pid):
        raise HTTPException(404, "项目不存在")
    if not body.file.endswith(".py"):
        raise HTTPException(400, "仅支持对 .py 文件生成测试")
    project_dir = UPLOAD_DIR / pid
    try:
        result = test_generator.generate_tests(project_dir, body.file, body.functions)
    except Exception as e:
        logger.exception("测试生成异常 pid=%s", pid)
        raise HTTPException(500, f"生成失败: {e}")
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "生成失败"))
    return result


@router.get("/projects/{pid}/generated-tests")
def list_generated_tests(pid: str):
    project_dir = UPLOAD_DIR / pid
    out_dir = project_dir / "_generated_tests"
    if not out_dir.exists():
        return {"ok": True, "tests": []}
    tests = [
        {"file": f"_generated_tests/{p.name}", "size": p.stat().st_size}
        for p in sorted(out_dir.glob("test_*.py"))
    ]
    return {"ok": True, "tests": tests}


@router.post("/projects/{pid}/run-tests")
def run_tests(pid: str, body: RunBody):
    project_dir = (UPLOAD_DIR / pid).resolve()
    if not project_dir.exists():
        raise HTTPException(404, "项目不存在")
    out_dir = project_dir / "_generated_tests"
    if body.test_file:
        target = (project_dir / body.test_file).resolve()
        try:
            target.relative_to(project_dir)
        except ValueError:
            raise HTTPException(404, "测试文件不存在")
        if not target.exists():
            raise HTTPException(404, "测试文件不存在")
    else:
        if not out_dir.exists() or not list(out_dir.glob("test_*.py")):
            return {"ok": True, "ran": False, "message": "还没有生成的测试文件"}
        target = out_dir

    sandbox_env = {k: v for k, v in os.environ.items() if k not in TEST_SANDBOX["env_block"]}
    cmd = [sys.executable, "-m", "pytest", str(target), "-v"] + TEST_SANDBOX["extra_args"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=TEST_SANDBOX["timeout"],
            encoding="utf-8",
            errors="replace",
            env=sandbox_env,
        )
        output = (proc.stdout + "\n" + proc.stderr)[-8000:]
        passed, failed = _parse_summary(proc.stdout)
        return {
            "ok": True, "ran": True, "exit_code": proc.returncode,
            "output": output, "passed": passed, "failed": failed,
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(504, f"测试执行超时（{TEST_SANDBOX['timeout']} 秒）")
    except Exception as e:
        logger.exception("运行测试异常 pid=%s", pid)
        raise HTTPException(500, f"运行失败: {e}")


@router.post("/projects/{pid}/advice")
def get_advice(pid: str, body: AdviceBody):
    if not database.get_project(pid):
        raise HTTPException(404, "项目不存在")
    analysis = database.get_analysis(pid)
    abs_path = database.get_file_abs_path(pid, body.file)
    if abs_path is None:
        raise HTTPException(404, "文件不存在")
    source = abs_path.read_text(encoding="utf-8", errors="replace")
    smells = []
    if analysis:
        import json
        smells = json.loads(analysis).get("smells", [])
    try:
        return advisor.generate_advice(body.file, source, smells)
    except Exception as e:
        logger.exception("建议生成异常 pid=%s", pid)
        raise HTTPException(500, f"生成建议失败: {e}")


@router.post("/projects/{pid}/fix")
def fix_file(pid: str, body: FixBody):
    project = database.get_project(pid)
    if not project:
        raise HTTPException(404, "项目不存在")
    abs_path = database.get_file_abs_path(pid, body.file)
    if abs_path is None:
        raise HTTPException(404, "文件不存在")
    source = abs_path.read_text(encoding="utf-8", errors="replace")

    if body.apply:
        if not body.candidate_id:
            raise HTTPException(400, "请先预览修复再应用，需要提供 candidate_id")
        cached = fixer.get_candidate(body.candidate_id, source)
        if not cached:
            raise HTTPException(400, "候选已过期或源文件已变化，请重新预览修复")
        result = dict(cached["result"])
        validation = cached["validation"]
        result["validation"] = validation
        if validation.get("valid"):
            backup = abs_path.with_suffix(abs_path.suffix + ".bak")
            backup.write_text(source, encoding="utf-8")
            abs_path.write_text(cached["fixed_code"], encoding="utf-8")
            result["applied"] = True
            result["backup"] = str(backup.relative_to(UPLOAD_DIR / pid))
            logger.info("已应用修复 pid=%s file=%s", pid, body.file)
        return result

    analysis = database.get_analysis(pid)
    smells = []
    if analysis:
        import json
        smells = json.loads(analysis).get("smells", [])
    try:
        result = fixer.fix_code(body.file, source, smells)
    except Exception as e:
        logger.exception("AI 修复异常 pid=%s", pid)
        raise HTTPException(500, f"修复失败: {e}")

    if result.get("ok") and result.get("fixed_code"):
        validation = fixer.validate_fixed(source, result["fixed_code"])
        result["validation"] = validation
        result["candidate_id"] = fixer.save_candidate(source, result["fixed_code"], validation, result)
    return result


def _parse_summary(stdout: str) -> tuple[int, int]:
    passed = failed = 0
    for line in stdout.splitlines():
        m_passed = re.search(r"(\d+)\s+passed", line)
        m_failed = re.search(r"(\d+)\s+failed", line)
        if m_passed:
            passed = int(m_passed.group(1))
        if m_failed:
            failed = int(m_failed.group(1))
    return passed, failed
