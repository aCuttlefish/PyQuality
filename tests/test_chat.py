import io
import zipfile

from fastapi.testclient import TestClient

from backend import database
from backend.main import app

client = TestClient(app)


def _upload_sample() -> str:
    r = client.post("/api/projects/sample")
    return r.json()["project"]["id"]


def _upload_zip(name: str = "demo.zip", content: dict | None = None) -> str:
    content = content or {"mod.py": "def f(x):\n    return x * 2\n"}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for fn, code in content.items():
            zf.writestr(fn, code)
    buf.seek(0)
    r = client.post("/api/projects/upload", files={"archive": (name, buf, "application/zip")})
    return r.json()["project"]["id"]


def _chat(message: str, pid: str = ""):
    return client.post("/api/chat", json={"message": message, "project_id": pid})


def test_help():
    r = _chat("/help")
    assert r.status_code == 200
    reply = r.json()["reply"]
    assert "命令帮助" in reply
    assert "/analyze" in reply
    assert "/tests" in reply


def test_help_alias_h():
    r = _chat("/h")
    assert r.status_code == 200
    assert "命令帮助" in r.json()["reply"]


def test_projects_empty():
    from tests.conftest import _purge_all_projects
    _purge_all_projects()
    r = _chat("/projects")
    assert r.status_code == 200
    assert "暂无项目" in r.json()["reply"]


def test_projects_with_sample():
    pid = _upload_sample()
    try:
        r = _chat("/projects")
        assert r.status_code == 200
        assert "项目列表" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_use_no_arg():
    r = _chat("/use")
    assert r.status_code == 200
    assert "用法" in r.json()["reply"]


def test_use_not_found():
    r = _chat("/use nonexistent-id")
    assert r.status_code == 200
    assert "不存在" in r.json()["reply"]


def test_use_success():
    pid = _upload_sample()
    try:
        r = _chat(f"/use {pid}")
        assert r.status_code == 200
        body = r.json()
        assert "已切换" in body["reply"]
        assert body["project_id"] == pid
    finally:
        client.delete(f"/api/projects/{pid}")


def test_no_project_selected():
    r = _chat("/analyze")
    assert r.status_code == 200
    assert "请先选择项目" in r.json()["reply"]


def test_project_not_found():
    r = _chat("/analyze", pid="ghost-id")
    assert r.status_code == 200
    assert "不存在" in r.json()["reply"]


def test_files():
    pid = _upload_sample()
    try:
        r = _chat("/files", pid=pid)
        assert r.status_code == 200
        assert "文件列表" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_analyze():
    pid = _upload_sample()
    try:
        r = _chat("/analyze", pid=pid)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "分析完成" in reply
        assert "可读性评分" in reply
    finally:
        client.delete(f"/api/projects/{pid}")


def test_summary():
    pid = _upload_sample()
    try:
        r = _chat("/summary", pid=pid)
        assert r.status_code == 200
        assert "分析完成" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_smells_after_analyze():
    pid = _upload_sample()
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/smells", pid=pid)
        assert r.status_code == 200
        assert "代码坏味" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_smells_without_analyze():
    pid = _upload_sample()
    try:
        r = _chat("/smells", pid=pid)
        assert r.status_code == 200
        assert "尚未分析" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_score():
    pid = _upload_sample()
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/score", pid=pid)
        assert r.status_code == 200
        assert "可读性评分" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_security():
    pid = _upload_sample()
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/security", pid=pid)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "安全问题" in reply or "未发现" in reply
    finally:
        client.delete(f"/api/projects/{pid}")


def test_deps():
    pid = _upload_sample()
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/deps", pid=pid)
        assert r.status_code == 200
        assert "依赖关系" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_unknown_command():
    pid = _upload_sample()
    try:
        r = _chat("/foobar", pid=pid)
        assert r.status_code == 200
        assert "未识别" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_natural_language_analyze():
    pid = _upload_sample()
    try:
        r = _chat("帮我分析一下", pid=pid)
        assert r.status_code == 200
        assert "分析完成" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_natural_language_smells():
    pid = _upload_sample()
    try:
        _chat("/analyze", pid=pid)
        r = _chat("有什么坏味", pid=pid)
        assert r.status_code == 200
        assert "代码坏味" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_natural_language_help():
    r = _chat("帮助")
    assert r.status_code == 200
    assert "命令帮助" in r.json()["reply"]


def test_natural_language_projects():
    from tests.conftest import _purge_all_projects
    _purge_all_projects()
    r = _chat("看看项目")
    assert r.status_code == 200
    assert "暂无项目" in r.json()["reply"]


