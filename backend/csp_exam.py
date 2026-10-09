"""Read-only connector for HydraBor/csp-exam-system admin pages.

Credentials stay in a private connection file. Worker parameters, source URLs,
student archives and error messages never contain the administrator key.
"""
import asyncio
import json
import re
import sys
import hashlib
from datetime import datetime
from urllib.parse import urlsplit, parse_qs
from zoneinfo import ZoneInfo
import httpx
from .config import DATA
from .html_tree import parse

CONNECTION = DATA / "csp-exam-connection.json"
def normalize_contests(values):
    base=urlsplit(connection().get("base_url",""))
    result=[]
    for value in values:
        parts=value.split(",")
        if any(not part.strip() for part in parts) or "，" in value:
            raise ValueError("多场周老师 OJ 比赛请用英文逗号分隔，不能留下空编号")
        for part in parts:
            cid=part.strip()
            if "://" in cid:
                url=urlsplit(cid)
                if (url.scheme,url.netloc)!=(base.scheme,base.netloc) or url.username or url.password or url.path not in ("/admin","/enter","/problem","/admin/scores","/admin/student"):
                    raise ValueError("请填写已连接的周老师 OJ 比赛链接")
                candidates=parse_qs(url.query).get("c",[])
                if len(candidates)!=1:raise ValueError("周老师 OJ 比赛链接必须包含唯一的 c 比赛号")
                cid=candidates[0]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,29}",cid):raise ValueError("周老师 OJ 比赛号无效，请填写如 c12 的编号")
            if cid not in result:result.append(cid)
    return result

def connection():
    return json.loads(CONNECTION.read_text()) if CONNECTION.exists() else {}

def public_connection():
    data=connection()
    return {"base_url":data.get("base_url",""),"configured":bool(data.get("admin_key"))}

def save_connection(data):
    previous=connection()
    url=urlsplit(data.get("admin_url") or data.get("base_url") or previous.get("base_url",""))
    if url.scheme not in ("http","https") or not url.hostname or url.username or url.password:
        raise ValueError("请输入周老师 OJ 的 http / https 管理地址")
    base=f"{url.scheme}://{url.netloc}"
    key=data.get("admin_key") or parse_qs(url.query).get("key",[""])[0] or (previous.get("admin_key","") if base==previous.get("base_url") else "")
    if not key or len(key)>1000:
        raise ValueError("请提供管理员密钥，或粘贴含 key 的管理链接")
    CONNECTION.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    temporary=CONNECTION.with_suffix(".tmp")
    temporary.write_text(json.dumps({"base_url":base,"admin_key":key},ensure_ascii=False))
    temporary.chmod(0o600);temporary.replace(CONNECTION)
    return public_connection()

class Client:
    def __init__(self):
        self.config=connection()
        if not self.config.get("admin_key"):
            raise ValueError("请先连接周老师 OJ 并保存管理员链接")
        self.http=httpx.AsyncClient(base_url=self.config["base_url"],timeout=40,follow_redirects=False)

    async def close(self):await self.http.aclose()

    async def get(self,path,params=None):
        # Callers use fixed read-only paths, not arbitrary external hrefs.
        if path=="/admin" and not (params or {}).get("c"):
            raise ValueError("采集周老师 OJ 必须指定比赛号")
        for attempt in range(3):
            try:
                response=await self.http.get(path,params={"key":self.config["admin_key"],**(params or {})})
                if response.status_code in (401,403):raise ValueError("周老师 OJ 管理员权限无效，请重新配置连接")
                if response.status_code>=500 or response.status_code==429:
                    await asyncio.sleep(attempt+1);continue
                if response.status_code>=400:raise ValueError(f"周老师 OJ 资料读取失败（HTTP {response.status_code}）")
                if response.is_redirect:raise ValueError("周老师 OJ 地址发生跳转，请核对连接配置")
                text=response.text
                if 'name="key"' in text and ("管理员登录" in text or "管理员密钥" in text) and '/admin/scores' not in text:
                    raise ValueError("周老师 OJ 管理员登录失效，请重新配置连接")
                return text
            except (httpx.TimeoutException,httpx.NetworkError):
                await asyncio.sleep(attempt+1)
        raise ValueError("周老师 OJ 连接超时或暂时不可用，请稍后重试")

