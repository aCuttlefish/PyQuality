import io
import zipfile

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def _make_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("demo/math_utils.py", '"""数学工具"""\n\ndef add(a, b):\n    """加法"""\n    return a + b\n')
        zf.writestr("demo/text_utils.py", "import os\n\n\ndef shout(s):\n    return s.upper()\n")
    buf.seek(0)
    return buf


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_upload_zip_and_full_flow():
    buf = _make_zip()
    r = client.post(
        "/api/projects/upload",
        data={"name": "测试项目", "description": "e2e"},
        files={"archive": ("demo.zip", buf, "application/zip")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    pid = body["project"]["id"]
    assert body["project"]["file_count"] == 2

    r = client.get("/api/projects")
    assert any(p["id"] == pid for p in r.json()["projects"])

    r = client.post(f"/api/projects/{pid}/analyze")
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["stats"]["total_files"] == 2
    assert result["readability"]["total"] > 0
    assert isinstance(result["smells"], list)

    r = client.get(f"/api/projects/{pid}/analysis")
    assert r.status_code == 200
    assert r.json()["result"] is not None

    r = client.get(f"/api/projects/{pid}/file", params={"path": "demo/math_utils.py"})
    assert r.status_code == 200
    assert "add" in r.json()["content"]

    r = client.get(f"/api/projects/{pid}/file", params={"path": "../etc/passwd"})
    assert r.status_code == 404

    r = client.post(f"/api/projects/{pid}/generate-tests", json={"file": "demo/math_utils.py"})
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r = client.post(f"/api/projects/{pid}/advice", json={"file": "demo/text_utils.py"})
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r = client.delete(f"/api/projects/{pid}")
    assert r.status_code == 200
    r = client.get(f"/api/projects/{pid}")
    assert r.status_code == 404


def test_upload_path_traversal_blocked():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.py", "print('evil')")
    buf.seek(0)
    r = client.post(
        "/api/projects/upload",
        files={"archive": ("evil.zip", buf, "application/zip")},
    )
    assert r.status_code == 400


def test_upload_rejects_empty():
    r = client.post("/api/projects/upload")
    assert r.status_code == 400


def test_generate_tests_missing_file():
    buf = _make_zip()
    r = client.post(
        "/api/projects/upload",
        files={"archive": ("demo2.zip", buf, "application/zip")},
    )
    pid = r.json()["project"]["id"]
    r = client.post(f"/api/projects/{pid}/generate-tests", json={"file": "nope.py"})
    assert r.status_code == 400
    client.delete(f"/api/projects/{pid}")

def test_load_sample():
    r = client.post("/api/projects/sample")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["project"]["file_count"] >= 1
    pid = body["project"]["id"]
    r2 = client.post(f"/api/projects/{pid}/analyze")
    assert r2.status_code == 200
    result = r2.json()["result"]
    assert "security" in result
    assert "dependencies" in result
    assert "functions" in result
    assert isinstance(result["security"], list)
    assert "stats" in result["dependencies"]
    client.delete(f"/api/projects/{pid}")


def test_analyze_includes_security_and_deps():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mod.py", "import pickle\n\ndef f(x):\n    return eval(x)\n")
    buf.seek(0)
    r = client.post("/api/projects/upload", files={"archive": ("s.zip", buf, "application/zip")})
    pid = r.json()["project"]["id"]
    r = client.post(f"/api/projects/{pid}/analyze")
    result = r.json()["result"]
    assert len(result["security"]) >= 2
    assert result["dependencies"]["stats"]["module_count"] >= 1
    assert len(result["functions"]) >= 1
    client.delete(f"/api/projects/{pid}")


def test_export_report_markdown():
    r = client.post("/api/projects/sample")
    pid = r.json()["project"]["id"]
    client.post(f"/api/projects/{pid}/analyze")
    r = client.get(f"/api/projects/{pid}/report?format=markdown")
    assert r.status_code == 200
    assert "代码质量报告" in r.text
    client.delete(f"/api/projects/{pid}")


def test_export_report_json():
    r = client.post("/api/projects/sample")
    pid = r.json()["project"]["id"]
    client.post(f"/api/projects/{pid}/analyze")
    r = client.get(f"/api/projects/{pid}/report?format=json")
    assert r.status_code == 200
    data = r.json()
    assert "readability" in data
    client.delete(f"/api/projects/{pid}")


def test_export_report_without_analysis():
    r = client.post("/api/projects/sample")
    pid = r.json()["project"]["id"]
    r = client.get(f"/api/projects/{pid}/report")
    assert r.status_code == 400
    client.delete(f"/api/projects/{pid}")


def test_analyze_single_file():
    r = client.post("/api/projects/sample")
    pid = r.json()["project"]["id"]
    r = client.post(f"/api/projects/{pid}/analyze-file", json={"file": "grades.py"})
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["stats"]["total_files"] == 1
    client.delete(f"/api/projects/{pid}")


def test_fix_endpoint_preview():
    r = client.post("/api/projects/sample")
    pid = r.json()["project"]["id"]
    client.post(f"/api/projects/{pid}/analyze")
    r = client.post(f"/api/projects/{pid}/fix", json={"file": "grades.py", "apply": False})
    assert r.status_code == 200
    body = r.json()
    assert "fixed_code" in body
    assert "validation" in body
    client.delete(f"/api/projects/{pid}")


def test_input_validation_long_name():
    long_name = "x" * 100
    buf = _make_zip()
    r = client.post(
        "/api/projects/upload",
        data={"name": long_name},
        files={"archive": ("n.zip", buf, "application/zip")},
    )
    assert r.status_code == 400


def test_run_tests_summary_parsed():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("t.py", "def add(a, b):\n    return a + b\n")
    buf.seek(0)
    r = client.post("/api/projects/upload", files={"archive": ("t.zip", buf, "application/zip")})
    pid = r.json()["project"]["id"]
    client.post(f"/api/projects/{pid}/generate-tests", json={"file": "t.py"})
    r = client.post(f"/api/projects/{pid}/run-tests", json={})
    assert r.status_code == 200
    body = r.json()
    assert "passed" in body and "failed" in body
    client.delete(f"/api/projects/{pid}")

def test_export_report_sarif():
    r = client.post("/api/projects/sample")
    pid = r.json()["project"]["id"]
    client.post(f"/api/projects/{pid}/analyze")
    r = client.get(f"/api/projects/{pid}/report?format=sarif")
    assert r.status_code == 200
    data = r.json()
    assert data["version"] == "2.1.0"
    assert data["runs"][0]["tool"]["driver"]["name"] == "PyQuality"
    assert isinstance(data["runs"][0]["results"], list)
    client.delete(f"/api/projects/{pid}")


def test_export_report_html():
    r = client.post("/api/projects/sample")
    pid = r.json()["project"]["id"]
    client.post(f"/api/projects/{pid}/analyze")
    r = client.get(f"/api/projects/{pid}/report?format=html")
    assert r.status_code == 200
    assert "<html" in r.text
    assert "代码质量报告" in r.text
    client.delete(f"/api/projects/{pid}")


def test_analyze_includes_dead_code():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("m.py", "def unused():\n    pass\n")
    buf.seek(0)
    r = client.post("/api/projects/upload", files={"archive": ("dc.zip", buf, "application/zip")})
    pid = r.json()["project"]["id"]
    r = client.post(f"/api/projects/{pid}/analyze")
    result = r.json()["result"]
    assert "dead_code" in result
    names = [d["name"] for d in result["dead_code"]["dead_code"]]
    assert "unused" in names
    client.delete(f"/api/projects/{pid}")

def test_config_get_and_update():
    from backend import config
    orig_st = dict(config.SMELL_THRESHOLDS)
    try:
        r = client.get("/api/config")
        assert r.status_code == 200
        assert "smell_thresholds" in r.json()
        r = client.put("/api/config", json={"smell_thresholds": {"long_function_lines": 10}})
        assert r.status_code == 200
        assert r.json()["config"]["smell_thresholds"]["long_function_lines"] == 10
        assert config.SMELL_THRESHOLDS["long_function_lines"] == 10
    finally:
        config.SMELL_THRESHOLDS.update(orig_st)
        if config.CONFIG_FILE.exists():
            config.CONFIG_FILE.unlink()


def test_config_rejects_unknown_key():
    r = client.put("/api/config", json={"smell_thresholds": {"nope": 1}})
    assert r.status_code == 400

def test_analysis_history():
    r = client.post("/api/projects/sample")
    pid = r.json()["project"]["id"]
    client.post(f"/api/projects/{pid}/analyze")
    client.post(f"/api/projects/{pid}/analyze")
    r = client.get(f"/api/projects/{pid}/history")
    assert r.status_code == 200
    history = r.json()["history"]
    assert len(history) >= 2
    assert "readability_total" in history[0]["summary"]
    client.delete(f"/api/projects/{pid}")

def test_pyqualityignore_skips_files():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("keep.py", "def used():\n    pass\n")
        zf.writestr("skip.py", "def unused():\n    pass\n")
        zf.writestr(".pyqualityignore", "skip.py\n")
    buf.seek(0)
    r = client.post("/api/projects/upload", files={"archive": ("ig.zip", buf, "application/zip")})
    pid = r.json()["project"]["id"]
    r = client.post(f"/api/projects/{pid}/analyze")
    result = r.json()["result"]
    assert result["stats"]["total_files"] == 1
    files_analyzed = {f["file"] for f in result["functions"]} | {s["file"] for s in result["smells"]}
    assert not any("skip.py" in f for f in files_analyzed)
    client.delete(f"/api/projects/{pid}")

def test_chat_help_and_sample():
    r = client.post("/api/chat", json={"message": "/help", "project_id": ""})
    assert r.status_code == 200
    assert "命令帮助" in r.json()["reply"]
    r = client.post("/api/chat", json={"message": "/sample", "project_id": ""})
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"]
    pid = body["project_id"]
    client.delete(f"/api/projects/{pid}")


def test_chat_analyze_and_new_commands():
    r = client.post("/api/chat", json={"message": "/sample", "project_id": ""})
    pid = r.json()["project_id"]
    try:
        r = client.post("/api/chat", json={"message": "/analyze", "project_id": pid})
        assert "分析完成" in r.json()["reply"]
        r = client.post("/api/chat", json={"message": "/deadcode", "project_id": pid})
        assert "死代码" in r.json()["reply"]
        r = client.post("/api/chat", json={"message": "/config", "project_id": pid})
        assert "阈值" in r.json()["reply"]
        r = client.post("/api/chat", json={"message": "/history", "project_id": pid})
        assert "历史" in r.json()["reply"]
        r = client.post("/api/chat", json={"message": "/export sarif", "project_id": pid})
        assert "sarif" in r.json()["reply"]
    finally:
        client.delete(f"/api/projects/{pid}")