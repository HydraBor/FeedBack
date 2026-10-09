import asyncio
import json
import httpx
import pytest
from backend import db,pipeline,provider,config
from backend.models import FeedbackInput,ProblemInput,ParentCopy,Analysis


def test_concurrent_diagnoses_save_siblings_and_resume_only_missing(tmp_path,monkeypatch):
    monkeypatch.setattr(db,"DATABASE",tmp_path/"feedback.sqlite3")
    db.init_db()
    student=db.save_student({"name":"测试学生","age":13,"grade":"初二","acgo_user_id":""})
    payload=FeedbackInput(student_id=student["id"],start_date="2026-10-01",end_date="2026-10-05",target_year=2026,tracks=["S"],
        problems=[ProblemInput(title=f"题目{i}",code="int main(){}",independent=True,editorial_seen=False) for i in range(7)]).model_dump(mode="json")
    report=db.create_feedback(payload)
    seen=[];finished=[];peak=0;active=0;fail_once=True;release_first=asyncio.Event()
    class FakeProvider:
        def __init__(self):
            self.config={"max_calls":48,"model":"test","analysis_concurrency":3};self.calls=0;self.usage={"prompt_tokens":0,"completion_tokens":0}
        async def generate(self,instruction,data,schema):
            nonlocal active,peak,fail_once
            self.calls+=1
            if schema.__name__=="Diagnosis":
                assert "assessment_basis" in data and "judge" not in data
                i=data["problem_index"];seen.append(i);active+=1;peak=max(peak,active)
                try:
                    if i==0:await release_first.wait()
                    await asyncio.sleep((7-i)*.004)
                    if i==2 and fail_once:
                        fail_once=False;raise provider.ProviderError("模拟网络失败")
                    finished.append(i)
                    return {"problem_index":i,"solution":"已形成思路","correctness":"尚需检验","efficiency":"需检查","implementation":"能实现","readability":"可读",
                        "observed_behaviors":[],"topic_ids":["K008"],"evidence":[data["evidence"]],"limitations":[]}
                finally:
                    active-=1
                    if i==1:release_first.set()
            if schema.__name__=="Analysis":return {"topic_scores":[{"id":"K008","score":60,"evidence":[f"current:p{i}" for i in range(7)],"reason":"综合材料","scope":""}],
                "abilities":[{"id":f"A{i:02d}","score":None,"evidence":[],"reason":"材料不足","source":"api"} for i in range(1,7)]}
            if schema.__name__=="Training":return {"horizon":"近期练习","recent":[{"title":"新题练习","activity":"先说明做法，再完成程序。","success":"独立完成练习。","evidence":["current:p0"],"collection_id":"","practice_mode":"new"}],"phases":[]}
            if schema.__name__=="ParentCopy":return {"summary":"本期完成了练习，锻炼了思考和动手能力。","highlights":["能把自己的想法写成程序。"],"next_steps":["继续练习同类新题。"]}
            raise AssertionError(schema.__name__)
    monkeypatch.setattr(pipeline,"DeepSeek",FakeProvider)
    monkeypatch.setattr(pipeline.knowledge,"references",lambda tracks:[])
    asyncio.run(pipeline.generate(report["id"]))
    failed=db.feedback(report["id"])
    assert failed["status"]=="failed" and peak==3 and len(seen)==7 and active==0
    assert len([k for k in failed["stages"] if k.startswith("diagnosis:")])==6
    assert failed["stages"]["analysis_progress"]["completed"]==6
    assert finished!=sorted(finished)
    seen.clear()
    asyncio.run(pipeline.generate(report["id"]))
    result=db.feedback(report["id"])
    assert result["status"]=="review",result["error"]
    assert seen==[2]
    assert [d["problem_index"] for d in result["analysis"]["diagnoses"]]==list(range(7))
    assert result["stages"]["analysis_progress"]["completed"]==7
    assert result["stages"]["analysis_progress"]["active"]==[]


