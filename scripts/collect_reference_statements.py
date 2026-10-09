"""Fetch public Luogu statements for cross-checking the CSP catalogue, never student data."""
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import knowledge, db

async def collect():
    folder = knowledge.PUBLIC / "raw/statement-crosschecks"
    folder.mkdir(parents=True, exist_ok=True)
    slots = asyncio.Semaphore(2)
    async with httpx.AsyncClient(timeout=35, follow_redirects=True, headers={"User-Agent":"Mozilla/5.0"}) as client:
        async def one(problem):
            path = folder / (problem["id"] + ".json")
            if path.exists():
                return
            async with slots:
                url = "https://www.luogu.com.cn/problem/" + problem["id"] + "?_contentOnly=1"
                for attempt in range(3):
                    try:
                        response = await client.get(url)
                        response.raise_for_status()
                        match = re.search(r'<script id="lentille-context" type="application/json">(.*?)</script>', response.text, re.S)
                        if not match:
                            raise ValueError("Public statement JSON missing")
                        source = json.loads(match[1])["data"]["problem"]
                        if source["pid"] != problem["id"] or problem["title"] not in source["name"]:
                            raise ValueError("Catalogue identity mismatch")
                        content = source["content"]
                        statement = "\n\n".join("## " + title + "\n" + content[key] for key, title in [("background","背景"),("description","题目描述"),("formatI","输入格式"),("formatO","输出格式"),("hint","说明与数据范围")] if content.get(key))
                        result = {"id":problem["id"], "source":url, "name":source["name"], "statement":statement,
                            "samples":source.get("samples",[]), "full_score":source.get("fullScore"),
                            "luogu_tags":source.get("tags",[]), "difficulty":source.get("difficulty"), "retrieved_at":db.now(),
                            "statement_sha256":hashlib.sha256(statement.encode()).hexdigest(),
                            "provenance":"洛谷公开题面交叉核对；并非官方题解或官方评测结论"}
                        path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
                        print(problem["id"], "cross-check saved", flush=True)
                        break
                    except (httpx.HTTPError,ValueError,KeyError) as exc:
                        if attempt == 2:
                            raise RuntimeError(problem["id"] + ": public statement could not be fetched") from exc
                        await asyncio.sleep(2 + attempt)
                await asyncio.sleep(0.4)
        await asyncio.gather(*(one(p) for p in knowledge.problems()))

if __name__ == "__main__":
    asyncio.run(collect())
