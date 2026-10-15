from backend.analyzers.parser import analyze_source
from backend.analyzers.readability import score_readability

CLEAN = '''"""一个文档完善的干净模块"""


def add(a, b):
    """返回两数之和"""
    return a + b


def sub(a, b):
    """返回两数之差"""
    return a - b


class Calculator:
    """简单计算器"""

    def multiply(self, a, b):
        """乘法"""
        return a * b
'''

MESSY = '''def x(p):
    if p:
        if p > 1:
            if p > 2:
                if p > 3:
                    if p > 4:
                        for i in range(10):
                            while i:
                                if i == 5:
                                    return p * i'''


def _report(sources: dict):
    analyses = [analyze_source(k, v) for k, v in sources.items()]
    return score_readability(analyses), analyses


def test_clean_code_scores_high():
    report, _ = _report({"clean.py": CLEAN})
    assert report["total"] >= 85
    assert report["grade"] == "A"


def test_messy_code_scores_lower():
    clean, _ = _report({"clean.py": CLEAN})
    messy, _ = _report({"messy.py": MESSY})
    assert messy["total"] < clean["total"]


def test_breakdown_structure():
    report, _ = _report({"clean.py": CLEAN})
    assert len(report["breakdown"]) == 7
    for item in report["breakdown"]:
        assert "metric" in item and "score" in item and "weight" in item


def test_empty_analysis():
    report = score_readability([])
    assert report["grade"] == "N/A"
    assert report["total"] == 0.0


def test_grade_boundaries():
    report, _ = _report({"clean.py": CLEAN})
    assert report["grade"] in ("A", "B", "C", "D", "E")