import React,{useState,useEffect} from 'react';
import QuestionCard,{SelectionActions,taskLabel} from './QuestionCard.jsx';

const Input=({label,children,hint})=><label className="field"><span>{label}</span>{React.Children.map(children,c=>React.isValidElement(c)?React.cloneElement(c,{'aria-label':label}):c)}{hint&&<small>{hint}</small>}</label>;
const dateTime=value=>new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});

export function ArchiveImport({api,student,students,onSaved}) {
  const [data,setData]=useState({student_id:student?.id||'',csp_contests:[],csp_exam_number:'',concurrency:3,name:student?.name||'',user_id:student?.profile.acgo_user_id||'',team:'',homework:'',contest:'',start_date:'',end_date:'',age:'',grade:'',contest_independent:true});
  const [job,setJob]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const put=(key,value)=>setData(d=>({...d,[key]:value}));
  useEffect(()=>{
    if(job?.status!=='running')return;
    let closed=false;
    const timer=setInterval(()=>api('/practice-archives/imports/'+job.id).then(j=>{if(!closed){setJob(j);if(j.status==='completed')onSaved(j.result)}}).catch(e=>{if(!closed){setError(e.message);setJob(j=>({...j,status:'failed'}))}}),1200);
    return()=>{closed=true;clearInterval(timer)};
  },[job?.id,job?.status]);
  function taskField(key,value){
    put(key,value);
    try{const u=new URL(value.split(',')[0].trim()),team=u.searchParams.get('teamCode');if(u.hostname==='www.acgo.cn'&&u.protocol==='https:'&&team)setData(d=>({...d,team:d.team||team}))}catch{}
  }
  async function start(event){
    event.preventDefault();setBusy(true);setError('');setJob(null);
    try{setJob(await api('/practice-archives/imports','POST',{...data,name:data.name.trim(),user_id:data.user_id.trim(),start_date:data.start_date||null,end_date:data.end_date||null,age:data.age?Number(data.age):null}))}
    catch(e){setError(e.message)}finally{setBusy(false)}
  }
  const running=busy||job?.status==='running';
  return <><div className="page-title"><div><div className="eyebrow">STUDENT WORK ARCHIVE</div><h1>一次导入，生成做题档案</h1><p>作业与比赛一起采集，完整保存代码版本，再从档案生成反馈。</p></div></div>
  <form onSubmit={start} className="panel"><div className="grid two">
    <Input label="选用已有学生档案（可选）"><select disabled={running} defaultValue={student?.id||''} onChange={e=>{const s=students.find(s=>s.id===e.target.value);setData(d=>({...d,student_id:s?.id||'',name:s?.name||'',user_id:s?.profile.acgo_user_id||''}))}}><option value="">输入姓名和 ACGO ID，新建或匹配档案</option>{students.map(s=><option key={s.id} value={s.id}>{s.name} · {s.id.slice(0,8)}</option>)}</select></Input>
    <Input label="学生姓名"><input required disabled={running} value={data.name} onChange={e=>put('name',e.target.value)}/></Input>
    <Input label="学生 ACGO ID" hint="以账号 ID 匹配已有档案，同名学生不自动合并。"><input required={Boolean(data.homework||data.contest)} disabled={running} inputMode="numeric" value={data.user_id} onChange={e=>put('user_id',e.target.value)}/></Input>
    <Input label="团队 ID 或链接"><input required={Boolean(data.homework||data.contest)} disabled={running} value={data.team} onChange={e=>put('team',e.target.value)}/></Input>
    <Input label="作业 ID 或链接（可选）"><input disabled={running} value={data.homework} onChange={e=>taskField('homework',e.target.value)} placeholder="例如 24031,24156"/></Input>
    <Input label="比赛 ID 或完整链接（可选）"><input disabled={running} value={data.contest} onChange={e=>taskField('contest',e.target.value)} placeholder="例如 22884,22900，也可填写完整链接"/></Input>
    <Input label="档案开始日期（可选）"><input disabled={running} type="date" value={data.start_date} onChange={e=>put('start_date',e.target.value)}/></Input>
    <Input label="档案结束日期（可选）"><input disabled={running} type="date" value={data.end_date} onChange={e=>put('end_date',e.target.value)}/></Input>
    <Input label="同时采集的任务数" hint="每份作业或比赛使用独立进程；根据网络情况设置 1-8，默认 3。"><input disabled={running} type="number" min="1" max="8" value={data.concurrency} onChange={e=>put('concurrency',Number(e.target.value)||1)}/></Input>
  </div><CSPTasks api={api} selected={data.csp_contests} onChange={v=>put('csp_contests',v)} running={running}/><Input label="周老师 OJ 考号（可选）" hint="默认按学生姓名逐场匹配；同名考生可填写本场考号后单独采集。"><input disabled={running} value={data.csp_exam_number} onChange={e=>put('csp_exam_number',e.target.value)}/></Input><p className="hint">日期同时留空：按任务中实际提交日期整理；填写范围：只采集范围内作品。多份作业或比赛用英文逗号 , 分隔；重复编号自动去重。ACGO 任务或周老师 OJ 比赛至少选择一个。比赛只有编号且无法解析时，会提示填写完整链接。</p>
  <details><summary>年龄与年级（仅用于后续评估，可稍后补充）</summary><div className="grid two"><Input label="当前年龄（可选）"><input disabled={running} type="number" min="5" max="25" value={data.age} onChange={e=>put('age',e.target.value)}/></Input><Input label="当前年级（可选）"><input disabled={running} value={data.grade} onChange={e=>put('grade',e.target.value)}/></Input></div></details>
  <label className="checkbox"><input disabled={running} type="checkbox" checked={data.contest_independent} onChange={e=>put('contest_independent',e.target.checked)}/>讲师确认：比赛为限时独立完成，比赛期间未接受题解或讲解</label>
  <div className="notice">作业按先尝试后讲解分析；早期非 AC 代码完整保存。相邻提交间隔只作弱参考，不填写为实际解题耗时。</div>
  <details><summary>ACGO 登录连接</summary><p>在项目目录的 Windows PowerShell 运行脚本，在专用 Edge 登录后保持窗口打开：</p><code>powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-acgo-edge.ps1</code></details>
  <div className="inline"><button className="primary" disabled={running}>{running?'正在采集并整理…':'采集并自动保存做题档案'}</button>{job?.status==='running'&&<button type="button" onClick={()=>api('/practice-archives/imports/'+job.id,'DELETE',{}).then(()=>setJob(null)).catch(e=>setError(e.message))}>取消</button>}</div>
  {job&&<div className="progress"><div className={job.status==='running'?'spinner':''}/><b>{job.progress}</b></div>}
  {(error||job?.error)&&<div className="notice amber" role="status">{error||job.error}</div>}
  </form></>;
}

