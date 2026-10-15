from backend.analyzers.docstrings import analyze_docstrings


def test_full_coverage():
    code = '"""mod"""\n\nclass C:\n    """cls"""\n    def m(self):\n        """m"""\n        pass'
    r = analyze_docstrings({"a.py": code})
    assert r["stats"]["overall"] == 100.0
    assert r["missing"] == []


def test_missing_module_docstring():
    code = "class C:\n    pass"
    r = analyze_docstrings({"a.py": code})
    assert any(m["kind"] == "module" for m in r["missing"])
    assert r["stats"]["module_coverage"] == 0.0


def test_missing_class_docstring():
    code = '"""mod"""\n\nclass C:\n    pass'
    r = analyze_docstrings({"a.py": code})
    assert any(m["kind"] == "class" for m in r["missing"])


def test_missing_function_docstring():
    code = '"""mod"""\n\ndef f():\n    pass'
    r = analyze_docstrings({"a.py": code})
    assert any(m["kind"] == "function" for m in r["missing"])
    assert r["stats"]["function_coverage"] == 0.0


def test_public_vs_private():
    code = '"""mod"""\n\ndef public():\n    """p"""\n    pass\n\ndef _private():\n    pass'
    r = analyze_docstrings({"a.py": code})
    assert r["stats"]["public_coverage"] == 100.0
    assert r["stats"]["function_coverage"] == 50.0


def test_dunder_skipped():
    code = '"""mod"""\n\nclass C:\n    def __init__(self):\n        pass\n    def __repr__(self):\n        return "C"'
    r = analyze_docstrings({"a.py": code})
    assert r["stats"]["functions"] == 1


def test_syntax_error_skipped():
    r = analyze_docstrings({"a.py": "def f(:\n    pass"})
    assert r["missing"] == []


def test_empty_files():
    r = analyze_docstrings({})
    assert r["stats"]["overall"] == 100.0