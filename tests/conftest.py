import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _disable_real_ai(monkeypatch):
    """强制所有测试使用规则降级模式，避免真实 DeepSeek 网络调用，保证测试离线可重复。"""
    from backend.ai import deepseek_client

    monkeypatch.setattr(deepseek_client, "is_available", lambda: False)

    def _no_network(*args, **kwargs):
        raise deepseek_client.DeepSeekError("测试环境已禁用真实 AI 调用")

    monkeypatch.setattr(deepseek_client, "chat", _no_network)
    monkeypatch.setattr(deepseek_client, "chat_json", _no_network)


@pytest.fixture(autouse=True)
def _clean_db():
    """每个测试前清理所有项目，确保测试隔离。"""
    _purge_all_projects()
    yield
    _purge_all_projects()


def _purge_all_projects():
    """清理所有项目及磁盘文件（供需要空数据库状态的测试使用）。"""
    import shutil

    from backend import database
    from backend.config import UPLOAD_DIR

    for p in database.list_projects():
        shutil.rmtree(UPLOAD_DIR / p["id"], ignore_errors=True)
        database.delete_project(p["id"])