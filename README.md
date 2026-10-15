# PyQuality - Python 代码质量检测平台 (v4.0)

一个参照 Codex 风格的**对话式** Python 代码质量检测平台：上传小型 Python 项目，通过自然语言或斜杠命令完成坏味检测、安全检测、依赖分析、死代码检测、可读性评分、AI 测试用例生成、AI 修复建议与 AI 代码修复，支持历史趋势跟踪与预警、阈值可配置与持久化、批量分析与修复、项目对比、全局仪表盘、代码片段直接分析、多格式报告导出。

## 功能

| 功能 | 说明 |
| --- | --- |
| **对话式交互** | Codex 风格对话界面，30+ 斜杠命令 + 自然语言关键词，markdown 渲染回复 |
| **智能推荐** | 分析完成后根据结果自动推荐下一步操作（修复/建议/测试/导出） |
| **趋势预警** | 历史趋势中坏味增加/可读性下降时自动发出预警 |
| 项目管理 | 上传 .zip 或多个 .py 文件，列表/删除/文件浏览/搜索；一键加载内置示例 |
| **代码片段分析** | `/snippet <代码>` 直接分析一段 Python 代码，无需上传项目 |
| **全局仪表盘** | `/dashboard` 跨项目统计概览（总文件/总坏味/平均健康度/等级分布） |
| **项目对比** | `/compare <id>` 对比两个项目的可读性/健康度/坏味/安全/复杂度等指标 |
| **批量分析** | `/analyze all` 一次分析所有项目并按健康度排名 |
| 坏味检测 | 14 类 AST 规则：长函数、参数过多、深嵌套、上帝类、魔法数字、宽泛异常、未用导入/变量、全局变量、命名不规范、过长文件、缺 docstring、超长行、重复代码 |
| **坏味排序+统计** | 按严重度排序，显示严重度分布和坏味类型统计 |
| 安全检测 | 危险函数（eval/exec/pickle/os.system/shell=True 等）、危险模块导入、硬编码密钥、assert 滥用 |
| 依赖分析 | 模块导入图、循环依赖检测、最大依赖深度 |
| 死代码检测 | 跨文件引用分析，识别未被使用的函数/类/方法（排除入口、test_*、装饰器注册） |
| **复杂度热力图** | 全部函数按圈复杂度排序+分桶（🟢低/🟡中/🟠高/🔴严重），进度条可视化 |
| 可读性评分 | 7 项指标加权 0-100 分 + A~E 评级 |
| **项目健康度** | 综合可读性 - 安全扣分 - 坏味扣分，A~E 评级 |
| 类型提示/文档覆盖 | 参数与返回值注解覆盖率、模块/类/函数 docstring 覆盖率 |
| 性能/重复检测 | 嵌套循环、字符串拼接、range(len) 热点；AST 归一化重复函数检测 |
| 测试用例生成 | DeepSeek AI 生成 pytest（无 Key 降级为规则骨架），语法校验 + 一键运行（沙箱隔离） |
| **批量测试生成** | `/tests all` 一次为所有文件生成测试用例 |
| 改进建议 | AI 逐条修复建议 + 整体总结（无 Key 降级为规则建议） |
| **批量建议** | `/advice all` 一次为所有文件生成改进建议 |
| AI 代码修复 | AI 直接输出修复后完整代码，语法校验 + 签名比对 + 行为等价性验证，diff 展示，一键写回（自动备份） |
| **批量修复** | `/fix all` 一次修复所有有坏味的文件，`/fix all apply` 写入所有修复 |
| 报告导出 | Markdown / JSON / SARIF（GitHub Code Scanning 标准）/ HTML 四种格式 |
| 阈值配置 | 坏味阈值、可读性权重可通过 `/config set` 动态调整并持久化（data/config.json） |
| **历史趋势+预警** | 每次分析记录摘要，ASCII 趋势图（▁▂▃▄▅▆▇█）+ 质量下降预警 |
| 忽略规则 | 项目根 `.pyqualityignore`（fnmatch 语法）跳过指定文件 |
| **前端增强** | 对话历史持久化(localStorage)、键盘快捷键(↑↓/Tab/Ctrl+L/Ctrl+K)、命令参数补全 |
| 鲁棒性 | 统一错误处理中间件、结构化日志、请求计时、输入校验、AI 全链路降级 |

## 架构

```
backend/                FastAPI 后端
├── main.py             应用入口（lifespan + 静态托管 + SPA fallback）
├── config.py           配置：API Key 链、坏味阈值、评分权重、持久化加载
├── database.py         SQLite 项目/文件/分析缓存/分析历史存储
├── schemas.py          Pydantic 请求/响应模型
├── routers/
│   ├── projects.py     上传（zip 防路径穿越）、列表、删除、文件读取
│   ├── analysis.py     11 类分析器编排 + 报告导出（md/json/sarif/html）+ 历史趋势
│   ├── ai.py           AI 状态、测试生成、运行测试、修复建议
│   ├── chat.py         对话端点（意图解析 + 命令路由 + markdown 回复）
│   └── config.py       分析阈值 GET/PUT（持久化）
├── analyzers/
│   ├── parser.py       AST 解析（函数/类/导入/名字使用分析）
│   ├── complexity.py   McCabe 圈复杂度 + 嵌套深度
│   ├── smells.py       坏味规则引擎 + 重复代码检测
│   ├── readability.py  加权评分模型
│   ├── security.py     安全检测
│   ├── dependencies.py 依赖图 + 循环检测
│   ├── dead_code.py    死代码检测（跨文件引用分析）
│   ├── type_hints.py   类型提示覆盖率
│   ├── docstrings.py   文档覆盖率
│   ├── performance.py  性能热点
│   └── duplication.py  结构性重复
└── ai/
    ├── deepseek_client.py  DeepSeek API 客户端（重试/超时/JSON模式）
    ├── test_generator.py   pytest 测试生成（AI + 规则降级）
    ├── advisor.py          修复建议（AI + 规则降级）
    └── fixer.py            AI 代码修复

frontend/               Codex 风格对话界面（原生 HTML/CSS/JS，深色/亮色主题，无构建依赖）
tests/                  pytest 单元测试 + API 端到端测试（228 用例，离线可重复）
scripts/                AI 量化验收度量脚本 + 核心功能综合验证脚本
samples/                故意含坏味的示例项目
```

