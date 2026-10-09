"""Recommendations resolve exclusively to the checked local ACGO catalogue."""
from . import knowledge


def catalogue():
    path = knowledge.PUBLIC / "acgo_collections.json"
    return knowledge.read("acgo_collections.json") if path.exists() else {"version": "unavailable", "collections": [], "failures": []}


def completed_ids(payload):
    return {p["source"]["question_id"] for p in payload["problems"] if p.get("source") and (p.get("code") or p.get("submissions"))}


def validate_training(training, snapshot, payload, allowed):
    records = {c["id"]: c for c in snapshot["collections"] if c["ready"]}
    for item in training["recent"]:
        if not set(item["evidence"]) <= allowed:
            raise ValueError("训练安排必须引用已提供材料")
        ident = item.get("collection_id", "")
        if not ident:
            continue
        if ident not in records:
            raise ValueError("只能推荐已核实题单库中的 collection_id")


def recommendations(training, snapshot):
    records = {c["id"]: c for c in snapshot["collections"] if c["ready"]}
    output, seen = [], set()
    for item in training["recent"]:
        c = records.get(item.get("collection_id"))
        if c and c['id'] not in seen:
            output.append({"collection_id": c["id"], "title": c["title"], "url": c["url"],
                "questions": [],
                "practice_mode": item.get("practice_mode", "new")})
            seen.add(c['id'])
    return output


def validate_recommendations(report, snapshot=None):
    records = {c["id"]: c for c in (snapshot or catalogue())["collections"] if c["ready"]}
    for item in report.get("practice_recommendations", []):
        c = records.get(item["collection_id"])
        if not c or item["title"] != c["title"] or item["url"] != c["url"]:
            raise ValueError("练习题单标题与链接必须来自已核实题单记录")
        by_id = {q["id"]: q for q in c["questions"]}
        ids = [q["id"] for q in item.get("questions",[])]
        if len(ids) != len(set(ids)):
            raise ValueError("推荐题目不能重复")
        for q in item.get("questions",[]):
            original = by_id.get(q["id"])
            if not original or any(q[k] != original[k] for k in ("title", "url")):
                raise ValueError("推荐题目必须属于所选题单，并保留核实的标题和链接")


def model_catalogue(snapshot, scoring=None):
    selected = [c for c in snapshot["collections"] if c["ready"]]
    if scoring:
        focus = {s["id"] for s in scoring["topic_scores"]}
        selected.sort(key=lambda c: (-len(set(c["topic_ids"]) & focus), c["id"]))
    return [{"id": c["id"], "title": c["title"], "topic_ids": c["topic_ids"],
        "description": c["description"][:700], "knowledge": c.get('knowledge',[]),
        "problem_count":len(c['questions']),"difficulties":sorted({str(q.get('difficulty','')) for q in c['questions'] if q.get('difficulty') is not None})}
        for c in selected]
