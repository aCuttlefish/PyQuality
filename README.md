# PyQuality v4.3 · Python AI 生成代码验收平台

PyQuality 帮你用可复核的测试回答一个问题：**AI 生成的 Python 代码满足功能需求吗？** 提交功能需求、原始提示词和候选代码，确认测试标准后运行验收。系统报告失败案例的输入、期望和实际结果，给出代码修改建议，并在模型可用时诊断提示词中的遗漏、歧义和冲突。修改代码或重新生成后，可以按同一标准复测。

[快速开始](#快速开始) · [验收规则](#验收规则) · [实测案例](#实测案例) · [课程交付](#课程交付)

## 快速开始

在 Windows 上准备 Python 并启动 Docker Desktop。首次运行时，在用于存放项目的目录执行以下命令。

```powershell
git clone https://github.com/aCuttlefish/PyQuality.git
Set-Location PyQuality
powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -Install
```

脚本创建 Python 虚拟环境、安装依赖，并准备执行镜像 `python:3.10-slim`。依赖装好后，后续启动可省略 `-Install`。打开 [验收工作台](http://127.0.0.1:8000/acceptance.html)。

### 用元音统计示例体验

1. 在「加载演示」选择「元音统计」并点击「填入」。页面会加载需求、原始提示词、错误实现和预先核对的测试。
2. 核对输入与期望，勾选确认框，依次点击「确认标准」和「开始验收」。原实现通过 **4/7**。例如，输入 `AEIOU` 时期望 `5`，实际返回 `0`。
3. 点击「换入示例正确实现」，再次点击「开始验收」。同一标准下通过 **7/7**。两轮报告都可下载为 JSON，供复核和对照。

### 验收自己的代码

填写功能需求、原始提示词、候选代码和待测函数名。使用「手动填写测试」输入每个案例的参数与期望，再确认并执行。位置参数按 JSON 数组填写，例如给函数传入一个字符串时填 `["AEIOU"]`。

如需「生成验收标准」和提示词语义诊断，在项目根目录的 `.env` 中配置 `DEEPSEEK_API_KEY`，再启动服务。内置演示和手工测试可在未配置模型时运行。完整操作、接口和运行环境见 [验收工作流](docs/workflow_acceptance.md)。

## 验收规则

先由人确认需求和测试预期，再由程序在 Docker 中执行候选代码，并将实际结果与固定预期比较。修改需求或函数入口时重新确认标准。代码或原始提示词变更时可以复用标准。

| 功能结论 | 判定依据 |
| --- | --- |
| 失败 `FAIL` | 必要需求出现有效失败证据，例如实际返回值与已确认的期望不符。 |
| 范围内通过 `PASS_WITHIN_SCOPE` | 满足标准确认条件，并通过本轮已确认的充分检查。结论覆盖已确认的验收范围。 |
| 无法判定 `INCONCLUSIVE` | 规格未确认、关键检查不足、执行超时或环境阻断。 |

报告分别展示功能结论、静态质量发现与改进建议。功能反例附带输入、期望、实际与证据编号。当前验收入口支持以 JSON 传参的 Python 函数。完整 Web、GUI 或数据库应用需要相应的集成测试。

## 实测案例

以下业务场景由课设设计。两组初始代码和改进后的代码均由 DeepSeek 实际生成。每组在 Docker 中复用同一份最终确认计划比较结果。

| 案例 | 原代码 | 使用改写后的提示词重新生成 | 发现的问题 |
| --- | ---: | ---: | --- |
| 电商满减金额计算 | 10/11 | 11/11 | 浮点误差导致恰好满 100 元的购物车未减免。 |
| 通讯录邮箱去重 | 5/9 | 9/9 | 比较邮箱时未去除首尾空格和统一大小写，导致重复联系人残留。 |

可复查生成提示词、模型原始输出、代码和两轮报告。[真实模型案例与证据](docs/real_cases/README.md)

## 测试与复现

最终交付版的回归验证通过了 **457 项自动化测试**和 **5 个 Docker 验收场景**（并新增首页统一对话入口 `/accept`、多轮需求追问 `/clarify`、基于失败反例的 AI 修复候选 `/repair` 及终期演示视频 `course-delivery/demo.mp4`）。完成首次安装后，在仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe scripts/verify_workflow.py
.\.venv\Scripts\python.exe scripts/run_real_cases.py --replay
```

第二条命令在 Docker 中验证错误实现、修正实现、证据引用及标准复用。第三条以留存的模型代码重跑两组业务案例。[交付验证记录](course-delivery/tests/交付验证记录.md) · [评测材料](course-delivery/eval/README.md)

## 项目结构

| 目录 | 用途 |
| --- | --- |
| [backend/acceptance](backend/acceptance/) | 验收标准、隔离执行、证据判定和建议生成。 |
| [backend/routers](backend/routers/) | FastAPI 接口。验收接口路径以 `/api/acceptance` 开头。 |
| [backend/analyzers](backend/analyzers/) | AST 静态分析，包括复杂度、代码坏味、依赖和可读性。 |
| [frontend](frontend/) | 原生 HTML、CSS 和 JavaScript 界面。 |
| [samples](samples/) · [tests](tests/) · [scripts](scripts/) | 演示样例、自动化测试、启动及复跑脚本。 |

服务首页提供项目质量分析，可上传 Python 项目，查看静态分析、历史趋势和修复建议。进入对话后输入 `/help` 查看命令。服务启动后可在 [API 文档](http://127.0.0.1:8000/docs) 浏览接口。[项目分析功能说明](docs/core_features.md)

## 课程交付

- [终期交付总目录](course-delivery/README.md) · [实机演示视频 demo.mp4](course-delivery/demo.mp4)
- [终期汇报 PPT](course-delivery/docs/汇报与实机演示/PyQuality_终期汇报.pptx) · [精简口播稿](course-delivery/docs/汇报与实机演示/PyQuality_终期汇报口播稿.md) · [AI 协作与核查记录](course-delivery/docs/AI协作与核查记录.md)
- [28 张 draw.io 配图及图片清单](course-delivery/docs/汇报与实机演示/draw.io配图/) · [PPT 大纲](course-delivery/docs/汇报与实机演示/PPT大纲/)
- [过程作业](course-delivery/docs/过程作业/) · [评测材料](course-delivery/eval/) · [四位组员的个人复盘报告](course-delivery/复盘报告/)

历次汇报版本保存在[汇报材料存档](archive/汇报材料/)。
