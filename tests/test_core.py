import asyncio
import io
import json
import zipfile
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from backend import db, knowledge
from backend.app import app
from backend.models import FeedbackInput, StudentInput, ParentCopy
from backend.pipeline import demo_results
from backend.validation import validate_parent, validate_scores, evidence_ids

@pytest.fixture
def database(tmp_path, monkeypatch):
    import importlib
    monkeypatch.setattr(importlib.import_module("backend.app"), "DATA", tmp_path)
    monkeypatch.setattr(importlib.import_module("backend.report"), "DATA", tmp_path)
    monkeypatch.setattr(db, "DATABASE", tmp_path / "test.sqlite3")
    db.init_db()
    return tmp_path

def profile(name="测试同学"):
    return StudentInput(name=name, age=13, grade="初二").model_dump()

def payload(sid, **extra):
    return FeedbackInput(student_id=sid, start_date="2026-09-01", end_date="2026-09-30", reference_date="2026-10-08", tracks=["J", "S"], target_year=2026, topics="模拟、排序", focus_score=82, mode="demo", **extra).model_dump(mode="json")

def draft(data):
    _, scores, _, _, copy = demo_results(data, knowledge.topics())
    return {**copy, "positions": knowledge.forecast_positions({}, data["tracks"], [], True), "admissions_text": "", "admissions_sources": [], "teacher": "", **scores}

def test_same_name_separate_and_snapshot(database):
    a, b = db.save_student(profile()), db.save_student(profile())
    assert a["id"] != b["id"] and len(db.students("测试")) == 2
    f = db.create_feedback(payload(a["id"]))
    db.save_student(profile("后来改名"), a["id"])
    assert db.feedback(f["id"])["student_snapshot"]["name"] == "测试同学"

def test_versions_revision_guard_and_immutable(database):
    s = db.save_student(profile())
    f = db.create_feedback(payload(s["id"]))
    content = draft(f["input"])
    db.save_review(f["id"], 0, content, {}, True)
    changed = deepcopy(content)
    changed["summary"] = "新的文案"
    changed['title']='测试同学的阶段成果'
    db.save_review(f["id"], 1, changed, {}, True)
    assert [v["content"]["summary"] for v in db.versions(f["id"])] == ["新的文案", content["summary"]]
    assert db.feedback(f['id'])['draft']['title']=='测试同学的阶段成果'
    assert db.versions(f['id'])[1]['content'].get('title','')==''
    with pytest.raises(ValueError, match="刷新"):
        db.save_review(f["id"], 1, changed, {}, True)

def test_history_excludes_demo_and_overlapping_period(database):
    s = db.save_student(profile())
    data = payload(s["id"])
    f = db.create_feedback(data)
    db.save_review(f["id"], 0, draft(data), {}, True)
    assert not db.history(s["id"], "2026-10-01", "none")
    data["mode"] = "live"
    f = db.create_feedback(data)
    db.save_review(f["id"], 0, draft(data), {}, True)
    assert len(db.history(s["id"], "2026-10-01", "none")) == 1
    db.save_review(f["id"], 1, draft(data), {}, False)
    assert len(db.history(s["id"], "2026-10-01", "none")) == 1
    assert db.history(s["id"], "2026-10-01", "none")[0]["confirmed_report"] == draft(data)
    assert not db.history(s["id"], "2026-09-15", "none")

def test_highest_six_and_tie_order():
    scores = [{"id": "K"+str(i).zfill(3), "score": s} for i, s in enumerate([99, 12, 98, 97, 96, 95, 94, 94], 1)]
    chosen = knowledge.top_topics(scores)
    assert {s["id"] for s in chosen} == {"K001", "K003", "K004", "K005", "K006", "K007"}

def test_evidence_and_history_not_period_score():
    data = payload("x")
    report = draft(data)
    allowed = evidence_ids(data, [])
    validate_scores(report["topic_scores"], report["abilities"], allowed, 82)
    report["topic_scores"][0]["evidence"] = ["history:x:p0"]
    with pytest.raises(ValueError):
        validate_scores(report["topic_scores"], report["abilities"], allowed | {"history:x:p0"}, 82)

def test_empty_fields_are_not_evidence():
    data=payload("x")
    data.update(topics="", supplements="仅有课堂观察", focus_score=None)
    assert evidence_ids(data, []) == {"current:supplements"}
    report=draft(data)
    validate_scores(report["topic_scores"], report["abilities"], evidence_ids(data, []), None)

def test_period_cannot_include_unfinished_future():
    from pydantic import ValidationError
    data=payload("x")
    data["end_date"]="2026-10-09"
    with pytest.raises(ValidationError, match="基准日期"):
        FeedbackInput.model_validate(data)

def test_existing_oj_result_only_applies_to_original_code():
    from backend.evidence import assessment_basis
    problem={"source":{"platform":"acgo","selected_submission_id":"one"},"code":"original", "submissions":[{"id":"one","code":"original","result":"AC","score":100}]}
    assert assessment_basis(problem)["result"]=="AC"
    assert assessment_basis({**problem,"code":"edited"})["kind"]=="static_only"

@pytest.mark.parametrize("bad", ["学生13岁", "学生初二", "年级：八", "学生八年级"])
def test_age_grade_excluded_from_parent(bad):
    data = payload("x")
    report = draft(data)
    report["summary"] = bad
    with pytest.raises(ValueError, match="年龄"):
        validate_parent(report, data)

def test_parent_grade_only_and_style():
    data = payload("x")
    report = draft(data)
    report["positions"][0]["label"] = "预计270分"
    with pytest.raises(ValueError, match="分数"):
        validate_parent(report, data)
    report = draft(data)
    report["summary"] = "表现很稳"
    assert validate_parent(report, data)