export function PracticeArchive({api,id,onBack,onFeedback}) {
  const [entry,setEntry]=useState(null),[selected,setSelected]=useState([]),[error,setError]=useState('');
  useEffect(()=>{setEntry(null);api('/practice-archives/'+id).then(a=>{setEntry(a);setSelected(a.content.problems.map((_,i)=>i))}).catch(e=>setError(e.message))},[id]);
  if(error)return <div className="notice amber">{error}</div>;
  if(!entry)return <div className="empty">正在读取做题档案…</div>;
  const data=entry.content;
  return <><div className="page-title"><div><div className="eyebrow">PERSISTED STUDY RECORD</div><h1>{entry.name}的做题档案</h1><p>{entry.start_date} — {entry.end_date} · {data.problems.length} 道题（{data.problems.filter(p=>(p.submission_state||'submitted')!=='submitted').length} 道本期无提交） · {data.problems.reduce((n,p)=>n+p.submissions.length,0)} 次提交</p></div><button onClick={onBack}>返回学生档案</button></div>
  <section className="panel"><div className="panel-head"><h2>已保存的作品与提交过程</h2><button className="primary" disabled={!selected.length} onClick={()=>onFeedback(entry,selected.map(i=>data.problems[i]))}>用所选 {selected.length} 道题生成本期反馈</button></div><p className="hint">同一学生、同一学习时段已有报告时更新原报告。全部题面与可取得的代码版本保存在档案中，题目和提交次数不设数量上限。点击题目展开详情；独立完成条件可在反馈表单里调整。</p>
  <SelectionActions total={data.problems.length} selected={selected} onChange={setSelected}/>
  {[...new Set(data.warnings)].map((w,i)=><p className="hint" key={i}>{w}</p>)}
  {(data.failed_tasks||[]).map((f,i)=><div className="notice amber" key={i}>{f.kind==='homework'?'作业':'比赛'} {f.task_id} 读取失败：{f.message}；其余成功任务已保存。</div>)}
  {data.failed_questions.map((f,i)=><div className="notice amber" key={i}>题目 {f.question_id} 读取失败：{f.message}；已保存成功部分，请补充或重新采集。</div>)}
  {data.problems.map((p,i)=><QuestionCard key={i} title={<><input aria-label={`选择 ${p.title}`} type="checkbox" checked={selected.includes(i)} onChange={e=>setSelected(e.target.checked?[...selected,i]:selected.filter(n=>n!==i))}/><b>{p.title}</b></>} meta={`${taskLabel(p.source)} · ${p.submissions.length} 次提交`}><p className="hint">{taskLabel(p.source)} · {p.submissions.length} 次提交 · {p.completion_context==='independent_timed_contest'?'讲师确认的限时独立比赛':p.source.kind==='homework'?'作业尝试与学习过程':'比赛完成条件待核对'}</p><p>{p.judge_result}</p>{p.submission_state&&p.submission_state!=='submitted'&&<p className="hint">已保留题面供分析覆盖范围。未提交原因待确认，不自动视为不会做；可在反馈表单补充。</p>}<details><summary>题面与最新代码</summary><pre>{p.statement}</pre><pre className="code">{p.code}</pre></details><details><summary>额外代码快照 · 时间未核实（{p.unverified_submissions?.length||0} 份）</summary>{(p.unverified_submissions||[]).map(v=><details key={v.id}><summary>{v.note||'逐次时间与评测未核实，不计入本期能力证据'}</summary><pre className="code">{v.code}</pre></details>)}</details><details><summary>所有代码版本与相邻提交间隔</summary>{p.submissions.map(s=><details key={s.id}><summary>{dateTime(s.submitted_at)} · {s.result} · {s.gap_seconds==null?'本期首次提交':`距上次同题提交 ${(s.gap_seconds/60).toFixed(1)} 分钟`}</summary><pre className="code">{s.code}</pre></details>)}</details></QuestionCard>)}
  </section></>;
}


