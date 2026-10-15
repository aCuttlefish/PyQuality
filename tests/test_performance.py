from backend.analyzers.performance import detect_performance


def test_nested_loop():
    code = "def f(a):\n    for i in a:\n        for j in a:\n            print(i, j)"
    issues = detect_performance("a.py", code)
    assert any(i["type"] == "nested_loop" for i in issues)


def test_string_concat_in_loop():
    code = "def f(a):\n    s = ''\n    for x in a:\n        s += str(x)\n    return s"
    issues = detect_performance("a.py", code)
    assert any(i["type"] == "string_concat_in_loop" for i in issues)


def test_range_len_loop():
    code = "def f(a):\n    for i in range(len(a)):\n        print(a[i])"
    issues = detect_performance("a.py", code)
    assert any(i["type"] == "range_len_loop" for i in issues)


def test_clean_code_no_issues():
    code = "def f(a):\n    return [x * 2 for x in a]"
    issues = detect_performance("a.py", code)
    assert issues == []


def test_single_loop_no_nested():
    code = "def f(a):\n    for x in a:\n        print(x)"
    issues = detect_performance("a.py", code)
    assert not any(i["type"] == "nested_loop" for i in issues)


def test_string_concat_outside_loop():
    code = "def f():\n    s = 'a'\n    s += 'b'\n    return s"
    issues = detect_performance("a.py", code)
    assert not any(i["type"] == "string_concat_in_loop" for i in issues)


def test_syntax_error_returns_empty():
    issues = detect_performance("a.py", "def f(:\n    pass")
    assert issues == []


def test_suggestion_present():
    code = "def f(a):\n    for i in a:\n        for j in a:\n            pass"
    issues = detect_performance("a.py", code)
    nested = [i for i in issues if i["type"] == "nested_loop"][0]
    assert nested["suggestion"]