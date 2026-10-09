"""Release regressions: audit provenance, annual forecasts and public/private boundaries."""
import asyncio
import importlib
import json
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from backend import db, knowledge, pipeline, provider, validation
from backend.library_audit import fingerprint, is_reviewed
from backend.models import FeedbackInput, ProblemInput, ParentCopy, ParentReport
from backend.validation import anonymize, validate_parent


def test_public_catalogue_all_reviewed_and_all_years_released():
    tasks = knowledge.problems()
    assert len(tasks) == 58 and all(is_reviewed(p) for p in tasks)
    papers = knowledge.references(['J', 'S'])
    assert {(p['rule']['track'], p['rule']['year']) for p in papers} == {(t, y) for t in ('J', 'S') for y in range(2019, 2026)}
    special = next(p for p in papers if p['rule']['year'] == 2019 and p['rule']['track'] == 'S')
    assert len(special['problems']) == 6 and special['duration_minutes'] == 420
    assert [s['duration_minutes'] for s in special['sessions']] == [210, 210]
    for task in tasks:
        review = json.loads((knowledge.PUBLIC / 'audits' / (task['id']+'.json')).read_text())
        assert review['review']['fingerprint'] == fingerprint(task)
        assert review['review']['assessment']['correctness_argument']
        compact = knowledge.reference_for_model(next(p for p in papers if task in p['problems']))
        assert 'editorial' not in compact['problems'][0]


def test_changed_material_closes_reference_release(monkeypatch):
    tasks = deepcopy(knowledge.problems())
    tasks[0]['editorial'] += '\n尚未复核的修改。'
    monkeypatch.setattr(knowledge, 'problems', lambda: tasks)
    assert not is_reviewed(tasks[0]) and knowledge.references(['J', 'S']) == []


@pytest.mark.parametrize('track, thresholds', [('J', [250, 100, 70]), ('S', [255, 110, 80])])
def test_2019_guangdong_grade_boundaries(track, thresholds):
    ref = next(p for p in knowledge.references([track]) if p['rule']['year'] == 2019)
    assert ref['rule']['thresholds'] == thresholds
    assert ref['rule']['reviewed'] and ref['rule']['complete_grade_lines']
    evidence = json.loads((knowledge.PUBLIC / ref['rule']['verification_evidence']).read_text())
    lists = sorted((item for item in evidence['award_lists'] if item['track'] == track), key=lambda item: item['grade'])
    assert [item['guangdong_min'] for item in lists] == thresholds
    assert all(item['scores_at_minimum'] > 0 and item['url'] in ref['rule']['verification_sources'] for item in lists)
    for index, threshold in enumerate(thresholds):
        for total, expected in ((threshold, ['一等', '二等', '三等'][index]),
                                (threshold - 1, ['二等', '三等', '基础训练阶段'][index])):
            per_task, remainder = divmod(total, len(ref['problems']))
            tasks = [{'problem_id': p['id'], 'lower': per_task + (i < remainder), 'upper': per_task + (i < remainder)}
                     for i, p in enumerate(ref['problems'])]
            result = {'papers': [{'track': track, 'year': 2019, 'tasks': tasks}]}
            position = knowledge.forecast_positions(result, [track], [ref])[0]
            assert expected in position['label']
            assert '2019' in position['basis']


def test_unknown_provincial_thresholds_are_not_invented():
    ref = next(p for p in knowledge.references(['J']) if p['rule']['year'] == 2019)
    ref = deepcopy(ref)
    ref['rule']['thresholds'][1:] = [None, None]
    ref['rule']['complete_grade_lines'] = False
    result = {'papers': [{'track':'J', 'year':2019, 'tasks':[{'problem_id':p['id'], 'lower':50, 'upper':50} for p in ref['problems']]}]}
    assert '暂不足' in knowledge.forecast_positions(result, ['J'], [ref])[0]['label']


def test_name_with_quotes_and_backslashes_is_anonymized():
    name = '测"试\\同学'
    value = {'code': f'// {name}\n', 'nested':[name, {'note': f'{name}完成练习'}], 'score':42, 'unknown':None}
    result = anonymize(value, name)
    assert name not in json.dumps(result, ensure_ascii=False)
    assert result['nested'][0] == '{{student}}' and result['score'] == 42 and result['unknown'] is None
    assert value['nested'][0] == name


