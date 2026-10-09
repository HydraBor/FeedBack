"""Browser acceptance for the locally owned application (not remote website automation)."""
import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1]

async def main():
    folder=ROOT/"tmp/ui";folder.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":1440,"height":1050},device_scale_factor=1)
        errors=[];page.on("pageerror",lambda error:errors.append(str(error)))
        await page.goto("http://127.0.0.1:8765")
        await page.get_by_role("button",name="＋ 新建学生档案").click()
        await page.get_by_label("学生姓名").fill("演示同学")
        await page.get_by_label("辨识备注").fill("虚构档案，浏览器流程验收")
        await page.get_by_role("button",name="保存学生档案").click()
        await page.get_by_text("演示同学",exact=True).first.wait_for()
        await page.screenshot(path=str(folder/"archive.png"),full_page=True)
        await page.get_by_role("button",name="新建反馈",exact=True).first.click()
        assert await page.get_by_label("学习开始日期").input_value()==""
        assert await page.get_by_label("学习结束日期").input_value()==""
        assert await page.get_by_role("button",name="保存材料并生成反馈",exact=True).is_disabled()
        study_today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        study_end = study_today.replace(day=min(study_today.day,5))
        await page.get_by_label("学习开始日期").fill(study_end.replace(day=1).isoformat())
        await page.get_by_label("学习结束日期").fill(study_end.isoformat())
        await page.get_by_role("button",name="竞赛资料",exact=True).click()
        await page.get_by_role("button",name="新建反馈",exact=True).first.click()
        assert await page.get_by_label("学习结束日期").input_value()==study_end.isoformat()
        assert await page.get_by_label("学习开始日期").input_value()==study_end.replace(day=1).isoformat()
        await page.get_by_label("学习的知识点").fill("模拟、枚举、排序、二分、前缀和、递归、搜索。演示输入，仅展示版式。")
        await page.get_by_label("专注投入（1—100，可留空）").fill("82")
        await page.get_by_label("分析模式").select_option("demo")
        await page.screenshot(path=str(folder/"form.png"),full_page=True)
        await page.get_by_role("button",name="保存材料并生成反馈").click()
        await page.get_by_role("button",name="确认并归档").wait_for(timeout=30000)
        title=page.get_by_label("报告标题",exact=True)
        assert await title.input_value()=="演示同学"
        await title.fill("演示同学 · 本期收获")
        await page.get_by_label("审核讲师署名（可选）").fill("演示讲师")
        await page.get_by_role("button",name="评分与依据",exact=True).click()
        inputs=page.get_by_label("掌握评分")
        await inputs.first.fill("96")
        await page.get_by_role("button",name="保存草稿",exact=True).click()
        await page.get_by_text("审核草稿已保存",exact=True).wait_for()
        await page.frame_locator("iframe").get_by_text("96",exact=True).wait_for()
        await page.get_by_role("button",name="确认并归档",exact=True).click()
        await page.get_by_text("已确认并归档，可下载 PDF",exact=True).wait_for()
        await page.get_by_role("button",name="确认版本",exact=True).click()
        await page.get_by_role("link",name="下载 PDF").wait_for()
        download=await page.request.get("http://127.0.0.1:8765"+await page.get_by_role("link",name="下载 PDF").get_attribute("href"))
        assert download.ok and (await download.body()).startswith(b"%PDF")
        (folder/"download.pdf").write_bytes(await download.body())
        await page.screenshot(path=str(folder/"review.png"),full_page=True)
        await page.get_by_role("button",name="竞赛资料",exact=True).click()
        await page.get_by_placeholder("年份、组别、编号或题名").fill("2025")
        await page.get_by_role("button",name="录入 / 审核").first.click()
        await page.get_by_label("完整题面").wait_for()
        assert len(await page.get_by_label("完整题面").input_value())>500
        await page.get_by_role("button",name="×",exact=True).first.click()
        await page.get_by_role("button",name="本地设置",exact=True).click()
        await page.get_by_label("API 密钥").wait_for()
        assert not await page.get_by_label("API 密钥").input_value()
        await page.set_viewport_size({"width":390,"height":844})
        await page.get_by_role("button",name="学生档案",exact=True).click()
        await page.screenshot(path=str(folder/"mobile.png"),full_page=True)
        assert not errors,errors
        (folder/"result.json").write_text(json.dumps({"passed":True,"page_errors":errors,"screenshots":4}),encoding="utf-8")
        print("Browser workflow passed: archive → form → demo analysis → edit scores → confirm → versions; mobile and library checked.")
        await browser.close()

if __name__=="__main__":asyncio.run(main())
