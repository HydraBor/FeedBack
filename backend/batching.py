"""Keep archives complete while limiting each model request's context size."""
import json
from collections import Counter
from .evidence import source_context,assessment_basis

def groups(items,limit=60000):
    batch=[];size=0
    for item in items:
        length=len(json.dumps(item,ensure_ascii=False))
        if batch and size+length>limit:
            yield batch;batch=[];size=0
        batch.append(item);size+=length
    if batch:yield batch

def problem_facts(problem,index):
    hidden={"statement","code","submissions","unverified_submissions"}
    facts={k:v for k,v in problem.items() if k not in hidden}
    basis=assessment_basis(problem)
    facts['assessment_basis']=basis
    if basis['kind']=='static_only':facts['judge_result']=basis['note']
    source=source_context(problem)
    if source:facts["source"]={k:source.get(k) for k in ("platform","kind","task_id","question_id","history_complete","tags","assessment_tags","contest_format","submission_semantics","contest_duration_minutes")}
    facts["evidence_id"]=f"current:p{index}"
    facts["submission_count"]=len(problem.get("submissions",[]))
    facts["submission_results"]=dict(Counter(s["result"] for s in problem.get("submissions",[])))
    return facts

def work_summary(works):
    """Deterministic counts for parent prose; no random selection of evidence."""
    grouped={}
    for work in works:
        conditions=work.get('比赛材料条件',{})
        key=(work["场景"],work["结果"],str(work["完成条件"]),json.dumps(conditions,sort_keys=True,ensure_ascii=False))
        bucket=grouped.setdefault(key,{"场景":work["场景"],"结果":work["结果"],"完成条件":work["完成条件"],"比赛材料条件":conditions,"题目数":0,"提交次数":0,"含不同代码版本的题目数":0})
        bucket["题目数"]+=1
        if bucket["提交次数"] is not None:
            bucket["提交次数"] = bucket["提交次数"]+work["有多少次提交"] if work["有多少次提交"] is not None else None
        bucket["过程限制"]="只依据已记录版本差异或讲师观察，不从最终代码数量推断实际尝试次数与检查习惯。"
        bucket["含不同代码版本的题目数"]+=work["有多少个不同代码版本"]>1
    return list(grouped.values())
