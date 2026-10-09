"""Approved voice at the API boundary, factual scoping and both writing paths."""
import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from backend import db, pipeline, provider, knowledge
from backend.models import FeedbackInput, ProblemInput, ParentCopy, Diagnosis
from backend.parent_style import APPROVED_A_EXAMPLE, STYLE_ID
from backend.validation import validate_parent


@pytest.mark.parametrize('phrase', ['综合任务', '本期核实到', '这个场景下', '部分通过'])
def test_parent_style_rejects_task_and_analyst_prose(phrase):
    data=FeedbackInput(student_id='fixture',start_date='2026-10-01',end_date='2026-10-05',target_year=2026,tracks=['J'],topics='本期学习了编程基础。').model_dump(mode='json')
    report={'summary':phrase,'highlights':['能理清题目要求。'],'next_steps':['继续练习。'],
        'positions':[{'track':'J','label':'基础训练阶段','basis':''}],'admissions_text':'','admissions_sources':[]}
    assert validate_parent(report,data)
    assert not validate_parent({**report,**APPROVED_A_EXAMPLE},data)


def test_writing_materials_use_plain_observations_and_both_learning_contexts():
    data=FeedbackInput(student_id='fixture',start_date='2026-10-01',end_date='2026-10-05',target_year=2026,tracks=['S'],
        problems=[ProblemInput(title='跳板迷宫',code='int main(){}') for _ in range(3)]).model_dump(mode='json')
    contest=data['problems'][2]
    contest.update(independent=True,editorial_seen=False,completion_context='independent_timed_contest',
        source={'platform':'csp_exam','kind':'contest','task_id':'c12','selected_submission_id':'final'})
    contest['submissions']=[{'id':'final','code':contest['code'],'result':'AC'}]
    diagnoses=[{'problem_index':i,'observed_behaviors':['DFS与变量调整'],
        'parent_observations':['能抓住题目的几项要求，按要求得出结果。'],'changes':'把dfs的下标改成i+1'} for i in range(3)]
    scores={'abilities':[{'id':'A01','score':75,'source':'api','evidence':['current:p0','current:p1','current:p2'],'reason':'专业判断：DFS'}]}
    result=pipeline.parent_copy_data(data,scores,{'recent':[]},[],None,diagnoses)
    examples=result['能力依据'][0]['具体表现供理解不照抄']
    assert examples[0]['场景']=='比赛题' and examples[1]['场景']=='课堂练习'
    assert examples[0]['完成条件']=={'独立':True,'接受题解或讲解':False}
    serialized=json.dumps(result,ensure_ascii=False)
    assert all(term not in serialized for term in ['跳板迷宫','DFS','dfs','提交次数','代码版本的题目数','专业判断'])


def test_contest_completion_does_not_establish_new_problem_transfer():
    data=FeedbackInput(student_id='fixture',start_date='2026-10-01',end_date='2026-10-05',target_year=2026,tracks=['J'],topics='本期练习').model_dump(mode='json')
    report={'summary':'能把学过的方法用在新题目上。','highlights':['能独立完成比赛题。'],'next_steps':['继续练习。'],
        'positions':[{'track':'J','label':'基础训练阶段','basis':''}],'admissions_text':'','admissions_sources':[]}
    assert any('此前没做过' in w for w in validate_parent(report,data))
    assert not validate_parent({**report,'summary':'接下来可以多用新题检验学过的方法。'},data)
    data['subjective_observation']='本期是未做过的题，能独立完成。'
    assert not validate_parent(report,data)