def clean_text(node):return " ".join(node.text().split()) if node else ""

def parse_time(value):
    try:
        timestamp=datetime.fromisoformat(value.strip())
        return timestamp.astimezone(ZoneInfo("Asia/Shanghai")) if timestamp.tzinfo else timestamp.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    except (ValueError,AttributeError):return None

def score_result(score,full,raw):
    result="AC" if score is not None and full is not None and score==full else "部分通过" if score else "未通过 / 状态未明"
    if "编译" in raw:result="CE（编译错误）"
    elif "超时" in raw or "TLE" in raw:result="部分通过（TLE）" if score else "TLE"
    return result

def contest_info(text,cid):
    root=parse(text)
    heading=clean_text(root.first("h1"))
    title=re.sub(r"^管理端\s*[·•:：-]\s*","",heading) or cid
    format_text=" ".join(clean_text(p) for p in root.all("p")[:3])
    contest_format="ioi" if "IOI" in format_text.upper() else "oi_csp"
    duration=root.first("input",name="duration")
    value=duration.attrs.get("value","") if duration else ""
    minutes=int(value) if re.fullmatch(r"\d+",value) and 1<=int(value)<=100000 else None
    return {"title":title,"format":contest_format,"duration_minutes":minutes}

def student_from_scores(text,name,exam_number=""):
    matches=[]
    for row in parse(text).all("tr"):
        cells=[n for n in row.children if getattr(n,"tag",None)=="td"]
        if len(cells)<3 or clean_text(cells[1])!=name.strip():continue
        for a in row.all("a"):
            url=urlsplit(a.attrs.get("href",""));number=parse_qs(url.query).get("k",[""])[0]
            if url.path=="/admin/student" and number and (not exam_number or number==exam_number):matches.append(number)
    matches=list(dict.fromkeys(matches))
    if len(matches)!=1:
        raise ValueError("比赛名单中未找到该考生，或存在同名考生；请补充本场考号核对")
    return matches[0]

def metadata_from_html(text):
    node=parse(text).first("input",name="problems_json")
    if not node:raise ValueError("比赛页面缺少题单数据，请核对考试系统版本")
    data=json.loads(node.attrs.get("value","[]"))
    if not data or any(not q.get("pid") for q in data):raise ValueError("比赛题单为空或格式发生变化")
    return data

def time_from_detail(root):
    for b in root.all("b"):
        if clean_text(b)=="提交时间":
            value=b.parent.text().replace(b.text(),"",1).strip()
            timestamp=parse_time(value)
            if timestamp:return timestamp
    return None

def question_outcome(block):
    kv=next((d for d in block.all("div") if d.attrs.get("class")=="kv"),None)
    fields={clean_text(d.first("b")):d.text().replace(d.first("b").text(),"",1).strip() for d in kv.children if getattr(d,"tag",None)=="div" and d.first("b")} if kv else {}
    match=re.match(r"(\d+(?:\.\d+)?)\s*/\s*(\d+)",fields.get("得分",""))
    score=float(match[1]) if match else None
    full=float(match[2]) if match else None
    raw=fields.get("判分结果","")
    result=score_result(score,full,raw) if "未提交" not in raw else "未提交"
    code=""
    for details in block.all("details"):
        summary=details.first("summary")
        if summary and "查看提交的代码" in summary.text():
            pre=details.first("pre");code=pre.text() if pre else ""
    count=re.search(r"\d+",fields.get("提交次数",""))
    latest=fields.get("最近一次","")
    recent=re.search(r"（(\d+(?:\.\d+)?)\s*分[，,]\s*(.*?)）",latest)
    return {"code":code,"score":score,"result":result,"raw":raw,"reported":int(count[0]) if count else 0,
        "latest_score":float(recent[1]) if recent else None,"latest_at":recent[2] if recent else None,"latest_status":latest,"full":full}

