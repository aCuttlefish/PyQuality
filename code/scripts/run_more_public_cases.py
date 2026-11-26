"""两个公开 Copilot 示例的真实缺陷复现：52 张牌、零项组合。

首次运行调用已配置模型生成建议，--replay 关闭模型调用。
上游文件按固定 Git 提交下载和校验，原文件及含源码请求仅缓存在 data/。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from itertools import product
import json
import os
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CARD_ADAPTER = '''"""仅模拟终端输入并观察上游真实执行后的牌组，不生成或修正牌。"""
from contextlib import redirect_stdout
import io
from pathlib import Path
import runpy
from unittest.mock import patch


def inspect_deck(num_players, metric):
    answers = [str(num_players)] + ["Player " + str(i + 1) for i in range(num_players)]
    with patch("builtins.input", side_effect=answers), redirect_stdout(io.StringIO()):
        result = runpy.run_path(str(Path(__file__).with_name("upstream.py")), run_name="__main__")
    hands = [player["hand"] for player in result["players"]]
    dealt = [card for hand in hands for card in hand]
    all_cards = result["deck"] + dealt
    if metric == "deck_count":
        return len(all_cards)
    if metric == "cards":
        return sorted(all_cards)
    if metric == "hand_sizes":
        return [len(hand) for hand in hands]
    if metric == "dealt_unique":
        return len(dealt) == len(set(dealt))
    raise ValueError("Unknown observation metric")
'''

COMBINATION_ADAPTER = '''"""仅调用原始 possibilities 函数，不过滤、排序或改写返回结果。"""
from pathlib import Path
import runpy


def enumerate_terms(target, terms):
    namespace = runpy.run_path(str(Path(__file__).with_name("upstream.py")), run_name="public_case_import")
    return namespace["possibilities"](target, terms)
'''


def case(cid, rid, args, expected, basis):
    return {"case_id": cid, "requirement_ids": [rid], "contract_id": "K_" + rid,
            "args": args, "kwargs": {}, "input_domain_status": "IN_SCOPE",
            "assertion": {"kind": "RETURN_EQUALS", "expected": expected}, "expected_basis": basis}


def scenarios():
    ranks = [str(i) for i in range(2, 11)] + ["Jack", "Queen", "King", "Ace"]
    suits = ["Clubs", "Diamonds", "Hearts", "Spades"]
    expected_cards = sorted(rank + " of " + suit for rank in ranks for suit in suits)
    assert len(expected_cards) == len(set(expected_cards)) == 52
    cards_requirements = [
        ("R1", "初始牌组恰好包含 52 张牌。"),
        ("R2", "牌面为 2 至 10、Jack、Queen、King、Ace，每种牌面各有 Clubs、Diamonds、Hearts、Spades 四种花色，无其他牌。"),
        ("R3", "对 1 至 7 名玩家按原程序流程给每人发 7 张牌，已发出的牌不能重复。"),
    ]
    card_cases = [
        case("CARD01", "R1", [1, "deck_count"], 52, "13 种牌面乘 4 种花色为 52；统计剩余牌和已发牌总数"),
        case("CARD02", "R1", [2, "deck_count"], 52, "发牌不改变初始牌组的总张数"),
        case("CARD03", "R1", [7, "deck_count"], 52, "7 人发出 49 张牌，剩余 3 张，合计 52"),
        case("CARD04", "R2", [2, "cards"], expected_cards, "独立构造标准 13 牌面与 4 花色的笛卡尔积；完整比较 52 张牌"),
        case("CARD05", "R3", [2, "hand_sizes"], [7, 7], "两名玩家各收到 7 张牌"),
        case("CARD06", "R3", [4, "hand_sizes"], [7, 7, 7, 7], "四名玩家各收到 7 张牌"),
        case("CARD07", "R3", [7, "dealt_unique"], True, "已发出的 49 张牌应互不重复"),
    ]
    combo_requirements = [("R1", "对非负整数目标和 m 与项数 n，返回全部长度恰好为 n、元素为非负整数且元素之和为 m 的有序列表；无解返回空列表。")]
    combo_cases = []
    pairs = [(0, 0), (1, 0), (5, 0), (10, 0), (0, 1), (5, 1), (3, 2), (2, 3), (0, 3)]
    for i, (target, terms) in enumerate(pairs, 1):
        # 与上游的递归算法独立：穷举有限笛卡尔积后按长度和总和筛选。
        expected = [list(values) for values in product(range(target + 1), repeat=terms) if sum(values) == target]
        combo_cases.append(case(f"SUM{i:02d}", "R1", [target, terms], expected,
                                f"独立穷举 0..{target} 的 {terms} 次笛卡尔积，保留总和为 {target} 的序列"))
    return [
        {"id": "copilot_cards", "title": "声称 52 张的扑克牌程序实际生成 56 张",
         "repository": "Soneji/copilot-demos", "commit": "2f9edf5216f11c0f958d7370a862a82f1b72c3c4",
         "commit_date": "2021-09-25T01:27:42Z", "path": "cards.py",
         "blob": "a3ef6a56a439e3702a5558495a0f9920081ea009",
         "provenance_path": "README.md",
         "ai_note": "作者在 README 声明这是 GitHub Copilot 编写的代码；来源为作者自述，没有逐行生成日志。",
         "requirement": "验收原程序注释声明的标准扑克牌生成和发牌功能。" + "".join(s for _, s in cards_requirements),
         "requirements": cards_requirements, "cases": card_cases, "adapter": CARD_ADAPTER,
         "entrypoint": {"module": "solution", "callable": "inspect_deck"},
         "scope": "七项固定检查，玩家数 1、2、4、7；仅验收标准牌组与每人七张发牌，不验收完整游戏规则、随机性或安全性。",
         "original_task_note": "源文件开头注释要求生成全部 52 张牌；后文注释要求给每名玩家发 7 张互不重复的牌。",
         "repair_note": "操作者仅删除牌面列表开头多余的数字 1，保留 Ace，形成 13 种牌面。",
         "defect_note": "原程序同时把 1 和 Ace 列为不同牌面，14 种牌面乘 4 种花色得到 56 张。程序能运行并发牌，但结果违反注释声明。",
         "expected_passed": 3, "dataset_suffix": "/case2/cards.py"},
        {"id": "copilot_zero_terms", "title": "组合枚举工具把无解情况报告成一个空方案",
         "repository": "d4vidsha/github-copilot-examples", "commit": "b498862156248610dd0151a6cfb385d936ff94e2",
         "commit_date": "2022-05-26T23:15:35Z", "path": "target-sum-with-n-terms.py",
         "blob": "de3d76cfe7762503b6925b63cf423429a56fd7e0",
         "provenance_path": "target-sum-with-n-terms.py",
         "ai_note": "作者在源文件开头明确说明整个 possibilities 函数由 GitHub Copilot 生成；来源为作者自述，没有完整生成日志。",
         "requirement": "验收原程序声明的目标和组合枚举功能。" + combo_requirements[0][1],
         "requirements": combo_requirements, "cases": combo_cases, "adapter": COMBINATION_ADAPTER,
         "entrypoint": {"module": "solution", "callable": "enumerate_terms"},
         "scope": "九组固定非负整数输入；最大目标和 10，最大项数 3；不验收负数输入、大规模性能或未测试输入。",
         "original_task_note": "源文件任务说明要求找到用 n 项构成目标和 m 的所有方式；其函数显式处理 n=0，且界面没有排除零项。",
         "repair_note": "操作者在 n == 0 的分支增加 m == 0 条件；仅当目标和也为零时添加空方案。",
         "defect_note": "当 m=5、n=0 时，原程序返回 [[]] 并在界面计为一个方案，但空列表元素之和为 0，无法构成目标和 5；正确结果是 []，表示无解。",
         "expected_passed": 6, "dataset_suffix": "/case7/target-sum-with-n-terms.py"},
    ]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load_source(scenario):
    cache = ROOT / "data" / "public_cases" / scenario["id"]
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / "upstream.original.py"
    raw_url = f"https://raw.githubusercontent.com/{scenario['repository']}/{scenario['commit']}/{scenario['path']}"
    if not path.exists():
        request = urllib.request.Request(raw_url, headers={"User-Agent": "PyQuality-public-case-reproduction"})
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
        path.write_bytes(raw)
    raw = path.read_bytes()
    actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if actual != scenario["blob"]:
        raise RuntimeError(f"{scenario['id']} 源码 Git blob 不一致，拒绝执行")
    return cache, raw, raw.decode("utf-8")


def repair_source(scenario, original):
    if scenario["id"] == "copilot_cards":
        old, new = "cards = [1, 2,", "cards = [2,"
    else:
        old = "    if n == 0:\n        combos.append([])"
        new = "    if n == 0:\n        if m == 0:\n            combos.append([])"
    if original.count(old) != 1:
        raise RuntimeError("固定提交中的修复位置与预期不符")
    return original.replace(old, new, 1)


def confirm_standard(scenario):
    from backend.acceptance import standards
    body = standards.StandardConfirmation.model_validate({
        "requirement": scenario["requirement"], "entrypoint": scenario["entrypoint"],
        "confirmed": True, "case_scope_confirmed": True,
        "scope_note": "本次复现实验操作者独立核对固定输入与完整预期；不是原作者提供的测试记录。" + scenario["scope"],
        "spec": {"spec_id": "PUBLIC-DRAFT", "requirements": [
            {"id": rid, "statement": text, "source_quote": text, "origin": "EXPLICIT", "kind": "FUNCTIONAL", "mandatory": True}
            for rid, text in scenario["requirements"]]},
        "plan": {"plan_id": "PLAN-" + scenario["id"], "contracts": [
            {"contract_id": "K_" + rid, "requirement_ids": [rid], "description": text,
             "relation_to_requirement": "EQUIVALENT", "relation_basis": "完整预期的充分性仅限本轮列出的固定检查，不覆盖未测输入",
             "oracle_origin": "USER_EXAMPLE"} for rid, text in scenario["requirements"]],
            "cases": scenario["cases"]},
    })
    return standards.confirm(body)


def run_scenario(scenario, replay):
    from backend.acceptance.models import EvaluationRequest
    from backend.acceptance.service import evaluate
    cache, raw, original = load_source(scenario)
    repaired = repair_source(scenario, original)
    folder = ROOT / ("data/more_public_cases_replay" if replay else "docs/public_cases") / scenario["id"]
    folder.mkdir(parents=True, exist_ok=True)
    record = confirm_standard(scenario)
    write_json(folder / "confirmation.json", record)
    (folder / "adapter.py").write_text(scenario["adapter"], encoding="utf-8")
    source_url = f"https://github.com/{scenario['repository']}/blob/{scenario['commit']}/{scenario['path']}"
    provenance_url = f"https://github.com/{scenario['repository']}/blob/{scenario['commit']}/{scenario['provenance_path']}"
    provenance = {
        "repository": "https://github.com/" + scenario["repository"], "source_url": source_url,
        "ai_provenance_url": provenance_url, "ai_provenance": scenario["ai_note"],
        "commit": scenario["commit"], "commit_date": scenario["commit_date"], "git_blob": scenario["blob"],
        "source_sha256": hashlib.sha256(raw).hexdigest(), "source_bytes": len(raw),
        "original_source_unmodified": True, "original_prompt": "未公开；保留空字段，不以源代码注释冒充完整生成提示词。",
        "original_task_note": scenario["original_task_note"], "test_author": "本次复现实验操作者",
        "repair_author": "本次复现实验操作者，非上游作者或模型重新生成", "repair": scenario["repair_note"],
        "scope": scenario["scope"], "reproduced_at": datetime.now(timezone.utc).isoformat(),
        "advice_context": "实际辅助文件源码及从 1 开始的显式行号",
    }
    marker = "cards = [" if scenario["id"] == "copilot_cards" else "    if n == 0:"
    provenance["verified_source_location"] = {
        "file": scenario["path"], "line": next(i for i, line in enumerate(original.splitlines(), 1) if line.startswith(marker))}
    archive_path = ROOT / "data/public_case_research/dataset.zip"
    if archive_path.exists():
        from zipfile import ZipFile
        with ZipFile(archive_path) as archive:
            names = [n for n in archive.namelist() if n.endswith(scenario["dataset_suffix"])]
            if len(names) == 1:
                provenance["dataset_url"] = "https://zenodo.org/records/14565942"
                provenance["dataset_member"] = names[0]
                provenance["dataset_snapshot_matches"] = archive.read(names[0]).replace(b"\r\n", b"\n") == raw.replace(b"\r\n", b"\n")
    write_json(folder / "provenance.json", provenance)
    reports = {}
    adapter_hashes = []
    for phase, source in (("initial", original), ("repaired", repaired)):
        request = EvaluationRequest(
            requirement=scenario["requirement"], generation_prompt="", code=scenario["adapter"],
            supporting_files=[{"path": "upstream.py", "content": source}], entrypoint=scenario["entrypoint"],
            generation_context={"is_complete": False, "requirements_also_visible": None,
                "additional_messages": ["上游完整原始提示词未公开。只可给出后续代码生成可采用的新提示词建议，不能推断原提示词遗漏造成错误。"]},
            acceptance_materials={"confirmed_spec_id": record["confirmed_spec_id"], "confirmed_spec_hash": record["confirmed_spec_hash"]},
            options={"oracle_policy": "confirmed_only"},
        )
        adapter_hashes.append(hashlib.sha256(request.code.encode()).hexdigest())
        write_json(cache / f"{phase}_request.json", request.model_dump())
        report = evaluate(request)
        reports[phase] = report
        write_json(folder / f"{phase}_report.json", report.model_dump())
        print(json.dumps({"case": scenario["id"], "phase": phase, "verdict": report.code_verdict,
                          "coverage": report.coverage.model_dump(), "isolation": report.isolation_level,
                          "advice_modes": sorted({s.mode for s in report.code_suggestions if s.category == "CORRECTNESS_FIX"})},
                         ensure_ascii=False), flush=True)
    first, after = reports["initial"], reports["repaired"]
    same_plan = first.reproducibility.plan_hash == after.reproducibility.plan_hash
    same_adapter = adapter_hashes[0] == adapter_hashes[1]
    rows = []
    for check in scenario["cases"]:
        row = {"case_id": check["case_id"], "input": check["args"], "expected": check["assertion"]["expected"]}
        for phase, report in reports.items():
            ev = next(e for e in report.evidence if e.case_id == check["case_id"] and e.kind == "EXECUTED_CASE")
            row[phase] = {"status": ev.status, "observation": ev.observation}
        rows.append(row)
    summary = {"id": scenario["id"], "title": scenario["title"], "source_url": source_url,
               "ai_provenance_url": provenance_url, "same_plan": same_plan, "same_adapter": same_adapter,
               "adapter_sha256": adapter_hashes[0], "initial_verdict": first.code_verdict,
               "repaired_verdict": after.code_verdict, "initial": first.coverage.model_dump(),
               "repaired": after.coverage.model_dump(), "isolation": first.isolation_level,
               "cases": rows, "scope": scenario["scope"]}
    write_json(folder / "summary.json", summary)
    fixes = [s.model_dump() for s in first.code_suggestions if s.category == "CORRECTNESS_FIX"]
    write_json(folder / "code_advice.json", fixes)
    prompt = first.prompt_report.optimized_prompt
    (folder / "recommended_prompt.txt").write_text(
        "以下是本轮 PyQuality 的新提示词建议，不是作者的原始提示词。本实验未用它重新生成代码。\n\n" +
        (prompt or "本次复现已关闭模型调用；原始模型建议见 docs/public_cases 下留存的同名案例。"), encoding="utf-8")
    table = "\n".join(
        f"{r['case_id']} | 输入 {r['input']} | 预期 {json.dumps(r['expected'], ensure_ascii=False)} | "
        f"原程序 {r['initial']['status']} | 修复后 {r['repaired']['status']}" for r in rows)
    method = ("预期牌组由本次实验操作者独立构造，使用 13 种牌面与 4 种花色的笛卡尔积。"
              if scenario["id"] == "copilot_cards" else
              "预期组合由本次实验操作者独立使用 itertools.product 穷举核对，与上游的递归算法不同。"
              "零项列为明确的验收边界：空序列总和为零，故只有 m=0、n=0 时 [[]] 才是合法解。")
    (folder / "case_report.txt").write_text(
        f"公开案例：{scenario['title']}\n\n源码：{source_url}\nAI 来源：{provenance_url}\n"
        f"来源说明：{scenario['ai_note']}\n提交时间：{scenario['commit_date']}\n"
        f"Git blob：{scenario['blob']}\nSHA-256：{provenance['source_sha256']}\n\n"
        f"原程序任务：{scenario['original_task_note']}\n缺陷：{scenario['defect_note']}\n\n"
        f"核对后的原代码位置：{scenario['path']}:{provenance['verified_source_location']['line']}\n\n"
        "实验方法：完整上游文件不改动，以辅助文件原样运行。适配器只模拟交互并观察状态，或直接转发函数调用。"
        + method + "\n\n"
        f"测试环境：{first.isolation_level}\n同一计划：{same_plan}\n同一适配器：{same_adapter}\n"
        f"计划哈希：{first.reproducibility.plan_hash}\n\n" + table + "\n\n"
        f"原程序判定：{first.code_verdict}；通过 {first.coverage.cases_passed}/{first.coverage.cases_planned}。\n"
        f"修复后判定：{after.code_verdict}；通过 {after.coverage.cases_passed}/{after.coverage.cases_planned}。\n"
        f"修复方法：{scenario['repair_note']}\n"
        "修改由操作者实施；完整模型建议及失败证据见 initial_report.json 和 code_advice.json。"
        "--replay 关闭模型调用，因此建议降级为规则模式，功能测试仍在 Docker 实际运行。\n\n"
        f"结论范围：{scenario['scope']}\n"
        "真实性边界：这是公开 AI 辅助示例项目中的真实代码缺陷，不声称已发生生产事故。"
        "原始提示词未知，不将空字段或注释冒充生成日志；未验证新提示词对重新生成成功率的提升。\n\n"
        "复现命令（仓库根目录，需要 Docker）：\n"
        f".\\.venv\\Scripts\\python.exe scripts\\run_more_public_cases.py --replay --case {scenario['id']}\n"
        "结果写入 data/more_public_cases_replay，不覆盖 docs 中的模型报告。"
        "首次无源码缓存时需联网下载固定提交；缓存后可断网复现功能测试。\n", encoding="utf-8")
    expected = scenario["expected_passed"]
    total = len(scenario["cases"])
    if not (same_plan and same_adapter and first.code_verdict == "FAIL"
            and first.coverage.cases_passed == expected and first.coverage.cases_failed == total - expected
            and after.code_verdict == "PASS_WITHIN_SCOPE" and after.coverage.cases_passed == total
            and after.coverage.cases_failed == 0 and first.isolation_level == after.isolation_level == "DOCKER"):
        raise RuntimeError("实际结果与预期不符，已保留原始报告，不修改模型输出或测试预期")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", action="store_true", help="关闭模型调用，保留原始模型报告")
    parser.add_argument("--case", choices=["all", "copilot_cards", "copilot_zero_terms"], default="all")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    os.environ.pop("PYQ_ACCEPTANCE_ALLOW_HOST", None)
    from backend.acceptance import runner, llm_provider
    from backend.ai import deepseek_client
    backend = runner.detect_execution_backend()
    if backend.name != "DOCKER" or not backend.available:
        raise SystemExit("需要启动 Docker Desktop；本实验不在宿主机运行上游代码")
    if args.replay:
        deepseek_client.is_available = lambda: False
    elif not llm_provider.is_available():
        raise SystemExit("首次留存模型建议需要配置模型服务；功能复现可加 --replay")
    results = [run_scenario(scenario, args.replay) for scenario in scenarios()
               if args.case == "all" or scenario["id"] == args.case]
    folder = ROOT / ("data/more_public_cases_replay" if args.replay else "docs/public_cases")
    write_json(folder / ("summary.json" if args.case == "all" else args.case + "_summary.json"), results)
    print("公开案例的修复前后同标准验收已完成。", flush=True)


if __name__ == "__main__":
    main()