@pytest.mark.parametrize('title,prose', [
    ('T146447.皇家宴会调度', '皇家宴会调度、跳板迷宫都通过了。'),
    ('CF1971A.My First Sorting Problem', '完成了 My First Sorting Problem。'),
    ('秘境', '比赛方面，秘境、其他题都通过了。'),
    ('分数', '完成了《分数》这道题。'),
])
def test_parent_prose_rejects_copied_problem_names(title,prose):
    payload={'problems':[{'title':title}]}
    report={'summary':prose,'highlights':[],'next_steps':[]}
    assert validation.parent_problem_names(report,payload)


def test_parent_short_everyday_words_and_chart_titles_are_not_blocked():
    payload={'problems':[{'title':'分数'},{'title':'课堂练习'}]}
    report={'summary':'本期完成多道课堂练习，分数说明放在图下方。','highlights':['能理清要求，把想法写成程序。'],'next_steps':['独立重做同类新题。'],
            'topic_scores':[{'scope':'《分数》'}],'practice_recommendations':[{'title':'分数专题题单'}]}
    assert not validation.parent_problem_names(report,payload)


def test_parent_writing_receives_behaviors_and_neutral_work_references():
    payload=FeedbackInput(student_id='fixture', start_date='2026-10-01', end_date='2026-10-05', target_year=2026, tracks=['J'],
        problems=[ProblemInput(title='跳板迷宫',code='int main(){}')]).model_dump(mode='json')
    scoring={'abilities':[{'id':'A01','score':70,'evidence':['current:p0'],'source':'api','reason':'读懂不同规则并按要求处理。'}]}
    diagnosis=[{'problem_index':0,'observed_behaviors':['按多项条件完成处理。'],'changes':'未提供修改过程。'}]
    materials=pipeline.parent_copy_data(payload,scoring,{'recent':[]},[],None,diagnosis)
    assert materials['本期作品事实'][0]['材料序号']==1
    assert '题目' not in materials['本期作品事实'][0]
    assert '跳板迷宫' not in json.dumps(materials,ensure_ascii=False)
    assert '内部判断理由' not in materials['能力依据'][0]
    example=materials['能力依据'][0]['具体表现供理解不照抄'][0]
    assert example['实际表现']==diagnosis[0]['observed_behaviors']
    assert example['已记录修改']=='未提供可核实的修改过程'


def test_parent_verified_contest_count_and_unknown_manual_source():
    payload=FeedbackInput(student_id='fixture', start_date='2026-10-01', end_date='2026-10-05', target_year=2026, tracks=['S'],
        problems=[ProblemInput(title='练习',code='int main(){}',completion_context='independent_timed_contest') for _ in range(3)]).model_dump(mode='json')
    for problem, task_id in zip(payload['problems'], ['c12','c12','c8']):
        problem['source']={'platform':'csp_exam','kind':'contest','task_id':task_id,'selected_submission_id':''}
    facts=pipeline.parent_copy_data(payload,{'abilities':[]},{'recent':[]},[],None)
    assert facts['本期成果概况']['已核实比赛场数']==2
    payload['problems'][0]['source']=None
    assert pipeline.parent_copy_data(payload,{'abilities':[]},{'recent':[]},[],None)['本期成果概况']['已核实比赛场数'] is None


def test_parent_technical_words_and_classroom_independence_are_checked():
    payload=FeedbackInput(student_id='fixture', start_date='2026-10-01', end_date='2026-10-05', target_year=2026, tracks=['J'],
        problems=[ProblemInput(title='课堂练习',code='int main(){}')]).model_dump(mode='json')
    report={'summary':'课堂练习中自己找到问题，完成了图论练习。','highlights':['能把想法写成程序。'],
            'next_steps':['练习合并关系并核对边界情况。'], 'positions':[{'track':'J','label':'基础训练阶段','basis':''}],
            'admissions_text':'','admissions_sources':[]}
    warnings=validate_parent(report,payload)
    assert any('图论' in w and '合并关系' in w and '边界情况' in w for w in warnings)
    assert any('课堂练习未记录独立' in w for w in warnings)
    report.update(summary='课堂练习完成后修改了遗漏的地方。比赛中独立完成了多道题。',next_steps=['重做几道相近的新题。'],topic_scores=[{'scope':'图论与合并关系'}])
    assert not validate_parent(report,payload)


