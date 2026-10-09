"""Optional live acceptance. Requires lecturer login and explicit task IDs.

Creates one materials draft in the selected archive; does not call DeepSeek.
"""
import argparse
import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]

async def main(args):
    folder = ROOT / "data/private/acgo-check"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":1440,"height":1050})
        errors=[]
        page.on("pageerror",lambda error: errors.append(str(error)))
        await page.goto("http://127.0.0.1:8765")
        await page.get_by_role("button",name="新建反馈",exact=True).first.click()
        await page.get_by_label("选择学生档案").select_option(args.student_id)
        await page.get_by_label("学习开始日期").fill(args.date)
        await page.get_by_label("学习结束日期").fill(args.date)
        importer=page.locator('.acgo-import').filter(has=page.get_by_role('heading',name='从 ACGO 导入学生作品',exact=True))
        await page.get_by_label("团队 ID 或链接").fill(args.team_id)
        await page.get_by_label("作业 ID 或链接").fill(args.homework_id)
        await page.get_by_role("button",name="检查连接",exact=True).click()
        await page.get_by_text("专用 Edge 已连接，导入时核对登录与权限",exact=True).wait_for(timeout=20000)
        counts=[]
        for kind,task in [("homework",args.homework_id),("contest",args.contest_url)]:
            if kind=="contest":
                await page.get_by_label("任务类型").select_option("contest")
                await page.get_by_label("比赛 ID 或完整链接").fill(task)
            await importer.get_by_role("button",name="读取学生作品",exact=True).click()
            await page.get_by_text("采集完成，请选择题目导入表单",exact=True).wait_for(timeout=180000)
            assert await page.get_by_label("学生 ACGO ID").input_value()==args.user_id
            assert not await page.locator('.acgo-preview .notice.amber').count(), '有失败题目，请检查'
            copies=importer.get_by_role("button",name=re.compile(r"将所选 \d+ 道题填写到表单"))
            assert await copies.is_enabled(), '没有可导入作品'
            counts.append(int(re.search(r"\d+",await copies.text_content())[0]))
            await copies.click()
        assert await page.locator('.problem-card').count()==sum(counts)
        assert not await page.locator('.problem-card').filter(has_text='我是分界线').count()
        await page.locator('.problem-card').evaluate_all("nodes=>nodes.forEach(n=>n.open=true)")
        await page.get_by_label("是否独立完成",exact=True).first.wait_for()
        # Unknown completion conditions remain blank after import.
        assert await page.get_by_label("是否独立完成",exact=True).count()==sum(counts)
        for index,select in enumerate(await page.get_by_label("是否独立完成",exact=True).all()):
            assert await select.input_value()==('' if index<counts[0] else 'true')
        for field in await page.get_by_label("耗时（分钟，未知留空）",exact=True).all():
            assert await field.input_value()==''
        await page.screenshot(path=str(folder/'ui-import.png'))
        async with page.expect_response(lambda response:response.url.endswith('/api/reports') and response.request.method=='POST') as saved:
            await page.get_by_role("button",name="仅保存材料草稿",exact=True).click()
        response=await saved.value
        assert response.ok,await response.text()
        entry=await response.json()
        assert len(entry['input']['problems'])==sum(counts)
        assert all(p['source']['user_id']==args.user_id for p in entry['input']['problems'])
        assert all('rank' not in p for p in entry['input']['problems'])
        await page.get_by_role('button',name='补充 / 修改材料',exact=True).wait_for()
        await page.get_by_role('button',name='补充 / 修改材料',exact=True).click()
        assert await page.locator('.problem-card').count()==sum(counts)
        await page.locator('.problem-card>summary').first.click()
        await page.get_by_label('是否独立完成',exact=True).first.wait_for()
        await page.get_by_label('是否独立完成',exact=True).first.select_option('true')
        # Restore unknown: this acceptance must not invent a real student's conditions.
        await page.get_by_label('是否独立完成',exact=True).first.select_option('')
        await page.get_by_role('button',name='仅保存材料草稿',exact=True).click()
        await page.get_by_role('button',name='补充 / 修改材料',exact=True).wait_for()
        await page.screenshot(path=str(folder/'ui-saved.png'))
        assert not errors,errors
        output={"passed":True,"report_id":entry['id'],"homework_problems":counts[0],"contest_problems":counts[1],
            "submissions":sum(p['source']['history_count'] for p in entry['input']['problems']),"page_errors":errors}
        (folder/'ui-result.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
        for artifact in folder.glob('ui-*'):artifact.chmod(0o600)
        print(json.dumps(output,ensure_ascii=False),flush=True)
        await browser.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for field in ['student-id','user-id','team-id','homework-id','contest-url','date']:parser.add_argument('--'+field,required=True)
    asyncio.run(main(parser.parse_args()))
