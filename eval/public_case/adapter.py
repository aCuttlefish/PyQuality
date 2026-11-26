"""实验测试适配器；不修改或重写上游计算逻辑。
upstream_fitness.py:35 weight=int(input("What is your weight in kg?"))
upstream_fitness.py:36 height=int(input("What is your height in meters?"))
"""
import io
from contextlib import redirect_stdout
from pathlib import Path
import runpy
from unittest.mock import patch


def calculate_bmi(weight, height):
    output = io.StringIO()
    answers = ["1", str(weight), str(height), "n"]
    with patch("builtins.input", side_effect=answers), redirect_stdout(output):
        runpy.run_path(str(Path(__file__).with_name("upstream_fitness.py")), run_name="__main__")
    for line in output.getvalue().splitlines():
        if line.startswith("Your BMI is "):
            return float(line.removeprefix("Your BMI is "))
    raise RuntimeError("Upstream program did not print a BMI value")
