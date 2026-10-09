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
        if "superseded_by" not in {r["name"] for r in conn.execute("PRAGMA table_info(feedbacks)")}:
            conn.execute("ALTER TABLE feedbacks ADD COLUMN superseded_by TEXT")
        # One current report per student, period and mode; retain replaced rows.
        current = {}
        for row in conn.execute("SELECT id,student_id,input FROM feedbacks WHERE superseded_by IS NULL ORDER BY created_at DESC,rowid DESC").fetchall():
            data = json.loads(row["input"])
            key = (row["student_id"], data["start_date"], data["end_date"], data["mode"])
            if key in current:
                conn.execute("UPDATE feedbacks SET superseded_by=? WHERE id=? OR superseded_by=?", (current[key], row["id"], row["id"]))
            else:
                current[key] = row["id"]
        conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS current_period_report ON feedbacks
            (student_id,json_extract(input,'$.start_date'),json_extract(input,'$.end_date'),json_extract(input,'$.mode'))
            WHERE superseded_by IS NULL""")
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
        rows = conn.execute("SELECT s.*, (SELECT COUNT(*) FROM feedbacks f WHERE f.student_id=s.id AND f.superseded_by IS NULL) AS report_count FROM students s WHERE instr(s.name,?)>0 ORDER BY s.updated_at DESC", (query,)).fetchall()
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

def list_feedbacks(sid=None, include_replaced=False):
    with connection() as conn:
        rows = conn.execute("SELECT f.*,s.name FROM feedbacks f JOIN students s ON s.id=f.student_id WHERE (? IS NULL OR f.student_id=?) AND (? OR f.superseded_by IS NULL) ORDER BY f.created_at DESC", (sid, sid, include_replaced)).fetchall()
    return [unpack(r) for r in rows]

def create_feedback(payload):
    entry = student(payload["student_id"])
    if entry is None:
        raise ValueError("学生档案不存在")
    fid = str(uuid4())
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute("""SELECT * FROM feedbacks WHERE student_id=? AND superseded_by IS NULL
            AND json_extract(input,'$.start_date')=? AND json_extract(input,'$.end_date')=? AND json_extract(input,'$.mode')=?""",
            (entry["id"], payload["start_date"], payload["end_date"], payload["mode"])).fetchone()
        if previous:
            fid = previous["id"]
            if json.loads(previous["input"]) != payload:
                _replace_materials(conn, previous, payload, entry["profile"])
        else:
            conn.execute("INSERT INTO feedbacks(id,student_id,input,student_snapshot,status,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (fid, entry["id"], json.dumps(payload, ensure_ascii=False), json.dumps(entry["profile"], ensure_ascii=False), "draft", "材料已保存", now(), now()))
    return feedback(fid)


def _replace_materials(conn, row, payload, profile):
    if row["superseded_by"]:
        raise ValueError("这份旧稿已合并，请打开本期当前报告")
    if row["status"] == "running":
        raise ValueError("本期报告正在分析或更新文案，请完成后再修改材料")
    # Keep the complete prior material/analysis snapshot outside the report list.
    archived = dict(row)
    archived.update(id=str(uuid4()), superseded_by=row["id"])
    archived["stages"] = json.dumps({**json.loads(row["stages"]),"_material_snapshot_of":row["id"]},ensure_ascii=False)
    conn.execute("INSERT INTO feedbacks("+",".join(archived)+") VALUES("+",".join("?" for _ in archived)+")", tuple(archived.values()))
    conn.execute("""UPDATE feedbacks SET input=?,student_snapshot=?,status='draft',stage='本期材料已更新，等待重新分析',
        stages='{}',analysis=NULL,draft=NULL,error=NULL,revision=revision+1,updated_at=? WHERE id=?""",
        (json.dumps(payload,ensure_ascii=False),json.dumps(profile,ensure_ascii=False),now(),row["id"]))

def update_feedback(fid, **values):
    allowed = {"status", "stage", "stages", "analysis", "draft", "revision", "error"}
    if not values or not set(values) <= allowed:
        raise ValueError("Invalid update fields")
    values["updated_at"] = now()
    args = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in values.values()]
    with connection() as conn:
        conn.execute("UPDATE feedbacks SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?", (*args, fid))


def start_job(fid, expected, stage):
    with connection() as conn:
        changed = conn.execute("""UPDATE feedbacks SET status='running',stage=?,error=NULL,updated_at=?
            WHERE id=? AND revision=? AND superseded_by IS NULL AND status!='running'""", (stage,now(),fid,expected))
        if changed.rowcount != 1:
            raise ValueError("本期报告已更新或正在处理，请刷新后再操作")

def save_materials(fid, expected, payload):
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM feedbacks WHERE id=?", (fid,)).fetchone()
        if not row or row["revision"] != expected:
            raise ValueError("材料已更新，请刷新后再保存")
        if row["student_id"] != payload["student_id"]:
            raise ValueError("已保存反馈不能更换学生档案")
        old = json.loads(row["input"])
        if any(old[key]!=payload[key] for key in ("start_date","end_date","mode")):
            raise ValueError("修改本期报告不能更换学习时段或分析模式；新时段请另建反馈")
        if row["status"] == "running" or row["superseded_by"]:
            raise ValueError("本期报告正在处理或已合并，请刷新后再修改材料")
        profile = json.loads(conn.execute("SELECT profile FROM students WHERE id=?", (row["student_id"],)).fetchone()["profile"])
        if old != payload:
            _replace_materials(conn, row, payload, profile)
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
    result = []
    for entry in entries:
        if entry["id"]==exclude or entry["input"]["end_date"]>=before or entry["input"]["mode"]!="live":
            continue
        confirmed = versions(entry["id"])
        if confirmed:
            context = version_context(entry, confirmed[0])
            result.append({"id":entry["id"],"input":context["input"],"student_snapshot":context["student_snapshot"],
                "status":"confirmed","confirmed_report":confirmed[0]["content"]})
    return result[:8]

def versions(fid):
    with connection() as conn:
        return [unpack(r) for r in conn.execute("""SELECT v.* FROM versions v JOIN feedbacks f ON f.id=v.feedback_id
            WHERE f.id=? OR f.superseded_by=? ORDER BY v.created_at DESC,(f.id=?) DESC,v.revision DESC""", (fid,fid,fid)).fetchall()]


def version_context(entry, version):
    snapshot = version["metadata"].get("material_snapshot")
    if snapshot:
        return {**entry, **snapshot}
    if version["feedback_id"] != entry["id"]:
        return feedback(version["feedback_id"])
    # Older confirmations predate explicit material snapshots.
    with connection() as conn:
        previous = conn.execute("""SELECT * FROM feedbacks WHERE superseded_by=? AND revision>=?
            AND json_extract(stages,'$._material_snapshot_of')=? ORDER BY revision ASC LIMIT 1""",
            (entry["id"],version["revision"],entry["id"])).fetchone()
    return unpack(previous) if previous else entry

def save_review(fid, expected, content, metadata, confirm):
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM feedbacks WHERE id=?", (fid,)).fetchone()
        if row is None or row["revision"] != expected:
            raise ValueError("内容已更新，请刷新后再保存")
        if row["status"] == "running":
            raise ValueError("分析中不能修改报告")
        if row["superseded_by"]:
            raise ValueError("这份旧稿已合并，请打开本期当前报告")
        revision = expected + 1
        raw = json.dumps(content, ensure_ascii=False)
        conn.execute("UPDATE feedbacks SET draft=?,revision=?,status=?,updated_at=? WHERE id=?", (raw, revision, "confirmed" if confirm else "review", now(), fid))
        if confirm:
            metadata = {**metadata,"material_snapshot":{"input":json.loads(row["input"]),"student_snapshot":json.loads(row["student_snapshot"])}}
            conn.execute("INSERT INTO versions VALUES(?,?,?,?,?,?,?)", (str(uuid4()), fid, revision, raw, json.dumps(metadata, ensure_ascii=False), None, now()))
    return feedback(fid)
