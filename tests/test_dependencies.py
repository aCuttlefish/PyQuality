from backend.analyzers.dependencies import analyze_dependencies


def test_single_file_no_deps():
    r = analyze_dependencies({"a.py": "x = 1\n"})
    assert r["stats"]["module_count"] >= 1
    assert r["stats"]["cycle_count"] == 0


def test_internal_dependency():
    sources = {
        "a.py": "import b\n",
        "b.py": "def f():\n    return 1\n",
    }
    r = analyze_dependencies(sources)
    assert r["stats"]["edge_count"] >= 1
    assert any(e["from"] == "a.py" and "b" in e["to"] for e in r["edges"])


def test_circular_dependency_detected():
    sources = {
        "a.py": "import b\n",
        "b.py": "import a\n",
    }
    r = analyze_dependencies(sources)
    assert r["stats"]["cycle_count"] >= 1
    assert len(r["cycles"]) >= 1


def test_external_import_ignored():
    sources = {"a.py": "import os\nimport sys\n"}
    r = analyze_dependencies(sources)
    assert r["stats"]["edge_count"] == 0


def test_from_import():
    sources = {
        "main.py": "from utils import helper\n",
        "utils.py": "def helper():\n    pass\n",
    }
    r = analyze_dependencies(sources)
    assert r["stats"]["edge_count"] >= 1


def test_syntax_error_skipped():
    sources = {"a.py": "def f(:\n    pass", "b.py": "import a\n"}
    r = analyze_dependencies(sources)
    assert r["stats"]["module_count"] >= 1


def test_stats_structure():
    r = analyze_dependencies({"a.py": "x = 1\n"})
    assert "module_count" in r["stats"]
    assert "edge_count" in r["stats"]
    assert "cycle_count" in r["stats"]
    assert "max_depth" in r["stats"]