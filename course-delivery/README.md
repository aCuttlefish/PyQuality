# PyQuality 终期交付

PyQuality 验收 AI 生成的 Python 函数。用户提交需求、原提示词、候选代码及入口，复核固定测试后确认标准。系统将执行结果与预期比较，给出结果、反例和修改建议，并用同一标准检验修正版。

## 课程材料

[终期汇报 PPT](docs/汇报与实机演示/PyQuality_终期汇报.pptx) · [精简口播稿](docs/汇报与实机演示/PyQuality_终期汇报口播稿.md) · [实机演示视频 demo.mp4](demo.mp4) · [团队 AI 协作记录](复盘报告/协作记录索引.md) · [AI 协作与核查记录](docs/AI协作与核查记录.md)

| 成员 | 学号 | 作业 1 · 可验证规格 | 作业 2 · 评测集与 AI 使用日志 | 个人复盘 |
| --- | --- | --- | --- | --- |
| 陈宏伟 | 3220261335 | [可验证规格](docs/过程作业/个人作业/陈宏伟_3220261335/作业1/requirements.md) | [评测集与日志](docs/过程作业/个人作业/陈宏伟_3220261335/作业2/评测集与AI使用日志.md) | [Word](复盘报告/陈宏伟_3220261335_个人复盘报告.docx) · [在线阅读](复盘报告/在线版/chen-hongwei.md) |
| 彭启诚 | 3220261380 | [可验证规格](docs/过程作业/个人作业/彭启诚_3220261380/作业1/requirements.md) | [评测集与日志](docs/过程作业/个人作业/彭启诚_3220261380/作业2/评测集与AI使用日志.md) | [Word](复盘报告/彭启诚_3220261380_个人复盘报告.docx) · [在线阅读](复盘报告/在线版/peng-qicheng.md) |
| 敖德太 | 3220261332 | [可验证规格](docs/过程作业/个人作业/敖德太_3220261332/作业1/requirements.md) | [评测集与日志](docs/过程作业/个人作业/敖德太_3220261332/作业2/评测集与AI使用日志.md) | [Word](复盘报告/敖德太_3220261332_个人复盘报告.docx) · [在线阅读](复盘报告/在线版/ao-detai.md) |
| 薛奕辰 | 3220261418 | [可验证规格](docs/过程作业/个人作业/薛奕辰_3220261418/作业1/requirements.md) | [评测集与日志](docs/过程作业/个人作业/薛奕辰_3220261418/作业2/评测集与AI使用日志.md) | [Word](复盘报告/薛奕辰_3220261418_个人复盘报告.docx) · [在线阅读](复盘报告/在线版/xue-yichen.md) |

## 启动和实机复现

环境为 Windows PowerShell、Python 和正在运行的 Docker Desktop。首次启动会安装 `code/backend/requirements.txt` 的依赖，并在缺少执行镜像时准备 `python:3.10-slim`。在本交付目录执行以下命令：

```powershell
Set-Location .\code
powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -Install
```

打开首页 `http://127.0.0.1:8000/`，点击顶部 **「🧾 发起代码验收」**（或在对话框输入 `/accept`），即可走完统一对话流验收：**步骤 1 提需求或提示词并由 AI 多轮追问澄清 → 步骤 2 生成卡片化测试用例并人工锁定标准 → 步骤 3 贴入代码进 Docker 隔离验收 → 步骤 4 手动修改或一键 AI 按失败反例修复并沿用原标准复测**（原独立验收页 `/acceptance.html` 保持兼容）。完整实机口播与复现数据见 [终期口播稿](docs/汇报与实机演示/PyQuality_终期汇报口播稿.md)，录制视频见 [demo.mp4](demo.mp4)。

默认的固定样例验收可以在无模型密钥时运行。要验证实时提示词诊断，需自行在启动进程中配置 `DEEPSEEK_API_KEY`。报告的模型配置状态和真实调用证据分别核对。交付中的历史模型记录保存在 `eval/`。

## 测试与评测

在另一个 PowerShell 窗口进入交付目录的 `code/`，确认虚拟环境已安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pytest ..\tests -q
.\.venv\Scripts\python.exe scripts\verify_workflow.py
.\.venv\Scripts\python.exe scripts\run_real_cases.py --replay
```

第一条运行项目回归测试。第二条用 Docker 执行五个固定样例的原实现及修正版，输出默认写到 `code/data/workflow_verification/`。第三条用留存的真实模型代码复跑两组业务实验，输出写到 `code/data/real_cases_replay/`。复跑环节不调用模型，模型行为请对照原始报告。参见 [测试说明](tests/README.md) 和 [评测说明](eval/README.md)。

本次交付副本的回归结果为 **457 项通过**（0 失败，新增统一对话 `/accept`、需求多轮追问 `/clarify`、无代码 `/prepare`、嵌套列表 `ORDERED`、排序自动补齐与 `/repair` 测试）。工作台验收接口已用真实 Docker 验证元音统计 **4/7 → 7/7** 以及 GitHub Copilot 公开案例 `possibilities(m, n)` 修复复测 **11/11**，标准 ID 与计划摘要一致。两组业务实验的留存代码也已复跑，结果与原报告一致。见[交付验证记录](tests/交付验证记录.md)。

## 交付目录

| 位置 | 内容 |
| --- | --- |
| `code/` | 应用源码、运行依赖、启动与复跑脚本、内置演示样例。 |
| `docs/` | 项目设计、验收记录、人机协作文档、汇报材料和两次过程作业。 |
| `tests/` | PyQuality 自身的自动化回归用例。 |
| `eval/` | 被验收代码的案例、预期值、前后报告和原始模型响应。 |
| `复盘报告/` | 陈宏伟、彭启诚、敖德太、薛奕辰的个人复盘报告。 |
| `demo.mp4` | 录制后由组长放到本目录，内容包括 PPT 讲解和工作台实机操作。 |

## 汇报材料

- [28 张汇报配图的 draw.io 总源文件](docs/汇报与实机演示/draw.io配图/PyQuality_28张汇报配图.drawio)、[图片清单](docs/汇报与实机演示/draw.io配图/图片清单.txt)和 [PNG 导出图](docs/汇报与实机演示/draw.io配图/png/)
- [PPT 大纲与参考脉络](docs/汇报与实机演示/PPT大纲/PyQuality_PPT大纲与参考脉络.txt)和[工作台演示截图](docs/汇报与实机演示/备用截图/)

## 结果范围

判定分为 `FAIL`、`PASS_WITHIN_SCOPE` 和 `INCONCLUSIVE`。范围内通过对应已确认、已执行的固定案例。功能结论与静态安全或质量问题分别报告。两组实验使用各自固定的测试计划。改写提示词后，满减案例从 10/11 提高到 11/11，通讯录案例从 5/9 提高到 9/9。总体成功率还需要更大规模的评测。完整应用的可靠性需要单独的集成验收。