def reference():
    return {"rule": {"year": 2025, "track": "J", "thresholds": [270, 205, 130]}, "problems": [{"id": str(i), "max_score": 100} for i in range(4)]}

def test_forecast_full_paper_same_year_and_lower_bound():
    ref = reference()
    papers = [{"track": "J", "year": 2025, "tasks": [{"problem_id": str(i), "lower": 60, "upper": 90} for i in range(4)]}]
    result = knowledge.forecast_positions({"papers": papers}, ["J"], [ref])
    assert "二等" in result[0]["label"] and "240" not in result[0]["basis"]
    papers[0]["year"] = 2024
    with pytest.raises(ValueError, match="同年"):
        knowledge.forecast_positions({"papers": papers}, ["J"], [ref])
    papers[0]["year"] = 2025
    papers[0]["tasks"].pop()
    with pytest.raises(ValueError, match="全部"):
        knowledge.forecast_positions({"papers": papers}, ["J"], [ref])

def test_forecast_rejects_phantom_evidence_and_duplicate_papers():
    from backend.validation import validate_forecasts
    ref=reference()
    paper={"track":"J","year":2025,"tasks":[{"problem_id":str(i),"lower":60,"upper":90,"evidence":["current:p0"]} for i in range(4)]}
    validate_forecasts({"papers":[paper]},["J"],[ref],{"current:p0"})
    with pytest.raises(ValueError,match="证据"):
        validate_forecasts({"papers":[paper]},["J"],[ref],set())
    with pytest.raises(ValueError,match="重复"):
        validate_forecasts({"papers":[paper,paper]},["J"],[ref],{"current:p0"})

def test_api_origin_private_files_and_key(database):
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/settings").status_code == 200
        assert "api_key" not in client.get("/api/settings").json()
        assert client.post("/api/students", json=profile(), headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.get("/api/students", headers={"Host": "evil.example"}).status_code == 403
        assert "sk-" not in client.get("/deepseek").text
        response = client.post("/api/students", json=profile())
        sid = response.json()["id"]
        assert client.post("/api/reports", json=payload(sid)).status_code == 200
        assert client.request("DELETE", "/api/students/"+sid, json={"confirm_name": "错误姓名"}).status_code == 400
        backup = zipfile.ZipFile(io.BytesIO(client.get("/api/backup").content))
        assert "feedback.sqlite3" in backup.namelist() and not any("settings" in n or "deepseek" in n for n in backup.namelist())

def test_review_can_add_teacher_focus_and_keeps_confirmed_preview(database, monkeypatch):
    import importlib
    from backend.pipeline import generate
    student=db.save_student(profile())
    data=payload(student["id"])
    data["focus_score"]=None
    entry=db.create_feedback(data)
    asyncio.run(generate(entry["id"]))
    entry=db.feedback(entry["id"])
    content=deepcopy(entry["draft"])
    next(a for a in content["abilities"] if a["id"]=="A06")["score"]=75
    with TestClient(app, base_url="http://127.0.0.1") as client:
        result=client.put(f"/api/reports/{entry['id']}/review?confirm=true",json={"revision":entry["revision"],"report":content})
        assert result.status_code==200, result.text
        saved=result.json()
        focus=next(a for a in saved["draft"]["abilities"] if a["id"]=="A06")
        assert focus["source"]=="teacher" and "teacher:review" in focus["evidence"]
        vid=saved["versions"][0]["id"]
        url=f"/api/reports/{entry['id']}/preview?version_id={vid}"
        html=client.get(url).text
        monkeypatch.setattr(importlib.import_module("backend.app"),"render",lambda *a,**k:"改变后的模板")
        assert client.get(url).text==html
        backup=zipfile.ZipFile(io.BytesIO(client.get("/api/backup").content))
        assert f"html/{vid}.html" in backup.namelist()
        assert client.request("DELETE",f"/api/students/{student['id']}",json={"confirm_name":student["name"]}).status_code==200
        assert not (database/"html"/f"{vid}.html").exists()

def test_admissions_interface_is_preserved_but_disabled(database):
    from backend.pipeline import generate
    student=db.save_student(profile())
    data=payload(student["id"], admissions=True, admissions_year=2027, target_schools=["深圳中学"])
    entry=db.create_feedback(data)
    asyncio.run(generate(entry["id"]))
    result=db.feedback(entry["id"])
    assert result["input"]["admissions"] is True
    assert not result["draft"]["admissions_text"] and not result["draft"]["admissions_sources"]
    assert not result["analysis"]["admissions"]["enabled"]
    with TestClient(app,base_url="http://127.0.0.1") as client:
        assert not client.get("/api/library").json()["features"]["admissions_enabled"]

def test_provider_json_retry_and_budget(monkeypatch):
    from backend import provider
    outputs = ["", '{"summary":"结果","highlights":["成果"],"next_steps":["建议"]}']
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            calls.append(kwargs["json"])
            import httpx
            return httpx.Response(200, json={"choices":[{"message":{"content":outputs.pop(0)}}],"usage":{"prompt_tokens":10}})
    monkeypatch.setattr(provider, "settings", lambda: {"api_key": "test", "base_url": "https://api.deepseek.com", "model": "test", "max_calls": 2, "timeout": 1})
    monkeypatch.setattr(provider.httpx, "AsyncClient", Client)
    instance = provider.DeepSeek()
    assert asyncio.run(instance.generate("json", {}, ParentCopy))["summary"] == "结果"
    assert instance.calls == 2 and instance.usage["prompt_tokens"] == 20
    with pytest.raises(RuntimeError, match="预算"):
        asyncio.run(instance.generate("json", {}, ParentCopy))
