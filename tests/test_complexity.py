import ast

from backend.analyzers.complexity import compute_complexity, compute_nesting


def test_complexity_simple_function():
    code = "def f():\n    return 1"
    node = ast.parse(code).body[0]
    assert compute_complexity(node) == 1


def test_complexity_with_branches():
    code = "def f(x):\n    if x > 0:\n        return 1\n    return 0"
    node = ast.parse(code).body[0]
    assert compute_complexity(node) == 2


def test_complexity_loop_and_or():
    code = "def f(xs):\n    for x in xs:\n        if x and x > 1 or x < -1:\n            return x"
    node = ast.parse(code).body[0]
    assert compute_complexity(node) == 5


def test_complexity_try_except():
    code = "def f():\n    try:\n        pass\n    except ValueError:\n        pass"
    node = ast.parse(code).body[0]
    assert compute_complexity(node) == 2


def test_nesting_flat():
    code = "def f():\n    return 1"
    node = ast.parse(code).body[0]
    assert compute_nesting(node) == 0


def test_nesting_deep():
    code = "def f(x):\n    if x:\n        for i in range(3):\n            while i:\n                if i == 1:\n                    return i"
    node = ast.parse(code).body[0]
    assert compute_nesting(node) == 4