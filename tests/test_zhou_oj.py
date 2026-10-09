import asyncio
import json
import time
import pytest
from fastapi.testclient import TestClient
from backend import acgo,csp_exam,db
from backend.app import app
from backend.evidence import source_context,assessment_basis
from backend.attempts import for_analysis
from backend.batching import problem_facts
from backend.pipeline import parent_materials,parent_copy_data


def test_contest_ids_and_links_normalize_without_directory_or_key(monkeypatch):
    monkeypatch.setattr(csp_exam,"connection",lambda:{"base_url":"http://example.test:8080","admin_key":"private-test"})
    result=csp_exam.normalize_contests(['c12,c8','http://example.test:8080/admin?c=c12&key=private-test','http://example.test:8080/enter?c=c13'])
    assert result==['c12','c8','c13'] and 'private-test' not in json.dumps(result)


@pytest.mark.parametrize('value',['c12,','c12，c8','http://other.test/admin?c=c12','http://example.test:8080/admin?c=c12&c=c13','../c12'])
def test_invalid_or_foreign_contest_values_are_rejected(monkeypatch,value):
    monkeypatch.setattr(csp_exam,"connection",lambda:{"base_url":"http://example.test:8080"})
    with pytest.raises(ValueError):csp_exam.normalize_contests([value])


def test_connector_requires_a_specific_contest(monkeypatch):
    monkeypatch.setattr(csp_exam,"connection",lambda:{"base_url":"http://example.test","admin_key":"private-test"})
    async def run():
        client=csp_exam.Client()
        try:
            with pytest.raises(ValueError,match='指定比赛号'):await client.get('/admin')
        finally:await client.close()
    asyncio.run(run())


def test_oi_metadata_and_teacher_overrides_reach_all_analysis_stages():
    info=csp_exam.contest_info('<h1>管理端 · 真实比赛</h1><p>CSP 赛制</p><input name="duration" value="210">','c12')
    assert info=={'title':'真实比赛','format':'oi_csp','duration_minutes':210}
    assert csp_exam.contest_info('<p>IOI 赛制</p>','c8')['format']=='ioi'
    problem={'title':'题目','code':'original','judge_result':'AC','source':{'platform':'csp_exam','selected_submission_id':'one','contest_format':'oi_csp','submission_semantics':'final_submission','contest_duration_minutes':210,
        'assessment_tags':['OI/CSP赛制','讲师确认独立完成','讲师确认未接受题解或讲解']},'independent':False,'editorial_seen':True,'submissions':[{'id':'one','code':'original','result':'部分通过','score':25}], 'unverified_submissions':[]}
    source=source_context(problem)
    assert 'OI/CSP赛制' in source['assessment_tags']
    assert '讲师确认独立完成' not in source['assessment_tags'] and '讲师确认未接受题解或讲解' not in source['assessment_tags']
    assert for_analysis(problem)['source']==source
    assert problem_facts(problem,0)['source']['submission_semantics']=='final_submission'
    assert problem_facts(problem,0)['source']['contest_duration_minutes']==210
    assert assessment_basis(problem)['score']==25
    edited=for_analysis({**problem,'code':'changed'})
    assert '不继承' in edited['judge_result'] and assessment_basis(edited)['kind']=='static_only'
    assert '不继承' in problem_facts({**problem,'code':'changed'},0)['judge_result']
    payload={**{k:None for k in ('start_date','end_date','reference_date','target_year','tracks','topics','supplements','subjective_observation')},'problems':[{**problem,'observation':'','minutes':None}]}
    materials=parent_materials(payload)
    assert materials['problems'][0]['source']['submission_semantics']=='final_submission'
    copy_data=parent_copy_data(payload,{'abilities':[]},{'recent':[]},[],None)
    assert copy_data['本期作品事实'][0]['比赛材料条件']['contest_format']=='oi_csp'
    assert '讲师确认独立完成' in problem['source']['assessment_tags']


def test_direct_import_and_poll_cancel_routes_do_not_expose_admin_key(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATABASE',tmp_path/'test.sqlite3');db.init_db()
    student=db.save_student({'name':'测试学生','age':13,'grade':'初二','acgo_user_id':''})
    monkeypatch.setattr(csp_exam,'connection',lambda:{'base_url':'http://example.test:8080','admin_key':'private-test'})
    monkeypatch.setattr(acgo,'imports',{});monkeypatch.setattr(acgo,'tasks',{})
    def start(data):
        configs=acgo.task_configs(data,student_id=data.student_id,start_date=data.start_date,end_date=data.end_date)
        result={'id':'safe-job','status':'completed','created':time.time(),'input':acgo.safe_import_input(data,configs),'tasks':configs}
        acgo.imports['safe-job']=result
        return result
    monkeypatch.setattr(acgo,'start',start)
    with TestClient(app,base_url='http://127.0.0.1') as client:
        response=client.post('/api/zhou-oj/imports',json={'student_id':student['id'],'contests':'http://example.test:8080/admin?c=c12&key=private-test,c8',
            'start_date':'2026-10-01','end_date':'2026-10-05'})
        assert response.status_code==200,response.text
        assert 'private-test' not in response.text
        assert response.json()['input']['contests']=='c12,c8'
        assert all(t['contest_independent'] for t in response.json()['tasks'])
        assert client.get('/api/zhou-oj/imports/safe-job').status_code==200
        assert client.request('DELETE','/api/zhou-oj/imports/safe-job',json={}).status_code==200
        health=client.get('/api/health').json()
        assert health['assessment_mode']=='oj_records_and_code_analysis' and 'sandbox_ready' not in health
        paths=client.get('/openapi.json').json()['paths']
        assert '/api/csp-exam/contests' not in paths and '/api/practice-archives/imports' in paths
