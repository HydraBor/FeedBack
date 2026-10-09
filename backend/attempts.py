"""Preserve every imported version; send representative code bodies to the LLM."""
from copy import deepcopy
from .evidence import source_context,assessment_basis

def for_analysis(problem):
    data = deepcopy(problem)
    if data.get("source"):
        data["source"]=source_context(problem)
        basis=assessment_basis(problem)
        if basis["kind"]=="static_only":data["judge_result"]=basis["note"]
    uncertain=data.pop("unverified_submissions",[])
    if uncertain:data["unverified_submission_count"]=len(uncertain)
    attempts = data.get("submissions", [])
    if not attempts:
        return data
    small_history = sum(len(item.get("code", "")) for item in attempts) <= 60000
    chosen = set(range(len(attempts))) if small_history else {0, len(attempts) - 1}
    non_ac = [i for i, item in enumerate(attempts) if item["result"] != "AC"]
    chosen.update(non_ac[:3])
    if non_ac:
        chosen.add(non_ac[-1])
    accepted = [i for i, item in enumerate(attempts) if item["result"] == "AC"]
    if accepted:
        chosen.add(accepted[0])
        chosen.add(accepted[-1])
        if accepted[0]:
            chosen.add(accepted[0] - 1)
    count = data.get("pre_explanation_submissions")
    if count is not None:
        if count > len(attempts):
            raise ValueError("讲解前提交次数不能超过已有提交记录数")
        if count:
            chosen.add(count - 1)
        if count < len(attempts):
            chosen.add(count)
    lecture_time = data.get("explanation_started_at")
    if lecture_time:
        from datetime import datetime
        time = datetime.fromisoformat(str(lecture_time).replace("Z", "+00:00"))
        before = [i for i, item in enumerate(attempts) if datetime.fromisoformat(item["submitted_at"].replace("Z", "+00:00")) < time]
        if before:
            chosen.add(before[-1])
        if len(before) < len(attempts):
            chosen.add(len(before))
    source = data.get("source") or {}
    chosen.update(i for i, item in enumerate(attempts) if item["id"] == source.get("selected_submission_id"))
    # All metadata remains, including results and intervals. Archive code bodies
    # are never removed; only this API request uses representative versions.
    for i, item in enumerate(attempts):
        item["code_in_analysis"] = i in chosen and bool(item.get("code"))
        if i not in chosen:
            item["code"] = ""
    data["submission_analysis_scope"] = "本次包含所有存档版本代码。" if small_history else "代码量较大：保留初次、最早三次非AC、首次AC前后、最近非AC/AC、主作品及讲解前后版本；其他版本仅提供时间与结果。未提供的代码不等于空提交。"
    return data