def test_parent_copy_length_limit_does_not_restrict_teacher_editing():
    text={'summary':'成'*241,'highlights':['有具体学习成果。'],'next_steps':['继续练习。']}
    with pytest.raises(ValueError):
        ParentCopy.model_validate(text)
    report=ParentReport.model_validate({**text,'positions':[],'topic_scores':[],'abilities':[]})
    assert len(report.summary)==241


def test_final_code_count_cannot_imply_checks_or_unrecorded_revision():
    data = FeedbackInput(student_id='fixture', start_date='2026-10-01', end_date='2026-10-05', target_year=2026, tracks=['S'], problems=[ProblemInput(title='练习', code='int main(){}')]).model_dump(mode='json')
    data['problems'][0]['source']={'platform':'csp_exam','selected_submission_id':'one'}
    data['problems'][0]['submissions']=[{'id':'one','result':'AC','code':'int main(){}'}]
    report={'summary':'只提交了一次，说明写之前想清楚，已有检查习惯。','highlights':['没有放弃，继续尝试和调整。'],'next_steps':['完成同类练习。'],'positions':[{'track':'S','label':'CSP-S：基础训练阶段','basis':'训练估计'}],'admissions_text':'','admissions_sources':[]}
    warnings = validate_parent(report, data)
    assert any('OI最终代码' in w for w in warnings)
    assert any('提交次数' in w for w in warnings)
    assert any('修改过程' in w for w in warnings)
    _, scores, _, training, _ = pipeline.demo_results(data, knowledge.topics())
    works = pipeline.parent_copy_data(data, scores, training, [], None)['本期作品事实']
    assert '有多少次提交' not in works[0] and '不能' in works[0]['过程限制']
    data['admissions']=True; report['admissions_text']='自招建议'
    with pytest.raises(ValueError, match='尚未启用'):
        validate_parent(report, data)


@pytest.fixture
def editable_library(tmp_path, monkeypatch):
    tasks = deepcopy(knowledge.problems()[:2])
    (tmp_path/'problems.json').write_text(json.dumps(tasks, ensure_ascii=False))
    (tmp_path/'topics.json').write_text(json.dumps(knowledge.topics(), ensure_ascii=False))
    (tmp_path/'rules.json').write_text(json.dumps(knowledge.rules(), ensure_ascii=False))
    monkeypatch.setattr(knowledge, 'PUBLIC', tmp_path)
    return tasks


def test_library_edit_invalidates_audit_and_explicit_teacher_review_restores(editable_library):
    app = importlib.import_module('backend.app').app
    pid = editable_library[0]['id']
    client = TestClient(app, base_url='http://localhost')
    response = client.put('/api/library/problems/'+pid, json={'editorial':editable_library[0]['editorial']+'\n人工补充。'})
    assert response.status_code == 200
    task = knowledge.problems()[0]
    assert task['status'] == 'collected' and not is_reviewed(task)
    response = client.put('/api/library/problems/'+pid, json={'status':'reviewed', 'review_confirmed':True})
    assert response.status_code == 200
    assert is_reviewed(knowledge.problems()[0]) and knowledge.problems()[0]['review_metadata']['kind'] == 'teacher'

@pytest.mark.parametrize('patch', [{'topic_ids':{'id':'K001'}}, {'subtasks':[{'score':True}]}, {'editorial':None}, {'source':'https://user:pass@example.com/x'}, {'review_metadata':{'status':'passed'}}])
def test_bad_library_patch_is_rejected_without_writing(editable_library, patch):
    client = TestClient(importlib.import_module('backend.app').app, base_url='http://localhost')
    response = client.put('/api/library/problems/'+editable_library[0]['id'], json=patch)
    assert response.status_code == 400
    assert knowledge.problems() == editable_library