def test_truncated_json_is_retried_with_more_output_budget(monkeypatch):
    calls=[]
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,**kwargs):
            calls.append(kwargs["json"])
            return httpx.Response(200,json={"choices":[{"finish_reason":"length" if len(calls)==1 else "stop","message":{"content":'{"topic_scores":[],"abilities":[]}',"reasoning_content":"private thought"}}],"usage":{"prompt_tokens":10}})
    monkeypatch.setattr(provider,"settings",lambda:{"api_key":"secret-test","base_url":"https://api.deepseek.com","model":"deepseek-flash","max_calls":3,"timeout":1})
    monkeypatch.setattr(provider.httpx,"AsyncClient",Client)
    instance=provider.DeepSeek()
    assert asyncio.run(instance.generate("json",{},Analysis))=={"topic_scores":[],"abilities":[]}
    assert len(calls)==2 and calls[1]["max_tokens"]==calls[0]["max_tokens"]*2
    assert calls[0]["thinking"]=={"type":"enabled"} and calls[0]["reasoning_effort"]=="low"
    assert [e["outcome"] for e in instance.events]==["started","truncated","started","success"]
    assert "secret-test" not in json.dumps(instance.events) and "private thought" not in json.dumps(instance.events)


def test_provider_parallel_limit_budget_and_usage_are_consistent(monkeypatch):
    active=0;peak=0
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,**kwargs):
            nonlocal active,peak
            active+=1;peak=max(peak,active)
            try:
                await asyncio.sleep(.01)
                return httpx.Response(200,json={"choices":[{"finish_reason":"stop","message":{"content":'{"summary":"结果","highlights":["成果"],"next_steps":["建议"]}'}}],"usage":{"prompt_tokens":10,"completion_tokens":2}})
            finally:active-=1
    monkeypatch.setattr(provider,"settings",lambda:{"api_key":"secret-test","base_url":"https://api.deepseek.com","model":"deepseek-flash","max_calls":4,"timeout":1,"analysis_concurrency":2})
    monkeypatch.setattr(provider.httpx,"AsyncClient",Client)
    instance=provider.DeepSeek()
    async def run():return await asyncio.gather(*(instance.generate("json",{},ParentCopy) for _ in range(6)),return_exceptions=True)
    results=asyncio.run(run())
    assert peak==2 and instance.calls==4
    assert sum(isinstance(r,provider.ProviderError) for r in results)==2
    assert instance.usage=={"prompt_tokens":40,"completion_tokens":8}
    assert [e["call"] for e in instance.events if e["outcome"]=="started"]==[1,2,3,4]


def test_remote_protocol_error_retries_and_records_safe_cause(monkeypatch):
    calls=0
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,**kwargs):
            nonlocal calls
            calls+=1
            if calls==1:raise httpx.RemoteProtocolError("secret-test should never be logged")
            return httpx.Response(200,json={"choices":[{"message":{"content":'{"summary":"结果","highlights":["成果"],"next_steps":["建议"]}'}}]})
    async def no_wait(seconds):pass
    monkeypatch.setattr(provider,"settings",lambda:{"api_key":"secret-test","base_url":"https://api.deepseek.com","model":"deepseek-flash","max_calls":3,"timeout":1})
    monkeypatch.setattr(provider.httpx,"AsyncClient",Client)
    monkeypatch.setattr(provider.asyncio,"sleep",no_wait)
    instance=provider.DeepSeek()
    assert asyncio.run(instance.generate("json",{},ParentCopy))["summary"]=="结果"
    assert calls==2 and instance.events[1]["error_type"]=="RemoteProtocolError"
    assert "secret-test" not in json.dumps(instance.events)


def test_saving_concurrency_keeps_root_key_source(tmp_path,monkeypatch):
    monkeypatch.setattr(config,"ROOT",tmp_path)
    monkeypatch.setattr(config,"SETTINGS",tmp_path/"settings.json")
    monkeypatch.delenv("DEEPSEEK_API_KEY",raising=False)
    key="sk-test-only-1234567890"
    (tmp_path/"deepseek").write_text(key)
    config.save_settings({"analysis_concurrency":6})
    assert json.loads(config.SETTINGS.read_text())=={"analysis_concurrency":6}
    assert config.settings()["api_key"]==key and config.settings()["analysis_concurrency"]==6
    config.save_settings({"model":"deepseek-v4-pro"})
    assert "api_key" not in json.loads(config.SETTINGS.read_text())


def test_fatal_provider_failure_cancels_running_siblings():
    finished=[]
    async def operation(i,item):
        try:
            if i==0:
                await asyncio.sleep(.01)
                raise provider.ProviderError("密钥失效",fatal=True)
            await asyncio.sleep(30)
        finally:finished.append(i)
    with pytest.raises(provider.ProviderError,match="密钥"):
        asyncio.run(pipeline.parallel_map(list(range(4)),operation,4))
    assert sorted(finished)==[0,1,2,3]
