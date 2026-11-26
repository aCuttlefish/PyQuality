# PyQuality 核心功能与实现说明

> 版本：v4.0 ｜ 架构：FastAPI + Pydantic v2 + SQLite(WAL) + 原生前端（零构建）+ DeepSeek API（可降级）

## 功能总览

```
┌─────────────────────────────────────────────────────────┐
│  前端（聊天页 index.html + 验收页 acceptance.html）        │
├─────────────────────────────────────────────────────────┤
│  聊天命令系统 (chat.py)     │  代码验收 API (acceptance.py) │
├─────────────────────────────────────────────────────────┤
│  静态分析引擎 (analyzers/)  │  验收内核 (acceptance/)       │
│  11 类确定性分析器          │  规约→隔离执行→判定→报告      │
├─────────────────────────────────────────────────────────┤
│  AI 混合层 (ai/)  DeepSeek + 规则降级，离线可用           │
├─────────────────────────────────────────────────────────┤
│  SQLite 存储层 (database.py)  项目/分析/会话/快照         │
└─────────────────────────────────────────────────────────┘
```

---

## 一、静态代码分析（确定性规则引擎）

**入口**：`POST /api/projects/{pid}/analyze` → `analysis.py:_build_analysis`

对项目全部 `.py` 文件（尊重 `.pyqualityignore`）执行 11 类分析，全部基于 AST，不依赖模型：

| 分析器 | 文件 | 检测内容 |
|--------|------|---------|
| AST 解析 | `analyzers/parser.py` | 函数/类/复杂度/注释/导入统计，语法错误带行号 |
| 代码坏味 | `analyzers/smells.py` | 长函数、深嵌套、魔法数字、未用变量（含函数作用域）、坏命名、裸 except、全局变量、重复块 |
| 可读性评分 | `analyzers/readability.py` | 0-100 综合分 + A-E 等级 |
| 安全检测 | `analyzers/security.py` | eval/exec、硬编码密钥、shell 注入、SQL 拼接 |
| 依赖分析 | `analyzers/dependencies.py` | import 图、循环依赖检测、相对导入解析 |
| 类型提示 | `analyzers/type_hints.py` | 参数/返回值注解覆盖率 |
| 文档字符串 | `analyzers/docstrings.py` | docstring 覆盖率 |
| 性能坏味 | `analyzers/performance.py` | 字符串拼接、循环内重复计算 |
| 重复代码 | `analyzers/duplication.py` | 跨文件重复块检测 |
| 死代码 | `analyzers/dead_code.py` | 未引用函数/模块 |
| 复杂度 | `analyzers/complexity.py` | 圈复杂度 + 嵌套深度 |

**关键实现点**：
- 分析结果双写：当前缓存（`/summary`、`/smells` 等命令读取）+ 历史快照（`analysis_history.result_text` 存完整 JSON）
- 阈值动态可配置并持久化到 `data/config.json`，权重/阈值校验后才提交
- 前端通过 `/history <ID>` 回看任意一次历史分析完整结果

---

## 二、AI 混合层（DeepSeek + 全链路规则降级）

**入口**：`ai/deepseek_client.py` 统一模型调用；三个业务模块复用

| 能力 | 实现 | 降级行为（无 API Key / 超时 / JSON 非法） |
|------|------|------|
| AI 测试生成 | `ai/test_generator.py` | 规则模板生成 pytest 用例 |
| AI 代码修复 | `ai/fixer.py` | 规则修复（拆长函数等确定性改写） |
| AI 改进建议 | `ai/advisor.py` | 基于坏味清单的固定建议库 |

**关键护栏（v2.0 审查修复成果）**：
1. **修复三重验证**（`fixer.py:validate_fixed`）：签名变更/缺导入/缺 main guard → `valid=False` 拒绝写入；行为验证（跑测试对比前后）失败阻止 apply
2. **候选缓存**：预览时保存候选代码返回 candidate_id，apply 时从缓存取，避免重复调用
3. **沙箱环境**（`config.py:build_sandbox_env`）：子进程执行时屏蔽 API Key、限制 TMPDIR，防止密钥泄漏到被测代码
4. **失败测试不删除**：`_run_and_filter_tests` 只统计失败数，不删测试函数
5. **上下文截断保护**：单文件源码 6000-8000 字符上限，模型上下文不会爆炸

