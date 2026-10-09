"""One current report per study period, with safe replacement and legacy migration."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.models import FeedbackInput, StudentInput


@pytest.fixture
def database(tmp_path, monkeypatch):
    module = importlib.import_module('backend.app')
    monkeypatch.setattr(db, 'DATABASE', tmp_path/'reports.sqlite3')
    monkeypatch.setattr(module, 'DATA', tmp_path)
    db.init_db()
    return TestClient(module.app, base_url='http://localhost')


def materials():
    student = db.save_student(StudentInput(name='测试同学',age=13,grade='初二').model_dump())
    return FeedbackInput(student_id=student['id'],start_date='2026-10-01',end_date='2026-10-05',
        reference_date='2026-10-09',target_year=2026,tracks=['J','S'],topics='模拟',mode='live').model_dump(mode='json')


def test_changed_materials_replace_current_report_and_preserve_confirmed_context(database):
    data = materials()
    first = db.create_feedback(data)
    db.update_feedback(first['id'],status='review',draft={'summary':'已确认内容'},stages={'diagnosis:0':{'old':True}},analysis={'old':True})
    confirmed = db.save_review(first['id'],0,{'summary':'已确认内容'},{},True)
    old_versions = deepcopy(db.versions(first['id']))
    changed = {**data,'tracks':['S'],'supplements':'新的课堂观察'}
    result = database.post('/api/reports',json=changed)
    assert result.status_code==200,result.text
    current = result.json()
    assert current['id']==first['id'] and current['revision']==confirmed['revision']+1
    assert current['status']=='draft' and current['draft'] is None and current['analysis'] is None and current['stages']=={}
    assert len(db.list_feedbacks())==1 and db.students()[0]['report_count']==1
    assert len(db.list_feedbacks(include_replaced=True))==2
    assert db.versions(first['id'])==old_versions
    assert db.version_context(current,old_versions[0])['input']==data
    legacy_version={**old_versions[0],'metadata':{}}
    assert db.version_context(current,legacy_version)['input']==data
    assert db.version_context(current,legacy_version)['analysis']=={'old':True}
    assert db.history(data['student_id'],'2026-10-06','next')[0]['input']==data
    assert database.post('/api/reports',json=changed).json()['revision']==current['revision']
    later = {**data,'start_date':'2026-10-06','end_date':'2026-10-07'}
    assert database.post('/api/reports',json=later).json()['id']!=first['id']
    # Live and explicitly marked demonstration reports cannot replace each other.
    assert db.create_feedback({**data,'mode':'demo'})['id']!=first['id']
    assert len(db.list_feedbacks())==3


def test_concurrent_creation_reuses_id_and_processing_rejects_replacement(database):
    data = materials()
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda _:db.create_feedback(data)['id'],range(16)))
    assert len(set(ids))==1 and len(db.list_feedbacks())==1
    ident = ids[0]
    db.start_job(ident,0,'正在更新')
    response = database.post('/api/reports',json={**data,'supplements':'改动'})
    assert response.status_code==400 and db.feedback(ident)['input']==data
    assert len(db.list_feedbacks(include_replaced=True))==1
    with pytest.raises(ValueError,match='正在处理'):
        db.start_job(ident,0,'重复启动')


def test_legacy_duplicates_consolidate_without_losing_originals_or_versions(database):
    data = materials()
    older = db.create_feedback(data)
    db.save_review(older['id'],0,{'summary':'旧确认稿'},{},True)
    with db.connection() as conn:
        conn.execute('DROP INDEX current_period_report')
        newer = dict(conn.execute('SELECT * FROM feedbacks WHERE id=?',(older['id'],)).fetchone())
        newer.update(id=str(uuid4()),revision=0,status='draft',created_at='2026-10-09T23:00:00+08:00')
        newer['input']=json.dumps({**data,'tracks':['S']})
        conn.execute('INSERT INTO feedbacks('+','.join(newer)+') VALUES('+','.join('?' for _ in newer)+')',tuple(newer.values()))
    db.save_review(newer['id'],0,{'summary':'新确认稿'},{},True)
    original_versions = {v['id']:v for fid in (older['id'],newer['id']) for v in db.versions(fid)}
    db.init_db();db.init_db()
    assert [r['id'] for r in db.list_feedbacks()]==[newer['id']]
    assert db.feedback(older['id'])['superseded_by']==newer['id']
    assert db.feedback(older['id'])['draft']['summary']=='旧确认稿'
    assert {v['id']:v for v in db.versions(newer['id'])}==original_versions
    assert database.post('/api/reports/'+older['id']+'/rewrite',json={}).status_code==400
    assert db.students()[0]['report_count']==1


def test_material_edit_revision_and_period_guards(database):
    data = materials()
    entry = db.create_feedback(data)
    db.update_feedback(entry['id'],status='review',draft={'summary':'原稿'},stages={'done':True})
    path='/api/reports/'+entry['id']+'/input'
    changed={**data,'supplements':'补充观察'}
    result=database.put(path,json={'revision':0,'input':changed})
    assert result.status_code==200 and result.json()['id']==entry['id']
    assert database.put(path,json={'revision':0,'input':changed}).status_code==400
    assert database.put(path,json={'revision':1,'input':{**changed,'end_date':'2026-10-06'}}).status_code==400
    assert database.put(path,json={'revision':1,'input':changed}).json()['revision']==1
    with pytest.raises(ValueError,match='已更新'):
        db.start_job(entry['id'],0,'旧界面更新')
