# PyQuality 回归测试

本目录测试系统自身的判定、执行协议、标准确认、证据关联、静态发现和异常处理。`eval/` 则检验候选程序在给定业务需求下的结果。

先按[主说明](../README.md)安装依赖，再从 `code/` 运行：

```powershell
.\.venv\Scripts\python.exe -m pytest ..\tests -q
```

| 文件 | 重点 |
| --- | --- |
| `test_acceptance_workflow.py` | 标准可编辑与确认、版本绑定、真实观察回填、静态风险显示、超时清理。 |
| `test_acceptance_verdict.py` | 功能判定、证据门槛及可声称的保证等级。 |
| `test_acceptance_core_e2e.py` | 固定需求场景、环境阻断、缺证据时的处理。 |
| `test_acceptance_runner.py`、`test_acceptance_regression.py` | 执行器结果协议、关键分支及先前发现的回归问题。 |

单元和回归测试可能使用受控夹具、替身响应或宿主子进程。真实 Docker 与真实模型实验的留存结果请查 `../eval/`。旧版本的测试数字写在对应版本验收记录中。
