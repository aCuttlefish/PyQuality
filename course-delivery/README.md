# PyQuality 终期交付

PyQuality 验收 AI 生成的 Python 函数。用户提交需求、原提示词、候选代码及入口，复核固定测试后确认标准。系统将执行结果与预期比较，给出结果、反例和修改建议，并用同一标准检验修正版。

## 启动和实机复现

环境为 Windows PowerShell、Python 和正在运行的 Docker Desktop。首次启动会安装 `code/backend/requirements.txt` 的依赖，并在缺少执行镜像时准备 `python:3.10-slim`。在本交付目录执行以下命令：

```powershell
Set-Location .\code
powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -Install
```

打开 `http://127.0.0.1:8000/acceptance.html`。选择「元音统计」示例，核对固定标准，确认并开始验收。预期原实现 **4/7，失败**。大写 `AEIOU` 应返回 `5`，实际返回 `0`。点击「换入示例正确实现」，保持已确认标准再次运行，预期为 **7/7，范围内通过**。下载两轮 JSON 报告可复查实际值、证据编号和计划摘要。完整实机台词见 [录制稿](docs/汇报与实机演示/PyQuality_20分钟答辩稿_含实机演示.docx)。

默认的固定样例验收可以在无模型密钥时运行。要验证实时提示词诊断，需自行在启动进程中配置 `DEEPSEEK_API_KEY`。报告的模型配置状态和真实调用证据分别核对。交付中的历史模型记录保存在 `eval/`。

## 测试与评测

在另一个 PowerShell 窗口进入交付目录的 `code/`，确认虚拟环境已安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pytest ..\tests -q
.\.venv\Scripts\python.exe scripts\verify_workflow.py
.\.venv\Scripts\python.exe scripts\run_real_cases.py --replay
```

第一条运行项目回归测试。第二条用 Docker 执行五个固定样例的原实现及修正版，输出默认写到 `code/data/workflow_verification/`。第三条用留存的真实模型代码复跑两组业务实验，输出写到 `code/data/real_cases_replay/`。复跑环节不调用模型，模型行为请对照原始报告。参见 [测试说明](tests/README.md) 和 [评测说明](eval/README.md)。

本次交付副本的回归结果为 **449 项通过**。工作台验收接口已用真实 Docker 验证元音统计 **4/7 → 7/7**，标准 ID 与计划摘要一致。两组业务实验的留存代码也已复跑，结果与原报告一致。见[交付验证记录](tests/交付验证记录.md)。

## 交付目录

| 位置 | 内容 |
| --- | --- |
| `code/` | 应用源码、运行依赖、启动与复跑脚本、内置演示样例。 |
| `docs/` | 项目设计、验收记录、人机协作文档、汇报材料和两次过程作业。 |
| `tests/` | PyQuality 自身的自动化回归用例。 |
| `eval/` | 被验收代码的案例、预期值、前后报告和原始模型响应。 |
| `复盘报告/` | 陈宏伟、彭启诚、敖德太、薛奕辰的个人核对稿。 |
| `demo.mp4` | 录制后由组长放到本目录，内容包括 PPT 讲解和工作台实机操作。 |

## 结果范围

判定分为 `FAIL`、`PASS_WITHIN_SCOPE` 和 `INCONCLUSIVE`。范围内通过对应已确认、已执行的固定案例。功能结论与静态安全或质量问题分别报告。两组提示词改写实验表明留存的两份再生成代码在同一最终计划上改善，不能据此推断总体成功率。完整应用的可靠性需要单独的集成验收。

## GitHub 协作

本分支的终期材料位于 course-delivery/。过程作业和交付说明可直接编辑 Markdown。四份原始 Word 稿保存在复盘报告目录，同时提供[网页可编辑的复盘核对稿](复盘报告/在线核对/README.md)。复盘文字在 Markdown 核对稿中同步，定稿后再输出 Word。组长确认收到的视频可放在交付目录根部。
