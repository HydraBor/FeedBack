import asyncio
import json
import pytest
from backend import acgo,csp_exam
from backend.models import FeedbackInput,ProblemInput

def test_large_archive_has_no_question_or_submission_count_cap():
    attempts=[{"id":str(i),"submitted_at":"2026-10-01T10:00:00+08:00","result":"WA","language":"cpp","code":"int main(){}"} for i in range(151)]
    problem=ProblemInput(title="练习",submissions=attempts).model_dump(mode="json")
    data=FeedbackInput(student_id="student",start_date="2026-10-01",end_date="2026-10-05",reference_date="2026-10-08",target_year=2026,tracks=["S"],problems=[problem]*61)
    assert len(data.problems)==61 and len(data.problems[0].submissions)==151

def test_parallel_task_workers_preserve_order_and_cancel_siblings(monkeypatch):
    async def run():
        active=0;peak=0;finished=[]
        async def worker(config,progress=None):
            nonlocal active,peak
            active+=1;peak=max(active,peak)
            try:
                await asyncio.sleep((4-int(config["task_id"]))*0.01)
                finished.append(config["task_id"])
                return {"student":{"user_id":"1"},"problems":[],"kind":"homework","task_id":config["task_id"],"task_url":"https://www.acgo.cn/homework/"+config["task_id"],"warnings":[],"failed_questions":[]}
            finally:active-=1
        monkeypatch.setattr(acgo,"run_worker",worker)
        configs=[{"kind":"homework","task_id":str(i),"user_id":"1","start_date":"2026-10-01","end_date":"2026-10-05","concurrency":3} for i in range(1,4)]
        result=await acgo.collect_tasks(configs,lambda message:None)
        assert peak==3 and finished==["3","2","1"]
        assert [t["id"] for t in result["tasks"]]==["1","2","3"]
        cancelled=[]
        async def slow(config,progress=None):
            try:
                if config["task_id"]=="1":
                    await asyncio.sleep(0.01);raise ValueError("学生 ID 不匹配")
                await asyncio.sleep(30)
            finally:cancelled.append(config["task_id"])
        monkeypatch.setattr(acgo,"run_worker",slow)
        with pytest.raises(ValueError,match="学生 ID"):
            await acgo.collect_tasks(configs,lambda message:None)
        assert sorted(cancelled)==["1","2","3"]
    asyncio.run(run())

def test_csp_connection_keeps_key_private_and_extracts_exact_student(tmp_path,monkeypatch):
    monkeypatch.setattr(csp_exam,"CONNECTION",tmp_path/"connection.json")
    response=csp_exam.save_connection({"admin_url":"http://example.test:8080/admin?key=secret-test"})
    assert response=={"base_url":"http://example.test:8080","configured":True}
    assert "secret-test" not in json.dumps(response)
    text='<table><tr><td>1</td><td><a href="/admin/student?c=c1&k=AA&key=secret-test">测试学生</a></td><td>100</td></tr></table>'
    assert csp_exam.student_from_scores(text,"测试学生")=="AA"
    duplicate=text.replace('</table>','<tr><td>2</td><td>测试学生</td><td><a href="/admin/student?c=c1&k=BB">BB</a></td></tr></table>')
    with pytest.raises(ValueError,match="同名"):
        csp_exam.student_from_scores(duplicate,"测试学生")
    assert csp_exam.student_from_scores(duplicate,"测试学生","BB")=="BB"

def test_csp_partial_score_code_and_time_do_not_require_browser():
    from backend.html_tree import parse
    page=parse('<div><b>提交时间</b>2026-10-03 12:26:51</div><div id="T1"><div class="kv"><div><b>得分</b>20 / 100 分</div><div><b>判分结果</b>部分正确</div><div><b>提交次数</b>3</div></div><details><summary>查看提交的代码</summary><pre>if(a&lt;b){}</pre></details></div>')
    assert csp_exam.time_from_detail(page).isoformat()=="2026-10-03T12:26:51+08:00"
    got=csp_exam.question_outcome(page.first("div",id="T1"))
    assert got["score"]==20 and got["result"]=="部分通过" and got["reported"]==3 and got["code"]=="if(a<b){}"

