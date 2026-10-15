from backend.analyzers.parser import analyze_source
from backend.analyzers.smells import detect_smells

SMELLY = '''
import os
import sys


def process(data, limit, flag, extra, more, another):
    result = []
    if data:
        if limit > 0:
            for item in data:
                if item > limit:
                    if flag:
                        result.append(item * 3.14159)
    return result


class Huge:
    pass


def findStudent(students, sid):
    for s in students:
        if s["id"] == sid:
            return s
    return None
'''

CLEAN = '''"""干净模块示例"""


def add(a, b):
    """返回两数之和"""
    return a + b
'''


def _run(sources: dict):
    analyses = [analyze_source(k, v) for k, v in sources.items()]
    return detect_smells(analyses, sources), analyses


def test_detects_long_params():
    smells, _ = _run({"a.py": SMELLY})
    types = {s["type"] for s in smells}
    assert "long_params" in types


def test_detects_deep_nesting():
    smells, _ = _run({"a.py": SMELLY})
    assert any(s["type"] == "deep_nesting" and s["line"] == 6 for s in smells)


def test_detects_unused_import():
    smells, _ = _run({"a.py": SMELLY})
    types = {s["type"] for s in smells}
    assert "unused_import" in types


def test_detects_missing_docstring():
    smells, _ = _run({"a.py": SMELLY})
    assert any(s["type"] == "missing_docstring" and "process" in s["message"] for s in smells)


def test_detects_bad_naming():
    smells, _ = _run({"a.py": SMELLY})
    assert any(s["type"] == "bad_naming" and "findStudent" in s["message"] for s in smells)


def test_detects_magic_number():
    code = "def f(x):\n    y = x * 3.14159\n    z = x * 3.14159\n    return y + z"
    smells, _ = _run({"m.py": code})
    assert any(s["type"] == "magic_number" for s in smells)


def test_detects_broad_except():
    code = "def f():\n    try:\n        pass\n    except Exception:\n        pass"
    smells, _ = _run({"b.py": code})
    assert any(s["type"] == "broad_except" for s in smells)


def test_detects_bare_except():
    code = "def f():\n    try:\n        pass\n    except:\n        pass"
    smells, _ = _run({"b.py": code})
    assert any(s["type"] == "broad_except" and "裸" in s["message"] for s in smells)


def test_detects_global_variable():
    code = "GLOBAL_X = 10\n\ndef f():\n    return GLOBAL_X"
    smells, _ = _run({"g.py": code})
    assert any(s["type"] == "global_variable" and s["line"] == 1 for s in smells)


def test_detects_syntax_error():
    smells, _ = _run({"bad.py": "def f(:\n    pass"})
    assert any(s["type"] == "syntax_error" for s in smells)


def test_clean_code_few_smells():
    smells, _ = _run({"clean.py": CLEAN})
    high = [s for s in smells if s["severity"] == "high"]
    assert not high


def test_suggestion_attached():
    smells, _ = _run({"a.py": SMELLY})
    assert all("suggestion" in s for s in smells)

def test_from_import_used_not_flagged():
    code = "from os import path\n\ndef f():\n    return path.join('a', 'b')\n"
    smells, _ = _run({"a.py": code})
    assert not any(s["type"] == "unused_import" for s in smells)


def test_from_import_unused_flagged():
    code = "from os import path\n\ndef f():\n    return 1\n"
    smells, _ = _run({"a.py": code})
    assert any(s["type"] == "unused_import" and "os.path" in s["message"] for s in smells)


def test_from_import_alias_used_not_flagged():
    code = "from os import path as p\n\ndef f():\n    return p.join('a', 'b')\n"
    smells, _ = _run({"a.py": code})
    assert not any(s["type"] == "unused_import" for s in smells)


def test_star_import_not_flagged():
    code = "from os import *\n\ndef f():\n    return getcwd()\n"
    smells, _ = _run({"a.py": code})
    assert not any(s["type"] == "unused_import" for s in smells)


def test_dotted_import_used_not_flagged():
    code = "import os.path\n\ndef f():\n    return os.path.join('a', 'b')\n"
    smells, _ = _run({"a.py": code})
    assert not any(s["type"] == "unused_import" for s in smells)