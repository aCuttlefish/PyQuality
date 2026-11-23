# 两个真实模型实测案例

实测日期：2026-11-15。生成模型：DeepSeek `deepseek-chat`。
候选代码由真实模型生成，验收在真实 Docker Python 3.10 容器中执行；
新代码使用 **PyQuality 输出的优化提示词**再次调用模型生成，没有手工修改模型代码。

这里的“真实”指真实模型调用、原始输出和执行结果可复查。
业务场景、联系人姓名及验收标准由课设实验设计，**不是对某公司线上事故或真实用户数据的引用**。

## 结果总览

| 案例 | 初始代码 | 用工具优化提示词后重新生成 | 相同验收计划 |
| --- | --- | --- | --- |
| 电商满减金额计算 | 10/11 通过，FAIL | 11/11 通过，PASS_WITHIN_SCOPE | 是 |
| 通讯录邮箱去重 | 5/9 通过，FAIL | 9/9 通过，PASS_WITHIN_SCOPE | 是 |

每个案例的初始代码与修正代码都在 **同一个最终确认计划**下执行。
另已用留存代码离线重放一遍，得到相同的功能结果。
真实模型建议在原始报告中；离线重放采用规则降级，不冒充新的模型调用。

## 案例一：电商满减，程序能运行却漏掉了 20 元优惠

### 业务需求

购物车每项含金额字符串 `price` 和整数 `quantity`。
精确计算总价；总价达到或超过 100.00 元，优惠 20.00 元一次；
返回两位小数的金额字符串，且不修改购物车数据。

### 初始提示词和模型代码

初始提示词明确要求“先将每项 price 转成 float……逐项累加后判断是否满 100 元”。
这是本案例需要检查的工程选择，不能说成模型无提示自行引入 float。

模型原始代码：

```python
def calculate_payable(items):
    total = sum(float(item['price']) * item['quantity'] for item in items)
    if total >= 100:
        total -= 20
    return f"{total:.2f}"
```

普通输入如单项 100.00 元能够正确返回 80.00，看起来功能已经完成。

### PyQuality 找到的真实反例

| 商品 | 单价 | 数量 |
| --- | --- | --- |
| A | 49.05 | 1 |
| B | 41.90 | 1 |
| C | 9.05 | 1 |

十进制总价为 `49.05 + 41.90 + 9.05 = 100.00`，应优惠后返回 `"80.00"`。
实际 Docker Python 3.10 中的 float 求和为 `99.99999999999999`，
门槛判断不成立，模型代码实际返回 **`"100.00"`**。
对应失败案例为 `M11`，可查验真实输入、固定预期及观察值。

PyQuality 判定 **FAIL**，并把使用 float 与“精确十进制金额计算”的要求映射为 **CONFLICT**。
代码建议要求从金额字符串构造 `decimal.Decimal`，用 Decimal 完成求和、门槛判断和格式化。

### 提示词改进及复评

工具的新提示词补入：

> 请使用精确十进制金额计算（例如 decimal.Decimal），不得使用二进制浮点数进行金额转换或累加。

完整新提示词还保留满减、只减一次、两位小数、空购物车及不修改输入的要求。
直接把这份提示词重新提交给模型，模型改用了 `Decimal`。
在同一个 11 案例计划下，结果从 **10/11、FAIL** 变为 **11/11、PASS_WITHIN_SCOPE**。

### 这说明工具的什么价值

代码语法正确、常规样例通过，仍可能违反业务规则。
工具通过执行反例给出“期望 80.00、实际 100.00”的证据，
并定位到原提示词中的技术选择冲突，给出可用于重新生成代码的修改建议。
即使通过比例为 90.9%，一条有效的必要需求反例仍然导致失败，不靠平均分掩盖问题。

### 实验过程说明

第一次使用的 10 项检查全部通过，记录保存在
[`preliminary_10_cases/initial_report.json`](order_discount/preliminary_10_cases/initial_report.json)。
其中一组在主机 Python 3.13 上出现的浮点边界，在 Docker Python 3.10 上没有触发。
随后增加了在目标运行时核对过的 `M11`，**保持同一份初始模型代码不变**，
冻结最终 11 项标准，再与新提示词生成的代码进行同标准比较。
这不是盲测基准，也不隐瞒第一次通过的结果，展示的是补充边界测试后的缺陷发现与修正验证。

材料：

