"""把已有静态分析并入验收报告；质量建议与功能判定分别保留依据。"""
from backend.acceptance.models import CodeSuggestion, Evidence, QualityReport
from backend.analyzers.parser import analyze_source
from backend.analyzers.smells import detect_smells
from backend.analyzers.security import detect_security
from backend.analyzers.performance import detect_performance
from backend.analyzers.readability import score_readability


def inspect_quality(request, code_hash):
    sources = {"solution.py": request.code, **{f.path: f.content for f in request.supporting_files}}
    analyses = [analyze_source(path, code) for path, code in sources.items()]
    score = score_readability(analyses)
    findings = [{**s, "category": "READABILITY"} for s in detect_smells(analyses, sources)]
    for path, code in sources.items():
        findings.extend({**s, "category": "POTENTIAL_RISK"} for s in detect_security(path, code))
        findings.extend({**s, "category": "PERFORMANCE"} for s in detect_performance(path, code))
    suggestions, evidence = [], []
    for i, finding in enumerate(findings):
        fid = f"QUALITY-{i + 1}"
        finding["finding_id"] = fid
        ev = Evidence(
            kind="STATIC_FACT", producer="static-quality/1.0", code_hash=code_hash,
            phase="ASSERT", status="PASSED", observation=finding,
        )
        finding["evidence_id"] = ev.evidence_id
        evidence.append(ev)
        suggestions.append(CodeSuggestion(
            suggestion_id=f"SUG-{fid}", finding_id=fid, evidence_ids=[ev.evidence_id],
            category=finding["category"],
            location=f"{finding['file']}:{finding['line']}",
            explanation=f"静态规则 {finding['type']}：{finding['message']}",
            fix=finding.get("suggestion") or "按该静态规则检查并简化实现，修改后重新执行功能验收",
            regression_check="修改后重跑同一标准的全部案例，确认行为保持",
        ))
    risky = any(f["category"] == "POTENTIAL_RISK" and f.get("severity") == "high" for f in findings)
    return QualityReport(
        status="REVIEW_REQUIRED" if risky else ("NEEDS_IMPROVEMENT" if findings else "CLEAN"),
        readability_score=score["total"], readability_grade=score["grade"], findings=findings,
    ), suggestions, evidence
