import pytest
from fastapi.testclient import TestClient

from backend import database
from backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_project():
    import uuid
    from backend.config import UPLOAD_DIR

    pid = uuid.uuid4().hex[:12]
    target = UPLOAD_DIR / pid
    target.mkdir(parents=True, exist_ok=True)
    (target / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    records = [{"rel_path": "calc.py", "size": 30}]
    project = database.create_project("test-session-proj", "test", records, pid=pid)
    yield pid
    import shutil
    shutil.rmtree(target, ignore_errors=True)
    database.delete_project(pid)


class TestSessionDatabase:
    def test_create_session(self):
        s = database.create_session("", "测试会话")
        assert s["id"]
        assert s["title"] == "测试会话"
        assert s["project_id"] == ""

    def test_create_session_with_project(self, sample_project):
        s = database.create_session(sample_project, "项目会话")
        assert s["project_id"] == sample_project

    def test_list_sessions_by_project(self, sample_project):
        database.create_session(sample_project, "s1")
        database.create_session(sample_project, "s2")
        database.create_session("", "s3")
        sessions = database.list_sessions(sample_project)
        assert len(sessions) == 2
        titles = {s["title"] for s in sessions}
        assert titles == {"s1", "s2"}

    def test_list_all_sessions(self, sample_project):
        database.create_session(sample_project, "s1")
        database.create_session("", "s2")
        sessions = database.list_sessions()
        assert len(sessions) >= 2

    def test_get_session(self):
        s = database.create_session("", "test")
        got = database.get_session(s["id"])
        assert got is not None
        assert got["title"] == "test"

    def test_get_session_not_found(self):
        assert database.get_session("nonexistent") is None

    def test_delete_session(self):
        s = database.create_session("", "test")
        assert database.delete_session(s["id"]) is True
        assert database.get_session(s["id"]) is None

    def test_delete_session_not_found(self):
        assert database.delete_session("nonexistent") is False

    def test_update_session_title(self):
        s = database.create_session("", "old")
        assert database.update_session(s["id"], "new") is True
        got = database.get_session(s["id"])
        assert got["title"] == "new"

    def test_add_and_list_messages(self):
        s = database.create_session("", "test")
        database.add_message(s["id"], "user", "你好")
        database.add_message(s["id"], "ai", "你好，有什么可以帮你？")
        msgs = database.list_messages(s["id"])
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "你好"
        assert msgs[1]["role"] == "ai"

    def test_delete_session_cascades_messages(self):
        s = database.create_session("", "test")
        database.add_message(s["id"], "user", "msg1")
        database.add_message(s["id"], "ai", "msg2")
        database.delete_session(s["id"])
        assert database.list_messages(s["id"]) == []


class TestAnalysisSnapshot:
    def test_save_and_get_snapshot(self, sample_project):
        summary = {"smell_count": 3, "readability_total": 75.0}
        result = {"stats": {"total_files": 1}, "smells": [{"type": "test"}]}
        database.save_analysis_snapshot(sample_project, summary, result)
        history = database.list_analysis_history(sample_project)
        assert len(history) == 1
        snapshot_id = history[0]["id"]
        snapshot = database.get_analysis_snapshot(snapshot_id)
        assert snapshot is not None
        assert snapshot["result"] is not None
        assert snapshot["result"]["stats"]["total_files"] == 1
        assert snapshot["summary"]["smell_count"] == 3

    def test_get_snapshot_not_found(self):
        assert database.get_analysis_snapshot(99999) is None


class TestSessionAPI:
    def test_create_session_api(self, client):
        r = client.post("/api/sessions", json={"project_id": "", "title": "API会话"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["session"]["title"] == "API会话"

    def test_list_sessions_api(self, client, sample_project):
        client.post("/api/sessions", json={"project_id": sample_project, "title": "s1"})
        r = client.get(f"/api/sessions?project_id={sample_project}")
        assert r.status_code == 200
        sessions = r.json()["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["title"] == "s1"

    def test_get_messages_api(self, client):
        r = client.post("/api/sessions", json={"project_id": "", "title": "test"})
        sid = r.json()["session"]["id"]
        database.add_message(sid, "user", "hello")
        database.add_message(sid, "ai", "hi there")
        r = client.get(f"/api/sessions/{sid}/messages")
        assert r.status_code == 200
        data = r.json()
        assert data["session"]["id"] == sid
        assert len(data["messages"]) == 2

    def test_delete_session_api(self, client):
        r = client.post("/api/sessions", json={"project_id": "", "title": "test"})
        sid = r.json()["session"]["id"]
        r = client.delete(f"/api/sessions/{sid}")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_delete_session_not_found_api(self, client):
        r = client.delete("/api/sessions/nonexistent")
        assert r.status_code == 404

    def test_update_session_api(self, client):
        r = client.post("/api/sessions", json={"project_id": "", "title": "old"})
        sid = r.json()["session"]["id"]
        r = client.put(f"/api/sessions/{sid}", json={"project_id": "", "title": "new"})
        assert r.status_code == 200
        assert r.json()["ok"] is True


class TestChatWithSession:
    def test_chat_persists_messages(self, client, sample_project):
        r = client.post("/api/sessions", json={"project_id": sample_project, "title": "test"})
        sid = r.json()["session"]["id"]
        r = client.post("/api/chat", json={
            "message": "/help", "project_id": sample_project, "session_id": sid
        })
        assert r.status_code == 200
        assert r.json()["session_id"] == sid
        msgs = database.list_messages(sid)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "/help"
        assert msgs[1]["role"] == "ai"

    def test_chat_sessions_command(self, client, sample_project):
        r = client.post("/api/chat", json={
            "message": "/sessions", "project_id": sample_project
        })
        assert r.status_code == 200
        assert "会话" in r.json()["reply"]

    def test_chat_session_new(self, client, sample_project):
        r = client.post("/api/chat", json={
            "message": "/session new 测试会话", "project_id": sample_project
        })
        assert r.status_code == 200
        data = r.json()
        assert data["session_id"]
        assert "测试会话" in data["reply"]

    def test_chat_session_switch(self, client, sample_project):
        r1 = client.post("/api/sessions", json={"project_id": sample_project, "title": "s1"})
        sid = r1.json()["session"]["id"]
        database.add_message(sid, "user", "test message")
        r2 = client.post("/api/chat", json={
            "message": f"/session {sid}", "project_id": sample_project
        })
        assert r2.status_code == 200
        assert r2.json()["session_id"] == sid
        assert "s1" in r2.json()["reply"]

    def test_chat_session_delete(self, client, sample_project):
        r1 = client.post("/api/sessions", json={"project_id": sample_project, "title": "to-delete"})
        sid = r1.json()["session"]["id"]
        r2 = client.post("/api/chat", json={
            "message": f"/session delete {sid}", "project_id": sample_project
        })
        assert r2.status_code == 200
        assert "已删除" in r2.json()["reply"]
        assert database.get_session(sid) is None

    def test_history_with_snapshot_id(self, client, sample_project):
        client.post("/api/chat", json={
            "message": "/analyze", "project_id": sample_project
        })
        history = database.list_analysis_history(sample_project)
        assert len(history) >= 1
        snapshot_id = history[0]["id"]
        r = client.post("/api/chat", json={
            "message": f"/history {snapshot_id}", "project_id": sample_project
        })
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "快照" in reply
        assert str(snapshot_id) in reply

    def test_history_invalid_snapshot_id(self, client, sample_project):
        r = client.post("/api/chat", json={
            "message": "/history abc", "project_id": sample_project
        })
        assert r.status_code == 200
        assert "用法" in r.json()["reply"] or "⚠" in r.json()["reply"]

    def test_history_nonexistent_snapshot(self, client, sample_project):
        r = client.post("/api/chat", json={
            "message": "/history 99999", "project_id": sample_project
        })
        assert r.status_code == 200
        assert "不存在" in r.json()["reply"]

    def test_history_shows_snapshot_ids(self, client, sample_project):
        client.post("/api/chat", json={
            "message": "/analyze", "project_id": sample_project
        })
        r = client.post("/api/chat", json={
            "message": "/history", "project_id": sample_project
        })
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "ID" in reply
        assert "/history <ID>" in reply