def test_export_markdown():
    pid = _upload_sample()
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/export markdown", pid=pid)
        assert r.status_code == 200
        assert "报告" in r.json()["reply"] or "导出" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")

def test_analyze_all_empty():
    from tests.conftest import _purge_all_projects
    _purge_all_projects()
    r = _chat("/analyze all")
    assert r.status_code == 200
    assert "暂无项目" in r.json()["reply"]


def test_analyze_all_with_projects():
    from tests.conftest import _purge_all_projects
    pid1 = _upload_sample()
    pid2 = _upload_zip("clean.zip", {"clean.py": "def add(a, b):\n    return a + b\n"})
    try:
        r = _chat("/analyze all")
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "批量分析" in reply
        assert "健康度排名" in reply
    finally:
        client.delete(f"/api/projects/{pid1}")
        client.delete(f"/api/projects/{pid2}")


def test_compare_no_arg_shows_list():
    pid1 = _upload_sample()
    pid2 = _upload_zip("clean.zip", {"clean.py": "def add(a, b):\n    return a + b\n"})
    try:
        r = _chat("/compare", pid=pid1)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "选择项目" in reply or "对比" in reply
    finally:
        client.delete(f"/api/projects/{pid1}")
        client.delete(f"/api/projects/{pid2}")


def test_compare_two_projects():
    pid1 = _upload_sample()
    pid2 = _upload_zip("clean.zip", {"clean.py": "def add(a, b):\n    return a + b\n"})
    try:
        _chat("/analyze", pid=pid1)
        _chat("/analyze", pid=pid2)
        r = _chat(f"/compare {pid2}", pid=pid1)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "项目对比" in reply
        assert "综合评价" in reply
    finally:
        client.delete(f"/api/projects/{pid1}")
        client.delete(f"/api/projects/{pid2}")


def test_compare_self():
    pid = _upload_sample()
    try:
        r = _chat(f"/compare {pid}", pid=pid)
        assert r.status_code == 200
        assert "不能与自身" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_compare_nonexistent():
    pid = _upload_sample()
    try:
        r = _chat("/compare nonexistent123", pid=pid)
        assert r.status_code == 200
        assert "不存在" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_history_trend_chart():
    pid = _upload_sample()
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/history", pid=pid)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "历史趋势" in reply
        assert "▁" in reply or "█" in reply
    finally:
        client.delete(f"/api/projects/{pid}")


def test_score_shows_health():
    pid = _upload_sample()
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/score", pid=pid)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "健康度" in reply
        assert "计算方式" in reply
    finally:
        client.delete(f"/api/projects/{pid}")


def test_natural_language_compare():
    pid1 = _upload_sample()
    pid2 = _upload_zip("clean.zip", {"clean.py": "def add(a, b):\n    return a + b\n"})
    try:
        r = _chat("对比", pid=pid1)
        assert r.status_code == 200
        assert "选择项目" in r.json()["reply"] or "对比" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid1}")
        client.delete(f"/api/projects/{pid2}")

def test_snippet_basic():
    r = _chat("/snippet def foo():\n    return 42")
    assert r.status_code == 200
    data = r.json()
    assert "分析完成" in data["reply"]
    assert data["project_id"] != ""
    client.delete(f"/api/projects/{data['project_id']}")


def test_snippet_no_code():
    r = _chat("/snippet")
    assert r.status_code == 200
    assert "用法" in r.json()["reply"]


def test_snippet_with_smells():
    code = "def f(x):\n    if x:\n        if x:\n            if x:\n                return True\n    return False"
    r = _chat(f"/snippet {code}")
    assert r.status_code == 200
    data = r.json()
    assert "分析完成" in data["reply"]
    client.delete(f"/api/projects/{data['project_id']}")


def test_dashboard_empty():
    from tests.conftest import _purge_all_projects
    _purge_all_projects()
    r = _chat("/dashboard")
    assert r.status_code == 200
    assert "暂无项目" in r.json()["reply"]


def test_dashboard_with_projects():
    from tests.conftest import _purge_all_projects
    pid1 = _upload_sample()
    pid2 = _upload_zip("clean.zip", {"clean.py": "def add(a, b):\n    return a + b\n"})
    try:
        _chat("/analyze", pid=pid1)
        _chat("/analyze", pid=pid2)
        r = _chat("/dashboard")
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "仪表盘" in reply
        assert "等级分布" in reply
    finally:
        client.delete(f"/api/projects/{pid1}")
        client.delete(f"/api/projects/{pid2}")