def test_concurrent_catalogue_edits_preserve_both_tasks(editable_library):
    client = TestClient(importlib.import_module('backend.app').app, base_url='http://localhost')
    def change(i):
        return client.put('/api/library/problems/'+editable_library[i]['id'], json={'editorial':editable_library[i]['editorial']+f'\n修改{i}。'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(change, [0, 1]))
    assert all(r.status_code == 200 for r in results)
    assert all(knowledge.problems()[i]['editorial'].endswith(f'修改{i}。') for i in (0, 1))


def test_removed_routes_and_backup_blocks_active_import(monkeypatch):
    module = importlib.import_module('backend.app')
    client = TestClient(module.app, base_url='http://localhost')
    assert client.get('/api/csp-exam/connection').status_code == 404
    assert '/api/acgo/archives' not in client.get('/openapi.json').json()['paths']
    assert client.post('/api/acgo/archives', json={}).status_code in (404, 405)
    class Pending:
        def done(self): return False
    monkeypatch.setattr(module.acgo, 'tasks', {'import':Pending()})
    assert client.get('/api/backup').status_code == 400


def test_annual_forecasts_run_concurrently_and_resume_failed_paper(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DATABASE', tmp_path/'feedback.sqlite3')
    db.init_db()
    student = db.save_student({'name':'测试同学', 'age':13, 'grade':'初二', 'acgo_user_id':''})
    data = FeedbackInput(student_id=student['id'], start_date='2026-10-01', end_date='2026-10-05', target_year=2026, tracks=['J','S'], problems=[ProblemInput(title='练习', code='int main(){}', independent=True, editorial_seen=False)]).model_dump(mode='json')
    entry = db.create_feedback(data)
    seen = []; peak = 0; active = 0; fail_once = True
    class FakeProvider:
        def __init__(self):
            self.config={'max_calls':48, 'model':'test', 'analysis_concurrency':3}; self.calls=0; self.usage={}
        async def generate(self, instruction, data, schema):
            nonlocal active, peak, fail_once
            self.calls += 1
            if schema.__name__ == 'Diagnosis':
                return {'problem_index':0,'solution':'已形成思路','correctness':'尚需检验','efficiency':'需检查','implementation':'能实现','readability':'可读','observed_behaviors':[],'topic_ids':['K008'],'evidence':['current:p0'],'limitations':[]}
            if schema.__name__ == 'Analysis':
                return {'topic_scores':[{'id':'K008','score':60,'evidence':['current:p0'],'reason':'本期材料','scope':''}], 'abilities':[{'id':f'A{i:02d}','score':None,'evidence':[],'reason':'材料不足','source':'api'} for i in range(1,7)]}
            if schema.__name__ == 'Forecasts':
                assert len(data['reference_papers']) == 1
                ref=data['reference_papers'][0]; rule=ref['rule']; key=(rule['track'],rule['year']); seen.append(key)
                active += 1; peak=max(peak,active)
                try:
                    await asyncio.sleep(.008)
                    if key == ('S',2022) and fail_once:
                        fail_once=False; raise provider.ProviderError('模拟一个年份请求失败')
                    return {'papers':[{'track':key[0],'year':key[1],'tasks':[{'problem_id':p['id'],'lower':45,'upper':60,'reason':'保守迁移','evidence':['current:p0']} for p in ref['problems']],'assumptions':['相近训练条件']}], 'limitations':['材料有限']}
                finally: active -= 1
            if schema.__name__ == 'Training':
                return {'horizon':'近期练习','recent':[{'title':'新题练习','activity':'先说明做法，再完成程序。','success':'独立完成练习。','evidence':['current:p0'],'collection_id':'','practice_mode':'new'}],'phases':[]}
            if schema.__name__ == 'ParentCopy':
                return {'summary':'本期完成了练习，锻炼了思考和动手能力。','highlights':['能把自己的想法写成程序。'],'next_steps':['继续练习同类新题。']}
            raise AssertionError(schema.__name__)
    monkeypatch.setattr(pipeline, 'DeepSeek', FakeProvider)
    asyncio.run(pipeline.generate(entry['id']))
    failed = db.feedback(entry['id'])
    assert failed['status'] == 'failed' and peak == 3 and len(seen) == 14
    assert len([k for k in failed['stages'] if k.startswith('forecast-paper:')]) == 13
    seen.clear()
    asyncio.run(pipeline.generate(entry['id']))
    result = db.feedback(entry['id'])
    assert result['status'] == 'review', result['error']
    assert seen == [('S',2022)] and len(result['analysis']['forecast']['papers']) == 14
    assert result['error'] is None