async def collect(config,progress=lambda message:None):
    client=Client()
    cid=config["task_id"];name=config["student_name"]
    try:
        progress("核对比赛名单与该生考号")
        number=student_from_scores(await client.get("/admin/scores",{"c":cid}),name,config.get("exam_number",""))
        page=await client.get("/admin",{"c":cid})
        questions=metadata_from_html(page);info=contest_info(page,cid)
        root=parse(await client.get("/admin/student",{"c":cid,"k":number}))
        heading=next((h for h in root.all("h1") if name.strip() in h.text() and number in h.text()),None)
        if not heading:
            raise ValueError("考试详情的考生身份与请求不匹配，已阻止导入")
        batch_submitted=time_from_detail(root)
        problems=[];failed=[];warnings=[];dates={};outside_dates=set()
        fetched=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
        base=client.config["base_url"]
        files=[]
        for a in root.all("a"):
            url=urlsplit(a.attrs.get("href",""));params=parse_qs(url.query)
            if url.path=="/admin/file" and params.get("c")==[cid] and params.get("k")==[number]:
                file=params.get("f",[""])[0]
                if file and re.search(r"\.(cpp|cc|cxx|py)$",file,re.I):files.append(file)
        files=list(dict.fromkeys(files))
        for i,q in enumerate(questions,1):
            progress(f"读取题面与代码 {i}/{len(questions)}")
            try:
                statement_root=parse(await client.get("/admin/problem-detail",{"pid":q["pid"]}))
                textarea=statement_root.first("textarea",name="statement")
                if not textarea:raise ValueError("题目详情没有可读取的完整题面")
                statement=textarea.text()
                block=root.first("div",id=f"T{i}")
                if not block:raise ValueError("学生页面与比赛题序不一致")
                outcome=question_outcome(block)
                submitted=parse_time(outcome["latest_at"]) or batch_submitted
                day=submitted.date().isoformat() if submitted else None
                inside=bool(day and config["start_date"]<=day<=config["end_date"])
                if day and outcome["code"]:
                    dates[day]=dates.get(day,0)+1
                    if not inside:outside_dates.add(day)
                code=outcome["code"] if inside else ""
                version_files=[f for f in files if re.fullmatch(re.escape(q.get("name",""))+r"\.(cpp|cc|cxx|py)",f.rsplit("/",1)[-1],re.I)]
                root_file=next((f for f in version_files if not f.startswith("__submissions/")),None)
                unverified=[]
                if inside and root_file:
                    latest_code=await client.get("/admin/file",{"c":cid,"k":number,"f":root_file,"dl":"1"})
                    if latest_code.strip() and latest_code.replace("\r\n","\n")!=code.replace("\r\n","\n"):
                        code=latest_code
                        outcome["score"]=outcome["latest_score"]
                        outcome["result"]=score_result(outcome["score"],outcome["full"],outcome["latest_status"]) if outcome["score"] is not None else "最新代码评测未核实"
                language="python" if root_file and root_file.lower().endswith(".py") else "cpp"
                if inside:
                    for file in version_files:
                        if file==root_file:continue
                        body=await client.get("/admin/file",{"c":cid,"k":number,"f":file,"dl":"1"})
                        if body.strip():unverified.append({"id":hashlib.sha256(file.encode()).hexdigest()[:32],"code":body,"source_file":file,"language":"python" if file.lower().endswith(".py") else "cpp"})
                state="submitted" if code else "no_submission_in_period" if outcome["code"] and day else "unverified_time" if outcome["code"] else "no_submission"
                ident=f"{cid}:{number}:{i}:{submitted.strftime('%Y%m%d%H%M%S') if submitted else 'unknown'}"
                history=[{"id":ident,"submitted_at":submitted.isoformat(),"result":outcome["result"],"language":language,"code":code,"score":outcome["score"],"gap_seconds":None}] if code else []
                incomplete=outcome["reported"]>1
                notice=["平台登记了多次提交，可读取的本期代码快照单独保存；快照缺少可靠的逐次时间和评测，不推断修改顺序，也不计入本期提交次数"] if incomplete else []
                tags=["周老师OJ","限时测试","OI/CSP赛制" if info["format"]=="oi_csp" else "IOI赛制","最终提交材料"]
                if config.get("contest_independent"):tags+=["讲师确认独立完成","讲师确认未接受题解或讲解"]
                problems.append({"title":q.get("title") or q["pid"],"problem_id":f"csp_exam:{cid}:{q['pid']}","statement":statement,"code":code,"language":language,
                    "independent":True if code and config.get("contest_independent") else None,"editorial_seen":False if code and config.get("contest_independent") else None,"minutes":None,
                    "judge_result":(f"{outcome['result']} · {outcome['score']:g} / {q.get('full',100)} 分" if outcome["score"] is not None else "最新代码评测未核实") if code else "本期没有可核实的提交代码",
                    "observation":"；".join(notice),"submissions":history,"unverified_submissions":unverified if incomplete else [],"submission_state":state,"non_submission_reason":"unknown",
                    "completion_context":"independent_timed_contest" if code and config.get("contest_independent") else "unspecified",
                    "source":{"platform":"csp_exam","kind":"contest","task_id":cid,"task_title":info["title"],"team_id":base,"user_id":number,
                        "question_id":q["pid"],"task_url":base+"/enter?c="+cid,"problem_url":base+"/problem?c="+cid+"&p="+str(i),"fetched_at":fetched,
                        "selected_submission_id":ident if code else "","period_start":config["start_date"],"period_end":config["end_date"],"history_count":len(history),"reported_submission_count":outcome["reported"],"history_complete":not incomplete,"warnings":notice,
                        "assessment_tags":tags,"contest_format":info["format"],"submission_semantics":"final_submission","contest_duration_minutes":info["duration_minutes"]}})
            except ValueError as exc:
                if "权限" in str(exc) or "身份" in str(exc):raise
                failed.append({"question_id":q["pid"],"message":str(exc)})
        if outside_dates:warnings.append(f"部分提交在 {', '.join(sorted(outside_dates))}，不在所选学习时段；题面保留，相关代码不纳入本期")
        if not dates:warnings.append("未取得可靠提交时间，本场代码不纳入本期能力证据")
        if any(not p["source"]["history_complete"] for p in problems):warnings.append("平台未提供完整的逐次提交时间和评测，可读取的额外代码快照单独保存；本期评估只使用可核实的提交，不将快照当作完整历史")
        return {"student":{"user_id":number,"display_name":name},"platform":"csp_exam","kind":"contest","task_id":cid,"task_url":base+"/enter?c="+cid,
            "problems":problems,"warnings":warnings,"failed_questions":failed,"available_dates":dates}
    finally:await client.close()

async def main():
    config=json.loads(sys.stdin.read())
    def emit(message):print(json.dumps(message,ensure_ascii=False),flush=True)
    try:
        result=await collect(config,lambda message:emit({"type":"progress","message":message}))
        from pathlib import Path
        Path(config["output_path"]).write_text(json.dumps(result,ensure_ascii=False))
        emit({"type":"result-file"})
    except Exception as exc:
        emit({"type":"error","message":str(exc) if isinstance(exc,ValueError) else "周老师 OJ 资料格式变化，请核对连接或系统版本"})
        sys.exit(1)

if __name__=="__main__":asyncio.run(main())