def test_projects_search():
    from tests.conftest import _purge_all_projects
    pid1 = _upload_sample()
    pid2 = _upload_zip("clean.zip", {"clean.py": "def add(a, b):\n    return a + b\n"})
    try:
        r = _chat("/projects 示例")
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "示例" in reply
        assert "搜索" in reply
    finally:
        client.delete(f"/api/projects/{pid1}")
        client.delete(f"/api/projects/{pid2}")


def test_projects_search_no_match():
    pid = _upload_sample()
    try:
        r = _chat("/projects 不存在的项目名xyz")
        assert r.status_code == 200
        assert "未找到" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_config_set():
    from backend import config
    r = _chat("/config set long_params 8")
    assert r.status_code == 200
    reply = r.json()["reply"]
    assert "已设置" in reply
    assert config.SMELL_THRESHOLDS["long_params"] == 8
    config.SMELL_THRESHOLDS["long_params"] = 5
    if config.CONFIG_FILE.exists():
        config.CONFIG_FILE.unlink()


def test_config_set_unknown_key():
    r = _chat("/config set unknown_key 123")
    assert r.status_code == 200
    assert "未知" in r.json()["reply"]


def test_config_set_invalid_value():
    r = _chat("/config set long_params abc")
    assert r.status_code == 200
    assert "无法" in r.json()["reply"]


def test_config_reset():
    from backend import config
    config.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.CONFIG_FILE.write_text('{"smell_thresholds": {"long_params": 99}}', encoding="utf-8")
    r = _chat("/config reset")
    assert r.status_code == 200
    assert "恢复" in r.json()["reply"]
    assert not config.CONFIG_FILE.exists()

def test_smart_recommendations_with_smells():
    pid = _upload_sample()
    try:
        r = _chat("/analyze", pid=pid)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "智能推荐" in reply
    finally:
        client.delete(f"/api/projects/{pid}")


def test_smart_recommendations_clean_code():
    pid = _upload_zip("clean.zip", {"clean.py": "def add(a: int, b: int) -> int:\n    \"\"\"Add two numbers.\"\"\"\n    return a + b\n"})
    try:
        r = _chat("/analyze", pid=pid)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "智能推荐" in reply
        assert "良好" in reply
    finally:
        client.delete(f"/api/projects/{pid}")


def test_summary_has_recommendations():
    pid = _upload_sample()
    try:
        r = _chat("/summary", pid=pid)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "智能推荐" in reply
    finally:
        client.delete(f"/api/projects/{pid}")

def test_funcs_heatmap():
    pid = _upload_sample()
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/funcs", pid=pid)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "热力图" in reply
        assert "分布" in reply
    finally:
        client.delete(f"/api/projects/{pid}")


def test_smells_sorted_with_stats():
    pid = _upload_sample()
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/smells", pid=pid)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "严重度分布" in reply
        assert "坏味类型" in reply
    finally:
        client.delete(f"/api/projects/{pid}")

def test_fix_all_no_analysis():
    pid = _upload_sample()
    try:
        r = _chat("/fix all", pid=pid)
        assert r.status_code == 200
        assert "尚未分析" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_fix_all_no_smells():
    pid = _upload_zip("clean.zip", {"clean.py": "def add(a: int, b: int) -> int:\n    \"\"\"Add.\"\"\"\n    return a + b\n"})
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/fix all", pid=pid)
        assert r.status_code == 200
        assert "无需修复" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_fix_all_with_smells():
    pid = _upload_sample()
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/fix all", pid=pid)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "批量" in reply
        assert "汇总" in reply
    finally:
        client.delete(f"/api/projects/{pid}")

def test_tests_all():
    pid = _upload_sample()
    try:
        r = _chat("/tests all", pid=pid)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "批量" in reply
        assert "汇总" in reply
    finally:
        client.delete(f"/api/projects/{pid}")

def test_advice_all():
    pid = _upload_sample()
    try:
        r = _chat("/advice all", pid=pid)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "批量" in reply
        assert "汇总" in reply
    finally:
        client.delete(f"/api/projects/{pid}")


def test_history_trend_alert():
    pid = _upload_sample()
    try:
        _chat("/analyze", pid=pid)
        _chat("/analyze", pid=pid)
        r = _chat("/history", pid=pid)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "趋势" in reply
    finally:
        client.delete(f"/api/projects/{pid}")

def test_rename():
    pid = _upload_sample()
    try:
        r = _chat("/rename 我的新项目", pid=pid)
        assert r.status_code == 200
        assert "重命名" in r.json()["reply"]
        project = database.get_project(pid)
        assert project["name"] == "我的新项目"
    finally:
        client.delete(f"/api/projects/{pid}")


