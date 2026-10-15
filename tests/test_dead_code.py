from backend.analyzers.dead_code import analyze_dead_code


def test_unused_function_detected():
    files = {"m.py": "def helper():\n    return 1\n"}
    r = analyze_dead_code(files)
    names = [d["name"] for d in r["dead_code"]]
    assert "helper" in names


def test_called_function_not_dead():
    files = {"m.py": "def helper():\n    return 1\n\ndef main():\n    return helper()\n"}
    r = analyze_dead_code(files)
    names = [d["name"] for d in r["dead_code"]]
    assert "helper" not in names


def test_cross_module_import_not_dead():
    files = {
        "a.py": "def util():\n    return 0\n",
        "b.py": "from a import util\n\ndef main():\n    return util()\n",
    }
    r = analyze_dead_code(files)
    names = [d["name"] for d in r["dead_code"]]
    assert "util" not in names


def test_main_guard_call_not_dead():
    files = {"m.py": "def entry():\n    pass\n\nif __name__ == '__main__':\n    entry()\n"}
    r = analyze_dead_code(files)
    names = [d["name"] for d in r["dead_code"]]
    assert "entry" not in names


def test_test_prefix_skipped():
    files = {"m.py": "def test_thing():\n    assert True\n"}
    r = analyze_dead_code(files)
    names = [d["name"] for d in r["dead_code"]]
    assert "test_thing" not in names


def test_decorated_function_skipped():
    files = {"m.py": "def deco(f):\n    return f\n\n@deco\ndef handler():\n    pass\n"}
    r = analyze_dead_code(files)
    names = [d["name"] for d in r["dead_code"]]
    assert "handler" not in names


def test_unused_class_detected():
    files = {"m.py": "class Unused:\n    pass\n"}
    r = analyze_dead_code(files)
    names = [d["name"] for d in r["dead_code"]]
    assert "Unused" in names


def test_syntax_error_skipped():
    files = {"m.py": "def (\n"}
    r = analyze_dead_code(files)
    assert r["dead_code"] == []


def test_empty_files():
    r = analyze_dead_code({})
    assert r["stats"]["total_definitions"] == 0
    assert r["dead_code"] == []


def test_stats_structure():
    files = {"m.py": "def used():\n    pass\n\ndef unused():\n    pass\n\nused()\n"}
    r = analyze_dead_code(files)
    s = r["stats"]
    assert s["total_definitions"] == 2
    assert s["dead_count"] == 1
    assert 0 < s["dead_rate"] <= 100


def test_suggestion_present():
    files = {"m.py": "def orphan():\n    pass\n"}
    r = analyze_dead_code(files)
    assert r["dead_code"][0]["suggestion"]

def test_unused_nested_function_detected():
    files = {"m.py": "def outer():\n    def inner():\n        pass\n    return 1\n"}
    r = analyze_dead_code(files)
    names = [d["name"] for d in r["dead_code"]]
    assert "inner" in names


def test_nested_function_used_not_dead():
    files = {"m.py": "def outer():\n    def inner():\n        return 1\n    return inner()\n"}
    r = analyze_dead_code(files)
    names = [d["name"] for d in r["dead_code"]]
    assert "inner" not in names


def test_nested_function_returned_not_dead():
    files = {"m.py": "def outer():\n    def inner():\n        return 1\n    return inner\n\nouter()\n"}
    r = analyze_dead_code(files)
    names = [d["name"] for d in r["dead_code"]]
    assert "inner" not in names


def test_nested_function_in_method_detected():
    files = {"m.py": "class C:\n    def m(self):\n        def unused():\n            pass\n        return 1\n"}
    r = analyze_dead_code(files)
    names = [d["name"] for d in r["dead_code"]]
    assert "unused" in names

def test_dunder_protocol_methods_not_dead():
    files = {"m.py": "class C:\n    def __str__(self):\n        return 'C'\n    def __repr__(self):\n        return 'C()'\n    def __len__(self):\n        return 0\n    def __eq__(self, o):\n        return False\n    def __enter__(self):\n        return self\n    def __exit__(self, *a):\n        pass\n"}
    r = analyze_dead_code(files)
    names = [d["name"] for d in r["dead_code"]]
    for dunder in ("__str__", "__repr__", "__len__", "__eq__", "__enter__", "__exit__"):
        assert dunder not in names, f"{dunder} 不应被报为死代码"


def test_single_underscore_method_still_detected():
    files = {"m.py": "class C:\n    def _helper(self):\n        pass\n"}
    r = analyze_dead_code(files)
    names = [d["name"] for d in r["dead_code"]]
    assert "_helper" in names