- [初始提示词](order_discount/initial_prompt.txt) / [原始模型响应](order_discount/model_initial.json)
- [初始代码](order_discount/initial_code.py) / [初始验收报告](order_discount/initial_report.json)
- [优化提示词](order_discount/optimized_prompt.txt) / [重新生成的代码](order_discount/regenerated_code.py)
- [重新生成后的验收报告](order_discount/regenerated_report.json)

## 案例二：通讯录导入，“按邮箱去重”没有覆盖真实业务规则

### 业务需求

导入联系人时，以去除首尾空格并忽略大小写后的邮箱作为比较键；
重复时保留第一条完整记录，保持首次出现顺序。
只规范化比较键，不改写输出联系人原来的邮箱内容，也不修改输入数据。

### 初始提示词和模型代码

初始提示词只要求：

> 按 email 字段去重，每个邮箱只保留一条，返回去重后的联系人列表。用字典实现，代码简洁。

没有说明比较邮箱需要去空格、忽略大小写。模型初始实现的核心是：

```python
seen = {}
for contact in contacts:
    email = contact.get('email')
    if email not in seen:
        seen[email] = contact
return list(seen.values())
```

这里模型已经正确选择了保留首次出现的记录。
因此不能把“保留首条错误”作为本次发现，实际缺陷是比较键没有规范化。

### PyQuality 找到的真实反例

| 输入的两个邮箱 | 期望 | 初始实现实际结果 |
| --- | --- | --- |
| `Alice@Example.com`、`alice@example.com` | 保留第一条，共 1 条 | 保留 2 条 |
| `" bob@example.com "`、`bob@example.com` | 保留第一条，共 1 条 | 保留 2 条 |
| 大小写、空格与其他联系人混合 | 合并重复，保持首次顺序 | 重复联系人残留 |

失败案例为 `C05`、`C06`、`C07`、`C09`。
初始实现 **5/9 通过，判定 FAIL**。

工具指出提示词未体现比较键规范化等要求，建议将比较键改为
`email.strip().lower()`，同时仍然保存和返回原始 `contact`，
以满足“不改写输出邮箱”的要求。

### 提示词改进及复评

工具的新提示词补入：

> 比较邮箱时须去除首尾空格并忽略字母大小写；去重键的规范化不得改变输出记录原有的 email 内容。

并明确保留第一次出现的完整记录、保持顺序、不修改输入及空列表行为。
使用该提示词重新调用模型后，新代码采用：

```python
email = contact.get("email", "")
key = email.strip().lower()
if key not in seen:
    seen[key] = contact
```

在原有同一组 9 项检查下，结果变为 **9/9 通过，PASS_WITHIN_SCOPE**。

### 这说明工具的什么价值

自然语言中的“去重”往往没有说明比较规则。工具把完整业务需求转成具体检查，
发现“代码能运行但没有达到效果”的问题，同时区分：
提示词未明确要求保留首条，但代码已经正确实现；真正的执行反例集中在规范化遗漏。
因此不会把每一项提示词遗漏都直接当成代码缺陷。

材料：

- [初始提示词](contact_import/initial_prompt.txt) / [原始模型响应](contact_import/model_initial.json)
- [初始代码](contact_import/initial_code.py) / [初始验收报告](contact_import/initial_report.json)
- [优化提示词](contact_import/optimized_prompt.txt) / [重新生成的代码](contact_import/regenerated_code.py)
- [重新生成后的验收报告](contact_import/regenerated_report.json)

## 三分钟演示顺序

1. 打开 `/acceptance.html`，在示例列表选择两个“真实模型实测”案例之一，点击填入。
2. 展示完整业务需求、原提示词及模型代码，说明代码来源有原始 JSON 可复查。
3. 核对固定测试案例并确认，点击开始验收，展示失败输入、期望和实际输出。
4. 展示工具的提示词诊断和改写建议。
5. 点击“换入示例正确实现”，页面同时换入真实重新生成的代码和它对应的新提示词。
6. 复用同一标准再次验收，展示前后结果。

示例按钮加载的是已保存的真实模型输出，便于稳定复现；
这不等于演示时再次调用模型生成代码。评估中的模型建议仍取决于当时的模型服务。

离线复现功能结果：

```powershell
.venv/Scripts/python.exe scripts/run_real_cases.py --replay
```

重放仅执行留存代码，不再次访问模型，报告写入 `data/real_cases_replay/`。
原始实测报告中的模型诊断与新提示词在 `docs/real_cases/` 留存。
以上是两个案例的观察结果，不能据此推算对任意 AI 代码的检出率，
也不能据一次重新生成成功宣称提示词优化具有统计意义上的普遍提升。
