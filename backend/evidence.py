"""Read existing OJ records; never compile, execute, or manufacture test results."""

def source_context(problem):
    source=problem.get("source")
    if not source:return None
    data={**source}
    if source.get("platform","acgo")=="csp_exam":
        tags=[t for t in source.get("assessment_tags",[]) if t not in ("讲师确认独立完成","讲师确认未接受题解或讲解")]
        for tag in ("周老师OJ","限时测试","最终提交材料"):
            if tag not in tags:tags.append(tag)
        if problem.get("independent") is True:tags.append("讲师确认独立完成")
        if problem.get("editorial_seen") is False:tags.append("讲师确认未接受题解或讲解")
        data["assessment_tags"]=tags
        if data.get("submission_semantics","unknown")=="unknown":data["submission_semantics"]="final_submission"
    return data

def assessment_basis(problem):
    source=problem.get("source")
    if source:
        original=next((s for s in problem.get("submissions",[]) if s["id"]==source.get("selected_submission_id") and s.get("code")==problem.get("code")),None)
        if original:
            return {"kind":"oj_record","platform":source.get("platform","acgo"),"submission_id":original["id"],"result":original["result"],"score":original.get("score"),
                "note":"OJ 已有结果，只适用于这份原始提交代码；系统不重新运行或评测。"}
        return {"kind":"static_only","note":"没有与当前代码对应的可核实 OJ 结果。旧版提交成绩不继承到修改后的代码。"}
    if problem.get("judge_result"):
        return {"kind":"teacher_supplied","result":problem["judge_result"],"note":"讲师提供的已有结果，系统未运行代码。"}
    return {"kind":"static_only","note":"仅按题面和代码分析，不声称程序已通过测试。"}
