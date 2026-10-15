from backend.analyzers.duplication import analyze_duplication

DUP_FUNC = """def process(data):
    result = []
    for item in data:
        value = item * 2
        result.append(value)
    return result
"""


def test_detect_duplicate_functions():
    r = analyze_duplication({"a.py": DUP_FUNC, "b.py": DUP_FUNC})
    assert r["stats"]["duplicate_groups"] >= 1
    assert len(r["duplicates"]) >= 1


def test_different_functions_no_dup():
    code_a = "def f(x):\n    return x + 1\n" * 1
    code_b = "def g(x):\n    return x * 100 - 50\n"
    r = analyze_duplication({"a.py": code_a, "b.py": code_b})
    assert r["stats"]["duplicate_groups"] == 0


def test_short_function_skipped():
    code = "def f(x):\n    return x\n"
    r = analyze_duplication({"a.py": code, "b.py": code})
    assert r["stats"]["total_functions"] == 0


def test_renamed_duplicate_detected():
    code_a = "def calc(items):\n    total = 0\n    for it in items:\n        total += it\n    return total\n"
    code_b = "def sum_all(nums):\n    acc = 0\n    for n in nums:\n        acc += n\n    return acc\n"
    r = analyze_duplication({"a.py": code_a, "b.py": code_b}, min_lines=4)
    assert r["stats"]["duplicate_groups"] >= 1


def test_syntax_error_skipped():
    r = analyze_duplication({"a.py": "def f(:\n    pass"})
    assert r["stats"]["total_functions"] == 0


def test_empty_files():
    r = analyze_duplication({})
    assert r["stats"]["rate"] == 0.0
    assert r["duplicates"] == []


def test_rate_calculation():
    r = analyze_duplication({"a.py": DUP_FUNC, "b.py": DUP_FUNC})
    assert r["stats"]["rate"] > 0.0


def test_duplicates_sorted_by_length():
    r = analyze_duplication({"a.py": DUP_FUNC, "b.py": DUP_FUNC})
    if len(r["duplicates"]) >= 2:
        assert r["duplicates"][0]["lines"] >= r["duplicates"][1]["lines"]