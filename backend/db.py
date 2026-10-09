import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo
from .config import DATA

DATABASE = DATA / "feedback.sqlite3"

def now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")

@contextmanager
def connection():
    conn = sqlite3.connect(DATABASE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS students (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, profile TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS student_name ON students(name);
        CREATE TABLE IF NOT EXISTS feedbacks (
            id TEXT PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            input TEXT NOT NULL, student_snapshot TEXT NOT NULL, status TEXT NOT NULL,
            stage TEXT NOT NULL, stages TEXT NOT NULL DEFAULT '{}', analysis TEXT,
            draft TEXT, revision INTEGER NOT NULL DEFAULT 0, error TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS student_feedback ON feedbacks(student_id, created_at);
        CREATE TABLE IF NOT EXISTS versions (
            id TEXT PRIMARY KEY, feedback_id TEXT NOT NULL REFERENCES feedbacks(id) ON DELETE CASCADE,
            revision INTEGER NOT NULL, content TEXT NOT NULL, metadata TEXT NOT NULL,
            pdf_path TEXT, created_at TEXT NOT NULL, UNIQUE(feedback_id, revision)
        );
        CREATE TABLE IF NOT EXISTS practice_archives (
            id TEXT PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            start_date TEXT NOT NULL, end_date TEXT NOT NULL, content TEXT NOT NULL,
            content_hash TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(student_id,content_hash)
        );
        ''')
        conn.execute("UPDATE feedbacks SET status='failed', error='上次运行中断，可恢复分析', stage='等待恢复' WHERE status='running'")

def unpack(row):
    if row is None:
        return None
    result = dict(row)
    for key in ("profile", "input", "student_snapshot", "stages", "analysis", "draft", "content", "metadata"):
        if key in result and result[key] is not None:
            result[key] = json.loads(result[key])
    return result

def student(sid):
    with connection() as conn:
        return unpack(conn.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone())

def students(query=""):
    with connection() as conn:
        rows = conn.execute("SELECT s.*, (SELECT COUNT(*) FROM feedbacks f WHERE f.student_id=s.id) AS report_count FROM students s WHERE instr(s.name,?)>0 ORDER BY s.updated_at DESC", (query,)).fetchall()
    return [unpack(r) for r in rows]

def save_student(profile, sid=None):
    sid = sid or str(uuid4())
    with connection() as conn:
        if conn.execute("SELECT id FROM students WHERE id=?", (sid,)).fetchone():
            conn.execute("UPDATE students SET name=?,profile=?,updated_at=? WHERE id=?", (profile["name"], json.dumps(profile, ensure_ascii=False), now(), sid))
        else:
            conn.execute("INSERT INTO students VALUES(?,?,?,?,?)", (sid, profile["name"], json.dumps(profile, ensure_ascii=False), now(), now()))
    return student(sid)

def feedback(fid):
    with connection() as conn:
        return unpack(conn.execute("SELECT * FROM feedbacks WHERE id=?", (fid,)).fetchone())

def list_feedbacks(sid=None):
    with connection() as conn:
        rows = conn.execute("SELECT f.*,s.name FROM feedbacks f JOIN students s ON s.id=f.student_id WHERE (? IS NULL OR f.student_id=?) ORDER BY f.created_at DESC", (sid, sid)).fetchall()
    return [unpack(r) for r in rows]

def create_feedback(payload):
    entry = student(payload["student_id"])
    if entry is None:
        raise ValueError("学生档案不存在")
    fid = str(uuid4())
    with connection() as conn:
        conn.execute("INSERT INTO feedbacks(id,student_id,input,student_snapshot,status,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (fid, entry["id"], json.dumps(payload, ensure_ascii=False), json.dumps(entry["profile"], ensure_ascii=False), "draft", "材料已保存", now(), now()))
    return feedback(fid)

def update_feedback(fid, **values):
    allowed = {"status", "stage", "stages", "analysis", "draft", "revision", "error"}
    if not values or not set(values) <= allowed:
        raise ValueError("Invalid update fields")
    values["updated_at"] = now()
    args = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in values.values()]
    with connection() as conn:
        conn.execute("UPDATE feedbacks SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?", (*args, fid))

def save_materials(fid, expected, payload):
    with connection() as conn:
        row = conn.execute("SELECT student_id,status,revision,stages FROM feedbacks WHERE id=?", (fid,)).fetchone()
        if not row or row["revision"] != expected:
            raise ValueError("材料已更新，请刷新后再保存")
        if row["status"] != "draft" or json.loads(row["stages"]):
            raise ValueError("分析已开始，修改成果请新建反馈，保留原始依据")
        if row["student_id"] != payload["student_id"]:
            raise ValueError("已保存反馈不能更换学生档案")
        changed = conn.execute("UPDATE feedbacks SET input=?,revision=revision+1,updated_at=? WHERE id=? AND status='draft' AND revision=?",
            (json.dumps(payload, ensure_ascii=False), now(), fid, expected))
        if changed.rowcount != 1:
            raise ValueError("材料状态已变化，请刷新后再保存")
    return feedback(fid)

def save_practice_archive(sid, content):
    import hashlib
    from copy import deepcopy
    stable = deepcopy(content)
    for problem in stable["problems"]:
        if problem.get("source"):
            problem["source"].pop("fetched_at", None)
    digest = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    with connection() as conn:
        previous = conn.execute("SELECT id FROM practice_archives WHERE student_id=? AND content_hash=?", (sid,digest)).fetchone()
        ident = previous["id"] if previous else str(uuid4())
        if not previous:
            conn.execute("INSERT INTO practice_archives VALUES(?,?,?,?,?,?,?)", (ident,sid,content["start_date"],content["end_date"],json.dumps(content,ensure_ascii=False),digest,now()))
    return practice_archive(ident)

def practice_archive(ident):
    with connection() as conn:
        return unpack(conn.execute("SELECT p.*,s.name FROM practice_archives p JOIN students s ON p.student_id=s.id WHERE p.id=?",(ident,)).fetchone())

def practice_archives(sid=None):
    with connection() as conn:
        rows = conn.execute("SELECT p.*,s.name FROM practice_archives p JOIN students s ON p.student_id=s.id WHERE (? IS NULL OR p.student_id=?) ORDER BY p.created_at DESC",(sid,sid)).fetchall()
    return [{"id":a["id"],"student_id":a["student_id"],"name":a["name"],"start_date":a["start_date"],"end_date":a["end_date"],"created_at":a["created_at"],
             "problem_count":len(a["content"]["problems"]),"submission_count":sum(len(p["submissions"]) for p in a["content"]["problems"])} for a in map(unpack,rows)]

def history(sid, before, exclude):
    # Only earlier periods; the fixed history snapshot is cached with the generation.
    entries = list_feedbacks(sid)
    with connection() as conn:
        confirmed = {r["feedback_id"] for r in conn.execute("SELECT DISTINCT v.feedback_id FROM versions v JOIN feedbacks f ON f.id=v.feedback_id WHERE f.student_id=?", (sid,))}
    return [{"id": f["id"], "input": f["input"], "student_snapshot": f["student_snapshot"], "status": "confirmed",
             "confirmed_report": versions(f["id"])[0]["content"]}
            for f in entries if f["id"] != exclude and f["input"]["end_date"] < before and f["input"]["mode"] == "live" and f["id"] in confirmed][:8]

def versions(fid):
    with connection() as conn:
        return [unpack(r) for r in conn.execute("SELECT * FROM versions WHERE feedback_id=? ORDER BY revision DESC", (fid,)).fetchall()]

def save_review(fid, expected, content, metadata, confirm):
    with connection() as conn:
        row = conn.execute("SELECT revision,status FROM feedbacks WHERE id=?", (fid,)).fetchone()
        if row is None or row["revision"] != expected:
            raise ValueError("内容已更新，请刷新后再保存")
        if row["status"] == "running":
            raise ValueError("分析中不能修改报告")
        revision = expected + 1
        raw = json.dumps(content, ensure_ascii=False)
        conn.execute("UPDATE feedbacks SET draft=?,revision=?,status=?,updated_at=? WHERE id=?", (raw, revision, "confirmed" if confirm else "review", now(), fid))
        if confirm:
            conn.execute("INSERT INTO versions VALUES(?,?,?,?,?,?,?)", (str(uuid4()), fid, revision, raw, json.dumps(metadata, ensure_ascii=False), None, now()))
    return feedback(fid)