---

## 三、聊天命令系统（30+ 命令的自然语言入口）

**入口**：`POST /api/chat` → `routers/chat.py`（1445+ 行，命令路由 + 会话集成）

**命令分派**：`_parse_intent` 将用户消息映射到命令 + 参数，支持中文别名（如"分析"→`/analyze`）

| 类别 | 命令 |
|------|------|
| 分析 | `/analyze` `/summary` `/smells` `/score` `/security` `/deps` `/deadcode` `/funcs` `/tree` `/files` |
| 深度检查 | `/doc` `/type` `/dup` `/perf` `/refactor` `/search` `/ignore` |
| AI 任务 | `/tests` `/fix` `/advice` `/snippet` |
| 管理 | `/projects` `/use` `/rename` `/delete` `/dashboard` `/compare` `/export` `/cicd` `/config` `/history` |
| 会话 | `/sessions` `/session new\|<id>\|delete\|rename` |

**实现要点**：
- 命令 Tab 补全、上下箭头历史（前端 app.js）
- `/compare` 双项目指标对比表；`/dashboard` 多项目健康度排名
- `/fix` 返回带预览 diff 的 Markdown + `[text](url)` 链接渲染（内部链接同标签页，兼容 Safari 下载）

---

## 四、会话持久化与多会话管理（v3.0）

**解决的问题**：聊天记录原存 localStorage（换设备即丢），且所有对话混在一个流里

**实现**（`database.py` + `chat.py` + 前端侧栏）：
- 两张新表：`chat_sessions`（会话元数据）、`chat_messages`（消息，级联删除）
- `POST /api/chat` 携带 `session_id`，每条消息（user/ai）自动落库 SQLite
- REST API：`GET/POST /api/sessions`、`GET /api/sessions/{sid}/messages`、`PUT/DELETE /api/sessions/{sid}`
- 前端左侧会话侧栏：显示标题/消息数/时间，点击切换（从后端加载完整消息流），"＋新建"按钮
- `delete_project` 级联清理关联会话

---

## 五、历史分析快照（v3.0）

**解决的问题**：`/history` 只存 20 条摘要趋势，无法回看某次完整分析

**实现**：
- `analysis_history` 表增加 `result_text` 列，`save_analysis_snapshot()` 同时存摘要 + 完整分析 JSON
- `/history` 输出趋势图（ASCII 火柴图）+ 带快照 ID 的表格
- `/history <ID>` 从快照重建完整报告：可读性/坏味明细/安全问题，带 `_format_snapshot_result` 格式化
- 趋势预警：坏味增加、可读性下降时自动提示对应修复命令

---

## 六、需求驱动的代码验收 Agent（v4.0，M0-M4）

**解决的问题**：对「需求 R + 生成提示词 P + 代码 C」三元组做可信赖验收，三大功能彼此独立

**入口**：`POST /api/acceptance/evaluate` ｜ CLI `python -m backend.acceptance.cli` ｜ 独立页面 `acceptance.html`

### 核心工作流（阶段 A-F，`acceptance/service.py` 编排）

```
R/P/C 输入 → 编译检查(TECH_COMPILE) → 需求提取(夹具/LLM) → 测试计划+审查冻结
→ 隔离执行(真实子进程) → 确定规则判定 → 提示词诊断+建议 → EvaluationReport
```

### 模块职责（`backend/acceptance/`，14 个模块）

