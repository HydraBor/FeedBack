"""One-student, read-only import; credentials remain in the browser worker."""
import asyncio
import json
import os
import shutil
import subprocess
import time
import uuid
import tempfile
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode
from .config import ROOT, DATA
from .models import ACGOImportInput, ACGOArchiveInput, ZhouOJImportInput, ProblemInput, StudentInput
from . import db

imports: dict[str, dict] = {}
tasks: dict[str, asyncio.Task] = {}
queue = asyncio.Semaphore(1)
worker_slots = asyncio.Semaphore(8)
browser_lock = asyncio.Lock()

def normalize(data: ACGOImportInput) -> dict:
    import re
    def official_url(value):
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.hostname != "www.acgo.cn" or parsed.port not in (None, 443) or parsed.username or parsed.password:
            raise ValueError("请输入 ACGO 官方 https://www.acgo.cn 链接或编号")
        return parsed
    team = data.team.strip()
    task = data.task.strip()
    params = {}
    if "://" in team:
        url = official_url(team)
        params = {key: values[0] for key, values in parse_qs(url.query).items() if values}
        match = re.search(r"/team/(?:home/)?([A-Za-z0-9_-]+)", url.path)
        team = params.get("teamCode") or (match[1] if match else "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", team):
        raise ValueError("团队 ID 无效，请填写团队编号或含 teamCode 的链接")
    if "://" in task:
        url = official_url(task)
        pattern = r"^/homework/(\d+)/?$" if data.kind == "homework" else r"^/contest/(?:detail|ranking|question)/(\d+)/?$"
        match = re.fullmatch(pattern, url.path)
        if not match:
            raise ValueError("链接类型与所选作业 / 比赛不一致")
        task = match[1]
        params = {key: values[0] for key, values in parse_qs(url.query).items() if values}
        if params.get("teamCode") and params["teamCode"] != team:
            raise ValueError("链接中的团队 ID 与填写的团队不一致")
    if not re.fullmatch(r"\d{1,30}", task):
        raise ValueError("作业 / 比赛编号必须为数字，或填写对应官方链接")
    allowed = {k: v for k, v in params.items() if k in ("examId", "matchRoundId", "openLevel")}
    for key in ("examId", "matchRoundId"):
        if key in allowed and not re.fullmatch(r"\d{1,30}", allowed[key]):
            raise ValueError("比赛链接中的试卷 / 轮次编号无效")
    allowed["teamCode"] = team
    if data.kind == "homework":
        path = f"/homework/{task}"
        allowed = {"teamCode": team, "tab": "question"}
    else:
        path = f"/contest/detail/{task}"
    return {**data.model_dump(mode="json"), "team_id": team, "task_id": task,
            "task_url": "https://www.acgo.cn" + path + "?" + urlencode(sorted(allowed.items()))}

def task_configs(data, *, student_id, start_date, end_date):
    """Comma-separated tasks, validated before starting any browser work."""
    pairs = [(data.kind, data.task)] if isinstance(data, ACGOImportInput) else [] if isinstance(data,ZhouOJImportInput) else [("homework", data.homework), ("contest", data.contest)]
    configs, seen = [], set()
    for kind, value in pairs:
        if not value.strip():
            continue
        parts = value.split(",")
        if any(not part.strip() for part in parts):
            raise ValueError("多个作业 / 比赛请用英文逗号分隔，逗号之间不能留空编号")
        for part in parts:
            if "，" in part:
                raise ValueError("多个编号请使用英文逗号 , 分隔")
            single = ACGOImportInput(student_id=student_id, user_id=data.user_id, team=data.team, kind=kind, task=part.strip(),
                start_date=start_date, end_date=end_date, contest_independent=data.contest_independent,
                submission_mode=getattr(data,"submission_mode","latest_history"), cdp_port=getattr(data,"cdp_port",9223))
            config = normalize(single)
            key = (kind,config["task_id"],parse_qs(urlparse(config["task_url"]).query).get("examId",[""])[0],parse_qs(urlparse(config["task_url"]).query).get("matchRoundId",[""])[0])
            if key not in seen:
                configs.append(config)
                seen.add(key)
    for config in configs:
        config["platform"] = "acgo"
        config["concurrency"] = data.concurrency
    zhou_values=[data.contests] if isinstance(data,ZhouOJImportInput) else getattr(data,"csp_contests",[])
    if zhou_values:
        from . import csp_exam
        saved=csp_exam.public_connection()
        if not saved["configured"]:raise ValueError("请先连接周老师 OJ")
        student_name=db.student(student_id)["name"] if isinstance(data,ZhouOJImportInput) else data.name.strip()
        for cid in csp_exam.normalize_contests(zhou_values):
            configs.append({"platform":"csp_exam","kind":"contest","task_id":cid,"student_name":student_name,
                "exam_number":data.exam_number if isinstance(data,ZhouOJImportInput) else data.csp_exam_number,"student_id":student_id,"start_date":str(start_date),"end_date":str(end_date),
                "contest_independent":data.contest_independent,"concurrency":data.concurrency})
    if not configs:raise ValueError("请至少选择一份作业或比赛")
    return configs