def test_csp_latest_code_uses_latest_score_and_question_time(monkeypatch):
    import html
    questions=html.escape(json.dumps([{"pid":"one","name":"one","title":"测试题","full":100}]),quote=True)
    class FakeClient:
        def __init__(self):self.config={"base_url":"http://example.test"}
        async def close(self):pass
        async def get(self,path,params=None):
            if path=="/admin/scores":return '<table><tr><td>1</td><td>学生</td><td><a href="/admin/student?c=c1&k=AA">详情</a></td></tr></table>'
            if path=="/admin":
                assert params=={"c":"c1"}
                return f'<h1>管理端 · 限时测试</h1><p>CSP 赛制</p><input name="duration" value="210"><input name="problems_json" value="{questions}">'
            if path=="/admin/problem-detail":return '<textarea name="statement">完整题面</textarea>'
            if path=="/admin/file":return 'latest code'
            if path=="/admin/student":return '''<h1>学生 AA</h1><div><b>提交时间</b>2026-10-03 12:00:00</div>
                <a href="/admin/file?c=c1&k=AA&f=one.cpp">one.cpp</a>
                <div id="T1"><div class="kv"><div><b>得分</b>100 / 100 分</div><div><b>判分结果</b>全部正确</div>
                <div><b>提交次数</b>2</div><div><b>最近一次</b>超时（10 分，2026-10-04T09:00:00+08:00）</div></div>
                <details><summary>查看提交的代码</summary><pre>best code</pre></details></div>'''
            raise AssertionError(path)
    monkeypatch.setattr(csp_exam,"Client",FakeClient)
    config={"task_id":"c1","student_name":"学生","start_date":"2026-10-04","end_date":"2026-10-04","contest_independent":True}
    result=asyncio.run(csp_exam.collect(config))
    problem=result["problems"][0]
    assert problem["code"]=="latest code" and problem["submissions"][0]["score"]==10
    assert problem["submissions"][0]["result"]=="部分通过（TLE）"
    assert problem["submissions"][0]["submitted_at"]=="2026-10-04T09:00:00+08:00"
    assert result["available_dates"]=={"2026-10-04":1}
    assert not problem["source"]["history_complete"]
    assert problem["source"]["contest_format"]=="oi_csp" and problem["source"]["submission_semantics"]=="final_submission"
    assert problem["source"]["contest_duration_minutes"]==210 and "讲师确认独立完成" in problem["source"]["assessment_tags"]
    outside=asyncio.run(csp_exam.collect({**config,"start_date":"2026-10-03","end_date":"2026-10-03"}))
    assert outside["problems"][0]["code"]=="" and outside["problems"][0]["submissions"]==[]
    assert csp_exam.score_result(None,None,"")!="AC"

def test_worker_start_failure_cleans_temporary_result_file(tmp_path,monkeypatch):
    monkeypatch.setattr(acgo,"DATA",tmp_path)
    async def fail(*args,**kwargs):raise OSError("worker unavailable")
    monkeypatch.setattr(asyncio,"create_subprocess_exec",fail)
    with pytest.raises(OSError):asyncio.run(acgo.run_worker({"platform":"csp_exam"}))
    assert list(tmp_path.iterdir())==[]

def test_unknown_time_snapshots_are_saved_but_excluded_from_model_evidence():
    from backend.attempts import for_analysis
    problem={"title":"练习","submissions":[],"unverified_submissions":[{"id":"old","code":"old secret source","source_file":"old.cpp"}]}
    analysed=for_analysis(problem)
    assert analysed["unverified_submission_count"]==1
    assert "old secret source" not in json.dumps(analysed)
    assert problem["unverified_submissions"][0]["code"]=="old secret source"

def test_large_feedback_diagnoses_every_problem_beyond_old_call_budget(tmp_path,monkeypatch):
    from backend import db,pipeline
    monkeypatch.setattr(db,"DATABASE",tmp_path/"feedback.sqlite3")
    db.init_db()
    student=db.save_student({"name":"测试学生","age":13,"grade":"初二","acgo_user_id":""})
    payload=FeedbackInput(student_id=student["id"],start_date="2026-10-01",end_date="2026-10-05",reference_date="2026-10-08",target_year=2026,tracks=["S"],
        problems=[ProblemInput(title=f"题目{i}",code="int main(){}",independent=True,editorial_seen=False) for i in range(61)]).model_dump(mode="json")
    feedback=db.create_feedback(payload)
    seen=[];instances=[]
    class FakeProvider:
        def __init__(self):
            self.config={"max_calls":48,"model":"test"};self.calls=0;self.usage={"prompt_tokens":0,"completion_tokens":0};instances.append(self)
        async def generate(self,instruction,data,schema):
            assert self.calls<self.config["max_calls"]
            self.calls+=1
            if schema.__name__=="Diagnosis":
                seen.append(data["problem_index"])
                return {"problem_index":data["problem_index"],"solution":"已有思路"*500,"correctness":"需要检验"*500,"efficiency":"需要检查"*500,"implementation":"有代码","readability":"可读",
                    "observed_behaviors":[],"topic_ids":["K008"],"evidence":[data["evidence"]],"limitations":[],"early_attempts":"未知","changes":"未知","completion_basis":"独立条件由讲师提供"}
            if schema.__name__=="Analysis":
                ids=[d["evidence"][0] for d in data["diagnoses"]] if "diagnoses" in data else list(dict.fromkeys(e for g in data["groups"] for s in g["topic_scores"] for e in s["evidence"]))
                return {"topic_scores":[{"id":"K008","score":60,"evidence":ids,"reason":"综合材料","scope":""}],
                    "abilities":[{"id":f"A{i:02d}","score":None,"evidence":[],"reason":"材料不足","source":"api"} for i in range(1,7)]}
            if schema.__name__=="Training":return {"horizon":"近期练习","recent":[{"title":"新题练习","activity":"先说明做法，再动手完成。","success":"独立完成练习。","evidence":["current:p0"],"collection_id":"","practice_mode":"new"}],"phases":[]}
            if schema.__name__=="ParentCopy":return {"summary":"本期完成了练习，锻炼了思考和动手能力。","highlights":["能把自己的想法写成程序。"],"next_steps":["继续练习同类新题。"]}
            raise AssertionError(schema.__name__)
    monkeypatch.setattr(pipeline,"DeepSeek",FakeProvider)
    monkeypatch.setattr(pipeline.knowledge,"references",lambda tracks:[])
    asyncio.run(pipeline.generate(feedback["id"]))
    result=db.feedback(feedback["id"])
    assert result["status"]=="review",result["error"]
    assert seen==list(range(61)) and instances[0].calls>48
    assert len(result["analysis"]["scoring"]["topic_scores"][0]["evidence"])==61
