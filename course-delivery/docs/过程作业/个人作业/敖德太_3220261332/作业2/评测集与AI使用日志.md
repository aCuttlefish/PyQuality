# PyQuality 评测集与 AI 使用日志

《软件理论与工程》过程作业 2

敖德太 · 3220261332

这里重点检查两类边界：多件商品的合计金额恰好达到优惠门槛，以及同一邮箱出现大小写或首尾空格差异。

业务场景为团队设计的固定样例，候选代码来自真实 DeepSeek 调用。验收人可到 `eval/real_cases/` 对照场景、确认计划与实际报告，并在 Docker 中复跑留存代码。预期值依据需求独立核算，两个版本使用同一最终计划。

完整基线为电商 **10/11 → 11/11**、通讯录 **5/9 → 9/9**，两组均从 `FAIL` 变为 `PASS_WITHIN_SCOPE`。下表展示所选的独立评测条目，两个证据编号分别指向初始和再生成报告。

## 电商满减 · 8 条

原始材料见 `eval/real_cases/order_discount/`。

| 案例 | 需求 | 入参 | 预期或断言 | 初始实际 | 再生成实际 | 证据编号（前 / 后） |
| --- | --- | --- | --- | --- | --- | --- |
| M01 | R3 | `[[]]` | `"0.00"` | `"0.00"` · `PASSED` | `"0.00"` · `PASSED` | `EV-5c9c250d5805` / `EV-cfd3a66a06ee` |
| M02 | R1 | `[[{"price":"19.90","quantity":2},{"price":"9.90","quantity":1}]]` | `"49.70"` | `"49.70"` · `PASSED` | `"49.70"` · `PASSED` | `EV-fd04d4b68231` / `EV-0ab6e10ea529` |
| M03 | R2 | `[[{"price":"100.00","quantity":1}]]` | `"80.00"` | `"80.00"` · `PASSED` | `"80.00"` · `PASSED` | `EV-938b8d10c6c0` / `EV-728f16eaa5c8` |
| M05 | R1/R2 | `[[{"price":"100.01","quantity":1}]]` | `"80.01"` | `"80.01"` · `PASSED` | `"80.01"` · `PASSED` | `EV-50a55f2c242e` / `EV-688cf7931f93` |
| M06 | R1/R2 | `[[{"price":"73.96","quantity":1},{"price":"4.14","quantity":1},{"price":"21.90","quantity":1}]]` | `"80.00"` | `"80.00"` · `PASSED` | `"80.00"` · `PASSED` | `EV-8f7758818ed5` / `EV-3640881f1300` |
| M08 | R1/R3 | `[[{"price":"0.10","quantity":3}]]` | `"0.30"` | `"0.30"` · `PASSED` | `"0.30"` · `PASSED` | `EV-b381c3bcc5d0` / `EV-976bf6c824e8` |
| M09 | R3 | `[[{"price":"0.00","quantity":1}]]` | `"0.00"` | `"0.00"` · `PASSED` | `"0.00"` · `PASSED` | `EV-d0da9d6ac7a9` / `EV-4603394de50d` |
| M11 | R1/R2 | `[[{"price":"49.05","quantity":1},{"price":"41.90","quantity":1},{"price":"9.05","quantity":1}]]` | `"80.00"` | `"100.00"` · `ASSERTION_FAILED` | `"80.00"` · `PASSED` | `EV-a63e6a8957ba` / `EV-6ce58f640415` |

### 预期值依据

- `M01` 空购物车明确返回 0.00
- `M02` 19.90 × 2 + 9.90 = 49.70，不满减
- `M03` 100.00 达到门槛，减 20.00
- `M05` 100.01 减 20.00 = 80.01
- `M06` 十进制精确和为 100.00，须优惠 20.00
- `M08` 0.10 × 3 = 0.30
- `M09` 零金额按两位小数格式返回
- `M11` 十进制精确和为 100.00；Docker Python 3.10 的 float 求和为 99.99999999999999，须保持满减资格

## 通讯录去重 · 5 条

原始材料见 `eval/real_cases/contact_import/`。

