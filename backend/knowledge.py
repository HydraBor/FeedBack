import json
import fcntl
from contextlib import contextmanager
from threading import RLock
from .config import ROOT
from .library_audit import is_reviewed, assessment

PUBLIC = ROOT / "data/public"
_problem_lock = RLock()

@contextmanager
def problem_write_lock():
    """Serialize catalogue updates in API threads and the offline audit process."""
    with _problem_lock, (PUBLIC / ".problems.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
ABILITIES = {"A01": "阅读理解", "A02": "分析推理", "A03": "方案设计", "A04": "编程实现", "A05": "检查改进", "A06": "专注投入"}

def read(name):
    return json.loads((PUBLIC / name).read_text(encoding="utf-8"))

def topics():
    return read("topics.json")

def problems():
    return read("problems.json")

def rules():
    return read("rules.json")

def top_topics(scores):
    selected = sorted((s for s in scores if s["score"] is not None), key=lambda s: (-s["score"], s["id"]))[:6]
    return sorted(selected, key=lambda s: s["id"])

def event(year):
    return next((e for e in rules()["events"] if e["year"] == year), None)

def references(tracks):
    # Release the catalogue only after every national CSP task has a current review.
    all_problems = problems()
    if not all_problems or not all(is_reviewed(p) for p in all_problems):
        return []
    results = []
    for line in rules()["grade_lines"]:
        if line["track"] not in tracks or not line["reviewed"] or line.get("province") != "广东" or line.get("stage") != "second":
            continue
        paper = [p for p in all_problems if p["year"] == line["year"] and p["track"] == line["track"]]
        expected = 6 if line["year"] == 2019 and line["track"] == "S" else 4
        if len(paper) == expected and all(is_reviewed(p) for p in paper):
            results.append({"rule": line, "problems": sorted(paper,key=lambda p:p["index"]), "duration_minutes":line["duration_minutes"], "sessions":line["sessions"]})
    return results

def reference_for_model(reference):
    return {"rule":reference["rule"],"duration_minutes":reference["duration_minutes"],"sessions":reference.get("sessions",[]),
        "problems":[{**{k:p[k] for k in ("id","year","track","index","title","max_score","statement","topic_ids","subtasks")},
            "reviewed_assessment":assessment(p),**({"editorial":p["editorial"]} if not assessment(p) else {})} for p in reference["problems"]]}

def forecast_positions(raw, tracks, allowed_refs, demo=False):
    results = []
    for track in tracks:
        estimates = []
        for paper in raw.get("papers", []):
            if paper["track"] != track:
                continue
            ref = next((r for r in allowed_refs if r["rule"]["year"] == paper["year"] and r["rule"]["track"] == track), None)
            if not ref:
                raise ValueError("预测引用了未审核或没有同年等级线的试卷")
            tasks = {t["problem_id"]: t for t in paper["tasks"]}
            required = {p["id"]: p for p in ref["problems"]}
            if set(tasks) != set(required) or len(tasks) != len(paper["tasks"]):
                raise ValueError("预测必须覆盖参考卷全部题目且不能重复")
            for pid, task in tasks.items():
                if task["lower"] > task["upper"] or task["upper"] > required[pid]["max_score"]:
                    raise ValueError("预测分值超出任务范围")
            lower = sum(t["lower"] for t in tasks.values())
            thresholds = ref["rule"]["thresholds"]
            grade = next((i + 1 for i, threshold in enumerate(thresholds) if threshold is not None and lower >= threshold), None)
            # Unknown provincial thresholds must not be invented; retain the
            # score internally if no verified threshold supports a grade.
            if grade is None and all(t is not None for t in thresholds):
                grade = 4
            if grade is not None:
                estimates.append((grade, lower, paper["year"]))
        if demo:
            label = f"CSP-{track} 第二轮广东省二等（演示定位）"
            basis = "仅用于演示报告布局，不代表学生实力评估。"
        elif not estimates:
            label = f"CSP-{track}：暂不足以形成等级定位"
            basis = "当前缺少完整且已审核的参考卷或有效成果对应，已保留任务分析与训练建议。"
        else:
            conservative = max(e[0] for e in estimates)
            label = f"CSP-{track} 第二轮广东省{['一等', '二等', '三等'][conservative - 1]}" if conservative <= 3 else f"CSP-{track}：基础训练阶段"
            basis = "基于本期成果及历史背景的保守估计，参考 " + "、".join(str(e[2]) for e in estimates) + " 年广东标准；以具备第二轮资格为前提。"
        results.append({"track": track, "label": label, "basis": basis})
    return results


POSITION_NOTE = "此评估为保守估计，表示在相近难度和正常发挥条件下预计可达到的水平。"


SCORE_LEVELS = [
    {"range": "1-20", "label": "能理解老师讲的"},
    {"range": "21-40", "label": "在提示下能完成练习"},
    {"range": "41-60", "label": "能独立做基础题"},
    {"range": "61-80", "label": "能独立做综合题"},
    {"range": "81-100", "label": "能灵活运用讲清做法"},
]
