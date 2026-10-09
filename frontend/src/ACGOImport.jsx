import React, {useState,useEffect} from 'react';
import QuestionCard,{SelectionActions} from './QuestionCard.jsx';
import {ZhouOJConnection} from './PracticeArchive.jsx';
import {importRequirements,studyPeriodText} from './importRequirements.js';

export default function ACGOImport({api,student,startDate,endDate,onApply,onCompletePeriod,platform='acgo'}) {
  const isZhou=platform==='zhou-oj',base=isZhou?'/zhou-oj':'/acgo',label=isZhou?'周老师 OJ':'ACGO';
  const [config,setConfig]=useState({user_id:student?.profile.acgo_user_id||'',team:'',kind:'homework',task:'',submission_mode:'latest_history',contest_independent:true,exam_number:''});
  const [job,setJob]=useState(null),[selected,setSelected]=useState([]),[error,setError]=useState(''),[connection,setConnection]=useState(null),[starting,setStarting]=useState(false);
  useEffect(()=>{setConfig(c=>({...c,user_id:student?.profile.acgo_user_id||''}));setJob(null);setSelected([]);setError('')},[student?.id]);
  useEffect(()=>{
    if(!job?.id||job.status!=='running')return;
    let cancelled=false;
    const timer=setInterval(()=>api(base+'/imports/'+job.id).then(j=>{
      if(cancelled)return;
      setJob(j);
      if(j.status==='completed')setSelected(j.result.problems.map((_,i)=>i));
    }).catch(e=>{if(!cancelled){setError(e.message);setJob(j=>({...j,status:'failed'}))}}),1200);
    return()=>{cancelled=true;clearInterval(timer)};
  },[job?.id,job?.status]);
  const field=(key,value)=>{setConfig(c=>({...c,[key]:value}));setJob(null);setSelected([]);setError('')};
  const taskField=value=>{
    field('task',value);
    try{const url=new URL(value.split(',')[0].trim());const team=url.searchParams.get('teamCode');if(url.protocol==='https:'&&url.hostname==='www.acgo.cn'&&team)setConfig(c=>({...c,team:c.team||team}))}catch{}
  };
  async function start(){
    const missing=importRequirements({student,startDate,endDate,config,platform});
    if(missing.length){setError('请先填写：'+missing.join('、')+'。');return}
    setStarting(true);setError('');setJob(null);setSelected([]);
    try{
      const {exam_number,...acgoConfig}=config;
      const input=isZhou?{contests:config.task,exam_number,contest_independent:config.contest_independent}: {...acgoConfig,user_id:config.user_id.trim()};
      setJob(await api(base+'/imports','POST',{...input,student_id:student.id,start_date:startDate,end_date:endDate}));
    }
    catch(e){setError(e.message)}finally{setStarting(false)}
  }
  async function apply(){
    setError('');
    try{
      if(job.student_id!==student?.id||job.input.start_date!==startDate||job.input.end_date!==endDate)throw Error('学生或学习时间段已修改，请按当前表单重新采集');
      const count=onApply(selected.map(i=>job.result.problems[i]),job);
      setSelected([]);setError(`已填写 ${count} 道题；重复作品已跳过。可以补充完成条件后生成反馈。`);
    }catch(e){setError(e.message)}
  }
  const running=starting||job?.status==='running';
  const missing=importRequirements({student,startDate,endDate,config,platform});
  const periodIncomplete=!startDate||!endDate||endDate<startDate;
  const result=job?.result;
  return <div className="acgo-import soft-card">
    <div className="panel-head"><h3>从 {label} 导入学生作品</h3>{!isZhou&&<button type="button" disabled={running} onClick={()=>api('/acgo/status').then(setConnection).catch(e=>setError(e.message))}>检查连接</button>}</div>
    <p className="hint">{isZhou?'填写比赛号或链接，只读取这些比赛的题面、指定学生的最终代码和已有成绩。':'在专用 Edge 登录 ACGO 后，读取指定学生的作业或比赛。'}多个编号用英文逗号 , 分隔。先填写上方学习起止日期，再按该时段筛选提交；未提交题目也保留题面供确认和补练。</p>
    {connection&&<div className={'notice '+(connection.connected?'':'amber')}>{connection.message}</div>}
    {isZhou?<ZhouOJConnection api={api} running={running}/>:<details><summary>首次连接 / 登录方法</summary><p>在项目目录的 PowerShell 运行下方脚本，在新开的 Edge 窗口登录 ACGO，并保持窗口打开。</p><code>powershell -ExecutionPolicy Bypass -File .\scripts\start-acgo-edge.ps1</code><p className="hint">使用专用浏览器目录与本机端口 9223。无需复制密码或 Cookie。</p></details>}
    {isZhou?<div className="grid two"><label className="field"><span>周老师 OJ 比赛号或链接</span><input aria-label="周老师 OJ 比赛号或链接" disabled={running} value={config.task} onChange={e=>field('task',e.target.value)} placeholder="c12,c8,c13"/><small>当前学生：{student?.name||'请先选择学生'}；按姓名逐场匹配。</small></label><label className="field"><span>周老师 OJ 考号（可选）</span><input disabled={running} value={config.exam_number} onChange={e=>field('exam_number',e.target.value)} placeholder="同名时填本场考号并单独采集"/></label></div>:<div className="grid two">
      <label className="field"><span>学生 ACGO ID</span><input disabled={running} value={config.user_id} onChange={e=>field('user_id',e.target.value)} inputMode="numeric" placeholder="填写学生账号的数字 ID"/><small>当前档案：{student?.name||'请先选择学生'}；按账号 ID 匹配。</small></label>
      <label className="field"><span>团队 ID 或链接</span><input disabled={running} value={config.team} onChange={e=>field('team',e.target.value)} placeholder="团队编号或含 teamCode 的链接"/></label>
      <label className="field"><span>任务类型</span><select disabled={running} value={config.kind} onChange={e=>{field('kind',e.target.value);field('task','')}}><option value="homework">团队作业</option><option value="contest">团队比赛</option></select></label>
      <label className="field"><span>{config.kind==='homework'?'作业 ID 或链接':'比赛 ID 或完整链接'}</span><input disabled={running} value={config.task} onChange={e=>taskField(e.target.value)} placeholder={config.kind==='homework'?'例如 24031,24156':'例如 22884,22900 或完整链接'}/></label>
    </div>}
    {(isZhou||config.kind==='contest')&&<label className="checkbox"><input type="checkbox" disabled={running} checked={config.contest_independent} onChange={e=>field('contest_independent',e.target.checked)}/>讲师确认：所填比赛为限时独立完成，比赛期间未接受题解或讲解</label>}
    {isZhou&&<p className="hint">OI/CSP 赛制以最终提交为主要成果；只有一份代码不会被当作缺少尝试或修改。特殊情况可取消确认，或在题目卡片中修改。</p>}
    <div className="inline"><button type="button" className="primary" disabled={running||missing.length>0} title={running?'正在采集，请等待完成':missing.length?'请先填写：'+missing.join('、'):'按所选学生和学习时段读取作品'} onClick={start}>{running?'正在采集…':'读取学生作品'}</button>{job?.status==='running'&&<button type="button" onClick={()=>api(base+'/imports/'+job.id,'DELETE',{}).then(()=>setJob(null)).catch(e=>setError(e.message))}>取消导入</button>}<small>学习时段：{studyPeriodText(startDate,endDate)} · {isZhou?'最终代码＋已有成绩':'最新代码＋提交过程'}</small></div>
    {!running&&missing.length>0&&<div className="notice amber" role="status">请先填写：{missing.join('、')}。{periodIncomplete&&onCompletePeriod&&<button type="button" className="text" onClick={onCompletePeriod}>填写学习时段 ↑</button>}</div>}
    {job&&<div className="progress"><div className={job.status==='running'?'spinner':''}/><strong>{job.progress}</strong></div>}
    {(error||job?.error)&&<div className="notice amber" role="status">{error||job.error}</div>}
    {result&&<div className="acgo-preview">
      <p><b>平台学生：{result.student.display_name||'未提供昵称'} · {isZhou?'首场考号':'ID'} {result.student.user_id}</b><br/><small>{label} {result.kind==='homework'?'作业':'比赛'} {result.task_id} · 采集 {result.tasks?.length||1} 份任务，{result.problems.length} 道题。请核对与当前档案对应关系。</small></p>
      {result.warnings.map((w,i)=><p className="hint" key={i}>{w}</p>)}
      {!!Object.keys(result.available_dates||{}).length&&<details open={!result.problems.length}><summary>任务中的实际提交日期</summary><p>{Object.entries(result.available_dates).sort().map(([day,count])=>`${day}（${count} 次）`).join('；')}</p></details>}
      {(result.failed_tasks||[]).map((f,i)=><div className="notice amber" key={i}>任务 {f.task_id}：{f.message}</div>)}
      {result.failed_questions.map(p=><div className="notice amber" key={p.question_id}>题目 {p.question_id}：{p.message}</div>)}
      {!result.problems.length&&<p>当前时间段内没有可导入的代码。请核对上方实际提交日期或任务信息后重试。</p>}
      {result.problems.length>0&&<><SelectionActions total={result.problems.length} selected={selected} onChange={setSelected}/>
      {result.problems.map((p,i)=><QuestionCard key={i} title={<><input aria-label={`选择 ${p.title}`} type="checkbox" checked={selected.includes(i)} onChange={e=>setSelected(e.target.checked?[...selected,i]:selected.filter(n=>n!==i))}/><b>{p.title}</b></>} meta={`${p.submissions.length} 次提交`}>
        
        <small>{p.judge_result} · 本期提交 {p.source.history_count} 次</small>
        <details><summary>查看题面与主作品</summary><p className="hint">{p.source.assessment_tags?.join(' · ')}{p.source.contest_duration_minutes?` · 整场限时 ${p.source.contest_duration_minutes} 分钟`:''}</p><pre>{p.statement}</pre><pre className="code">{p.code}</pre><a href={p.source.problem_url} target="_blank" rel="noreferrer">{label} 原题 ↗</a></details>
        <details><summary>额外代码快照 · 时间未核实（{p.unverified_submissions?.length||0} 份）</summary>{(p.unverified_submissions||[]).map(v=><details key={v.id}><summary>{v.note||'逐次时间与评测未核实，不计入本期能力证据'}</summary><pre className="code">{v.code}</pre></details>)}</details><details><summary>提交过程与来源</summary>{p.submissions.map(s=><div key={s.id}><small>{new Date(s.submitted_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})} 北京时间 · 提交 {s.id} · {s.result} · {s.gap_seconds==null?'本期首次提交':`与上次同题提交相隔 ${(s.gap_seconds/60).toFixed(1)} 分钟`}</small><details><summary>{s.code?'查看该版代码':'较早版本：仅保留时间与结果'}</summary><pre className="code">{s.code}</pre></details></div>)}{p.source.warnings.map((w,i)=><p className="hint" key={i}>{w}</p>)}</details>
      </QuestionCard>)}
      <button type="button" className="primary" disabled={!selected.length} onClick={apply}>将所选 {selected.length} 道题填写到表单</button></>}
    </div>}
  </div>;
}
