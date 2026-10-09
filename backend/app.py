import asyncio
import math
import hashlib
import io
import json
import sqlite3
import tempfile
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from . import db, knowledge, acgo, practice, csp_exam
from .config import ROOT, DATA, settings, save_settings, ADMISSIONS_ENABLED
from .models import StudentInput, FeedbackInput, ReviewInput, SettingsInput, ACGOImportInput, MaterialsEdit, ACGOArchiveInput, ZhouOJImportInput
from .pipeline import generate, rewrite_parent_copy
from .provider import DeepSeek
from .report import render, save_version
from .validation import evidence_ids, validate_scores, validate_parent
from .library_audit import is_reviewed, fingerprint

jobs = {}
queue = asyncio.Semaphore(2)

@asynccontextmanager
async def lifespan(app):
    db.init_db()
    yield
    await acgo.shutdown()
    for task in jobs.values():
        task.cancel()
    await asyncio.gather(*jobs.values(), return_exceptions=True)

app = FastAPI(title="成长反馈 · CSP", lifespan=lifespan)

@app.middleware("http")
async def local_only(request: Request, call_next):
    host = urlparse("http://" + request.headers.get("host", "")).hostname
    if host not in ("localhost", "127.0.0.1", "::1"):
        return Response("仅允许通过本机地址访问", status_code=403)
    origin = request.headers.get("origin")
    if origin and (urlparse(origin).hostname not in ("localhost", "127.0.0.1", "::1") or urlparse(origin).netloc != request.headers.get("host")):
        return Response("禁止跨站访问本地学生资料", status_code=403)
    if request.headers.get("sec-fetch-site") == "cross-site":
        return Response("禁止跨站访问", status_code=403)
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.headers.get("content-type", "").split(";")[0] != "application/json":
        return Response("请使用 JSON 请求", status_code=415)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response

@app.exception_handler(ValueError)
async def invalid(request, exc):
    return Response(json.dumps({"detail": str(exc)}, ensure_ascii=False), status_code=400, media_type="application/json")

def require_feedback(fid, current=False):
    entry = db.feedback(fid)
    if not entry:
        raise HTTPException(404, "反馈不存在")
    if current and entry["superseded_by"]:
        raise ValueError("这份旧稿已合并，请打开本期当前报告")
    return entry

@app.get("/api/health")
async def health():
    return {"status": "ok", "api_configured": bool(settings()["api_key"]), "assessment_mode":"oj_records_and_code_analysis",
        "timezone": "Asia/Shanghai", "reference_papers": len(knowledge.references(["J", "S"]))}

@app.get("/api/students")
def students(q: str = ""):
    return db.students(q[:100])

@app.get("/api/acgo/status")
async def acgo_status():
    return await acgo.status()

@app.get("/api/zhou-oj/connection")
def csp_connection():return csp_exam.public_connection()

@app.put("/api/zhou-oj/connection")
def csp_connect(data:dict):return csp_exam.save_connection(data)

@app.post("/api/zhou-oj/imports")
async def zhou_import(data:ZhouOJImportInput):
    if not db.student(data.student_id):raise HTTPException(404,"请先选择或建立学生档案")
    return acgo.start(data)

@app.get("/api/zhou-oj/imports/{ident}")
async def zhou_import_status(ident:str):return await acgo_import_result(ident)

@app.delete("/api/zhou-oj/imports/{ident}")
async def zhou_import_cancel(ident:str,data:dict):return await acgo_cancel(ident,data)

@app.post("/api/acgo/imports")
async def acgo_import(data: ACGOImportInput):
    student = db.student(data.student_id)
    if not student:
        raise HTTPException(404, "请先选择或建立学生档案")
    known = student["profile"].get("acgo_user_id")
    if known and known != data.user_id:
        raise ValueError("ACGO 学生 ID 与档案记录不一致，请先核对并修改档案")
    return acgo.start(data)

@app.post("/api/practice-archives/imports")
async def acgo_archive(data: ACGOArchiveInput):
    return acgo.start_archive(data)

@app.get("/api/practice-archives")
def practice_archives(student_id: str | None = None):
    return db.practice_archives(student_id)