| 模块 | 职责 |
|------|------|
| `models.py` | Pydantic 严格契约：请求/规格/证据/报告，状态维度分离（job_status ≠ code_verdict ≠ assurance_level） |
| `hashing.py` | 统一序列化 hash：code_hash/spec_hash/plan_hash/request_hash，版本不匹配拒绝复用证据 |
| `verdict.py` | **纯规则判定内核**（方案 8.1-8.3 逐字实现）：证据门槛 → 需求状态 → 聚合，模型零参与 |
| `checks.py` | 7 种固定断言模板：RETURN_EQUALS（无类型强转）/RETURN_IS_NONE/RAISES（白名单异常）/INPUT_UNCHANGED（前快照对比）/ALL_ITEMS_MATCH/ORDERED/SAME_MULTISET（带类型多重集） |
| `runner.py` | 隔离执行器：子进程 + 沙箱环境 + 任务临时目录 + 结果文件协议；stdout 不能控制 verdict；超时终止 |
| `fixtures.py` | max_even/payable 人工确认夹具（USER_CONFIRMED 规格 + 固定 TestPlan） |
| `llm_provider.py` | DeepSeek 薄适配层；受保护字段（verdict/verified/evidence）schema 层拒绝 |
| `spec_extractor.py` | 需求提取：source_quote 程序校验（不在 R 原文中的引用直接拒绝） |
| `review.py` | 测试计划生成 + 规约/oracle 审查（语义审查通过 = AUTO_REVIEWED，非数学证明） |
| `prompt_auditor.py` | 提示词映射（COVERED/CONFLICT/MISSING...6 态）+ 改写 + 与代码结果关联（不写因果） |
| `recommender.py` | 代码建议：每条关联 finding/requirement_ids/evidence_ids，LLM + 规则模板双模式 |
| `service.py` | 端到端编排：含 confirmed_only/source_backed 双策略、TECH_COMPILE 聚合 |

### 关键设计保证（防伪造机制）

- **verdict 只由 `aggregate_verdict` 确定规则生成** — 一条符合门槛的确认反例即 FAIL；全部认可检查执行且通过才 PASS_WITHIN_SCOPE；否则 INCONCLUSIVE
- **模型不能**：创建执行证据（由 runner 生成）、伪造用户确认（USER_CONFIRMED 仅真实确认事件可赋值）、修改验收标准（A21/A22 场景测试验证拒绝）
- **测试通过率不作为 verdict 依据**；语法错误直接 FAIL 不伪造执行（A12）；超时 = INCONCLUSIVE 非性能违规（A16）
- 隔离级别如实报告：进程级沙箱（无 Docker 网络隔离），写入每份报告 limitations

---

## 七、项目管理与安全

**入口**：`routers/projects.py`

- 上传 `.zip` / 多文件，安全护栏：`Path.relative_to()` 防路径穿越、ZIP 文件数与单文件大小限制、解压安全检查
- SQLite 登记项目/文件元数据；`/rename` `/delete confirm`（二次确认）
- `/sample` 加载内置 9 坏味示例项目；`/snippet` 快速验收代码片段

---

## 八、报告导出

**入口**：`GET /api/projects/{pid}/report?format=...`（`analysis.py:export_report`）

四种格式：**markdown**（结构化文档）/ **json**（完整分析数据）/ **sarif**（GitHub Code Scanning 兼容，startLine ≥ 1）/ **html**（独立可分享页面）。`Content-Disposition: attachment` 触发下载。

---

## 九、前端界面

- **聊天页**（`index.html` + `app.js`）：视口锁定布局（输入框钉底），会话侧栏，Markdown 渲染（代码高亮/表格/链接），Tab 命令补全，深/亮主题
- **验收页**（`acceptance.html`）：R/P/C 三输入 + 可折叠输入区 + 三块结果（验收结论/提示词诊断/建议）+ 执行证据表

---

## 十、质量保障

- **357 个 pytest 测试**（conftest 自动禁用真实 AI + 每测试清理数据库，离线可重复）
- 其中 101 个验收测试：判定内核纯函数 / 7 种检查模板 / 真实子进程执行（5/2、7/0 夹具结果与设计文档 15.1 一致）/ mock 明确标注（仅 `test_acceptance_llm_mock.py`）
- 三份真实报告样本：`docs/acceptance_samples/{report_fail,report_pass,report_inconclusive}.json`
- `scripts/ai_metrics.py`：14 项 AI 输出量化验收指标（BUG 检出率基线对比法）

---

## 运行命令

```bash
# 启动
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# 测试
python -m pytest tests/ -q

# 验收 CLI（真实执行演示）
python -m backend.acceptance.cli demo max_even-wrong
```

## 已知边界（如实声明）

1. 隔离执行为进程级沙箱，非 Docker 网络隔离/资源限额
2. M5 可选功能（Hypothesis/CrossHair/修复候选生成）未实施，SKIPPED 不产生虚假证据
3. MVP 不对任意 Python/任意自然语言需求提供普遍正确性证明