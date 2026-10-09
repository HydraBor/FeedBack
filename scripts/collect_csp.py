"""Archive the publicly exposed statement/editorial API. Collected material is NOT auto-reviewed."""
import concurrent.futures
import hashlib
import json
import sys
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import knowledge, db
from backend.library_audit import is_reviewed, fingerprint

HOST = "https://www.cspfirstround.com"
RAW = knowledge.PUBLIC / "raw"
SOURCE_TAGS = {
    "枚举与模拟": ["K001", "K002"], "排序算法": ["K003"], "二分查找与二分答案": ["K004"],
    "前缀和与差分": ["K005", "K006"], "搜索与图遍历（DFS/BFS）": ["K008", "K009"],
    "贪心算法": ["K010"], "动态规划": ["K011"], "图论算法": ["K017"], "树上的问题": ["K021"],
    "表达式求值": ["K024"], "线段树与ST表": ["K029"], "初等数学": ["K031"],
    "组合计数": ["K033", "K045"], "位运算与进制": ["K034"], "字符串算法": ["K035"], "哈希表": ["K036"]
}

def get(url):
    response = httpx.get(url, timeout=25, follow_redirects=False)
    response.raise_for_status()
    return response

def main():
    RAW.mkdir(exist_ok=True)
    tasks = knowledge.problems()
    originals = {p["id"]:fingerprint(p) for p in tasks}
    dictionary = knowledge.topics()["items"]
    index = get(HOST + "/app/data/round2-editorials/index.json").json()
    entries = {(r["year"], r["group"], r["title"]): r for r in index["problems"]}
    def collect(task):
        if is_reviewed(task):
            return task["id"], task, "保留已审核版本"
        entry = entries.get((task["year"], task["track"].lower(), task["title"]))
        # A spelling mismatch must be reviewed; do not infer a match from position.
        if entry is None:
            return task["id"], None, "源索引题名未匹配"
        url = HOST + f"/api/round2/problems/{entry['slug']}?year={entry['year']}&group={entry['group']}"
        try:
            body = get(url).json()
            editorial = get(HOST + entry["explanationFile"])
            if hashlib.sha256(editorial.content).hexdigest() != entry["explanationSha256"]:
                raise ValueError("题解 SHA256 与来源索引不符")
            if body["title"] != task["title"] or not body["statement"].strip():
                raise ValueError("题面标题或正文不匹配")
            snapshot = {"statement": body, "editorial_metadata": entry, "retrieved_at": db.now(), "source": url}
            (RAW / f"{task['id']}.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
            (RAW / f"{task['id']}.md").write_bytes(editorial.content)
            ids = [t["id"] for t in dictionary if any(t["name"] == s or t.get("label") == s for s in body.get("topics", []))]
            for tag in body.get("topics", []):
                ids.extend(SOURCE_TAGS.get(tag, []))
            ids = sorted(set(ids))
            updated = {**task, "statement": body["statement"], "editorial": editorial.text,
                "source": body["seo"]["url"], "editorial_source": HOST + entry["explanationFile"], "topic_ids": ids,
                "statement_sha256": hashlib.sha256(body["statement"].encode()).hexdigest(), "editorial_sha256": entry["explanationSha256"],
                "editorial_provenance": entry.get("generation", {}), "source_verification": entry.get("programVerification", {}),
                "scoring_note": body.get("scoringNote", ""), "time_ms": body.get("timeLimitMs"), "memory_mb": body.get("memoryLimitMb"),
                "samples": body.get("samples", []), "retrieved_at": db.now(), "status": "collected", "review_metadata":{"status":"invalidated"},
                "license": "源站整理资料，第三方题解包含模型生成内容；保存于本机待审核。原题权利归CCF，2025题目和数据按官方CC BY-NC声明；其他年度待核实。"}
            return task["id"], updated, "已收录，待审核"
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            return task["id"], None, str(exc)[:200]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for pid, result, status in pool.map(collect, tasks):
            results.append({"id": pid, "status": status})
            if result:
                tasks[next(i for i, p in enumerate(tasks) if p["id"] == pid)] = result
            print(pid, status, flush=True)
    with knowledge.problem_write_lock():
        current=knowledge.problems()
        collected={p["id"]:p for p in tasks}
        for i,task in enumerate(current):
            if fingerprint(task)==originals.get(task["id"]):current[i]=collected[task["id"]]
        path = knowledge.PUBLIC / "problems.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    (knowledge.PUBLIC / "collection_manifest.json").write_text(json.dumps({"date": db.now(), "source": HOST, "results": results, "policy": "收集与审核分离；原始内容哈希与来源记录保留"}, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__": main()