export function ZhouOJConnection({api,running=false}){
  const [connection,setConnection]=useState(null),[adminURL,setAdminURL]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  useEffect(()=>{api('/zhou-oj/connection').then(setConnection).catch(e=>setError(e.message))},[]);
  async function connect(){setBusy(true);setError('');try{setConnection(await api('/zhou-oj/connection','PUT',{admin_url:adminURL}));setAdminURL('')}catch(e){setError(e.message)}finally{setBusy(false)}}
  return <><p className="hint">{connection?.configured?`管理员连接已配置：${connection.base_url}。只读取填写的比赛，不抓取比赛目录；无需开启 Edge。`:'首次保存管理员链接，之后只需填写比赛号或链接。'}</p>
    <details open={connection?.configured===false}><summary>{connection?.configured?'更新周老师 OJ 管理员连接':'配置周老师 OJ 管理员连接'}</summary><Input label="周老师 OJ 管理员链接" hint="密钥只保存在本机连接配置，题目来源和报告链接中不包含密钥。"><input type="password" autoComplete="off" disabled={running||busy} value={adminURL} onChange={e=>setAdminURL(e.target.value)} placeholder="粘贴含 key 的管理员链接"/></Input><button type="button" disabled={running||busy||!adminURL} onClick={connect}>保存管理员连接</button></details>{error&&<div className="notice amber">{error}</div>}</>;
}
function CSPTasks({api,selected,onChange,running}){
  return <div className="csp-connection"><h3>周老师 OJ 比赛（可选）</h3><ZhouOJConnection api={api} running={running}/>
    <Input label="周老师 OJ 比赛号或链接（可选）" hint="多场比赛用英文逗号分隔，如 c12,c8,c13；也可以粘贴含 c 参数的比赛链接。"><input disabled={running} value={selected.join(',')} onChange={e=>onChange(e.target.value?e.target.value.split(','):[])} placeholder="c12,c8,c13"/></Input>
    <p className="hint">默认按限时独立测试分析，特殊情况可取消下方确认或在反馈表单调整。OI/CSP 赛制按最终提交分析，只有一份代码不代表缺少尝试或修改。</p>
  </div>;
}
