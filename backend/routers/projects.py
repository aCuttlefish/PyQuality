import json
import shutil
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend import database
from backend.config import (
    BASE_DIR,
    MAX_DESCRIPTION_LEN,
    MAX_PROJECT_NAME_LEN,
    MAX_SINGLE_FILE_SIZE,
    MAX_UPLOAD_FILES,
    UPLOAD_DIR,
)
from backend.logger import get_logger

logger = get_logger("projects")
router = APIRouter(prefix="/api/projects", tags=["projects"])

ALLOWED_SUFFIXES = {".py", ".txt", ".md", ".cfg", ".toml", ".ini", ".json", ".yaml", ".yml", ".rst", ".pyqualityignore"}
MAX_PROJECT_SIZE = 20 * 1024 * 1024
SAMPLE_DIR = BASE_DIR / "samples" / "demo_project"


@router.post("/sample")
def load_sample():
    if not SAMPLE_DIR.exists():
        raise HTTPException(500, "示例项目不存在")
    pid = uuid.uuid4().hex[:12]
    target_dir = UPLOAD_DIR / pid
    target_dir.mkdir(parents=True, exist_ok=True)
    file_records = []
    for src in sorted(SAMPLE_DIR.rglob("*.py")):
        rel = src.relative_to(SAMPLE_DIR)
        dest = target_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        file_records.append({"rel_path": str(rel).replace("\\", "/"), "size": src.stat().st_size})
    if not file_records:
        raise HTTPException(500, "示例项目无 Python 文件")
    project = database.create_project("示例项目-学生成绩管理", "内置示例，含多种代码坏味供演示", file_records, pid=pid)
    logger.info("加载示例项目 pid=%s", pid)
    return {"ok": True, "project": project, "files": file_records}


@router.post("/upload")
async def upload_project(
    files: list[UploadFile] = File(default_factory=list),
    archive: UploadFile | None = File(default=None),
    name: str = Form(""),
    description: str = Form(""),
):
    project_name = name.strip()
    if len(project_name) > MAX_PROJECT_NAME_LEN:
        raise HTTPException(400, f"项目名称过长（超过 {MAX_PROJECT_NAME_LEN} 字符）")
    if len(description) > MAX_DESCRIPTION_LEN:
        raise HTTPException(400, f"描述过长（超过 {MAX_DESCRIPTION_LEN} 字符）")
    file_records: list[dict] = []

    pid = uuid.uuid4().hex[:12]
    target_dir = UPLOAD_DIR / pid
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        if archive is not None and archive.filename:
            if not archive.filename.lower().endswith(".zip"):
                raise HTTPException(400, "压缩包仅支持 .zip 格式")
            archive_path = target_dir / "_upload.zip"
            total = 0
            with open(archive_path, "wb") as f:
                while chunk := await archive.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_PROJECT_SIZE:
                        raise HTTPException(400, "项目过大（超过 20MB）")
                    f.write(chunk)
            _safe_extract(archive_path, target_dir)
            archive_path.unlink(missing_ok=True)
        elif files:
            if len(files) > MAX_UPLOAD_FILES:
                raise HTTPException(400, f"文件过多（超过 {MAX_UPLOAD_FILES} 个）")
            seen_py = False
            for uf in files:
                if not _allowed(uf.filename):
                    continue
                if uf.filename and uf.filename.endswith(".py"):
                    seen_py = True
                dest = _safe_join(target_dir, uf.filename)
                total = 0
                with open(dest, "wb") as f:
                    while chunk := await uf.read(1024 * 1024):
                        total += len(chunk)
                        if total > MAX_SINGLE_FILE_SIZE:
                            raise HTTPException(400, f"文件 {uf.filename} 过大（超过 {MAX_SINGLE_FILE_SIZE // 1024 // 1024}MB）")
                        f.write(chunk)
            if not seen_py and not any(p.suffix == ".py" for p in target_dir.rglob("*.py")):
                pass
        else:
            raise HTTPException(400, "请上传 .zip 压缩包或至少一个 .py 文件")
    except HTTPException:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(target_dir, ignore_errors=True)
        logger.exception("上传失败")
        raise HTTPException(500, f"上传失败: {e}")

    py_files = _collect_python_files(target_dir)
    if not py_files:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(400, "项目中未找到任何 Python 文件")

    for rel in py_files:
        file_records.append({
            "rel_path": rel.replace("\\", "/"),
            "size": (target_dir / rel).stat().st_size,
        })

    if not project_name:
        project_name = _infer_project_name(archive, files)
    project = database.create_project(project_name, description, file_records, pid=pid)
    return {"ok": True, "project": project, "files": file_records}


@router.get("")
def list_projects():
    projects = database.list_projects()
    for p in projects:
        cached = database.get_analysis(p["id"])
        if cached:
            try:
                result = json.loads(cached)
                rd = result.get("readability", {})
                p["score"] = rd.get("total")
                p["grade"] = rd.get("grade")
            except (json.JSONDecodeError, KeyError):
                pass
    return {"ok": True, "projects": projects}


@router.get("/{pid}")
def get_project(pid: str):
    project = database.get_project(pid)
    if not project:
        raise HTTPException(404, "项目不存在")
    project["files"] = database.list_files(pid)
    return {"ok": True, "project": project}


@router.delete("/{pid}")
def delete_project(pid: str):
    project = database.get_project(pid)
    if not project:
        raise HTTPException(404, "项目不存在")
    shutil.rmtree(UPLOAD_DIR / pid, ignore_errors=True)
    database.delete_project(pid)
    return {"ok": True}


@router.get("/{pid}/file")
def read_file(pid: str, path: str):
    abs_path = database.get_file_abs_path(pid, path)
    if abs_path is None:
        raise HTTPException(404, "文件不存在")
    try:
        content = abs_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(500, f"读取失败: {e}")
    return {"ok": True, "path": path, "content": content}


def _safe_extract(archive_path: Path, target_dir: Path) -> None:
    try:
        with zipfile.ZipFile(archive_path) as zf:
            for member in zf.namelist():
                dest = (target_dir / member).resolve()
                if not str(dest).startswith(str(target_dir.resolve())):
                    raise HTTPException(400, f"压缩包含不安全路径: {member}")
                if member.endswith("/"):
                    continue
                zf.extract(member, target_dir)
    except zipfile.BadZipFile:
        raise HTTPException(400, "无效的 zip 文件")


def _safe_join(base: Path, filename: str) -> Path:
    rel = filename.replace("\\", "/").lstrip("/")
    if ".." in rel.split("/"):
        raise HTTPException(400, f"不安全的文件路径: {filename}")
    dest = (base / rel).resolve()
    if not str(dest).startswith(str(base.resolve())):
        raise HTTPException(400, f"不安全的文件路径: {filename}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def _allowed(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_SUFFIXES


def _collect_python_files(base: Path) -> list[str]:
    excluded = {"__pycache__", ".git", ".venv", "venv", "node_modules", "_generated_tests"}
    result = []
    for p in sorted(base.rglob("*.py")):
        rel = p.relative_to(base)
        if any(part in excluded for part in rel.parts):
            continue
        result.append(str(rel))
    return result


def _infer_project_name(archive, files) -> str:
    if archive and archive.filename:
        return Path(archive.filename).stem
    if files and files[0].filename:
        return Path(files[0].filename).stem + " 等"
    return "未命名项目"