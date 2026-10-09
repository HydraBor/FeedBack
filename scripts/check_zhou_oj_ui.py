"""Live UI acceptance for explicitly supplied Zhou OJ contests.

Reads only those contests and saves one materials draft; does not call DeepSeek.
"""
import argparse
import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main(args):
    folder = ROOT / "data/private/zhou-oj-check"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1100})
        errors, catalogue_requests = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: catalogue_requests.append(request.url)
                if '/api/zhou-oj/contests' in request.url else None)
        await page.goto("http://127.0.0.1:8765")
        await page.get_by_role("button", name="新建反馈", exact=True).first.click()
        await page.get_by_label("选择学生档案").select_option(args.student_id)
        await page.get_by_label("学习开始日期").fill(args.start_date)
        await page.get_by_label("学习结束日期").fill(args.end_date)
        await page.get_by_role('button', name='CSP-'+args.track, exact=True).click()
        importer = page.locator('.acgo-import').filter(has=page.get_by_role(
            'heading', name='从 周老师 OJ 导入学生作品', exact=True))
        await importer.get_by_label("周老师 OJ 比赛号或链接", exact=True).fill(args.contests)
        confirmation = importer.get_by_role('checkbox', name=re.compile('讲师确认'))
        assert await confirmation.is_checked()
        await importer.get_by_role("button", name="读取学生作品", exact=True).click()
        await importer.get_by_text("采集完成，请选择题目导入表单", exact=True).wait_for(timeout=180000)
        assert not await importer.locator('.notice.amber').count(), '存在采集失败'
        copy = importer.get_by_role("button", name=re.compile(r"将所选 \d+ 道题填写到表单"))
        count = int(re.search(r"\d+", await copy.text_content())[0])
        assert count > 0 and await copy.is_enabled()
        await importer.get_by_role('button', name='全不选', exact=True).click()
        assert await copy.is_disabled()
        assert await copy.evaluate("e=>getComputedStyle(e).cursor") == 'not-allowed'
        await importer.get_by_role('button', name='全选', exact=True).click()
        assert await copy.is_enabled()
        await copy.click()
        problems = page.locator('.problem-card')
        assert await problems.count() == count
        assert await problems.evaluate_all("nodes=>nodes.every(n=>!n.open)")
        await problems.locator(':scope > summary').first.click()
        independent = page.get_by_label('是否独立完成', exact=True).first
        editorial = page.get_by_label('本次是否接触题解 / 讲解', exact=True).first
        assert await independent.input_value() == 'true'
        assert await editorial.input_value() == 'false'
        await independent.select_option('false')
        await editorial.select_option('true')
        await independent.select_option('true')
        await editorial.select_option('false')
        await problems.locator(':scope > summary').first.click()
        await page.screenshot(path=str(folder/'ui-import.png'), full_page=True)
        async with page.expect_response(lambda response:
                response.url.endswith('/api/reports') and response.request.method == 'POST') as saved:
            await page.get_by_role('button', name='仅保存材料草稿', exact=True).click()
        response = await saved.value
        assert response.ok, await response.text()
        entry = await response.json()
        assert len(entry['input']['problems']) == count
        assert entry['input']['tracks'] == [args.track]
        for problem in entry['input']['problems']:
            source = problem['source']
            assert source['platform'] == 'csp_exam'
            assert source['contest_format'] == 'oi_csp'
            assert source['submission_semantics'] == 'final_submission'
            assert source['contest_duration_minutes'] > 0
            assert problem['independent'] is True and problem['editorial_seen'] is False
            assert 'key=' not in source['problem_url'] and 'key=' not in source['task_url']
            assert problem['judge_result']
        await page.get_by_role('button', name='补充 / 修改材料', exact=True).wait_for()
        await page.screenshot(path=str(folder/'ui-saved.png'), full_page=True)
        await page.get_by_role('button', name='补充 / 修改材料', exact=True).click()
        assert await page.locator('.problem-card').count() == count
        await page.set_viewport_size({'width': 390, 'height': 844})
        await page.screenshot(path=str(folder/'ui-mobile.png'), full_page=True)
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        assert not catalogue_requests, catalogue_requests
        output = {'passed': True, 'report_id': entry['id'], 'problems': count,
                  'submissions': sum(len(p['submissions']) for p in entry['input']['problems']),
                  'page_errors': errors, 'catalogue_requests': len(catalogue_requests)}
        (folder/'ui-result.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
        for artifact in folder.glob('ui-*'):
            artifact.chmod(0o600)
        print(json.dumps(output, ensure_ascii=False), flush=True)
        await browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for field in ['student-id', 'contests', 'start-date', 'end-date']:
        parser.add_argument('--'+field, required=True)
    parser.add_argument('--track', choices=['J', 'S'], default='S')
    asyncio.run(main(parser.parse_args()))
