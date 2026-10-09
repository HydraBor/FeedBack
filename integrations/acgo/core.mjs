import JSONbigFactory from 'json-bigint';
import {resolveContestQuestionOrder} from './vendor/reliability.mjs';

export const parseJSON = JSONbigFactory({storeAsString:true, protoAction:'error', constructorAction:'error'}).parse;
export const exactId = value => {
  if (typeof value === 'number' && !Number.isSafeInteger(value)) throw new Error('平台返回的编号超出整数精度范围');
  const id = String(value ?? '');
  if (!/^\d+$/.test(id)) throw new Error('平台返回了无效编号');
  return id;
};
export function safeNumber(value) {
  const id=exactId(value), result=Number(id);
  if (!Number.isSafeInteger(result)) throw new Error('此接口要求数字编号，但编号超出安全精度范围');
  return result;
}
export function timestamp(value) {
  if (value === null || value === undefined || value === '') return null;
  let ms;
  if (/^\d+(?:\.\d+)?$/.test(String(value))) {
    const n=Number(value); ms=n<1e12?n*1000:n;
  } else {
    let text=String(value).trim().replace(/\//g,'-');
    // ACGO's timezone-less display strings are Beijing local time.
    if (/^\d{4}-\d{1,2}-\d{1,2}[ T]\d{1,2}:\d{2}/.test(text) && !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(text)) {
      const match=text.match(/^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2})(\.\d+)?)?$/);
      if (!match) return null;
      const [,y,m,d,h,minute,s='00',fraction='']=match;
      text=`${y}-${m.padStart(2,'0')}-${d.padStart(2,'0')}T${h.padStart(2,'0')}:${minute}:${s}${fraction}+08:00`;
    }
    // Date-only values cannot locate a code submission accurately.
    if (!/[T ]\d{1,2}:\d{2}/.test(text)) return null;
    ms=Date.parse(text);
  }
  return Number.isFinite(ms) && ms>=Date.UTC(2010,0,1) && ms<Date.UTC(2100,0,1)?ms:null;
}
export function periodRecords(records,config) {
  if (!Array.isArray(records)) throw new Error('提交列表格式发生变化，无法确认采集完整性');
  const start=Date.parse(config.start_date+'T00:00:00+08:00');
  const end=Date.parse(config.end_date+'T23:59:59.999+08:00');
  const seen=new Set(); let unknown=0,outside=0; const availableDates={};
  const kept=[];
  for (const record of records) {
    const id=exactId(record.id);
    if (seen.has(id)) continue;
    seen.add(id);
    const time=timestamp(record.createdAt);
    if (time===null) {unknown++;continue;}
    const day=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date(time));
    availableDates[day]=(availableDates[day]||0)+1;
    if(time<start||time>end){outside++;continue;}
    kept.push({...record,id,_time:time});
  }
  kept.sort((a,b)=>a._time-b._time||(BigInt(a.id)<BigInt(b.id)?-1:BigInt(a.id)>BigInt(b.id)?1:0));
  return {records:kept,unknown,outside,availableDates};
}
export function resultOf(detail,record) {
  if(detail.compileError)return 'CE（编译错误）';
  const flatten=items=>Array.isArray(items)?items.flatMap(flatten):[items];
  const results=[...new Set(flatten(detail.list||[]).map(x=>x?.result||x?.resultDesc).filter(Boolean))];
  if(results.includes('AC')&&results.some(r=>r!=='AC'))return `部分通过（测试点：${results.join('、')}）`;
  if(Number(detail.status??record.status)===1)return 'AC';
  if(results.length===1&&results[0]==='AC')return '测试点显示 AC（整体提交状态未核实）';
  return results.join('、')||'未通过 / 状态未明';
}
export function isSectionMarker(problem) {
  return /[-—]{3,}.*(?:必做题|选做题|分界|分隔).*[-—]{3,}/.test(problem.title)
    && /(?:我是|本题.{0,8}(?:是|为)).{0,8}(?:分界线|分隔线)/.test(problem.markdown);
}
export function submissionOf(record,detail,config) {
  for(const value of [record.userId,detail.userId]) {
    // The homework endpoint currently emits userId=0 as a placeholder. It is
    // not an identity assertion; attribution comes from the target-scoped
    // request plus its record ID matched against this student's task row.
    if(value!==undefined&&value!==null&&String(value)!=='0'&&exactId(value)!==config.user_id) throw new Error('提交详情的学生 ID 不匹配，已阻止导入');
  }
  if(detail.id!=null&&exactId(detail.id)!==record.id)throw new Error('提交详情编号不匹配，已阻止导入');
  const raw=Array.isArray(detail.answer)?detail.answer[0]:detail.answer;
  if(typeof raw!=='string'||!raw.trim())throw new Error('提交详情未返回代码，请确认账号具有查看学生代码的权限');
  if(raw.length>100000)throw new Error('提交代码超过 100KB，请手动筛选材料');
  const languageValue=detail.language??record.language;
  const language=Number(languageValue)===2?'cpp':Number(languageValue)===4?'python':'text';
  const number=value=>value!==''&&value!=null&&Number.isFinite(Number(value))?Number(value):null;
  // Only the timestamp actually used to filter the list may become current evidence.
  return {id:record.id,submitted_at:new Date(record._time).toISOString(),result:resultOf(detail,record),language,
    code:raw.replace(/\r\n/g,'\n'),score:number(detail.score??record.score),
    cpu_ms:number(detail.maxCpuTime),memory_bytes:number(detail.maxUsedMemory)};
}
export function materialOf(problem,submissions,config,question,counts) {
  if(!submissions.length) {
    const state=counts.unknown?'unverified_time':counts.outside?'no_submission_in_period':'no_submission';
    const labels={no_submission:'本任务无提交记录（原因待确认）',no_submission_in_period:'本期无提交记录（其他日期有提交）',unverified_time:'提交时间无法核实，未作为本期作品'};
    return {title:problem.title,problem_id:`acgo:${problem.questionId}`,statement:problem.markdown,code:'',language:'cpp',
      independent:null,editorial_seen:null,minutes:null,completion_context:config.kind==='homework'?'practice_then_explanation':'unspecified',
      submission_state:state,non_submission_reason:'unknown',judge_result:labels[state],observation:'',submissions:[],
      source:{platform:'acgo',kind:config.kind,task_id:config.task_id,team_id:config.team_id,user_id:config.user_id,
        question_id:problem.questionId,contest_question_id:config.kind==='contest'?question.questionId:'',task_url:config.task_url,
        problem_url:problem.url,fetched_at:new Date().toISOString(),selected_submission_id:'',period_start:config.start_date,
        period_end:config.end_date,tags:(problem.knowledgeList||[]).map(t=>typeof t==='string'?t:t.tagTitle||t.name||t.title||'').filter(Boolean),
        warnings:['没有本期代码作品，仅用于分析任务覆盖和安排补练，不能据此证明不会做或能力不足'],history_count:0}};
  }
  const latest=submissions.at(-1);
  const accepted=submissions.findLast(x=>x.result==='AC');
  const selected=config.submission_mode==='accepted_history'?(accepted||latest):latest;
  const warnings=[];
  if(counts.unknown)warnings.push(`${counts.unknown} 次提交缺少可靠时间，未计入本期`);
  if(config.submission_mode==='accepted_history'&&selected.id!==latest.id)warnings.push('主代码采用本期通过版本，最新一次提交仍在过程记录中');
  const withGaps=submissions.map((s,i)=>({...s,gap_seconds:i?Math.max(0,(Date.parse(s.submitted_at)-Date.parse(submissions[i-1].submitted_at))/1000):null}));
  const history=config.submission_mode==='latest_only'?withGaps.slice(-1):withGaps;
  const independentContest=config.kind==='contest'&&config.contest_independent===true;
  const tags=(problem.knowledgeList||[]).map(t=>typeof t==='string'?t:t.tagTitle||t.name||t.title||'').filter(Boolean);
  const submittedLocal=new Date(selected.submitted_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
  return {title:problem.title,problem_id:`acgo:${problem.questionId}`,statement:problem.markdown,code:selected.code,
    language:selected.language,independent:independentContest?true:null,editorial_seen:independentContest?false:null,minutes:null,
    completion_context:independentContest?'independent_timed_contest':config.kind==='homework'?'practice_then_explanation':'unspecified',
    pre_explanation_submissions:null,explanation_started_at:null,
    judge_result:`ACGO ${selected.result}${selected.score===null?'':`；本次提交得分 ${selected.score}`}（提交 ${selected.id}，${submittedLocal} 北京时间）`,
    submission_state:'submitted',non_submission_reason:'unknown',observation:'',submissions:history,source:{platform:'acgo',kind:config.kind,task_id:config.task_id,team_id:config.team_id,
      user_id:config.user_id,question_id:problem.questionId,contest_question_id:config.kind==='contest'?question.questionId:'',
      task_url:config.task_url,problem_url:problem.url,fetched_at:new Date().toISOString(),selected_submission_id:selected.id,
      period_start:config.start_date,period_end:config.end_date,tags,warnings,history_count:submissions.length}};
}
export async function findStudent({loadPage,records,total,userId,idOf,maxPages=50}) {
  const seen=new Set();let count=0;
  for(let page=1;page<=maxPages;page++) {
    const data=await loadPage(page),rows=records(data);
    if(!Array.isArray(rows))throw new Error('学生完成记录格式发生变化');
    const matches=rows.filter(row=>String(idOf(row)??'')===userId);
    if(matches.length>1)throw new Error('学生完成记录重复，无法确认来源');
    if(matches[0])return {student:matches[0],pageData:data};
    if(!rows.length)break;
    let fresh=0;
    for(const row of rows){const id=String(idOf(row)??'');if(!seen.has(id)){seen.add(id);fresh++;}}
    if(!fresh)throw new Error('分页未产生新学生记录，无法确认目标学生');
    count+=fresh;
    if(Number(total(data))>0&&count>=Number(total(data)))break;
  }
  throw new Error('未在此作业或比赛中找到指定 ACGO 学生 ID，请检查团队、任务和访问权限');
}
export function contestOrder(questions,pageQuestions,links,student) {
  const rawProblems=links.map(q=>({questionId:q.publicId,url:`https://www.acgo.cn/problemset/info/${q.publicId}`}));
  return resolveContestQuestionOrder({apiQuestions:questions,pageQuestions,rawProblems,rankingRecords:[student]});
}