def test_actual_deepseek_messages_use_the_approved_voice_without_analyst_examples(monkeypatch):
    sent=[]
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,**kwargs):
            sent.append(kwargs['json'])
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(APPROVED_A_EXAMPLE,ensure_ascii=False)}}]})
    monkeypatch.setattr(provider,'settings',lambda:{'api_key':'test-only','base_url':'https://api.deepseek.com','model':'deepseek-flash','max_calls':3,'timeout':1})
    monkeypatch.setattr(provider.httpx,'AsyncClient',Client)
    asyncio.run(provider.DeepSeek().generate(pipeline.PARENT_COMMON+pipeline.PARENT_INSTRUCTION,{'事实':'本次输入'},ParentCopy))
    system=sent[0]['messages'][0]['content']
    assert system.startswith(pipeline.STYLE_RULE)
    assert all(sentence in system for sentence in APPROVED_A_EXAMPLE['highlights'])
    assert '必须用输入材料的真实编号' not in system and '格式示例，请按实际材料填写' not in system
    assert '信息学竞赛教学分析员' not in system
    assert '本次输入' in sent[0]['messages'][1]['content']
    internal=provider.messages_for_schema(pipeline.COMMON,{},Diagnosis)[0]['content']
    assert '必须用输入材料的真实编号' in internal


def test_initial_generation_and_rewrite_retry_in_the_same_approved_voice(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATABASE',tmp_path/'feedback.sqlite3');db.init_db()
    student=db.save_student({'name':'测试同学','age':13,'grade':'初二','acgo_user_id':''})
    data=FeedbackInput(student_id=student['id'],start_date='2026-10-01',end_date='2026-10-05',target_year=2026,tracks=['J'],
        problems=[ProblemInput(title='练习题',code='int main(){}')]).model_dump(mode='json')
    entry=db.create_feedback(data)
    stages={'copy_prompt_version':pipeline.PROMPT_VERSION,
        'diagnosis:0':{'problem_index':0,'evidence':['current:p0'],'topic_ids':['K008'],'observed_behaviors':['按要求处理了题目。']},
        'analysis':{'topic_scores':[{'id':'K008','score':60,'evidence':['current:p0'],'reason':'本期成果','scope':''}],
            'abilities':[{'id':f'A{i:02d}','score':None,'evidence':[],'source':'api' if i<6 else 'teacher','reason':'材料不足'} for i in range(1,7)]},
        'training':{'horizon':'最近两周','recent':[{'title':'新题练习','activity':'选几道相近的新题。','success':'能说清自己的做法。','evidence':['current:p0'],'collection_id':'','practice_mode':'new'}],'phases':[]}}
    db.update_feedback(entry['id'],stages=stages)
    instructions=[]
    class FakeProvider:
        def __init__(self):self.calls=0;self.usage={};self.config={'model':'test','max_calls':20,'analysis_concurrency':2}
        async def generate(self,instruction,materials,schema):
            assert schema is ParentCopy
            self.calls+=1;instructions.append(instruction)
            copy={'summary':'本期完成了练习，能把自己的想法写成程序。','highlights':['能抓住题目的关键要求，并按要求得出结果。'],
                'next_steps':['未来两周选几道相近的新题，先说清准备怎么做，再独立完成。']}
            if self.calls==1:copy['summary']='本期核实到完成了一道综合任务。'
            return copy
    monkeypatch.setattr(pipeline,'DeepSeek',FakeProvider)
    monkeypatch.setattr(knowledge,'references',lambda tracks:[])
    asyncio.run(pipeline.generate(entry['id']))
    first=db.feedback(entry['id'])
    assert first['status']=='review',first['error']
    assert first['analysis']['versions']['parent_style']==STYLE_ID
    scores=deepcopy(first['draft']['topic_scores']);positions=deepcopy(first['draft']['positions'])
    asyncio.run(pipeline.rewrite_parent_copy(entry['id'],refresh_training=False))
    second=db.feedback(entry['id'])
    assert second['status']=='review' and second['error'] is None
    assert second['draft']['topic_scores']==scores and second['draft']['positions']==positions
    assert second['analysis']['copy_refreshes'][-1]['parent_style']==STYLE_ID
    assert len(instructions)==4
    assert instructions[0]==instructions[2]
    for instruction in instructions:
        assert instruction.startswith(pipeline.STYLE_RULE)
        assert '读题时能抓住关键要求' in instruction
        assert '逐项核对给定的编号' not in instruction
    assert '按A版的自然讲师口吻重新组织' in instructions[1] and instructions[1]==instructions[3]