| 案例 | 需求 | 入参 | 预期或断言 | 初始实际 | 再生成实际 | 证据编号（前 / 后） |
| --- | --- | --- | --- | --- | --- | --- |
| C03 | R3 | `[[{"name":"Bob 原始记录","email":" bob@example.com "},{"name":"Alice 首次导入","email":"Alice@Example.com"},{"name":"Carol","email":"carol@example.com"}]]` | `[{"name":"Bob 原始记录","email":" bob@example.com "},{"name":"Alice 首次导入","email":"Alice@Example.com"},{"name":"Carol","email":"carol@example.com"}]` | `[{"name":"Bob 原始记录","email":" bob@example.com "},{"name":"Alice 首次导入","email":"Alice@Example.com"},{"name":"Carol","email":"carol@example.com"}]` · `PASSED` | `[{"name":"Bob 原始记录","email":" bob@example.com "},{"name":"Alice 首次导入","email":"Alice@Example.com"},{"name":"Carol","email":"carol@example.com"}]` · `PASSED` | `EV-c0c8df506895` / `EV-9d215ebb5e2c` |
| C04 | R2 | `[[{"name":"Alice 首次导入","email":"Alice@Example.com"},{"name":"Alice 后续更新","email":"Alice@Example.com"}]]` | `[{"name":"Alice 首次导入","email":"Alice@Example.com"}]` | `[{"name":"Alice 首次导入","email":"Alice@Example.com"}]` · `PASSED` | `[{"name":"Alice 首次导入","email":"Alice@Example.com"}]` · `PASSED` | `EV-9a4cdbb3c852` / `EV-e0654b591df0` |
| C06 | R1/R2 | `[[{"name":"Bob 原始记录","email":" bob@example.com "},{"name":"Bob 重复记录","email":"bob@example.com"}]]` | `[{"name":"Bob 原始记录","email":" bob@example.com "}]` | `[{"name":"Bob 原始记录","email":" bob@example.com "},{"name":"Bob 重复记录","email":"bob@example.com"}]` · `ASSERTION_FAILED` | `[{"name":"Bob 原始记录","email":" bob@example.com "}]` · `PASSED` | `EV-5997b3f9fb3f` / `EV-6c2c3b5cfa4a` |
| C07 | R2/R3 | `[[{"name":"Bob 原始记录","email":" bob@example.com "},{"name":"Alice 首次导入","email":"Alice@Example.com"},{"name":"Bob 重复记录","email":"bob@example.com"},{"name":"Carol","email":"carol@example.com"}]]` | `[{"name":"Bob 原始记录","email":" bob@example.com "},{"name":"Alice 首次导入","email":"Alice@Example.com"},{"name":"Carol","email":"carol@example.com"}]` | `[{"name":"Bob 原始记录","email":" bob@example.com "},{"name":"Alice 首次导入","email":"Alice@Example.com"},{"name":"Bob 重复记录","email":"bob@example.com"},{"name":"Carol","email":"carol@example.com"}]` · `ASSERTION_FAILED` | `[{"name":"Bob 原始记录","email":" bob@example.com "},{"name":"Alice 首次导入","email":"Alice@Example.com"},{"name":"Carol","email":"carol@example.com"}]` · `PASSED` | `EV-5576e2e8e276` / `EV-2acaa52725ae` |
| C09 | R1/R2/R3 | `[[{"name":"Alice 首次导入","email":"Alice@Example.com"},{"name":"重复","email":"  ALICE@EXAMPLE.COM  "},{"name":"Bob 原始记录","email":" bob@example.com "}]]` | `[{"name":"Alice 首次导入","email":"Alice@Example.com"},{"name":"Bob 原始记录","email":" bob@example.com "}]` | `[{"name":"Alice 首次导入","email":"Alice@Example.com"},{"name":"重复","email":"  ALICE@EXAMPLE.COM  "},{"name":"Bob 原始记录","email":" bob@example.com "}]` · `ASSERTION_FAILED` | `[{"name":"Alice 首次导入","email":"Alice@Example.com"},{"name":"Bob 原始记录","email":" bob@example.com "}]` · `PASSED` | `EV-a238f18e65eb` / `EV-42b38a98d1d1` |

### 预期值依据

- `C03` 不同邮箱按输入顺序输出
- `C04` 相同邮箱不同姓名时保留第一条完整记录
- `C06` 去除首尾空格后相同，保留第一条且不改写原 email
- `C07` 去重后仍按原始首次出现顺序排列
- `C09` 同时存在大小写与空格差异，保持第一条和顺序

## AI 使用日志

| 模型与环节 | 输入和输出原件 | 验证 |
| --- | --- | --- |
| 2026-11-15 · DeepSeek `deepseek-chat` · 电商满减初次生成及改写后再生成 | `eval/real_cases/order_discount/` 的 `initial_prompt.txt`、`optimized_prompt.txt`、`model_initial.json` 和 `model_regenerated.json`。 | 原代码保留。补充目标环境可复现的 `M11` 后冻结 11 条计划，使用同一计划核对前后报告。 |
| 2026-11-15 · DeepSeek `deepseek-chat` · 通讯录初次生成及改写后再生成 | `eval/real_cases/contact_import/` 下同名文件。 | 用 9 条固定案例核对邮箱比较键、保留首条记录及输入不变等行为。 |
| 本次交付整理 · Codex | 陈宏伟提供课程模板，借助 Codex 按案例编号整理输入、预期和实际结果。 | 检查前后计划摘要、案例输入和预期值一致。 |
