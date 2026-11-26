"""两组真实模型实测：原提示词生成→PyQuality 验收→改写提示词重新生成→同标准复评。

首次运行需要 Docker 和已配置的 DeepSeek。--replay 使用留存代码离线复现。
业务场景及验收案例为实验设计，不冒充公开生产事故。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def scenarios():
    money_requirement = (
        "实现 calculate_payable(items)。items 是商品字典列表，price 是最多两位小数的非负十进制金额字符串，"
        "quantity 是非负整数。按精确十进制金额计算总价，不能因二进制浮点误差改变优惠判断。"
        "总价达到或超过 100.00 元时减 20.00 元，每单只减一次；不足 100.00 元不优惠。"
        "返回恰好两位小数的金额字符串；空购物车返回 '0.00'。不得修改输入列表及商品字典。"
    )
    contacts_requirement = (
        "实现 deduplicate_contacts(contacts)，用于通讯录导入去重。contacts 为联系人字典列表，"
        "每条均有 name 和 email；email 是非空 ASCII 字符串，可带首尾空格。"
        "比较邮箱时须去除首尾空格并忽略字母大小写；去重键的规范化不得改变输出记录原有的 email 内容。"
        "重复邮箱保留第一次出现的完整记录，结果按被保留记录在原列表中第一次出现的顺序排列。"
        "不得修改输入列表或任一联系人字典；空列表返回空列表。"
    )

    def outcome(cid, rids, args, expected, note):
        return {"case_id":cid, "requirement_ids":rids, "args":args,
                "assertion":{"kind":"RETURN_EQUALS","expected":expected}, "expected_basis":note}

    def unchanged(cid, rid, args):
        return {"case_id":cid, "requirement_ids":[rid], "args":args,
                "assertion":{"kind":"INPUT_UNCHANGED","targets":[{"kind":"ARG","index":0}]},
                "expected_basis":"独立保存输入快照，验证调用前后列表及嵌套记录完全相同"}

    def cart(*prices):
        return [{"price":p,"quantity":1} for p in prices]

    a = {"name":"Alice 首次导入","email":"Alice@Example.com"}
    a2 = {"name":"Alice 后续导入","email":"alice@example.com"}
    b = {"name":"Bob 原始记录","email":" bob@example.com "}
    b2 = {"name":"Bob 重复记录","email":"bob@example.com"}
    c = {"name":"Carol","email":"carol@example.com"}
    exact_a = {"name":"Alice 后续更新","email":"Alice@Example.com"}
    return [
        {
            "id":"order_discount", "title":"电商满减：浮点误差导致满 100 元未优惠",
            "requirement":money_requirement,
            "entrypoint":{"module":"solution","callable":"calculate_payable"},
            "initial_prompt":(
                "帮我写一个 Python 函数 calculate_payable(items)，items 是商品字典列表，"
                "price 为金额字符串，quantity 为整数。先将每项 price 转成 float 乘以 quantity，"
                "逐项累加后判断是否满 100 元；满 100 减 20 元，每单只减一次。"
                "最后把应付金额格式化为两位小数字符串并返回。只用标准库，代码简洁。"
            ),
            "design_note":"初始提示词明确指定 float，这是待诊断的工程选择；不声称模型无提示自行引入错误。",
            "requirements":[
                {"id":"R1","quote":"按精确十进制金额计算总价，不能因二进制浮点误差改变优惠判断。","kind":"FUNCTIONAL"},
                {"id":"R2","quote":"总价达到或超过 100.00 元时减 20.00 元，每单只减一次；不足 100.00 元不优惠。","kind":"FUNCTIONAL"},
                {"id":"R3","quote":"返回恰好两位小数的金额字符串；空购物车返回 '0.00'。","kind":"FUNCTIONAL"},
                {"id":"R4","quote":"不得修改输入列表及商品字典。","kind":"SIDE_EFFECT"},
            ],
            "cases":[
                outcome("M01",["R3"],[[]],"0.00","空购物车明确返回 0.00"),
                outcome("M02",["R1"],[[{"price":"19.90","quantity":2},{"price":"9.90","quantity":1}]],"49.70","19.90 × 2 + 9.90 = 49.70，不满减"),
                outcome("M03",["R2"],[cart("100.00")],"80.00","100.00 达到门槛，减 20.00"),
                outcome("M04",["R2"],[cart("99.99")],"99.99","99.99 未达到门槛"),
                outcome("M05",["R1","R2"],[cart("100.01")],"80.01","100.01 减 20.00 = 80.01"),
                outcome("M06",["R1","R2"],[cart("73.96","4.14","21.90")],"80.00","十进制精确和为 100.00，须优惠 20.00"),
                outcome("M07",["R2"],[cart("200.00")],"180.00","200.00 仍只优惠一次，减 20.00"),
                outcome("M08",["R1","R3"],[[{"price":"0.10","quantity":3}]],"0.30","0.10 × 3 = 0.30"),
                outcome("M09",["R3"],[cart("0.00")],"0.00","零金额按两位小数格式返回"),
                unchanged("M10","R4",[cart("73.96","4.14","21.90")]),
                outcome("M11",["R1","R2"],[cart("49.05","41.90","9.05")],"80.00","十进制精确和为 100.00；Docker Python 3.10 的 float 求和为 99.99999999999999，须保持满减资格"),
            ],
        },
        {
            "id":"contact_import", "title":"通讯录导入：邮箱规范化遗漏造成重复联系人",
            "requirement":contacts_requirement,
            "entrypoint":{"module":"solution","callable":"deduplicate_contacts"},
            "initial_prompt":(
                "帮我写一个 Python 函数 deduplicate_contacts(contacts)。contacts 是联系人字典列表，"
                "每条有 name 和 email。按 email 字段去重，每个邮箱只保留一条，"
                "返回去重后的联系人列表。用字典实现，代码简洁，只用标准库。"
            ),
            "design_note":"初始提示词是有意保留常见遗漏的简短需求；完整业务规则先独立写入验收标准。",
            "requirements":[
                {"id":"R1","quote":"比较邮箱时须去除首尾空格并忽略字母大小写；去重键的规范化不得改变输出记录原有的 email 内容。","kind":"FUNCTIONAL"},
                {"id":"R2","quote":"重复邮箱保留第一次出现的完整记录","kind":"FUNCTIONAL"},
                {"id":"R3","quote":"结果按被保留记录在原列表中第一次出现的顺序排列。","kind":"FUNCTIONAL"},
                {"id":"R4","quote":"不得修改输入列表或任一联系人字典；空列表返回空列表。","kind":"SIDE_EFFECT"},
            ],
            "cases":[
                outcome("C01",["R4"],[[]],[],"空列表返回空列表"),
                outcome("C02",["R1"],[[a]],[a],"保留输出原记录的邮箱大小写"),
                outcome("C03",["R3"],[[b,a,c]],[b,a,c],"不同邮箱按输入顺序输出"),
                outcome("C04",["R2"],[[a,exact_a]],[a],"相同邮箱不同姓名时保留第一条完整记录"),
                outcome("C05",["R1","R2"],[[a,a2]],[a],"Alice@Example.com 和 alice@example.com 归为同一邮箱"),
                outcome("C06",["R1","R2"],[[b,b2]],[b],"去除首尾空格后相同，保留第一条且不改写原 email"),
                outcome("C07",["R2","R3"],[[b,a,b2,c]],[b,a,c],"去重后仍按原始首次出现顺序排列"),
                unchanged("C08","R4",[[b,a,a2,b2,c]]),
                outcome("C09",["R1","R2","R3"],[[a,{"name":"重复","email":"  ALICE@EXAMPLE.COM  "},b]],[a,b],"同时存在大小写与空格差异，保持第一条和顺序"),
            ],
        },
    ]


def validate_independent_expectations(case):
    """先核对人工标准的计算，再生成候选代码；不读取候选实现来推导 expected。"""
    from decimal import Decimal
    from copy import deepcopy
    from backend.acceptance.checks import evaluate_assertion
    from pydantic import TypeAdapter
    from backend.acceptance.models import Assertion
    for check in case["cases"]:
        if check["assertion"]["kind"] != "RETURN_EQUALS":
            continue
        values = deepcopy(check["args"][0])
        if case["id"] == "order_discount":
            total = sum((Decimal(i["price"]) * i["quantity"] for i in values), Decimal("0.00"))
            result = format(total - (Decimal("20.00") if total >= Decimal("100.00") else Decimal("0.00")), ".2f")
        else:
            seen, result = set(), []
            for contact in values:
                key = contact["email"].strip().lower()
                if key not in seen:
                    seen.add(key)
                    result.append(contact)
        assert evaluate_assertion(TypeAdapter(Assertion).validate_python(check["assertion"]),
                                  {"return_value":result}).passed, check["case_id"]


def make_confirmation(case):
    from backend.acceptance.standards import StandardConfirmation
    # 每个需求有独立契约，多需求案例的原文归属保持一致。
    contracts = [{
        "contract_id":"K_"+r["id"], "requirement_ids":[r["id"]], "description":r["quote"],
        "relation_to_requirement":"EQUIVALENT",
        "relation_basis":"实验操作者独立核对固定案例的完整预期；充分性仅限声明的案例范围",
        "oracle_origin":"USER_EXAMPLE",
    } for r in case["requirements"]]
    cases = []
    for item in case["cases"]:
        cid = "K_CASE_"+item["case_id"]
        contracts.append({
            "contract_id":cid,"requirement_ids":item["requirement_ids"],"description":item["expected_basis"],
            "relation_to_requirement":"EQUIVALENT","relation_basis":"独立核对的固定输入及期望，结论不覆盖未测试输入",
            "oracle_origin":"USER_EXAMPLE",
        })
        cases.append({**item,"contract_id":cid,"kwargs":{},"input_domain_status":"IN_SCOPE"})
    return StandardConfirmation.model_validate({
        "requirement":case["requirement"],"entrypoint":case["entrypoint"],"confirmed":True,
        "scope_note":"实验操作者已独立核对以下固定案例；结论只覆盖本轮检查，不保证未测试输入。",
        "spec":{"spec_id":"REAL-CASE-DRAFT","requirements":[{
            "id":r["id"],"statement":r["quote"],"source_quote":r["quote"],"origin":"EXPLICIT",
            "mandatory":True,"kind":r["kind"],
        } for r in case["requirements"]]},
        "plan":{"plan_id":"PLAN-"+case["id"],"contracts":contracts,"cases":cases},
    })


def write_json(path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")


def generate(prompt, folder, phase, model):
    from backend.ai import deepseek_client
    path = folder / f"model_{phase}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        system = "你是 Python 开发者。根据用户提示词编写实现。只返回 JSON 对象，格式为 {\"code\":\"完整 Python 源码\"}，不要用 Markdown 围栏。"
        data = deepseek_client.chat_json([{"role":"system","content":system},{"role":"user","content":prompt}],temperature=0.2)
        # 保留真实原始 JSON，不为使案例成立而手改模型代码或反复抽样。
        write_json(path, {"model":model,"generated_at":datetime.now(timezone(timedelta(hours=8))).isoformat(),
                          "system_prompt":system,"user_prompt":prompt,"response":data})
        data = json.loads(path.read_text(encoding="utf-8"))
    code = data["response"].get("code")
    if not isinstance(code,str) or not code.strip():
        raise RuntimeError("模型未返回有效 code 字段；原始返回已保存")
    (folder / f"{phase}_code.py").write_text(code,encoding="utf-8")
    return code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay",action="store_true",help="用留存的真实模型代码离线复现；报告写入 data/real_cases_replay")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    os.environ.pop("PYQ_ACCEPTANCE_ALLOW_HOST",None)
    from backend.acceptance import llm_provider, runner, standards
    from backend.acceptance.models import EvaluationRequest
    from backend.acceptance.service import evaluate
    from backend.config import DEEPSEEK_MODEL
    from backend.ai import deepseek_client
    backend = runner.detect_execution_backend()
    if backend.name != "DOCKER" or not backend.available:
        raise SystemExit("需要真实 Docker 容器执行，请先启动 Docker Desktop")
    if args.replay:
        deepseek_client.is_available = lambda:False
    elif not llm_provider.is_available():
        raise SystemExit("需要已配置的真实 DeepSeek 服务")
    artifact_root = ROOT / "docs" / "real_cases"
    summaries = []
    for case in scenarios():
        folder = artifact_root / case["id"]
        folder.mkdir(parents=True,exist_ok=True)
        validate_independent_expectations(case)
        # 先落盘独立标准，再调用生成模型。
        if not args.replay:
            write_json(folder / "scenario.json",case)
            (folder / "initial_prompt.txt").write_text(case["initial_prompt"],encoding="utf-8")
        confirmation = make_confirmation(case)
        record = standards.confirm(confirmation)
        target = ROOT / "data" / "real_cases_replay" / case["id"] if args.replay else folder
        target.mkdir(parents=True,exist_ok=True)
        write_json(target / "confirmation.json",record)
        results = {}
        optimized = ""
        for phase in ("initial","regenerated"):
            prompt = case["initial_prompt"] if phase == "initial" else optimized
            if args.replay:
                code = (folder / f"{phase}_code.py").read_text(encoding="utf-8")
                if phase == "regenerated":
                    prompt = (folder / "optimized_prompt.txt").read_text(encoding="utf-8")
            else:
                code = generate(prompt,folder,phase,DEEPSEEK_MODEL)
            req = EvaluationRequest(
                requirement=case["requirement"],generation_prompt=prompt,code=code,entrypoint=case["entrypoint"],
                generation_context={"is_complete":True,"requirements_also_visible":False},
                options={"oracle_policy":"confirmed_only"},
                acceptance_materials={"confirmed_spec_id":record["confirmed_spec_id"],"confirmed_spec_hash":record["confirmed_spec_hash"]},
            )
            write_json(target / f"{phase}_request.json",req.model_dump())
            report = evaluate(req)
            write_json(target / f"{phase}_report.json",report.model_dump())
            results[phase] = report
            print(json.dumps({"case":case["id"],"phase":phase,"verdict":report.code_verdict,
                              "coverage":report.coverage.model_dump(),"prompt_mode":report.prompt_report.mode},ensure_ascii=False),flush=True)
            if phase == "initial" and not args.replay:
                if report.prompt_report.mode != "LLM" or not report.prompt_report.changes:
                    raise RuntimeError("没有产生真实模型提示词改写；保留现有结果，不伪造优化")
                optimized = report.prompt_report.optimized_prompt
                (folder / "optimized_prompt.txt").write_text(optimized,encoding="utf-8")
            expected = "FAIL" if phase == "initial" else "PASS_WITHIN_SCOPE"
            if report.code_verdict != expected:
                raise RuntimeError(f"实际结果为 {report.code_verdict}，与设计预期 {expected} 不同。代码及报告已保留，不手改模型输出。")
        same = results["initial"].reproducibility.plan_hash == results["regenerated"].reproducibility.plan_hash
        assert same
        row = {"id":case["id"],"title":case["title"],"provider":"DeepSeek","model":DEEPSEEK_MODEL,
               "same_plan":same,"isolation":"DOCKER",
               "initial":results["initial"].coverage.model_dump(),
               "regenerated":results["regenerated"].coverage.model_dump(),
               "initial_verdict":results["initial"].code_verdict,"regenerated_verdict":results["regenerated"].code_verdict,
               "scope":"业务场景和标准由实验设计；代码由真实模型生成，保留原始输出；不是公开生产事故记录"}
        write_json(target / "summary.json",row)
        summaries.append(row)
        if not args.replay:
            # 与既有演示格式兼容，页面可直接加载这两组真实生成代码。
            demo = {"id":"real_"+case["id"],"title":"真实模型实测："+case["title"],
                    "requirement":case["requirement"],"generation_prompt":case["initial_prompt"],
                    "correct_prompt":optimized,
                    "code":(folder / "initial_code.py").read_text(encoding="utf-8"),
                    "correct_code":(folder / "regenerated_code.py").read_text(encoding="utf-8"),
                    "entrypoint":case["entrypoint"],"provenance":row,"examples":[]}
            for item in case["cases"]:
                example={"args":item["args"],"assertion":item["assertion"],"note":item["expected_basis"]}
                if item["assertion"]["kind"]=="RETURN_EQUALS":
                    example["expected"]=item["assertion"]["expected"]
                demo["examples"].append(example)
            write_json(ROOT / "samples" / "acceptance" / ("real_"+case["id"]+".json"),demo)
    write_json((ROOT / "data" / "real_cases_replay" if args.replay else artifact_root) / "summary.json",summaries)
    print("两个真实模型案例已完成，均使用相同标准复评。")


if __name__ == "__main__":
    main()
