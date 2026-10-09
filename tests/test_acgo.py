import asyncio
import importlib
import io
import json
import sqlite3
import zipfile
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from backend import acgo, db
from backend.app import app
from backend.models import ACGOImportInput, ACGOArchiveInput, FeedbackInput, StudentInput
from backend.attempts import for_analysis
from backend import practice
from backend.validation import validate_scores

def config(**extra):
    data = dict(student_id="student", user_id="5085016", team="2042058713337094144", kind="contest",
                task="https://www.acgo.cn/contest/detail/22884?matchRoundId=22884&examId=91139&teamCode=2042058713337094144&openLevel=3", start_date="2026-08-14", end_date="2026-08-14")
    data.update(extra)
    return ACGOImportInput(**data)

def test_normalization_retains_snowflake_and_verified_contest_parameters():
    out = acgo.normalize(config())
    assert out["team_id"] == "2042058713337094144"
    assert out["task_id"] == "22884" and "examId=91139" in out["task_url"]
    assert "matchRoundId=22884" in out["task_url"]
    with pytest.raises(ValueError, match="团队 ID"):
        acgo.normalize(config(team="another-team"))
    with pytest.raises(ValueError, match="官方"):
        acgo.normalize(config(task="https://example.com/contest/detail/22884"))
    with pytest.raises(ValueError, match="类型"):
        acgo.normalize(config(kind="homework"))

def test_import_period_guard_prevents_old_submission_becoming_current_evidence():
    problem = dict(title="题目", submissions=[dict(id="1",submitted_at="2026-08-13T15:59:59Z",result="AC",language="cpp",code="code")])
    base = dict(student_id="student",start_date="2026-08-14",end_date="2026-08-14",reference_date="2026-10-08",tracks=["J"],target_year=2026,problems=[problem])
    with pytest.raises(ValueError, match="本期"):
        FeedbackInput(**base)
    problem["submissions"][0]["submitted_at"]="2026-08-13T16:00:00Z"
    assert FeedbackInput(**base).problems[0].minutes is None
    problem["submissions"][0]["submitted_at"]="2026-08-14T00:00:00"
    with pytest.raises(ValueError, match="时区"):
        FeedbackInput(**base)

def test_import_api_mismatched_student_and_cancel(tmp_path,monkeypatch):
    monkeypatch.setattr(db,"DATABASE",tmp_path/"test.sqlite3")
    db.init_db()
    student=db.save_student(StudentInput(name="测试同学",age=12,grade="初一",acgo_user_id="5085016").model_dump())
    async def worker(data,progress=None):
        await asyncio.sleep(3600)
    monkeypatch.setattr(acgo,"run_worker",worker)
    with TestClient(app, base_url="http://localhost") as client:
        payload=config(student_id=student["id"]).model_dump(mode="json")
        assert client.post("/api/acgo/imports",json={**payload,"user_id":"123"}).status_code==400
        assert client.post("/api/acgo/imports",json={**payload,"student_id":"missing"}).status_code==404
        result=client.post("/api/acgo/imports",json=payload).json()
        assert result["status"]=="running"
        assert client.request("DELETE","/api/acgo/imports/"+result["id"],json={}).status_code==200
        assert client.get("/api/acgo/imports/"+result["id"]).status_code==404
        result=client.post("/api/acgo/imports",json=payload).json()
        assert client.request("DELETE","/api/students/"+student["id"],json={"confirm_name":"测试同学"}).status_code==200
        assert client.get("/api/acgo/imports/"+result["id"]).status_code==404

def test_saved_materials_allow_completion_conditions_before_analysis_only(tmp_path,monkeypatch):
    monkeypatch.setattr(db,"DATABASE",tmp_path/"test.sqlite3")
    db.init_db()
    student=db.save_student(StudentInput(name="测试同学",age=12,grade="初一").model_dump())
    data=FeedbackInput(student_id=student["id"],start_date="2026-08-14",end_date="2026-08-14",tracks=["J"],target_year=2026,topics="模拟").model_dump(mode="json")
    feedback=db.create_feedback(data)
    with TestClient(app,base_url="http://localhost") as client:
        data["subjective_observation"]="课堂观察"
        path=f"/api/reports/{feedback['id']}/input"
        assert client.put(path,json={"revision":0,"input":data}).status_code==200
        assert client.put(path,json={"revision":0,"input":data}).status_code==400
        db.update_feedback(feedback["id"],status="running")
        assert client.put(path,json={"revision":1,"input":data}).status_code==400