async def collect_tasks(configs, progress):
    slots=asyncio.Semaphore(configs[0].get("concurrency",3))
    states={};completed=0
    async def collect_one(index,config):
        nonlocal completed
        label = f"{index+1}/{len(configs)} " + ("作业" if config["kind"]=="homework" else "比赛") + " " + config["task_id"]
        def update(message):
            states[index]=label+"："+message
            progress(f"已完成 {completed}/{len(configs)} · "+" | ".join(states[k] for k in sorted(states)))
        try:
            async with slots, worker_slots:
                update("开始采集")
                result = await run_worker(config, update)
            if config.get("platform","acgo")=="acgo" and result["student"]["user_id"] != config["user_id"]:
                raise ValueError("返回学生 ID 与请求不匹配，已阻止导入")
            result["problems"] = [ProblemInput.model_validate(p).model_dump(mode="json") for p in result["problems"]]
            return result,None
        except ValueError as exc:
            if any(word in str(exc) for word in ("登录", "权限", "学生 ID", "身份", "浏览器")):
                raise
            return None,{"platform":config.get("platform","acgo"),"kind":config["kind"],"task_id":config["task_id"],"message":str(exc)[:500]}
        finally:
            completed+=1;states.pop(index,None)
            progress(f"已完成 {completed}/{len(configs)} · "+" | ".join(states[k] for k in sorted(states)))
    workers=[asyncio.create_task(collect_one(i,c)) for i,c in enumerate(configs)]
    try:
        outcomes=await asyncio.gather(*workers)
    except BaseException:
        for worker in workers:worker.cancel()
        await asyncio.gather(*workers,return_exceptions=True)
        raise
    results=[r for r,_ in outcomes if r];failed_tasks=[f for _,f in outcomes if f]
    if not results:
        raise ValueError("所有任务读取失败："+"；".join(f["message"] for f in failed_tasks)[:400])
    problems, seen = [], set()
    for result in results:
        for problem in result["problems"]:
            source=problem["source"]
            key=(source["platform"],source["kind"],source["team_id"],source["task_id"],source["contest_question_id"],source["question_id"],source["task_url"])
            if key not in seen:
                seen.add(key)
                problems.append(problem)
    dates={}
    for result in results:
        for day,count in result.get("available_dates",{}).items():
            dates[day]=dates.get(day,0)+count
    return {"student":results[0]["student"],"kind":configs[0]["kind"] if len({c["kind"] for c in configs})==1 else "mixed",
        "task_id":",".join(r["task_id"] for r in results),"task_url":results[0]["task_url"] if len(results)==1 else "",
        "start_date":configs[0]["start_date"],"end_date":configs[0]["end_date"],"problems":problems,"available_dates":dates,
        "tasks":[{"platform":r.get("platform","acgo"),"kind":r["kind"],"id":r["task_id"],"url":r["task_url"]} for r in results],"failed_tasks":failed_tasks,
        "warnings":list(dict.fromkeys([w for r in results for w in r["warnings"]]+[f"{len(failed_tasks)} 份任务读取失败，已保存其他成功任务，请核对" for _ in [0] if failed_tasks])),
        "failed_questions":[{**f,"kind":r["kind"],"task_id":r["task_id"]} for r in results for f in r["failed_questions"]]}

def worker_command():
    script = ROOT / "integrations" / "acgo" / "collector.mjs"
    # In WSL the browser is on Windows. Running a Windows Node worker keeps
    # CDP bound to Windows loopback without exposing a debugging port to LAN.
    windows_node = Path("/mnt/c/Program Files/nodejs/node.exe")
    if windows_node.exists() and "microsoft" in os.uname().release.lower():
        converted = subprocess.run(["wslpath", "-w", str(script)], capture_output=True, text=True, check=True).stdout.strip()
        return [str(windows_node), converted]
    node = shutil.which("node") or str(ROOT / ".tools" / "node" / "bin" / "node")
    return [node, str(script)]

