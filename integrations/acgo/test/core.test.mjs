import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseJSON,exactId,safeNumber,timestamp,periodRecords,submissionOf,materialOf,findStudent,contestOrder,isSectionMarker,resultOf} from '../core.mjs';

const config={user_id:'5085016',team_id:'2042058713337094144',kind:'homework',task_id:'24031',task_url:'https://www.acgo.cn/homework/24031',start_date:'2026-08-14',end_date:'2026-08-14',submission_mode:'latest_history'};
test('keep task statements without inventing submitted work or mixing outside-period records',()=>{
  const problem={questionId:'33',title:'题目',markdown:'完整题面',url:'https://www.acgo.cn/problemset/info/33'};
  for(const [counts,state] of [[{unknown:0,outside:0},'no_submission'],[{unknown:0,outside:2},'no_submission_in_period'],[{unknown:1,outside:0},'unverified_time']]){
    const m=materialOf(problem,[],config,{questionId:'33'},counts);
    assert.equal(m.submission_state,state);
    assert.equal(m.code,'');assert.deepEqual(m.submissions,[]);
    assert.equal(m.source.history_count,0);assert.equal(m.source.selected_submission_id,'');
    assert.equal(m.independent,null);assert.equal(m.minutes,null);
  }
});
test('snowflake IDs survive JSON parsing and numeric endpoints reject unsafe conversions',()=>{
  assert.equal(parseJSON('{"teamCode":2042058713337094144}').teamCode,config.team_id);
  assert.throws(()=>safeNumber(config.team_id),/精度/);
  assert.throws(()=>exactId(Number(config.team_id)),/精度/);
});
test('homework grouping markers are excluded only when title and statement both identify a divider',()=>{
  assert.equal(isSectionMarker({title:'U139051.-----上午必做题-----',markdown:'### 题目描述\n我是分界线嘻嘻'}),true);
  assert.equal(isSectionMarker({title:'-----上午必做题-----',markdown:'求最短路径'}),false);
  assert.equal(isSectionMarker({title:'破墙寻径',markdown:'我是分界线'}),false);
});
test('mixed accepted/failed test points remain partial rather than whole-submission AC',()=>{
  assert.match(resultOf({status:2,list:[[{result:'AC'},{result:'WA'}]]},{}),/^部分通过/);
  assert.equal(resultOf({status:1,list:[[{result:'AC'}]]},{}),'AC');
  assert.match(resultOf({status:2,list:[[{result:'AC'}]]},{}),/未核实/);
});
test('Beijing date filtering includes midnight boundaries, excludes earlier/later/unknown records',()=>{
  const list=[{id:'1',createdAt:'2026-08-13 23:59:59'},{id:'2',createdAt:'2026-08-14 00:00:00'},
    {id:'3',createdAt:'2026-08-14 23:59:59'},{id:'4',createdAt:'2026-08-15 00:00:00'},{id:'5',createdAt:''}];
  const out=periodRecords(list,config);
  assert.deepEqual(out.records.map(x=>x.id),['2','3']);assert.equal(out.outside,2);assert.equal(out.unknown,1);
  assert.equal(timestamp('2026-08-14 00:00:00'),Date.parse('2026-08-13T16:00:00Z'));
  assert.equal(timestamp(String(Date.parse('2026-08-14T00:00:00+08:00')/1000)),timestamp('2026-08-14 00:00:00'));
  assert.equal(timestamp('2026-08-14'),null);
});
test('latest WA remains main work after earlier AC; OJ CPU time never becomes student solving time',()=>{
  const list=periodRecords([{id:'1',createdAt:'2026-08-14 10:00:00',status:1},{id:'2',createdAt:'2026-08-14 11:00:00',status:2}],config);
  const submissions=list.records.map((r,i)=>submissionOf(r,{answer:[`code${i}`],language:2,status:i?2:1,list:i?[{result:'WA'}]:[],maxCpuTime:8},config));
  const material=materialOf({questionId:'33',title:'题目',markdown:'完整题面',url:'https://www.acgo.cn/problemset/info/33',knowledgeList:[]},submissions,config,{questionId:'33'},list);
  assert.equal(material.code,'code1');assert.match(material.judge_result,/WA/);assert.equal(material.minutes,null);
  assert.equal(material.independent,null);assert.equal(material.editorial_seen,null);assert.equal(material.submissions[0].cpu_ms,8);
  assert.equal(material.source.history_count,2);
});
test('missing code and cross-student submission details are rejected',()=>{
  const record={id:'1',_time:Date.parse('2026-08-14T00:00:00+08:00')};
  assert.throws(()=>submissionOf(record,{answer:[''],userId:config.user_id},config),/未返回代码/);
  assert.throws(()=>submissionOf(record,{answer:['code'],userId:'123'},config),/学生 ID 不匹配/);
  assert.equal(submissionOf({...record,userId:0},{answer:['code'],language:2},config).code,'code');
});
test('find by student ID across pages without confusing same-name students',async()=>{
  const calls=[];
  const found=await findStudent({userId:config.user_id,idOf:r=>r.userInfo.userId,records:d=>d.records,total:d=>d.total,
    loadPage:async page=>{calls.push(page);return {records:[{userInfo:{userId:page===1?'123':config.user_id,nickName:'同名'}}],total:20}}});
  assert.equal(found.student.userInfo.userId,config.user_id);assert.deepEqual(calls,[1,2]);
});
test('contest internal IDs map to public problem IDs; reordered pages fail',()=>{
  const questions=[{questionId:'900',acgoQuestionId:'100'},{questionId:'901',acgoQuestionId:'101'}];
  const student={rank:[{questionId:'900'},{questionId:'901'}]};
  const order=contestOrder(questions,questions,[{publicId:'100'},{publicId:'101'}],student);
  assert.deepEqual(order.map(q=>[q.questionId,q.acgoQuestionId]),[['900','100'],['901','101']]);
  assert.throws(()=>contestOrder(questions,questions.toReversed(),[{publicId:'100'},{publicId:'101'}],student),/不一致/);
});
test('retain every early code version in the archive, including pre-AC failures',()=>{
  const submissions=Array.from({length:15},(_,i)=>({id:String(i+1),code:`v${i}`,result:'AC',language:'cpp',submitted_at:'2026-08-14T00:00:00Z',score:100}));
  const material=materialOf({questionId:'33',title:'题目',markdown:'题面',url:'https://www.acgo.cn/problemset/info/33'},submissions,config,{questionId:'33'},{unknown:0});
  assert.equal(material.submissions.length,15);assert.equal(material.code,'v14');
  assert.equal(material.submissions[0].code,'v0');assert.equal(material.submissions.at(-1).code,'v14');
});
test('teacher-confirmed contest conditions carry stronger evidence and gaps stay separate from solving time',()=>{
  const records=periodRecords([{id:'1',createdAt:'2026-08-14 10:00:00',status:2},{id:'2',createdAt:'2026-08-14 10:10:00',status:1}],config);
  const attempts=records.records.map(r=>submissionOf(r,{answer:['code'],language:2,status:r.status},config));
  const contest={...config,kind:'contest',contest_independent:true};
  const material=materialOf({questionId:'33',title:'题目',markdown:'题面',url:'https://www.acgo.cn/problemset/info/33'},attempts,contest,{questionId:'333'},records);
  assert.equal(material.independent,true);assert.equal(material.editorial_seen,false);
  assert.equal(material.completion_context,'independent_timed_contest');
  assert.equal(material.submissions[1].gap_seconds,600);assert.equal(material.minutes,null);
  const unknown=materialOf({questionId:'33',title:'题目',markdown:'题面',url:'https://www.acgo.cn/problemset/info/33'},attempts,{...contest,contest_independent:false},{questionId:'333'},records);
  assert.equal(unknown.independent,null);assert.equal(unknown.completion_context,'unspecified');
});