## 启动

```bash
pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 http://127.0.0.1:8000

## 配置 AI（可选）

Key 读取顺序：环境变量 `DEEPSEEK_API_KEY` → `.env` 文件 → `COMMONSENSE_API_KEY`。

```bash
# 方式一：环境变量
set DEEPSEEK_API_KEY=sk-xxxx

# 方式二：项目根目录 .env 文件
DEEPSEEK_API_KEY=sk-xxxx
```

未配置时坏味检测和评分照常工作，测试生成/修复建议自动降级为规则模式。

## 测试

```bash
python -m pytest tests/ -v
```

测试通过 conftest 自动隔离 AI 调用（monkeypatch 为规则降级模式），无需网络即可运行。

## AI 输出量化验收

```bash
python scripts/ai_metrics.py      # AI 量化验收（14 项指标）
python scripts/verify_all.py      # 核心功能综合验证（66 项）
```

验收指标覆盖测试生成（语法/收集/执行/覆盖/断言密度/BUG 检出）、代码修复（语法保留/函数保留/坏味消除/编译）、改进建议（坏味覆盖/行号准确/类型准确/可操作性），全部达标。

## 对话命令

在对话界面输入斜杠命令或自然语言关键词：

| 命令 | 说明 | 自然语言示例 |
| --- | --- | --- |
| `/help` | 查看命令帮助 | 帮助 |
| `/projects [关键词]` | 列出/搜索项目 | 看看项目 |
| `/use <id>` | 切换项目 | — |
| `/sample` | 加载示例项目 | — |
| `/files` | 列出项目文件 | 文件 |
| `/snippet <代码>` | 直接分析代码片段 | — |
| `/dashboard` | 全局仪表盘 | 仪表盘 |
| `/analyze [all]` | 执行分析 / 批量分析所有项目 | 分析一下 |
| `/summary` | 分析概览（含智能推荐） | 概览 |
| `/smells` | 代码坏味（按严重度排序+统计） | 有什么坏味 |
| `/score` | 可读性评分 + 项目健康度 | 评分 |
| `/security` | 安全问题 | 安全 |
| `/deps` | 依赖关系 | 依赖 |
| `/deadcode` | 死代码检测 | — |
| `/funcs` | 函数复杂度热力图 | — |
| `/compare <id>` | 对比当前项目与另一项目 | 对比 |
| `/tests [all\|文件]` | AI 生成测试 / 批量生成 | 生成测试 |
| `/fix [all\|apply\|文件]` | AI 修复 / 批量修复 / 写入修复 | 修复 |
| `/advice [all\|文件]` | AI 建议 / 批量建议 | 建议 |
| `/config [set\|reset]` | 查看/修改/重置阈值 | — |
| `/history` | 分析历史趋势+预警 | — |
| `/export [格式]` | 导出报告 | — |

## API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/projects/upload | 上传项目（multipart: archive(zip) 或 files[], name, description） |
| POST | /api/projects/sample | 一键加载内置示例项目 |
| GET | /api/projects | 项目列表 |
| GET | /api/projects/{id} | 项目详情（含文件列表） |
| DELETE | /api/projects/{id} | 删除项目 |
| GET | /api/projects/{id}/file?path= | 读取项目内文件 |
| POST | /api/projects/{id}/analyze | 全项目分析（11 类分析器，尊重 .pyqualityignore） |
| POST | /api/projects/{id}/analyze-file | 单文件分析 |
| GET | /api/projects/{id}/analysis | 读取缓存的分析结果 |
| GET | /api/projects/{id}/history?limit= | 分析历史趋势 |
| GET | /api/projects/{id}/report?format=markdown\|json\|sarif\|html | 导出报告 |
| POST | /api/projects/{id}/generate-tests | AI 生成 pytest 测试 |
| GET | /api/projects/{id}/generated-tests | 列出已生成测试 |
| POST | /api/projects/{id}/run-tests | 运行生成的测试（沙箱，60s 超时） |
| POST | /api/projects/{id}/advice | AI 修复建议 |
| POST | /api/projects/{id}/fix | AI 代码修复（apply=true 写回并备份） |
| GET | /api/ai/status | AI 可用性状态 |
| GET | /api/config | 读取分析阈值 |
| PUT | /api/config | 更新分析阈值（持久化） |
| GET | /api/health | 健康检查 || POST | /api/chat | 对话端点（意图解析 + 命令路由 + markdown 回复） |