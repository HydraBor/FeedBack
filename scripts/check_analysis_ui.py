"""Read-only UI check: real report + browser-only simulated running progress.

Does not create students/reports, save settings or call DeepSeek.
"""
import argparse
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def main(args):
    folder=Path(__file__).resolve().parents[1]/"data/private/analysis-check"
    folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(headless=True)
        try:
            page=await browser.new_page(base_url="http://127.0.0.1:8765",viewport={"width":1440,"height":1050})
            errors=[];page.on("pageerror",lambda error:errors.append(str(error)))
            response=await page.request.get('/api/reports/'+args.report_id)
            assert response.ok
            report=await response.json()
            assert report['status']=='review' and report['draft']
            await page.goto('/?report='+args.report_id)
            await page.get_by_role('button',name='确认并归档',exact=True).wait_for()
            assert len(report['analysis']['diagnoses'])==len(report['input']['problems'])
            await page.screenshot(path=str(folder/'completed-review.png'))
            fixture={**report,'status':'running','draft':None,'error':None,'stage':'并发分析题目：已完成 12/38 · 正在处理 4 题',
                'stages':{**report['stages'],'analysis_progress':{'completed':12,'total':38,'active':[13,14,15,16],'failed':[],'concurrency':4}}}
            async def running(route):
                if route.request.method=='GET':await route.fulfill(json=fixture)
                else:await route.continue_()
            await page.route('**/api/reports/'+args.report_id,running)
            await page.reload()
            bar=page.get_by_label('逐题分析进度');await bar.wait_for()
            assert await bar.get_attribute('value')=='12' and await bar.get_attribute('max')=='38'
            await page.get_by_text('正在处理第 13、14、15、16 题；各题完成后立即保存。',exact=True).wait_for()
            await page.screenshot(path=str(folder/'concurrent-progress.png'))
            await page.set_viewport_size({'width':390,'height':844})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            await page.screenshot(path=str(folder/'concurrent-progress-mobile.png'))
            await page.get_by_role('button',name='本地设置',exact=False).click()
            field=page.get_by_label('同时分析的题目数',exact=True)
            await field.wait_for();assert await field.locator('option').count()==8
            await field.select_option('6');assert await field.input_value()=='6'
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            await page.screenshot(path=str(folder/'concurrency-settings-mobile.png'))
            assert not errors,errors
            result={'passed':True,'report_id':args.report_id,'status':report['status'],'problems':len(report['input']['problems']),'page_errors':errors}
            (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
            print(json.dumps(result,ensure_ascii=False))
        finally:await browser.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report-id',required=True)
    asyncio.run(main(parser.parse_args()))
