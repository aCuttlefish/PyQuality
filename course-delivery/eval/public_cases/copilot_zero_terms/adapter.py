"""仅调用原始 possibilities 函数，不过滤、排序或改写返回结果。"""
from pathlib import Path
import runpy


def enumerate_terms(target, terms):
    namespace = runpy.run_path(str(Path(__file__).with_name("upstream.py")), run_name="public_case_import")
    return namespace["possibilities"](target, terms)