@app.get("/api/practice-archives/{ident}")
def practice_archive(ident: str):
    entry=db.practice_archive(ident)
    if not entry:
        raise HTTPException(404,"做题档案不存在")
    return entry

@app.get("/api/acgo/imports/{ident}")
@app.get("/api/practice-archives/imports/{ident}")
async def acgo_import_result(ident: str):
    acgo.cleanup()
    if ident not in acgo.imports:
        raise HTTPException(404, "导入预览已过期，请重新采集")
    return acgo.imports[ident]

@app.delete("/api/acgo/imports/{ident}")
@app.delete("/api/practice-archives/imports/{ident}")
async def acgo_cancel(ident: str, data: dict):
    if ident not in acgo.imports:
        raise HTTPException(404, "导入任务不存在")
    if ident in acgo.tasks and not acgo.tasks[ident].done():
        acgo.tasks[ident].cancel()
        await asyncio.gather(acgo.tasks[ident], return_exceptions=True)
    acgo.imports.pop(ident, None)
    acgo.tasks.pop(ident, None)
    return {"deleted": True}

@app.post("/api/students")
def create_student(data: StudentInput):
    return db.save_student(data.model_dump())

@app.put("/api/students/{sid}")
def update_student(sid: str, data: StudentInput):
    if not db.student(sid):
        raise HTTPException(404, "学生不存在")
    return db.save_student(data.model_dump(), sid)

@app.delete("/api/students/{sid}")
async def delete_student(sid: str, data: dict):
    student = db.student(sid)
    if not student:
        raise HTTPException(404, "学生不存在")
    if data.get("confirm_name") != student["name"]:
        raise ValueError("请输入完整姓名确认删除")
    entries = db.list_feedbacks(sid, include_replaced=True)
    if any(f["id"] in jobs and not jobs[f["id"]].done() for f in entries):
        raise ValueError("请等分析完成后再删除")
    await acgo.forget_student(sid)
    paths = [DATA / folder / f"{v['id']}.{suffix}" for f in entries for v in db.versions(f["id"]) for folder,suffix in (("pdf","pdf"),("html","html"))]
    with db.connection() as conn:
        conn.execute("DELETE FROM students WHERE id=?", (sid,))
    for path in paths:
        path.unlink(missing_ok=True)
    return {"deleted": True}

@app.get("/api/reports")
def reports(student_id: str | None = None):
    return [{k: v for k, v in f.items() if k not in ("stages", "analysis", "draft", "input", "student_snapshot")} | {"period": f["input"]["start_date"] + " — " + f["input"]["end_date"], "mode": f["input"]["mode"], "tracks": f["input"]["tracks"]} for f in db.list_feedbacks(student_id)]

@app.post("/api/reports")
def create_report(data: FeedbackInput):
    prepare_materials(data)
    return db.create_feedback(data.model_dump(mode="json"))

def prepare_materials(data: FeedbackInput):
    student = db.student(data.student_id)
    if not student:
        raise HTTPException(404, "学生档案不存在")
    known_acgo = student["profile"].get("acgo_user_id")
    if known_acgo and any(p.source and p.source.platform=="acgo" and p.source.user_id != known_acgo for p in data.problems):
        raise ValueError("导入作品的 ACGO 学生 ID 与档案不匹配")
    for problem in data.problems:
        if problem.source and problem.source.practice_archive_id:
            archive=db.practice_archive(problem.source.practice_archive_id)
            if not archive or archive["student_id"]!=data.student_id:
                raise ValueError("做题档案来源与当前学生不匹配")
    if data.target_year < data.reference_date.year:
        raise ValueError("目标年份不能早于资料基准年份")
    event = knowledge.event(data.target_year)
    if event and data.reference_date.isoformat() > event["second_date"]:
        raise ValueError("目标 CSP 已结束，请选择下一目标年份")
    catalogue = {p["id"]: p for p in knowledge.problems()}
    for problem in data.problems:
        if not problem.statement.strip() and problem.problem_id in catalogue:
            problem.statement = catalogue[problem.problem_id]["statement"]

@app.put("/api/reports/{fid}/input")
def edit_materials(fid: str, data: MaterialsEdit):
    require_feedback(fid, current=True)
    prepare_materials(data.input)
    return db.save_materials(fid, data.revision, data.input.model_dump(mode="json"))

