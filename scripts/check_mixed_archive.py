"""Verify an explicitly selected archive in the UI and save a materials draft.

Reads existing local work, creates one draft, and never calls DeepSeek or crawls
remote platforms. Use --archive-id and optionally --track J/S.
"""
import argparse
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def main(args):
    folder=Path(__file__).resolve().parents[1]/"data/private/csp-exam-check"
    folder.mkdir(mode=0o700,exist_ok=True)
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(headless=True)
        try:
            page=await browser.new_page(base_url="http://127.0.0.1:8765",viewport={"width":1440,"height":1050})
            errors=[];page.on("pageerror",lambda e:errors.append(str(e)))
            response=await page.request.get('/api/practice-archives/'+args.archive_id)
            assert response.ok
            archive=await response.json();count=len(archive['content']['problems'])
            await page.goto('/?archive='+args.archive_id)
            await page.get_by_role('heading',name=archive['name']+'的做题档案',exact=True).wait_for()
            assert await page.locator('.fold-question[open]').count()==0
            await page.get_by_role('button',name='全不选',exact=True).click()
            disabled=page.get_by_role('button',name='用所选 0 道题新建反馈',exact=True)
            assert await disabled.is_disabled()
            assert await disabled.evaluate('(n)=>getComputedStyle(n).cursor')=='not-allowed'
            await page.locator('.fold-question input[type=checkbox]').first.check()
            assert await page.locator('.fold-question[open]').count()==0
            await page.locator('.fold-question .question-title b').first.click()
            await page.locator('.fold-question .question-body').first.wait_for()
            await page.locator('.fold-question .question-title b').first.click()
            await page.get_by_role('button',name='反选',exact=True).click()
            assert await page.locator('.fold-question input:checked').count()==count-1
            await page.get_by_role('button',name='全选',exact=True).click()
            await page.screenshot(path=str(folder/'mixed-archive-desktop.png'),full_page=True)
            await page.get_by_role('button',name=f'用所选 {count} 道题新建反馈',exact=True).click()
            await page.get_by_role('heading',name='记录本期学习成果',exact=True).wait_for()
            assert await page.locator('.problem-card').count()==count
            assert await page.locator('.problem-card[open]').count()==0
            await page.get_by_role('button',name='CSP-'+args.track,exact=True).click()
            await page.set_viewport_size({'width':390,'height':844})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            await page.screenshot(path=str(folder/'mixed-feedback-mobile.png'),full_page=True)
            async with page.expect_response(lambda r:r.url.endswith('/api/reports') and r.request.method=='POST') as saved:
                await page.get_by_role('button',name='仅保存材料草稿',exact=True).click()
            response=await saved.value
            assert response.ok,await response.text()
            report=await response.json()
            assert len(report['input']['problems'])==count
            assert all(p['source']['practice_archive_id']==args.archive_id for p in report['input']['problems'])
            assert report['status']=='draft' and report['input']['tracks']==[args.track]
            assert not errors,errors
            result={'passed':True,'archive_id':args.archive_id,'report_id':report['id'],'problems':count,'track':args.track,'page_errors':errors}
            path=folder/'mixed-ui-result.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2));path.chmod(0o600)
            for name in ['mixed-archive-desktop.png','mixed-feedback-mobile.png']:(folder/name).chmod(0o600)
            print(json.dumps(result,ensure_ascii=False))
        finally:await browser.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--archive-id',required=True)
    parser.add_argument('--track',choices=['J','S'],default='S')
    asyncio.run(main(parser.parse_args()))