def test_rename_no_arg():
    pid = _upload_sample()
    try:
        r = _chat("/rename", pid=pid)
        assert r.status_code == 200
        assert "用法" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_delete_confirm():
    pid = _upload_sample()
    r = _chat("/delete confirm", pid=pid)
    assert r.status_code == 200
    assert "已删除" in r.json()["reply"]
    assert r.json()["project_id"] == ""


def test_delete_needs_confirm():
    pid = _upload_sample()
    try:
        r = _chat("/delete", pid=pid)
        assert r.status_code == 200
        assert "确认" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")

def test_cicd_github():
    r = _chat("/cicd github")
    assert r.status_code == 200
    reply = r.json()["reply"]
    assert "GitHub Actions" in reply
    assert "quality.yml" in reply
    assert "sarif" in reply


def test_cicd_gitlab():
    r = _chat("/cicd gitlab")
    assert r.status_code == 200
    reply = r.json()["reply"]
    assert "GitLab" in reply
    assert "gitlab-ci.yml" in reply


def test_cicd_default():
    r = _chat("/cicd")
    assert r.status_code == 200
    assert "GitHub Actions" in r.json()["reply"]


def test_cicd_invalid():
    r = _chat("/cicd invalid")
    assert r.status_code == 200
    assert "格式" in r.json()["reply"]

def test_tree():
    pid = _upload_sample()
    try:
        r = _chat("/tree", pid=pid)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "文件树" in reply
        assert "└" in reply or "├" in reply
    finally:
        client.delete(f"/api/projects/{pid}")


def test_ignore_empty():
    pid = _upload_sample()
    try:
        r = _chat("/ignore", pid=pid)
        assert r.status_code == 200
        assert "忽略规则" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_ignore_add_and_del():
    pid = _upload_sample()
    try:
        r = _chat("/ignore add tests/*", pid=pid)
        assert r.status_code == 200
        assert "已添加" in r.json()["reply"]
        r = _chat("/ignore", pid=pid)
        assert "tests/*" in r.json()["reply"]
        r = _chat("/ignore del tests/*", pid=pid)
        assert r.status_code == 200
        assert "已删除" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")

def test_search():
    pid = _upload_sample()
    try:
        r = _chat("/search def", pid=pid)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "搜索" in reply
        assert "匹配" in reply
    finally:
        client.delete(f"/api/projects/{pid}")


def test_search_no_arg():
    pid = _upload_sample()
    try:
        r = _chat("/search", pid=pid)
        assert r.status_code == 200
        assert "用法" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_search_no_match():
    pid = _upload_sample()
    try:
        r = _chat("/search xyzzy_nonexistent_token", pid=pid)
        assert r.status_code == 200
        assert "未找到" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")

def test_doc():
    pid = _upload_sample()
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/doc", pid=pid)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "文档覆盖" in reply
    finally:
        client.delete(f"/api/projects/{pid}")


def test_doc_clean():
    pid = _upload_zip("clean.zip", {"clean.py": '"""Module."""\n\n\ndef add(a: int, b: int) -> int:\n    """Add two numbers."""\n    return a + b\n'})
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/doc", pid=pid)
        assert r.status_code == 200
        assert "都有" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_refactor():
    pid = _upload_sample()
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/refactor", pid=pid)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "重构" in reply
    finally:
        client.delete(f"/api/projects/{pid}")


def test_refactor_clean():
    pid = _upload_zip("clean.zip", {"clean.py": '"""Module."""\n\n\ndef add(a: int, b: int) -> int:\n    """Add two numbers."""\n    return a + b\n'})
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/refactor", pid=pid)
        assert r.status_code == 200
        assert "良好" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")

def test_type_hints():
    pid = _upload_sample()
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/type", pid=pid)
        assert r.status_code == 200
        assert "类型注解" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_type_hints_clean():
    pid = _upload_zip("clean.zip", {"clean.py": '"""Module."""\n\n\ndef add(a: int, b: int) -> int:\n    """Add two numbers."""\n    return a + b\n'})
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/type", pid=pid)
        assert r.status_code == 200
        assert "都有" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")


def test_dup():
    pid = _upload_sample()
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/dup", pid=pid)
        assert r.status_code == 200
        assert "重复" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")

def test_perf():
    pid = _upload_sample()
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/perf", pid=pid)
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "性能" in reply
    finally:
        client.delete(f"/api/projects/{pid}")


def test_perf_clean():
    pid = _upload_zip("clean.zip", {"clean.py": '"""Module."""\n\n\ndef add(a: int, b: int) -> int:\n    """Add two numbers."""\n    return a + b\n'})
    try:
        _chat("/analyze", pid=pid)
        r = _chat("/perf", pid=pid)
        assert r.status_code == 200
        assert "未检测到" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")
