# PyQuality AI 输出量化验收报告

> 生成时间: 2026-10-15 17:48:51
> AI 状态: ✅ 已连接
> 测试输入: `samples/demo_project/grades.py`（4 个函数）

## 总览

- 验收指标: **14** 项
- 通过: **14** 项  失败: **0** 项
- 通过率: **100.0%**

## 1. 测试生成指标

| 指标 | 实测值 | 阈值 | 结果 |
| --- | --- | --- | --- |
| test_syntax_pass_rate | 100.0% | ≥95% | ✅ |
| test_collect_pass_rate | 100.0% | ≥90% | ✅ |
| test_execute_pass_rate | 100.0% | ≥50% | ✅ |
| test_function_coverage | 100.0% | ≥80% | ✅ |
| test_assertion_density | 1.09 | ≥0.9 | ✅ |
| test_bug_detection_rate | 100.0% | ≥40% | ✅ |

**详情:**
- 目标函数: ['calculate_average', 'findStudent', 'process_grades', 'weighted_score']
- 已覆盖: ['calculate_average', 'findStudent', 'process_grades', 'weighted_score']
- 测试函数数: 54, 断言数: 59
- pytest 结果: 54 passed, 0 failed, 0 errors
- 注入 BUG: ['bug_minus', 'bug_neq', 'bug_div_weight']
- 检出 BUG: ['bug_minus', 'bug_neq', 'bug_div_weight']

## 2. 代码修复指标

| 指标 | 实测值 | 阈值 | 结果 |
| --- | --- | --- | --- |
| fix_syntax_preserve_rate | 100.0% | ≥95% | ✅ |
| fix_function_count_preserve_rate | 100.0% | ≥90% | ✅ |
| fix_smell_reduction_rate | 66.7% | ≥30% | ✅ |
| fix_compile_rate | 100.0% | ≥95% | ✅ |

**详情:**
- 修复前坏味: 9, 修复后坏味: 3
- 模式: ai

## 3. 改进建议指标

| 指标 | 实测值 | 阈值 | 结果 |
| --- | --- | --- | --- |
| advice_smell_coverage | 100.0% | ≥90% | ✅ |
| advice_line_accuracy | 100.0% | ≥90% | ✅ |
| advice_type_accuracy | 100.0% | ≥95% | ✅ |
| advice_actionable_rate | 100.0% | ≥80% | ✅ |

**详情:**
- 总坏味: 9, 建议条数: 9
- 模式: ai

## 4. 不达标项

✅ 全部指标达标。