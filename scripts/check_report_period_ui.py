"""Isolated browser regression: same-period reuse, rewrite and material replacement.

Uses a temporary database, a mock AI provider and its own local server. No real
student record, existing service or external AI request is modified.
"""
import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import tempfile

import httpx
from playwright.async_api import async_playwright
import uvicorn
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


async def check(directory):
    os.environ['FEEDBACK_DATA_DIR'] = directory
    from backend import db, pipeline
    from backend.app import app
    from backend.models import FeedbackInput, StudentInput

    class Provider:
        def __init__(self):
            self.config={'model':'isolated-fixture','max_calls':10};self.calls=0;self.usage={}
        async def generate(self,instruction,data,schema):
            self.calls+=1
            if schema.__name__=='Training':
                return {'horizon':'近期练习','recent':[{'title':'独立练习','activity':'练习相近的新题。',
                    'success':'能说清自己的做法。','evidence':['current:topics'],'collection_id':'','practice_mode':'new'}],'phases':[]}
            assert schema.__name__=='ParentCopy'
            return {'summary':'这段时间，{{student}}完成了课堂任务，表现较稳，能读懂题目要求，把自己的想法写成程序。',
                'highlights':['能抓住题目的关键要求，安排好需要完成的步骤。'],'next_steps':['接下来练习相近的新题，完成后由讲师带着复盘。']}

    pipeline.DeepSeek=Provider
    db.init_db()
    student=db.save_student(StudentInput(name='流程测试同学',age=13,grade='初二').model_dump())
    data=FeedbackInput(student_id=student['id'],start_date='2026-10-01',end_date='2026-10-05',
        reference_date='2026-10-09',target_year=2026,tracks=['J','S'],topics='模拟、排序',mode='demo').model_dump(mode='json')
    report=db.create_feedback(data)
    await pipeline.generate(report['id'])
    # Reuse the locally generated layout fixture to exercise the live rewrite UI.
    data['mode']='live'
    with db.connection() as conn:
        conn.execute('UPDATE feedbacks SET input=? WHERE id=?',(json.dumps(data),report['id']))
    entry=db.feedback(report['id'])
    db.save_review(report['id'],entry['revision'],entry['draft'],{},True)
    originals=db.versions(report['id'])
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    task=asyncio.create_task(server.serve())
    try:
        async with httpx.AsyncClient(base_url=base) as client:
            for _ in range(100):
                if server.started:break
                if task.done():await task
                await asyncio.sleep(.05)
            assert server.started
            async with async_playwright() as p:
                browser=await p.chromium.launch(headless=True)
                try:
                    page=await browser.new_page(viewport={'width':1440,'height':1050})
                    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    writes=[]
                    page.on('request',lambda request:writes.append((request.method,request.url)) if request.method!='GET' else None)
                    await page.goto(base+'/?report='+report['id'])
                    await page.get_by_role('button',name='更新建议与文案',exact=True).click()
                    await page.wait_for_function("document.querySelector('.page-title .pill')?.textContent === '待审核'")
                    await page.get_by_text('文案提醒（不影响生成、保存和确认）',exact=True).wait_for()
                    assert len(db.list_feedbacks())==1 and db.versions(report['id'])==originals
                    assert db.feedback(report['id'])['analysis']['copy_refreshes']
                    await page.get_by_role('button',name='确认并归档',exact=True).click()
                    await page.get_by_text('已确认并归档，可下载 PDF',exact=True).wait_for()
                    assert len(db.versions(report['id']))==len(originals)+1
                    assert db.versions(report['id'])[-1]==originals[-1]
                    preserved_versions=db.versions(report['id'])
                    await page.get_by_role('button',name='返回反馈列表',exact=True).click()
                    await page.locator('[data-report-id]').wait_for()
                    assert await page.locator('[data-report-id]').count()==1
                    assert 'CSP-J / CSP-S' in await page.locator('[data-report-id]').inner_text()
                    # The creation API must reuse a completed report without restarting it.
                    response=await client.post('/api/reports',json=data)
                    assert response.json()['id']==report['id'] and response.json()['status']=='confirmed'
                    await page.locator('[data-report-id]').click()
                    await page.get_by_role('button',name='修改本期材料',exact=True).click()
                    assert await page.get_by_label('学习开始日期').is_disabled()
                    assert await page.get_by_label('学习结束日期').is_disabled()
                    await page.get_by_label('本期补充信息').fill('补充本期课堂观察')
                    await page.get_by_role('button',name='仅保存材料草稿',exact=True).click()
                    await page.get_by_role('button',name='开始分析',exact=True).wait_for()
                    changed=db.feedback(report['id'])
                    assert changed['status']=='draft' and changed['input']['supplements']=='补充本期课堂观察'
                    assert changed['analysis'] is None and len(db.list_feedbacks())==1
                    assert db.versions(report['id'])==preserved_versions
                    assert any(method=='POST' and url.endswith('/rewrite') for method,url in writes)
                    assert not any(method=='POST' and url.endswith('/api/reports') for method,url in writes)
                    assert not errors,errors
                finally:
                    await browser.close()
        print('Isolated browser checks passed: rewrite, one-row list, ID reuse, material edit, immutable confirmed versions.')
    finally:
        server.should_exit=True
        await task


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='feedback-report-period-ui-') as directory:
        asyncio.run(check(directory))