async def run_worker(config: dict, progress=None):
    is_csp=config.get("platform")=="csp_exam"
    command=[sys.executable,"-m","backend.csp_exam"] if is_csp else worker_command()
    if not is_csp and config.get("operation") != "probe":
        async with browser_lock:await ensure_browser(config.get("cdp_port", 9223), progress)
    descriptor,path=tempfile.mkstemp(prefix="collector-",suffix=".json",dir=DATA)
    os.close(descriptor)
    process = None
    result = None
    error = None
    async def read():
        nonlocal result, error
        while line := await process.stdout.readline():
            event = json.loads(line)
            if event.get("type") == "progress" and progress:
                progress(event["message"])
            elif event.get("type") == "result":
                result = event["result"]
            elif event.get("type") == "result-file":
                result=json.loads(Path(path).read_text(encoding="utf-8"))
            elif event.get("type") == "error":
                error = event.get("message", "ACGO 读取失败")
        await process.wait()
    try:
        output_path=path
        if not is_csp and command[0].endswith("node.exe"):
            output_path=subprocess.run(["wslpath","-w",path],capture_output=True,text=True,check=True).stdout.strip()
        config={**config,"output_path":output_path}
        process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.PIPE,cwd=ROOT,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=1024 * 1024)
        process.stdin.write(json.dumps(config, ensure_ascii=False).encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()
        await asyncio.wait_for(read(), timeout=20 if config.get("operation") == "probe" else 3600)
        if process.returncode or result is None:
            raise ValueError(error or "采集进程未返回有效结果，请检查 Node 与 ACGO 连接")
        return result
    except asyncio.TimeoutError:
        raise ValueError("导入超时，请缩小学习时段或稍后重试")
    finally:
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        Path(path).unlink(missing_ok=True)

async def status(port: int = 9223):
    try:
        probe = await run_worker({"operation": "probe", "cdp_port": port})
        if not probe["connected"]:
            await ensure_browser(port)
            probe = await run_worker({"operation": "probe", "cdp_port": port})
        return {**probe, "port": port, "message": "专用 Edge 已连接，导入时核对登录与权限" if probe["connected"] else "请运行 scripts/start-acgo-edge.ps1 并登录 ACGO"}
    except (OSError, ValueError):
        return {"connected": False, "port": port, "message": "采集环境不可用，请检查 Node 和浏览器启动脚本"}

async def ensure_browser(port=9223, progress=None):
    probe = await run_worker({"operation": "probe", "cdp_port": port})
    if probe["connected"]:
        return
    launcher = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    if port != 9223 or not launcher.exists():
        raise ValueError("未找到专用浏览器，请运行 scripts/start-acgo-edge.ps1")
    if progress:
        progress("专用 Edge 未运行，正在重新打开原登录窗口")
    script = subprocess.run(["wslpath", "-w", str(ROOT / "scripts/start-acgo-edge.ps1")], capture_output=True, text=True, check=True).stdout.strip()
    process = await asyncio.create_subprocess_exec(str(launcher), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        await asyncio.wait_for(process.wait(), 15)
    except asyncio.TimeoutError:
        process.terminate()
        await process.wait()
        raise ValueError("专用 Edge 启动超时，请运行浏览器启动脚本")
    if process.returncode:
        raise ValueError("专用 Edge 启动失败，请运行浏览器启动脚本")
    for attempt in range(12):
        if (await run_worker({"operation": "probe", "cdp_port": port}))["connected"]:
            return
        await asyncio.sleep(0.5)
    raise ValueError("未连接到重新打开的专用 Edge，请确认窗口已启动")

def cleanup():
    cutoff = time.time() - 3600
    for key in list(imports):
        if imports[key]["created"] < cutoff and (key not in tasks or tasks[key].done()):
            imports.pop(key, None)
            tasks.pop(key, None)

def safe_import_input(data,configs):
    values=data.model_dump(mode="json")
    # Raw administrator URLs may contain a key. Keep only normalized IDs.
    if isinstance(data,ZhouOJImportInput):values["contests"]=",".join(c["task_id"] for c in configs)
    elif values.get("csp_contests"):values["csp_contests"]=[c["task_id"] for c in configs if c.get("platform")=="csp_exam"]
    return values

def start(data: ACGOImportInput | ZhouOJImportInput):
    cleanup()
    if sum(not task.done() for task in tasks.values()) >= 3:
        raise ValueError("已有导入任务，请等待当前任务完成")
    configs = task_configs(data, student_id=data.student_id, start_date=data.start_date, end_date=data.end_date)
    ident = uuid.uuid4().hex
    imports[ident] = {"id": ident, "student_id": data.student_id, "status": "running", "progress": "等待浏览器采集",
                      "result": None, "error": None, "created": time.time(), "input": safe_import_input(data,configs)}
    async def work():
        try:
            async with queue:
                result = await collect_tasks(configs, lambda message: imports[ident].update(progress=message))
                imports[ident].update(status="completed", progress="采集完成，请选择题目导入表单", result=result)
        except asyncio.CancelledError:
            imports[ident].update(status="cancelled", progress="导入已取消")
            raise
        except Exception as exc:
            message = str(exc)[:500] if isinstance(exc, ValueError) else "采集结果未通过校验，请重试或检查平台接口变化"
            imports[ident].update(status="failed", progress="采集未完成", error=message)
    tasks[ident] = asyncio.create_task(work())
    return imports[ident]

async def shutdown():
    for task in tasks.values():
        task.cancel()
    await asyncio.gather(*tasks.values(), return_exceptions=True)

async def forget_student(student_id: str):
    identifiers = [key for key, item in imports.items() if item["student_id"] == student_id]
    running = [tasks[key] for key in identifiers if key in tasks and not tasks[key].done()]
    for task in running:
        task.cancel()
    await asyncio.gather(*running, return_exceptions=True)
    for key in identifiers:
        imports.pop(key, None)
        tasks.pop(key, None)

def archive_student(data):
    if data.student_id:
        student=db.student(data.student_id)
        if not student or student["name"]!=data.name.strip():raise ValueError("选用学生档案与姓名不一致，请核对")
        if data.user_id and student["profile"].get("acgo_user_id") and student["profile"]["acgo_user_id"]!=data.user_id:
            raise ValueError("学生档案与 ACGO ID 不一致，请核对")
        return student
    matched = [s for s in db.students() if (s["profile"].get("acgo_user_id") == data.user_id if data.user_id else s["name"]==data.name.strip())]
    if len(matched) > 1:
        raise ValueError("多个档案使用此 ACGO ID，请先在学生档案中核对" if data.user_id else "存在同名学生档案，请先选择已有档案核对")
    if matched and matched[0]["name"] != data.name.strip():
        raise ValueError("学生姓名与该 ACGO ID 的已有档案不一致，请先核对姓名")
    return matched[0] if matched else None

def start_archive(data: ACGOArchiveInput):
    cleanup()
    if sum(not task.done() for task in tasks.values()) >= 3:
        raise ValueError("已有导入任务，请等待当前任务完成")
    student = archive_student(data)
    from datetime import date, datetime
    from zoneinfo import ZoneInfo
    start = data.start_date or date(2010, 1, 1)
    end = data.end_date or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    configs = task_configs(data, student_id=student["id"] if student else "pending", start_date=start, end_date=end)
    ident = uuid.uuid4().hex
    imports[ident] = {"id":ident,"student_id":student["id"] if student else None,"status":"running","progress":"等待采集并生成做题档案",
        "result":None,"error":None,"created":time.time(),"input":safe_import_input(data,configs)}
    async def work():
        try:
            async with queue:
                merged = await collect_tasks(configs, lambda message: imports[ident].update(progress=message))
                problems = merged["problems"]
                if not problems:
                    raise ValueError("所选任务没有可读取题面，未创建空档案，请核对任务与权限")
                dates=sorted(datetime.fromisoformat(s["submitted_at"].replace("Z","+00:00")).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat() for p in problems for s in p["submissions"])
                if not dates and not data.start_date:
                    raise ValueError("这些任务没有可靠提交日期，请填写起止日期；未提交题目仍可纳入档案")
                period_start=data.start_date.isoformat() if data.start_date else dates[0]
                period_end=data.end_date.isoformat() if data.end_date else dates[-1]
                for p in problems:
                    p["source"]["period_start"],p["source"]["period_end"]=period_start,period_end
                content={"start_date":period_start,"end_date":period_end,"problems":problems,
                    "warnings":merged["warnings"],"failed_questions":merged["failed_questions"],"failed_tasks":merged["failed_tasks"],"tasks":merged["tasks"]}
                resolved=archive_student(data)
                if not resolved:
                    resolved=db.save_student(StudentInput(name=data.name.strip(),age=data.age,grade=data.grade,acgo_user_id=data.user_id).model_dump())
                archive=db.save_practice_archive(resolved["id"],content)
                imports[ident].update(student_id=resolved["id"],status="completed",progress="做题档案已自动保存",result={"archive_id":archive["id"],"student_id":resolved["id"],"start_date":period_start,"end_date":period_end,
                    "problem_count":len(problems),"unsubmitted_count":sum(p["submission_state"]!="submitted" for p in problems),"task_count":len(content["tasks"]),"submission_count":sum(len(p["submissions"]) for p in problems),"warnings":content["warnings"],"failed_questions":content["failed_questions"]})
        except asyncio.CancelledError:
            imports[ident].update(status="cancelled",progress="导入已取消")
            raise
        except Exception as exc:
            imports[ident].update(status="failed",progress="做题档案生成未完成",error=str(exc)[:500] if isinstance(exc,ValueError) else "采集或存档未通过校验，请检查平台接口或重试")
    tasks[ident]=asyncio.create_task(work())
    return imports[ident]
