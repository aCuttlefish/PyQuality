from backend.analyzers.type_hints import analyze_type_hints


def test_full_annotation_100_coverage():
    code = "def add(a: int, b: int) -> int:\n    return a + b"
    r = analyze_type_hints({"a.py": code})
    assert r["stats"]["coverage"] == 100.0
    assert r["stats"]["missing"] == 0


def test_missing_return_annotation():
    code = "def add(a: int, b: int):\n    return a + b"
    r = analyze_type_hints({"a.py": code})
    assert r["stats"]["coverage"] == 0.0
    assert any(m["kind"] == "return" for m in r["missing"])


def test_missing_param_annotation():
    code = "def add(a, b) -> int:\n    return a + b"
    r = analyze_type_hints({"a.py": code})
    assert any(m["kind"] == "params" for m in r["missing"])


def test_missing_both():
    code = "def add(a, b):\n    return a + b"
    r = analyze_type_hints({"a.py": code})
    assert any(m["kind"] == "both" for m in r["missing"])


def test_self_cls_not_required():
    code = "class C:\n    def m(self, x: int) -> int:\n        return x"
    r = analyze_type_hints({"a.py": code})
    assert r["stats"]["coverage"] == 100.0


def test_dunder_skipped_except_init():
    code = "class C:\n    def __init__(self):\n        pass\n    def __str__(self):\n        return 'x'"
    r = analyze_type_hints({"a.py": code})
    assert r["stats"]["total_functions"] == 1


def test_no_params_counts_as_annotated():
    code = "def f() -> int:\n    return 1"
    r = analyze_type_hints({"a.py": code})
    assert r["stats"]["coverage"] == 100.0


def test_syntax_error_skipped():
    r = analyze_type_hints({"a.py": "def f(:\n    pass"})
    assert r["stats"]["total_functions"] == 0


def test_empty_files():
    r = analyze_type_hints({})
    assert r["stats"]["coverage"] == 100.0
    assert r["missing"] == []