def test_analysis_keeps_early_failed_versions_without_deleting_archived_code():
    attempts=[dict(id=str(i),code=("version"+str(i))*1000,result="WA" if i<10 else "AC",submitted_at=f"2026-08-14T10:{i:02d}:00Z") for i in range(15)]
    problem={"title":"题目","submissions":attempts,"source":{"selected_submission_id":"14"}}
    original=deepcopy(problem)
    selected=for_analysis(problem)
    assert problem==original
    assert len(selected["submissions"])==15
    assert all(selected["submissions"][i]["code"] for i in [0,1,2,9,10,14])
    assert selected["submissions"][5]["code"]=="" and selected["submissions"][5]["code_in_analysis"] is False
    small={"title":"题目","submissions":[{**a,"code":"short"} for a in attempts]}
    assert all(a["code_in_analysis"] for a in for_analysis(small)["submissions"])

def test_automatic_archive_supports_two_tasks_dates_and_persistence(tmp_path,monkeypatch):
    monkeypatch.setattr(db,"DATABASE",tmp_path/"test.sqlite3")
    db.init_db()
    calls=[]
    async def worker(data,progress=None):
        calls.append((data["kind"],data["user_id"]))
        problem={"title":"题目","code":"code","submissions":[{"id":"1","submitted_at":"2026-08-14T01:00:00Z","result":"AC","language":"cpp","code":"code"}],
            "source":{"kind":data["kind"],"task_id":data["task_id"],"team_id":data["team_id"],"user_id":data["user_id"],"question_id":"33","task_url":data["task_url"],"problem_url":"https://www.acgo.cn/problemset/info/33","fetched_at":"2026-10-08T00:00:00Z","selected_submission_id":"1","period_start":data["start_date"],"period_end":data["end_date"],"history_count":1}}
        return {"student":{"user_id":data["user_id"]},"problems":[problem],"warnings":[],"failed_questions":[],"kind":data["kind"],"task_id":data["task_id"],"task_url":data["task_url"]}
    monkeypatch.setattr(acgo,"run_worker",worker)
    data=ACGOArchiveInput(name="新同学",user_id="5085016",team="2042058713337094144",homework="24156",contest="22884")
    async def run():
        job=acgo.start_archive(data)
        await acgo.tasks[job["id"]]
        assert job["status"]=="completed",job["error"]
        archive=db.practice_archive(job["result"]["archive_id"])
        assert archive["start_date"]==archive["end_date"]=="2026-08-14"
        assert len(archive["content"]["problems"])==2
        assert db.student(archive["student_id"])["profile"]["age"] is None
        repeated=acgo.start_archive(data)
        await acgo.tasks[repeated["id"]]
        assert repeated["result"]["archive_id"]==archive["id"]
        assert len(db.practice_archives())==1
        db.init_db()
        assert db.practice_archive(archive["id"])["content"]["problems"][0]["code"]=="code"
        with pytest.raises(ValueError,match="姓名"):
            acgo.start_archive(data.model_copy(update={"name":"其他名字"}))
        await acgo.forget_student(archive["student_id"])
    asyncio.run(run())
    assert calls==[("homework","5085016"),("contest","5085016")]*2
    archive = db.practice_archives()[0]
    with TestClient(app, base_url="http://localhost") as client:
        saved = client.get("/api/practice-archives/" + archive["id"])
        assert saved.status_code == 200
        assert saved.json()["content"]["problems"][0]["submissions"][0]["code"] == "code"
        backup = client.get("/api/backup")
        assert backup.status_code == 200
        with zipfile.ZipFile(io.BytesIO(backup.content)) as packed:
            database = next(name for name in packed.namelist() if name.endswith("feedback.sqlite3"))
            restored = tmp_path / "restored.sqlite3"
            restored.write_bytes(packed.read(database))
        with sqlite3.connect(restored) as conn:
            content = json.loads(conn.execute("SELECT content FROM practice_archives").fetchone()[0])
        assert content["problems"][0]["submissions"][0]["code"] == "code"
        assert client.request("DELETE", "/api/students/" + archive["student_id"], json={"confirm_name": "新同学"}).status_code == 200
        assert client.get("/api/practice-archives/" + archive["id"]).status_code == 404

def test_comma_tasks_deduplicate_and_validate_every_link():
    data = ACGOArchiveInput(name="同学", user_id="5085016", team="2042058713337094144",
        homework="24031, 24156,24156", contest="22884,22900")
    configs = acgo.task_configs(data, student_id="student", start_date="2026-08-12", end_date="2026-08-14")
    assert [(c["kind"],c["task_id"]) for c in configs] == [("homework","24031"),("homework","24156"),("contest","22884"),("contest","22900")]
    assert all(c["team_id"] == "2042058713337094144" for c in configs)
    with pytest.raises(ValueError, match="不能留空"):
        acgo.task_configs(data.model_copy(update={"homework":"24031,,24156"}), student_id="s",start_date="2026-08-12",end_date="2026-08-14")
    with pytest.raises(ValueError, match="官方"):
        acgo.task_configs(data.model_copy(update={"contest":"22884,https://example.com/contest/detail/22900"}), student_id="s",start_date="2026-08-12",end_date="2026-08-14")

