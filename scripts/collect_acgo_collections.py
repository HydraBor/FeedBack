"""Refresh the public collections linked by ACGO's learning mind map.

Stores collection descriptions and complete problem membership metadata;
does not download images, student data, solutions, or problem statements.
"""
import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[1]
MAP_URL = "https://gateway.acgo.cn/acgoPms/api/learning-path/getInfo"
INFO_URL = "https://gateway.acgo.cn/acgoPms/api/question/collection/info/"


def get_data(client, url):
    for attempt in range(3):
        response = client.get(url)
        if response.status_code == 429 or response.status_code >= 500:
            if attempt < 2:
                time.sleep(1 + attempt)
                continue
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 200:
            raise ValueError(f"Public ACGO API status {payload.get('code')}")
        return payload["data"]
    raise ValueError("ACGO service unavailable")


def main():
    public = ROOT / "data/public"
    raw = public / "raw/acgo-collections"
    raw.mkdir(parents=True, exist_ok=True)
    taxonomy = json.loads((public / "topics.json").read_text())
    dated = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        mapping = get_data(client, MAP_URL)
        (raw / "learning-map.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2))
        graph = json.loads(mapping["mapJson"]["key"])
        nodes = {str(n["data"]["id"]): n for n in graph["nodes"] if n.get("data", {}).get("id")}
        if any(not ident.isdigit() or len(ident)>30 for ident in nodes):
            raise ValueError("Mind-map collection ID format changed")
        graph_ids = {n["id"]: str(n["data"]["id"]) for n in nodes.values()}
        edges = [{"from": graph_ids[e["source"]], "to": graph_ids[e["target"]]} for e in graph.get("edges", []) if e.get("source") in graph_ids and e.get("target") in graph_ids]
        collections, failures = [], []
        for ident, node in nodes.items():
            try:
                info = get_data(client, INFO_URL + ident)
                if str(info["questionCollectionId"]) != ident:
                    raise ValueError("Collection ID mismatch")
                members = info.get("questionCollections")
                if not isinstance(members, list):
                    raise ValueError("Collection membership format changed")
                seen, questions = set(), []
                for q in members:
                    qid = str(q["questionId"])
                    if not qid.isdigit() or len(qid)>30:
                        raise ValueError("Problem ID format changed")
                    if qid in seen:
                        raise ValueError("Duplicate problem membership")
                    seen.add(qid)
                    questions.append({"id": qid, "title": q["title"], "url": "https://www.acgo.cn/problemset/info/" + qid,
                        "order": q.get("sort"), "difficulty": q.get("difficultyTagTitle", ""),
                        "knowledge": [k["knowledgeTitle"] for k in (q.get("knowledge") or [])]})
                expected = info.get("questionCollectionExtVo", {}).get("questionNum")
                complete = expected == len(questions) and bool(questions)
                tags = list(dict.fromkeys(k for q in questions for k in q["knowledge"] if k != "暂无评定"))
                labels = info["title"] + " " + " ".join(tags)
                topic_ids = [t["id"] for t in taxonomy["items"] if any(alias in labels for alias in t.get("aliases", [t["name"]]) if len(alias) >= 2)]
                description = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", info.get("digest") or "").strip()
                canonical = json.dumps(info, ensure_ascii=False, sort_keys=True)
                (raw / (ident + ".json")).write_text(canonical)
                collections.append({"id": ident, "map_label": node["data"]["label"], "title": info["title"],
                    "url": "https://www.acgo.cn/collection/" + ident, "description": description,
                    "problem_count": len(questions), "expected_count": expected, "questions": questions, "knowledge": tags,
                    "topic_ids": topic_ids, "topic_mapping": "local_alias_match", "ready": complete,
                    "source": INFO_URL + ident, "fetched_at": dated, "sha256": hashlib.sha256(canonical.encode()).hexdigest()})
                print(f"{len(collections)}/{len(nodes)} collection {ident}: {len(questions)} problems, complete={complete}", flush=True)
            except (ValueError, KeyError, httpx.HTTPError) as exc:
                failures.append({"id": ident, "message": str(exc)[:300]})
            time.sleep(0.25)
    output = {"version": "acgo-mindmap-" + dated[:10], "source": "https://www.acgo.cn/collection", "map_source": MAP_URL,
              "fetched_at": dated, "map_node_count": len(nodes), "collections": collections, "edges": edges, "failures": failures,
              "scope": "题单说明、题号、题名、难度、知识标签与链接；图谱连线为平台学习路径，不是学生掌握证据"}
    temporary = public / "acgo_collections.tmp"
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    temporary.replace(public / "acgo_collections.json")
    if failures or any(not c["ready"] for c in collections):
        raise SystemExit("Some collections could not be verified; only ready collections may be recommended")


if __name__ == "__main__":
    main()
