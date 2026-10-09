// API paths and extraction helpers adapted from HydraBor/ACGO-crawler (MIT).
// See vendor/SOURCE.json and vendor/LICENSE for the pinned upstream source.
import {chromium} from 'playwright-core';
import {writeFileSync} from 'node:fs';
import {buildQuestionDataUrl,problemFromNextData} from './vendor/problem-data.mjs';
import {parseJSON,exactId,safeNumber,periodRecords,submissionOf,materialOf,findStudent,contestOrder,isSectionMarker} from './core.mjs';

const emit=value=>process.stdout.write(JSON.stringify(value)+'\n');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let ownPage;
// Windows interoperability may not propagate a Linux worker cancellation signal.
// This watchdog bounds the lifetime of the Windows process as well.
setTimeout(async()=>{emit({type:'error',message:'导入超时，请稍后重试'});try{await ownPage?.close()}catch{}process.exit(1)},3600000).unref();
for(const signal of ['SIGTERM','SIGINT'])process.on(signal,async()=>{try{await ownPage?.close()}catch{}process.exit(1)});

export function captureHeaders(page) {
  let headers={};const pending=new Set();
  const handler=request=>{
    if(new URL(request.url()).hostname!=='gateway.acgo.cn')return;
    let task;
    task=request.allHeaders().then(data=>{
      for(const [name,value]of Object.entries(data))if(/^(access-token|authorization|x-access-token|app-id|appid|client-type|platform|x-[a-z0-9-]+)$/i.test(name))headers[name]=value;
    }).catch(()=>{}).finally(()=>pending.delete(task));
    pending.add(task);
  };
  page.on('request',handler);
  return {read:async()=>{while(pending.size)await Promise.allSettled([...pending]);return {...headers}},dispose:()=>{page.off('request',handler);headers={}}};
}
function apiFor(context,store) {
  let last=0;
  const call=async(method,endpoint,payload)=>{
    const headers=await store.read();
    if(!Object.keys(headers).some(name=>/token|authorization/i.test(name)))throw new Error('未获取 ACGO 登录态，请在专用 Edge 登录后重试');
    const url='https://gateway.acgo.cn'+endpoint;
    for(let attempt=0;attempt<3;attempt++) {
      await pause(Math.max(0,200-(Date.now()-last)));last=Date.now();
      let response;
      try{response=await context.request[method.toLowerCase()](url,{headers,timeout:30000,maxRedirects:0,...(method==='GET'?{params:payload}:{data:payload||{}})})}
      catch{if(attempt<2){await pause(500*(attempt+1));continue}throw new Error('ACGO 请求超时或网络不可用，请重试')}
      const status=response.status();let body;
      try{body=parseJSON(await response.text())}catch{}
      const code=Number(body?.code);
      if(status===401||status===403||code===401||code===403)throw new Error('ACGO 登录过期或没有权限查看该任务/学生代码，请重新登录或检查权限');
      if((status===429||status>=500||code===429||code>=500)&&attempt<2){
        const retry=Number(response.headers()['retry-after']);
        if(Number.isFinite(retry)&&retry>30)throw new Error('ACGO 要求稍后重试，请等待后再导入');
        await pause(Number.isFinite(retry)&&retry>0?retry*1000:500*(attempt+1));continue;
      }
      if(!response.ok()||code!==200)throw new Error(`ACGO 数据读取失败（HTTP ${status} / 状态 ${Number.isFinite(code)?code:'格式变化'}），请检查任务、账号权限或稍后重试`);
      return body.data;
    }
  };
  return {get:(endpoint,params)=>call('GET',endpoint,params),post:(endpoint,data)=>call('POST',endpoint,data)};
}
async function goto(page,url) {
  const parsed=new URL(url);
  if(parsed.protocol!=='https:'||parsed.hostname!=='www.acgo.cn')throw new Error('只允许访问 ACGO 官方页面');
  try{await page.goto(url,{waitUntil:'domcontentloaded',timeout:45000});await page.waitForTimeout(900)}catch{throw new Error('ACGO 页面加载失败，请检查网络并在专用 Edge 中确认可打开该任务')}
  if(new URL(page.url()).hostname!=='www.acgo.cn')throw new Error('页面跳转到站外，已停止采集');
}
async function nextData(page) {
  const text=await page.locator('#__NEXT_DATA__').textContent({timeout:5000}).catch(()=>'');
  if(!text)throw new Error('ACGO 页面缺少题目数据，请确认已登录，或平台页面结构已变化');
  return parseJSON(text);
}
async function problemLinks(page) {
  const links=await page.locator('a[href]').evaluateAll(nodes=>nodes.map(a=>({url:a.href,label:a.textContent.trim()})));
  const seen=new Set();return links.flatMap(link=>{
    const url=new URL(link.url),match=url.pathname.match(/^\/problemset\/info\/(\d+)\/?$/);
    if(url.hostname!=='www.acgo.cn'||!match||seen.has(match[1]))return [];
    seen.add(match[1]);return [{publicId:match[1],label:link.label}];
  });
}
async function readProblem(page,context,question,config,buildId) {
  const url=new URL(`https://www.acgo.cn/problemset/info/${question.publicId}`);
  url.searchParams.set('teamCode',config.team_id);
  if(config.kind==='homework')url.searchParams.set('homeworkId',config.task_id);
  let payload;
  if(buildId) {
    const dataUrl=buildQuestionDataUrl({buildId,questionId:question.publicId,teamCode:config.team_id,homeworkId:config.kind==='homework'?config.task_id:''});
    try{
      const response=await context.request.get(dataUrl,{timeout:30000,maxRedirects:0});
      if(response.ok())payload=parseJSON(await response.text());
    }catch{}
  }
  if(!payload?.pageProps?.questionInfo&&!payload?.props?.pageProps?.questionInfo){await goto(page,url.href);payload=await nextData(page)}
  const problem=problemFromNextData(payload,url.href);
  if(exactId(problem.questionId)!==question.publicId)throw new Error('题面返回的公开题号与任务题号不一致，已阻止导入');
  if(!problem.markdown?.trim())throw new Error('题面为空，无法形成可靠分析材料');
  return problem;
}
async function homeworkTask(page,api,config) {
  const rankingUrl=new URL(config.task_url);rankingUrl.searchParams.set('tab','ranking');
  await goto(page,rankingUrl.href);
  const found=await findStudent({userId:config.user_id,
    loadPage:page=>api.get(`/acgoPms/api/team/${config.team_id}/homework/ranking/${config.task_id}`,{groupId:'-1',homeworkId:config.task_id,teamCode:config.team_id,page:String(page),pageSize:'100'}),
    records:data=>data?.records,total:data=>data?.total,idOf:row=>row.userInfo?.userId});
  const scoreList=await api.get(`/acgoPms/api/team/${config.team_id}/homework/getQuestionScore/${config.task_id}`);
  if(!Array.isArray(scoreList))throw new Error('作业题单格式发生变化');
  const pageLinks=await problemLinks(page),ids=new Set(pageLinks.map(q=>q.publicId));
  for(const q of scoreList)ids.add(exactId(q.questionId));
  for(const q of found.student.homeworkAnswerList||[])ids.add(exactId(q.questionId));
  if(!ids.size)throw new Error('作业题单为空');
  const answers=new Map((found.student.homeworkAnswerList||[]).map(q=>[exactId(q.questionId),q]));
  return {student:{user_id:config.user_id,display_name:found.student.userInfo?.teamVo?.teamUserName||found.student.userInfo?.nickName||''},
    questions:[...ids].map(id=>({publicId:id,questionId:id,expected:Boolean(answers.get(id)?.recordId),expectedRecordId:answers.get(id)?.recordId?exactId(answers.get(id).recordId):''})),
    buildId:(await nextData(page)).buildId};
}
async function contestTask(page,api,config) {
  const initial=await nextData(page),props=initial.props?.pageProps||{};
  const hrefs=await page.locator('a[href]').evaluateAll(nodes=>nodes.map(a=>a.href));
  const roundValue=props.contestInfo?.matchRounds||props.contestInfo?.matchRound||{};
  const round=Array.isArray(roundValue)?(roundValue.find(r=>String(r.id)===new URL(config.task_url).searchParams.get('matchRoundId'))||(roundValue.length===1?roundValue[0]:{})):roundValue;
  const params=new URL(config.task_url).searchParams;
  for(const href of hrefs){const u=new URL(href);if(u.hostname==='www.acgo.cn'&&new RegExp(`^/contest/(detail|question|ranking)/${config.task_id}/?$`).test(u.pathname))for(const k of ['examId','matchRoundId','openLevel'])if(!params.get(k)&&u.searchParams.get(k))params.set(k,u.searchParams.get(k))}
  if(!params.get('examId'))params.set('examId',String(round.programExamId||round.paperId||props.examId||''));
  if(!params.get('matchRoundId'))params.set('matchRoundId',String(round.id||props.matchRoundId||''));
  if(!params.get('openLevel'))params.set('openLevel',String(props.contestInfo?.openLevel||props.openLevel||''));
  if(!params.get('examId')||!params.get('matchRoundId'))throw new Error('未找到比赛试卷或轮次编号，请填写包含 examId 和 matchRoundId 的完整比赛链接');
  params.set('teamCode',config.team_id);
  const rankingUrl=new URL(`https://www.acgo.cn/contest/ranking/${config.task_id}?${params}`);
  const found=await findStudent({userId:config.user_id,
    loadPage:async number=>{rankingUrl.searchParams.set('page',String(number));await goto(page,rankingUrl.href);return (await nextData(page)).props?.pageProps},
    records:data=>data?.listData?.list,total:data=>data?.listData?.total,idOf:row=>row.userId});
  const questions=await api.post('/acgoMatch/leaderboard/questionList',{examId:safeNumber(params.get('examId')),matchRoundId:safeNumber(params.get('matchRoundId'))});
  if(!Array.isArray(questions)||!questions.length)throw new Error('比赛题单为空或格式发生变化');
  const pageQuestions=found.pageData.questionList||[];
  const candidates=[questions,pageQuestions].map(list=>list.map(q=>({publicId:String(q.acgoQuestionId||q.acgoQuestion?.questionId||q.questionInfo?.questionId||q.problemId||'')}))).filter(list=>list.length&&list.every(q=>/^\d+$/.test(q.publicId)));
  let links=candidates.sort((a,b)=>b.length-a.length)[0];
  if(!links){const u=new URL(`https://www.acgo.cn/contest/question/${config.task_id}?${params}`);await goto(page,u.href);links=await problemLinks(page)}
  const order=contestOrder(questions,pageQuestions,links,found.student);
  return {student:{user_id:config.user_id,display_name:found.student.nickName||''},examId:params.get('examId'),
    taskUrl:`https://www.acgo.cn/contest/detail/${config.task_id}?${new URLSearchParams([...params].sort(([a],[b])=>a.localeCompare(b)))}`,
    questions:order.map(q=>({questionId:exactId(q.questionId),publicId:exactId(q.acgoQuestionId),expected:Number((found.student.rank||[]).find(r=>String(r.questionId)===String(q.questionId))?.submitNum)>0})),
    buildId:initial.buildId};
}
export async function collect(config) {
  emit({type:'progress',message:'连接专用 Edge 浏览器'});
  let browser;
  try{browser=await chromium.connectOverCDP(`http://127.0.0.1:${config.cdp_port}`,{timeout:10000})}catch{throw new Error('未连接到专用 Edge，请运行启动脚本、登录 ACGO 并保持窗口打开')}
  const context=browser.contexts()[0];
  if(!context)throw new Error('未找到可用浏览器会话');
  ownPage=await context.newPage();const store=captureHeaders(ownPage);
  try{
    await goto(ownPage,config.task_url);
    const api=apiFor(context,store);
    emit({type:'progress',message:'读取任务题单与指定学生完成记录'});
    const task=config.kind==='homework'?await homeworkTask(ownPage,api,config):await contestTask(ownPage,api,config);
    if(task.taskUrl)config={...config,task_url:task.taskUrl};
    const result={student:task.student,kind:config.kind,task_id:config.task_id,team_id:config.team_id,task_url:config.task_url,
      start_date:config.start_date,end_date:config.end_date,problems:[],warnings:[],failed_questions:[],available_dates:{},skipped:{outside_period:0,unknown_time:0,no_submissions:0,section_markers:0}};
    for(let index=0;index<task.questions.length;index++) {
      const question=task.questions[index];
      emit({type:'progress',message:`读取题目与本期提交 ${index+1}/${task.questions.length}`});
      try{
        const problem=await readProblem(ownPage,context,question,config,task.buildId);
        if(isSectionMarker(problem)){result.skipped.section_markers++;continue}
        const records=config.kind==='homework'?
          await api.post(`/acgoPms/api/team/${config.team_id}/homework/questionAnswerRecord/list`,{teamCode:config.team_id,questionId:safeNumber(question.questionId),homeworkId:safeNumber(config.task_id),userId:config.user_id}):
          await api.post(`/acgoMatch/api/team/${config.team_id}/questionAnswerRecord/list`,{teamCode:config.team_id,examId:task.examId,questionId:question.questionId,userId:config.user_id});
        if(Array.isArray(records)&&!records.length&&question.expected)throw new Error('完成记录显示已提交，但提交接口返回空列表，请检查查看代码权限');
        if(question.expectedRecordId&&Array.isArray(records)&&!records.some(r=>exactId(r.id)===question.expectedRecordId))throw new Error('提交列表与该生作业完成记录的提交编号不一致，已阻止导入');
        const chosen=periodRecords(records,config);
        for(const [day,count]of Object.entries(chosen.availableDates))result.available_dates[day]=(result.available_dates[day]||0)+count;
        result.skipped.outside_period+=chosen.outside;result.skipped.unknown_time+=chosen.unknown;
        if(!chosen.records.length){result.skipped.no_submissions++;result.problems.push(materialOf(problem,[],config,question,chosen));continue}
        const submissions=[];
        const toFetch=config.submission_mode==='latest_only'?chosen.records.slice(-1):chosen.records;
        for(const record of toFetch) {
          const detail=config.kind==='homework'?
            await api.post(`/acgoPms/api/team/${config.team_id}/homework/questionAnswerRecord/view`,{teamCode:config.team_id,id:safeNumber(record.id),homeworkId:safeNumber(config.task_id)}):
            await api.post(`/acgoMatch/api/team/${config.team_id}/questionAnswerRecord/matchView`,{teamCode:config.team_id,id:record.id});
          submissions.push(submissionOf(record,detail,config));
        }
        const material=materialOf(problem,submissions,config,question,chosen);
        result.problems.push(material);
      }catch(error){
        if(/登录|没有权限|登录态/.test(error.message))throw error;
        result.failed_questions.push({question_id:question.publicId,message:error.message});
      }
    }
    if(result.skipped.unknown_time)result.warnings.push(`${result.skipped.unknown_time} 次提交缺少可靠时间，未作为本期成果导入`);
    if(result.skipped.outside_period)result.warnings.push(`${result.skipped.outside_period} 次提交在所选学习时段之外，未导入`);
    if(result.failed_questions.length)result.warnings.push(`${result.failed_questions.length} 道题读取失败，请核对后重试；失败题目未导入`);
    if(result.skipped.section_markers)result.warnings.push(`${result.skipped.section_markers} 条作业分组标记已排除，不作为解题成果`);
    result.warnings.push('平台评测结果仅代表对应提交；是否独立、是否看过题解、做题耗时需讲师补充');
    return result;
  }finally{store.dispose();await ownPage.close().catch(()=>{});ownPage=null}
  // No browser.close(): disconnecting this worker must leave the lecturer's window alive.
}
async function main() {
  let input='';for await(const chunk of process.stdin){input+=chunk;if(input.length>20000)throw new Error('导入参数过大')}
  const config=JSON.parse(input);
  if(config.operation==='probe') {
    try{const response=await fetch(`http://127.0.0.1:${config.cdp_port}/json/version`,{signal:AbortSignal.timeout(3000)});if(!response.ok)throw Error();await response.json();emit({type:'result',result:{connected:true}})}
    catch{emit({type:'result',result:{connected:false}})}
  }else {
    const result=await collect(config);
    if(config.output_path){writeFileSync(config.output_path,JSON.stringify(result),'utf8');emit({type:'result-file'})}
    else emit({type:'result',result});
  }
}
if(process.argv[1]?.endsWith('collector.mjs'))main().then(()=>process.exit(0)).catch(error=>{emit({type:'error',message:error.message});process.exit(1)});