def test_missing_submission_is_context_not_a_zero_score():
    abilities = [{"id":f"A{i:02d}","score":None,"evidence":[],"reason":"未知"} for i in range(1,7)]
    score = {"id":"K008","score":30,"evidence":["current:p0"],"reason":"没有提交"}
    with pytest.raises(ValueError, match="未提交"):
        validate_scores([score],abilities,{"current:p0"},None,{"current:p0"})
    score["score"] = None
    validate_scores([score],abilities,{"current:p0"},None,{"current:p0"})

def test_recommendations_link_only_to_verified_collections():
    snapshot = {"collections":[{"id":"1","title":"题单","url":"https://www.acgo.cn/collection/1","ready":True,
        "questions":[{"id":"2","title":"题目","url":"https://www.acgo.cn/problemset/info/2"}]}]}
    payload = {"problems":[{"code":"code","source":{"question_id":"2"}}]}
    item = {"collection_id":"1","practice_mode":"new","evidence":["current:p0"]}
    practice.validate_training({"recent":[item]},snapshot,payload,{"current:p0"})
    recommended = practice.recommendations({"recent":[item]},snapshot)
    assert recommended[0]['questions']==[]
    practice.validate_recommendations({"practice_recommendations":recommended},snapshot)
    recommended[0]["url"] = "https://example.com/collection/1"
    with pytest.raises(ValueError, match="链接"):
        practice.validate_recommendations({"practice_recommendations":recommended},snapshot)

def test_partial_batch_preserves_successful_tasks_and_flags_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(db,"DATABASE",tmp_path/"test.sqlite3")
    db.init_db()
    async def worker(config, progress=None):
        if config["task_id"] == "1":
            raise ValueError("作业不存在")
        problem={"title":"未提交题目","submission_state":"no_submission","code":"","submissions":[],
            "source":{"kind":"homework","task_id":"2","team_id":config["team_id"],"user_id":config["user_id"],"question_id":"33",
                "task_url":config["task_url"],"problem_url":"https://www.acgo.cn/problemset/info/33","fetched_at":"2026-10-08T00:00:00Z",
                "selected_submission_id":"","period_start":config["start_date"],"period_end":config["end_date"],"history_count":0}}
        return {"student":{"user_id":config["user_id"]},"kind":"homework","task_id":"2","task_url":config["task_url"],
            "problems":[problem],"warnings":[],"failed_questions":[]}
    monkeypatch.setattr(acgo,"run_worker",worker)
    data=ACGOArchiveInput(name="同学",user_id="5085016",team="2042058713337094144",homework="1,2",start_date="2026-08-14",end_date="2026-08-14")
    async def run():
        job=acgo.start_archive(data)
        await acgo.tasks[job["id"]]
        assert job["status"]=="completed", job["error"]
        archived=db.practice_archive(job["result"]["archive_id"])
        assert archived["content"]["failed_tasks"][0]["task_id"]=="1"
        assert archived["content"]["problems"][0]["source"]["history_count"]==0
        assert job["result"]["unsubmitted_count"]==1
        undated=acgo.start_archive(data.model_copy(update={"start_date":None,"end_date":None}))
        await acgo.tasks[undated["id"]]
        assert undated["status"]=="failed" and "日期" in undated["error"]
    asyncio.run(run())


def test_parent_style_is_the_first_rule_in_every_model_instruction():
    from backend.pipeline import COMMON, STYLE_RULE, PARENT_COMMON, PARENT_INSTRUCTION
    assert COMMON.startswith(STYLE_RULE)
    assert "知识点名称" in STYLE_RULE and "自然交流" in STYLE_RULE
    assert (PARENT_COMMON+PARENT_INSTRUCTION).startswith(STYLE_RULE)

def test_parent_copy_does_not_invent_lecture_boundaries_or_future_first_round():
    from backend.validation import validate_parent
    payload={"problems":[{"completion_context":"practice_then_explanation","pre_explanation_submissions":None,"explanation_started_at":None}],
        "target_year":2026,"reference_date":"2026-10-08","tracks":["J"],"admissions":False}
    report={"summary":"讲解后能把题目做对。","highlights":[],"next_steps":["离第一轮还有一个月，可以安排两套第一轮模拟。"],
        "positions":[{"track":"J","label":"基础训练阶段","basis":""}],"admissions_text":"","admissions_sources":[]}
    warnings=validate_parent(report,payload)
    assert any("讲解时点" in w for w in warnings)
    assert any("第一轮已结束" in w for w in warnings)