@app.get("/api/reports/{fid}")
def report_detail(fid: str):
    entry = require_feedback(fid)
    entry["versions"] = db.versions(fid)
    if entry["draft"]:
        entry["warnings"] = validate_parent(entry["draft"], entry["input"])
    return entry

@app.post("/api/reports/{fid}/generate")
async def analyze(fid: str, data: dict):
    entry = require_feedback(fid, current=True)
    if fid in jobs and not jobs[fid].done():
        return {"status": "running"}
    if entry["status"] not in ("draft", "failed"):
        raise ValueError("分析已完成；需要重新评估请先修改本期材料，或只更新建议与文案")
    if entry["input"]["mode"] == "live" and not settings()["api_key"]:
        raise ValueError("请先在设置中填写 DeepSeek API 密钥，或新建明确标注的演示反馈")
    db.start_job(fid, entry["revision"], "等待分析任务")
    async def work():
        async with queue:
            await generate(fid)
    jobs[fid] = asyncio.create_task(work())
    return {"status": "running"}

@app.put("/api/reports/{fid}/review")
def review(fid: str, data: ReviewInput, confirm: bool = False):
    entry = require_feedback(fid, current=True)
    if not entry["draft"]:
        raise ValueError("尚无可审核报告")
    content = data.report.model_dump()
    allowed = evidence_ids(entry["input"], entry["stages"].get("history_snapshot", []), entry["student_snapshot"]) | {"teacher:review"}
    for field in ("topic_scores", "abilities"):
        previous = {s["id"]: s for s in entry["draft"][field]}
        for score in content[field]:
            if score["id"] in previous and score["score"] != previous[score["id"]]["score"]:
                score["evidence"] = list(dict.fromkeys([*score["evidence"], "teacher:review"]))
                if field == "abilities":
                    score["source"] = "teacher"
    focus = next((a["score"] for a in content["abilities"] if a["id"] == "A06"), None)
    validate_scores(content["topic_scores"], content["abilities"], allowed, focus)
    original_ids = {s["id"] for s in entry["analysis"]["scoring"]["topic_scores"]}
    if {s["id"] for s in content["topic_scores"]} != original_ids:
        raise ValueError("审核可调整评分，请保留本期已分析的知识标签")
    sources = entry["analysis"]["admissions"]["sources"]
    if content["admissions_sources"] != sources:
        raise ValueError("政策来源必须保留已核实的官方引用")
    practice.validate_recommendations(content, entry["stages"].get("collections_snapshot"))
    warnings = validate_parent(content, entry["input"])
    overrides = [k for k in content if content[k] != entry["analysis"].get("scoring", {}).get(k, entry["draft"].get(k))]
    result = db.save_review(fid, data.revision, content,
        {"versions": entry["analysis"]["versions"], "teacher_adjusted_fields": overrides, "confirmed_at": db.now(), "demo": entry["input"]["mode"] == "demo"}, confirm)
    result["versions"] = db.versions(fid)
    if confirm:
        version = result["versions"][0]
        snapshot = DATA / "html" / f"{version['id']}.html"
        snapshot.parent.mkdir(mode=0o700, exist_ok=True)
        snapshot.write_text(render(entry, version["content"], version["revision"]), encoding="utf-8")
        snapshot.chmod(0o600)
    result["warnings"] = warnings
    return result

@app.post("/api/reports/{fid}/rewrite")
async def rewrite_report(fid: str, data: dict):
    entry = require_feedback(fid, current=True)
    if fid in jobs and not jobs[fid].done():
        return {"status": "running"}
    if not entry["draft"] or not entry["analysis"] or entry["input"]["mode"] != "live":
        raise ValueError("请先完成真实材料分析，再更新文案与建议")
    refresh_training = data.get("refresh_training", True)
    if type(refresh_training) is not bool:
        raise ValueError("refresh_training 请使用布尔值")
    db.start_job(fid, entry["revision"], "等待更新文案与建议")
    async def work():
        async with queue:
            await rewrite_parent_copy(fid, refresh_training)
    jobs[fid] = asyncio.create_task(work())
    return {"status": "running"}

