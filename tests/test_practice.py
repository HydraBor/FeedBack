from copy import deepcopy

import pytest

from backend import practice
from backend.models import Training,ParentReport


def fixture(count=8):
    records=[{'id':str(i),'title':f'知识题单{i}','url':f'https://www.acgo.cn/collection/{i}',
              'ready':True,'topic_ids':['K001'],'knowledge':['模拟'],'description':'专题训练',
              'questions':[{'id':str(i),'title':'已有题目','url':f'https://www.acgo.cn/problemset/info/{i}','difficulty':1}]}
             for i in range(count)]
    items=[{'title':'专题训练','activity':'按需要选练，完成后复盘。','success':'能独立说清做法并完成程序。',
            'evidence':['current:p0'],'collection_id':str(i),'practice_mode':'new'} for i in range(count)]
    return {'collections':records},{'horizon':'目标CSP前','recent':items,'phases':[]}


def test_more_than_three_collections_need_no_specific_questions():
    snapshot,training=fixture()
    parsed=Training.model_validate(training).model_dump()
    practice.validate_training(parsed,snapshot,{'problems':[]},{'current:p0'})
    recommended=practice.recommendations(parsed,snapshot)
    assert len(recommended)==8 and all(not r['questions'] for r in recommended)
    practice.validate_recommendations({'practice_recommendations':recommended},snapshot)
    assert 'maxItems' not in ParentReport.model_json_schema()['properties']['practice_recommendations']
    assert 'question_ids' not in Training.model_json_schema()['$defs']['TrainingItem']['properties']


def test_duplicate_collections_are_combined_and_unknown_sources_fail():
    snapshot,training=fixture()
    training['recent']+=deepcopy(training['recent'])
    assert len(practice.recommendations(training,snapshot))==8
    training['recent'][0]['collection_id']='nonexistent'
    with pytest.raises(ValueError,match='已核实'):
        practice.validate_training(training,snapshot,{'problems':[]},{'current:p0'})
    training['recent'][0]['collection_id']='0'
    training['recent'][0]['evidence']=['made-up']
    with pytest.raises(ValueError,match='材料'):
        practice.validate_training(training,snapshot,{'problems':[]},{'current:p0'})


def test_model_receives_all_collection_metadata_without_member_lists():
    snapshot,_=fixture(40)
    catalog=practice.model_catalogue(snapshot,{'topic_scores':[{'id':'K001'}]})
    assert len(catalog)==40
    assert all('questions' not in item and item['problem_count']==1 for item in catalog)
