# PyQuality 课程项目个人复盘报告

敖德太　3220261332　案例设计与项目评测

## 一、我的分工与人机协作

电商满减实验最值得写进复盘的数字，其实是初筛时的 10/10。当时十项全部通过，那份程序却会让刚好满 100 元的顾客少拿 20 元优惠。从案例设计的角度看，真正要解释的是测试为什么漏掉了这个错误，以及后来加的那一项凭什么能把它测出来。

选例时可以请模型建议金额边界或异常输入。预期金额要按业务规则独立计算，触发条件还要放进交付用的 Python 环境验证。模型重新生成代码后，程序负责按冻结的计划运行，两轮原始输出都随报告保留。这样别人可以从输入开始重算一遍。

| 项目环节 | 模型参与 | 组员或程序的工作 |
| --- | --- | --- |
| 选例 | 建议边界输入 | 按业务规则计算金额 |
| 生成 | 编写候选代码 | 保留原始响应和版本 |
| 比较 | 建议修改提示词 | 冻结计划，复跑两份代码 |

## 二、三项工程取舍

（一）选一个读者能独立算出答案的例子。公开扑克牌案例可以逐张核对牌面和张数，实际生成 56 张就有了明确的检查对象。满减案例同样有这个好处。阈值和折扣写在需求里，预期金额可以直接算出来。

（二）在交付环境复现边界。一组在本机 Python 3.13 上出现的浮点边界，在 Docker 的 Python 3.10 环境里没有触发。我认为边界用例要同时写清业务上的预期和实际触发它的运行环境。

（三）保留初筛，冻结正式比较的计划。补入 M11 后，项目保留了最初的十例记录，并用最终十一例分别运行原代码和重新生成的代码。这样，比较的两端采用相同的难度。

## 三、恰好满 100 元的一笔订单

49.05、41.90 和 9.05 三件商品各买一件，合计正好 100.00 元，应付 80.00 元。原提示词要求用 float，原程序在目标环境中求和得到 99.99999999999999，没能触发满减，返回了 100.00 元。加入 M11 后，原代码通过 10/11。改写提示词明确要求精确十进制计算，模型重新生成的代码使用 Decimal，同一计划下通过 11/11。

下次设计类似评测，我会先列出低于阈值、恰好达到阈值和高于阈值的输入，再在目标环境逐一运行。探索时增加过哪些检查，同样值得写进报告。初筛漏测的经历，比单独报出最后的满分更能解释测试设计的作用。

## 四、AI 使用声明与日志

组长使用 Codex 辅助整理了本报告。下面两项均为项目组保存的 DeepSeek 实验。每项都保留了原始提示词、模型回答和前后两份运行报告。

2026 年 11 月 15 日，电商满减实验先按 float 生成候选代码，再用改写后的精确十进制要求重新生成。在冻结的十一项检查中，M11 的实际结果从 100.00 元变为 80.00 元［1］。

2026 年 11 月 15 日，通讯录实验把去除邮箱首尾空格、忽略大小写和保留第一条完整记录写入改进提示词。重新生成的代码在原九项检查中由 5 项通过提高到 9 项通过［2］。

## 项目记录

［1］[初次模型原始响应](https://github.com/aCuttlefish/PyQuality/blob/main/course-delivery/eval/real_cases/order_discount/model_initial.json)

［2］[重新生成的原始响应](https://github.com/aCuttlefish/PyQuality/blob/main/course-delivery/eval/real_cases/contact_import/model_regenerated.json)

［3］[评测方法与实验原件索引](https://github.com/aCuttlefish/PyQuality/blob/main/docs/real_cases/README.md)

［4］[金额实验初次验收报告](https://github.com/aCuttlefish/PyQuality/blob/main/course-delivery/eval/real_cases/order_discount/initial_report.json)

［5］[金额实验重新生成验收报告](https://github.com/aCuttlefish/PyQuality/blob/main/course-delivery/eval/real_cases/order_discount/regenerated_report.json)

［6］[扑克牌公开案例记录](https://github.com/aCuttlefish/PyQuality/blob/main/docs/public_cases/copilot_cards/case_report.txt)