@app.get("/api/reports/{fid}/preview", response_class=HTMLResponse)
def preview(fid: str, version_id: str | None = None):
    entry = require_feedback(fid)
    if version_id:
        version = next((v for v in db.versions(fid) if v["id"] == version_id), None)
        if not version:
            raise HTTPException(404, "确认版本不存在")
        snapshot = DATA / "html" / f"{version['id']}.html"
        return snapshot.read_text(encoding="utf-8") if snapshot.exists() else render(db.version_context(entry,version), version["content"], version["revision"])
    if not entry["draft"]:
        raise ValueError("请先完成分析")
    return render(entry, entry["draft"])

@app.post("/api/reports/{fid}/preview", response_class=HTMLResponse)
def preview_edits(fid: str, data: ReviewInput):
    entry = require_feedback(fid)
    content = data.report.model_dump()
    validate_parent(content, entry["input"])
    return render(entry, content)

@app.get("/api/reports/{fid}/versions/{vid}/pdf")
async def download_pdf(fid: str, vid: str):
    entry = require_feedback(fid)
    version = next((v for v in db.versions(fid) if v["id"] == vid), None)
    if not version:
        raise HTTPException(404, "确认版本不存在")
    try:
        path = await save_version(db.version_context(entry,version), version)
    except Exception:
        raise HTTPException(503, "PDF 渲染失败；请检查 Chromium 运行依赖。已确认文字仍保留，可重试下载。")
    with db.connection() as conn:
        conn.execute("UPDATE versions SET pdf_path=? WHERE id=?", (path.name, vid))
    return FileResponse(path, media_type="application/pdf", filename=f"{entry['student_snapshot']['name']}_学习反馈_v{version['revision']}.pdf")

@app.get("/api/settings")
def read_settings():
    config = settings()
    return {"configured": bool(config["api_key"]), "base_url": config["base_url"], "model": config["model"], "max_calls": config["max_calls"], "analysis_concurrency":config["analysis_concurrency"]}

@app.put("/api/settings")
def update_settings(data: SettingsInput):
    values = data.model_dump(exclude_none=True)
    if "base_url" in values and values["base_url"].rstrip("/") != "https://api.deepseek.com":
        raise ValueError("首版仅支持 DeepSeek 官方 API 地址")
    save_settings(values)
    return read_settings()

@app.post("/api/settings/test")
async def test_settings(data: dict):
    from pydantic import BaseModel
    class Ping(BaseModel):
        message: str
    try:
        result = await DeepSeek().generate("用JSON返回message字段，内容为连接成功。", {}, Ping)
    except (ValueError, RuntimeError) as exc:
        raise ValueError(str(exc))
    return {"message": result["message"]}

@app.get("/api/library")
def library():
    tasks = knowledge.problems()
    return {"practice_collections": practice.catalogue(), "topics": knowledge.topics(), "problems": tasks, "rules": knowledge.rules(), "abilities": knowledge.ABILITIES,
        "features": {"admissions_enabled": ADMISSIONS_ENABLED},
                "stats": {"catalogue": len(tasks), "statements": sum(bool(p["statement"]) for p in tasks), "editorials": sum(bool(p["editorial"]) for p in tasks),
            "reviewed": sum(is_reviewed(p) for p in tasks), "ai_reviewed":sum(is_reviewed(p) and p.get("review_metadata",{}).get("kind")=="ai" for p in tasks), "released":bool(tasks) and all(is_reviewed(p) for p in tasks), "reference_papers": len(knowledge.references(["J", "S"]))}}

@app.put("/api/library/problems/{pid}")
def edit_problem(pid: str, data: dict):
    with knowledge.problem_write_lock():
        _edit_problem(pid, data)
    return library()

