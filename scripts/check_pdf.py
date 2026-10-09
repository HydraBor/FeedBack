"""Create layout fixtures and verify privacy/pagination using actual Chromium PDFs."""
import asyncio
import sys
import unicodedata
from io import BytesIO
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.report import render,pdf_bytes
from backend import knowledge
from backend.models import FeedbackInput
from backend.pipeline import demo_results
from pypdf import PdfReader
ROOT=Path(__file__).resolve().parents[1]

async def main():
    payload=FeedbackInput(student_id="layout-fixture",start_date="2026-10-01",end_date="2026-10-05",target_year=2026,tracks=["J","S"],mode="demo",topics="模拟、枚举、排序、二分、前缀和、递归、搜索",focus_score=82).model_dump(mode="json")
    _,scores,_,_,copy=demo_results(payload,knowledge.topics())
    draft={**copy,**scores,"title":"","teacher":"演示讲师","positions":knowledge.forecast_positions({},payload["tracks"],[],True),"admissions_text":"","admissions_sources":[],"practice_recommendations":[]}
    entry={"input":payload,"student_snapshot":{"name":"版式验收同学","age":13,"grade":"初二"},"draft":draft,"revision":1}
    folder=ROOT/"tmp/pdfs";folder.mkdir(parents=True,exist_ok=True)
    from backend.knowledge import topics
    from backend import practice
    _,scores,_,_,_=demo_results(entry["input"],topics())
    variants={"normal":draft,"radar":{**draft,"topic_scores":scores["topic_scores"]},"bar":{**draft,"topic_scores":draft["topic_scores"][:2]},
        "overflow":{**draft,"summary":"本期完成了任务分析、程序实现与结果检查，并能根据反馈修改遗漏。"*25,
            "highlights":["能够整理条件并记录检查过程。在完成练习后，认真复盘任务中的选择，说明实现思路及验证依据。"*6]*4,
            "next_steps":["安排同类新题独立完成，记录方案、耗时和检查结果，完成后进行复盘。"*8]*3}}
    collections=[{'collection_id':c['id'],'title':c['title'],'url':c['url'],'questions':[],'practice_mode':'new'} for c in practice.catalogue()['collections'] if c['ready']]
    variants['collections']={**draft,'practice_recommendations':collections[:8]}
    variants['many_collections']={**draft,'practice_recommendations':collections}
    for name,report in variants.items():
        data=await pdf_bytes(render(entry,report,entry["revision"]))
        (folder/(name+".pdf")).write_bytes(data)
        reader=PdfReader(BytesIO(data));text=unicodedata.normalize("NFKC","\n".join(p.extract_text() for p in reader.pages))
        assert entry["student_snapshot"]["grade"] not in text and str(entry["student_snapshot"]["age"])+"岁" not in text
        assert "current:" not in text and "{{student}}" not in text
        assert entry['student_snapshot']['name']+'的学习反馈' not in text
        assert "本期成果" in text and "下一阶段重点" in text and "训练对照估计" in text
        assert "分数怎么看" in text and "能理解老师讲的" in text and "能灵活运用讲清做法" in text
        assert '资料基准' not in text and '待审核预览' not in text and '已确认版本' not in text
        assert '学生目前实力相当于' in text and '此评估为保守估计' in text
        assert "按最终评分展示最高" not in text
        for page in reader.pages:
            page_text=unicodedata.normalize("NFKC",page.extract_text())
            assert "本报告依据指定学习时段" in page_text
            locations=[]
            def locate_footer(value,cm,tm,font,size):
                if "本" in unicodedata.normalize("NFKC",value):
                    locations.append(cm[1]*tm[4]+cm[3]*tm[5]+cm[5])
            page.extract_text(visitor_text=locate_footer)
            assert locations and any(15<y<70 for y in locations), locations
        if name in ('collections','many_collections'):
            destinations=[]
            for page in reader.pages:
                for ref in page.get('/Annots',[]):
                    action=ref.get_object().get('/A',{})
                    if action.get('/URI'):destinations.append(str(action['/URI']))
            assert set(destinations)=={r['url'] for r in report['practice_recommendations']}
            assert 'problemset/info' not in data.decode('latin1')
        else:
            assert len(reader.pages)>1 if name=="overflow" else len(reader.pages)==1
        print(name,len(reader.pages),flush=True)

if __name__=="__main__":asyncio.run(main())
