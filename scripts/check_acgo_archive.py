"""Optional live check of the permanent ACGO practice archive workflow.

Requires lecturer login in the dedicated Edge and explicit student/task IDs.
Saves a practice archive, opens it again, then verifies the feedback form;
does not generate a report or call DeepSeek.
"""
import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main(args):
    folder = ROOT / "data/private/acgo-check"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(base_url="http://127.0.0.1:8765", viewport={"width": 1440, "height": 1050})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.goto("http://127.0.0.1:8765")
        await page.get_by_role("button", name="导入做题档案", exact=True).click()
        for label, value in [
            ("学生姓名", args.name),
            ("学生 ACGO ID", args.user_id),
            ("团队 ID 或链接", args.team_id),
            ("作业 ID 或链接（可选）", args.homework_id),
            ("比赛 ID 或完整链接（可选）", args.contest_url),
            ("档案开始日期（可选）", args.start_date),
            ("档案结束日期（可选）", args.end_date),
        ]:
            await page.get_by_label(label, exact=True).fill(value)
        async with page.expect_response(
            lambda response: response.url.endswith("/api/practice-archives/imports")
            and response.request.method == "POST"
        ) as started:
            await page.get_by_role("button", name="采集并自动保存做题档案", exact=True).click()
        response = await started.value
        assert response.ok, await response.text()
        job = await response.json()
        print(json.dumps({"started": True, "job_id": job["id"]}), flush=True)
        await page.get_by_role("heading", name=args.name + "的做题档案", exact=True).wait_for(timeout=240000)
        result_response = await page.request.get("/api/acgo/imports/" + job["id"])
        result = (await result_response.json())["result"]
        archive_id = result["archive_id"]
        archive_response = await page.request.get("/api/practice-archives/" + archive_id)
        assert archive_response.ok, await archive_response.text()
        archive = await archive_response.json()
        problems = archive["content"]["problems"]
        assert problems and all(p["source"]["user_id"] == args.user_id for p in problems)
        assert all(s["code"] for p in problems for s in p["submissions"]) and all(not p["code"] for p in problems if p.get("submission_state", "submitted") != "submitted")
        assert all(p["minutes"] is None for p in problems)
        assert all(p["source"]["team_id"] == args.team_id for p in problems)
        assert not archive["content"]["failed_questions"], archive["content"]["failed_questions"]
        assert all(p["completion_context"] == "practice_then_explanation" for p in problems if p["source"]["kind"] == "homework")
        assert all(p["completion_context"] == "independent_timed_contest" and p["independent"] is True and p["editorial_seen"] is False for p in problems if p["source"]["kind"] == "contest" and p.get("submission_state", "submitted") == "submitted")
        await page.screenshot(path=str(folder / "ui-practice-archive.png"))
        await page.goto("http://127.0.0.1:8765/?archive=" + archive_id)
        await page.get_by_role("heading", name=args.name + "的做题档案", exact=True).wait_for()
        selected = len(problems)
        await page.get_by_role("button", name="全选", exact=True).click()
        await page.get_by_role("button", name=f"用所选 {selected} 道题新建反馈", exact=True).click()
        assert await page.get_by_label("学习开始日期", exact=True).input_value() == archive["start_date"]
        assert await page.get_by_label("学习结束日期", exact=True).input_value() == archive["end_date"]
        assert await page.get_by_label("选择学生档案", exact=True).input_value() == archive["student_id"]
        assert await page.locator(".problem-card").count() == selected
        await page.screenshot(path=str(folder / "ui-archive-to-feedback.png"))
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.goto("http://127.0.0.1:8765/?archive=" + archive_id)
        await page.get_by_role("heading", name=args.name + "的做题档案", exact=True).wait_for()
        await page.screenshot(path=str(folder / "ui-practice-mobile.png"))
        assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "手机布局溢出"
        assert not errors, errors
        output = {"passed": True, "archive_id": archive_id,
                  "start_date": archive["start_date"], "end_date": archive["end_date"],
                  "problems": len(problems), "submissions": sum(len(p["submissions"]) for p in problems),
                  "submission_gaps": sum(s["gap_seconds"] is not None for p in problems for s in p["submissions"]),
                  "page_errors": errors}
        (folder / "archive-ui-result.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        for artifact in folder.glob("*practice*"):
            artifact.chmod(0o600)
        (folder / "archive-ui-result.json").chmod(0o600)
        (folder / "ui-archive-to-feedback.png").chmod(0o600)
        print(json.dumps(output, ensure_ascii=False), flush=True)
        await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for field in ["name", "user-id", "team-id"]:
        parser.add_argument("--" + field, required=True)
    for field in ["homework-id", "contest-url", "start-date", "end-date"]:
        parser.add_argument("--" + field, default="")
    asyncio.run(main(parser.parse_args()))