def _edit_problem(pid: str, data: dict):
    tasks = knowledge.problems()
    task = next((p for p in tasks if p["id"] == pid), None)
    if not task:
        raise HTTPException(404, "题目目录不存在")
    allowed = {"statement", "editorial", "topic_ids", "subtasks", "status", "source", "editorial_source", "license", "review_confirmed"}
    if not set(data) <= allowed:
        raise ValueError("包含不可修改字段")
    patch = {k:v for k,v in data.items() if k != "review_confirmed"}
    if "review_confirmed" in data and type(data["review_confirmed"]) is not bool:
        raise ValueError("审核确认请使用布尔值")
    updated = {**task, **patch}
    if updated["status"] not in ("catalogue", "collected", "reviewed"):
        raise ValueError("资料状态无效")
    for field in ("statement", "editorial"):
        if not isinstance(updated[field], str) or len(updated[field]) > 100000:
            raise ValueError("题面或题解过长")
    if not isinstance(updated["topic_ids"],list) or any(not isinstance(t,str) for t in updated["topic_ids"]) or len(set(updated["topic_ids"])) != len(updated["topic_ids"]):
        raise ValueError("知识标签必须是无重复的编号数组")
    if not set(updated["topic_ids"]) <= {t["id"] for t in knowledge.topics()["items"]}:
        raise ValueError("知识标签不在词表中")
    for field in ("source", "editorial_source"):
        if not isinstance(updated.get(field,""),str) or (updated.get(field) and (urlparse(updated[field]).scheme != "https" or not urlparse(updated[field]).hostname or urlparse(updated[field]).username or urlparse(updated[field]).password)):
            raise ValueError("来源请使用完整 https 地址")
    if updated["status"] == "reviewed" and (not updated["statement"].strip() or not updated["editorial"].strip() or not updated["topic_ids"] or not updated.get("editorial_source")):
        raise ValueError("审核入库需题面、题解、知识标签及题解来源齐全")
    if not isinstance(updated["subtasks"], list) or len(updated["subtasks"]) > 30:
        raise ValueError("子任务格式无效")
    if not isinstance(updated.get("license"),str) or len(updated["license"]) > 5000:
        raise ValueError("使用范围说明格式无效")
    if updated["subtasks"]:
        try:
            if any(not isinstance(item,dict) or type(item.get("score")) not in (int,float) or not math.isfinite(item["score"]) or item["score"] <= 0 for item in updated["subtasks"]):
                raise ValueError("子任务需包含正数 score 分值与范围说明")
            if not math.isclose(sum(item["score"] for item in updated["subtasks"]),updated["max_score"],abs_tol=1e-8):
                raise ValueError("子任务分数之和必须等于题目总分")
        except (KeyError,TypeError,OverflowError):
            raise ValueError("子任务需包含 score 分值与范围说明")
    changed=fingerprint(updated) != fingerprint(task)
    if updated["status"] == "reviewed":
        if data.get("review_confirmed"):
            updated["review_metadata"]={"status":"passed","kind":"teacher","fingerprint":fingerprint(updated),"at":db.now()}
        elif changed or not is_reviewed(task):
            updated["status"]="collected"
            updated["review_metadata"]={"status":"invalidated","kind":"teacher","at":db.now()}
    elif changed or updated["status"] != task["status"]:
        updated["review_metadata"]={"status":"invalidated","at":db.now()}
    for field in ("statement", "editorial"):
        updated[field+"_sha256"] = hashlib.sha256(updated[field].encode()).hexdigest()
    tasks[tasks.index(task)] = {**updated, "reviewed_at": updated.get("review_metadata",{}).get("at") if updated["status"] == "reviewed" else None}
    path = knowledge.PUBLIC / "problems.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)

@app.get("/api/backup")
def backup():
    if any(not t.done() for t in (*jobs.values(), *acgo.tasks.values())):
        raise ValueError("请等分析与采集完成后再备份")
    memory = io.BytesIO()
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "feedback.sqlite3"
        with sqlite3.connect(db.DATABASE) as source, sqlite3.connect(target) as dest:
            source.backup(dest)
        with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(target, "feedback.sqlite3")
            for path in (DATA / "pdf").glob("*.pdf"):
                archive.write(path, "pdf/" + path.name)
            for path in (DATA / "html").glob("*.html"):
                archive.write(path, "html/" + path.name)
            archive.writestr("README.txt", "学生档案备份，含代码和反馈。请妥善保管。API密钥不在备份中。恢复请在关闭程序后使用 scripts/restore.py。")
    return Response(memory.getvalue(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="feedback-backup.zip"'})

DIST = ROOT / "frontend/dist"
if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

@app.get("/{path:path}")
def frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "接口不存在")
    index = DIST / "index.html"
    if not index.is_file():
        return HTMLResponse("前端尚未构建，请运行 scripts/setup.sh。", status_code=503)
    return FileResponse(index)
