import re
from .knowledge import ABILITIES, topics

def evidence_ids(payload, historical, profile=None):
    ids = set()
    for field, suffix in (("topics", "topics"), ("supplements", "supplements"), ("subjective_observation", "observation")):
        if payload.get(field, "").strip():
            ids.add("current:" + suffix)
    if payload.get("focus_score") is not None or payload.get("focus_observation", "").strip():
        ids.add("current:focus")
    if profile and profile.get("background", "").strip():
        ids.add("student:background")
    ids.update(f"current:p{i}" for i in range(len(payload["problems"])))
    for item in historical:
        for field in ("topics", "supplements"):
            if item["input"].get(field, "").strip():
                ids.add(f"history:{item['id']}:{field}")
        if item.get("student_snapshot", {}).get("background", "").strip():
            ids.add(f"history:{item['id']}:background")
        ids.update(f"history:{item['id']}:p{i}" for i in range(len(item["input"]["problems"])))
    return ids

def validate_scores(scores, abilities, allowed_ids, focus_score=None, unsubmitted_ids=None):
    known = {t["id"] for t in topics()["items"]}
    seen = set()
    for score in scores:
        if score["id"] not in known or score["id"] in seen:
            raise ValueError("知识评分包含未配置或重复的标签")
        seen.add(score["id"])
        if not set(score["evidence"]) <= allowed_ids or (score["score"] is not None and not score["evidence"]):
            raise ValueError("有效知识评分必须引用已提供的材料")
        if any(e.startswith("history:") for e in score["evidence"]):
            raise ValueError("本期知识图不能把历史成果算成本期掌握证据")
        if score["score"] is not None and unsubmitted_ids and set(score["evidence"]) <= unsubmitted_ids:
            raise ValueError("未提交题目只能作为任务覆盖信息，不能单独形成知识分数")
    seen = set()
    for ability in abilities:
        if ability["id"] in seen:
            raise ValueError("基本素质不能重复")
        seen.add(ability["id"])
        if not set(ability["evidence"]) <= allowed_ids or (ability["score"] is not None and not ability["evidence"]):
            raise ValueError("基本素质评分缺少有效来源")
        if ability["id"] == "A06" and ability["score"] != focus_score:
            raise ValueError("首次专注投入评分必须使用讲师提供的分数")
        if ability["score"] is not None and unsubmitted_ids and set(ability["evidence"]) <= unsubmitted_ids:
            raise ValueError("未提交记录不能单独形成能力分数")
    if seen != set(ABILITIES):
        raise ValueError("基本素质必须包含已配置六项，未知项使用空分数")

def validate_forecasts(result, tracks, references, allowed_ids, unsubmitted_ids=None):
    from .knowledge import forecast_positions
    forecast_positions(result, tracks, references)
    expected={(r["rule"]["track"],r["rule"]["year"]) for r in references}
    seen=set()
    for paper in result["papers"]:
        key=(paper["track"],paper["year"])
        if key not in expected or key in seen:
            raise ValueError("参考卷年份与组别必须对应所提供资料，且不能重复")
        seen.add(key)
        for task in paper["tasks"]:
            if not set(task["evidence"])<=allowed_ids or (task["upper"]>0 and not task["evidence"]):
                raise ValueError("参考卷推算必须引用已有材料，不能虚构支持证据")
            if task["upper"] > 0 and unsubmitted_ids and set(task["evidence"]) <= unsubmitted_ids:
                raise ValueError("未提交题目不能单独作为正向成绩推算依据")
    if seen!=expected:
        raise ValueError("请逐一分析已提供的完整参考卷，材料不足的题目保守处理并说明依据")

def parent_texts(report):
    return [report.get('title',''), report["summary"], *report["highlights"], *report["next_steps"], report.get("admissions_text", ""), *[p["label"] + p["basis"] for p in report["positions"]]]

def parent_problem_names(report, payload):
    """Find copied task names, without banning incidental short everyday words."""
    prose="\n".join([report["summary"], *report["highlights"], *report["next_steps"]])
    found=[]
    for problem in payload["problems"]:
        raw=problem.get("title","").strip()
        name=re.sub(r'^[A-Za-z]+\d+[A-Za-z]?[.．]\s*', '', raw).strip()
        if not name:
            continue
        quoted=re.escape(name)
        generic={'课堂练习','比赛题','综合练习','基础练习','编程练习','基础训练','综合训练'}
        literal=(raw!=name and raw in prose) or (name not in generic and len(re.sub(r'\W','',name))>=4 and name in prose)
        explicit=re.search(r'(?:^|[《“"「、，,：:])\s*'+quoted+r'\s*(?:[》”"」、，,]|(?:这|那)?(?:道)?题|等(?:题|练习))',prose,re.M)
        named_task=re.search(quoted+r'\s*(?:这|那)?(?:道)?题',prose)
        if (literal or explicit or named_task) and name not in found:
            found.append(name)
    return found

def validate_parent(report, payload):
    text = "\n".join(parent_texts(report))
    if re.search(r"\d{1,2}\s*(周岁|岁)|[一二三四五六七八九十1-9]\s*年级|初[一二三]|高[一二三]|年龄[：:]|年级[：:]", text):
        raise ValueError("家长正文不能展示学生年龄或年级，请修改后保存")
    if any(re.search(r"\d+(?:\.\d+)?\s*分", p["label"] + p["basis"]) for p in report["positions"]):
        raise ValueError("家长 CSP 定位只展示等级，不能展示预测分数")
    if set(p["track"] for p in report["positions"]) != set(payload["tracks"]) or len(report["positions"]) != len(payload["tracks"]):
        raise ValueError("CSP 定位必须对应所选组别")
    from .config import ADMISSIONS_ENABLED
    if not ADMISSIONS_ENABLED and (report["admissions_text"] or report["admissions_sources"]):
        raise ValueError("深圳自招尚未启用，请保留空的预留报告字段")
    if not payload["admissions"] and (report["admissions_text"] or report["admissions_sources"]):
        raise ValueError("未勾选深圳自招，不能展示自招内容")
    if re.search(r"current:|history:|student:background|teacher:review|\b[KA]\d{2,3}\b|evidence|验收信息|专注观察为\d", text, re.I):
        raise ValueError("家长正文不能展示内部材料编号、评分记录或验收术语，请直接汇报成果与能力")
    warnings = []
    prose="\n".join([report["summary"], *report["highlights"], *report["next_steps"]])
    if "任务" in prose:
        warnings.append("做题统一称“题目”，请将正文中的“任务”改成“题目”，并把句子整理自然。")
    analyst_terms=re.findall(r"本期核实到|已核实到|有独立完成的依据|可以直接支持|证据支持|材料显示|作品反映出|这个场景下|代码版本|代码快照|部分通过|讲师确认|没有看(?:过)?题解|平台(?:给出|记录)",prose)
    if analyst_terms:
        warnings.append("正文仍有分析或评测口吻（"+'、'.join(dict.fromkeys(analyst_terms))+"），请按A版像讲师一样自然汇报具体表现。")
    repeated_counts=set(re.findall(r"\d+\s*道",report['summary'])) & set(re.findall(r"\d+\s*道","\n".join(report['highlights'])))
    if repeated_counts:
        warnings.append("能力表现重复了摘要中的题目数量，请改为不同的具体表现和收获。")
    observations=[payload.get('subjective_observation',''),payload.get('supplements',''),*[p.get('observation','') for p in payload['problems']]]
    novelty_known=any(re.search(r'题目此前没做过|未做过的题|未见过的题|第一次遇到|新题迁移已验证',o) for o in observations)
    if not novelty_known:
        sentences=re.split(r'[。！？；\n]',report['summary']+'\n'+'\n'.join(report['highlights']))
        if any(re.search(r'(?:能|可以|能够).{0,12}(?:用|运用|应用|解决|完成).{0,6}新题',s)
            and not re.search(r'接下来|下一步|今后|未来|建议|下一阶段',s) for s in sentences):
            warnings.append("没有核实本期题目此前没做过，不能断言已能应用到新题；请肯定实际独立解题，新题应用作为后续练习方向。")
    if parent_problem_names(report,payload):
        warnings.append("家长正文仍出现原题名或逐题清单，请概括成孩子实际做到的事情和能力；原题名只保留在讲师材料中。")
    guided = [p for p in payload["problems"] if p.get("completion_context") == "practice_then_explanation"]
    if guided and all(p.get("pre_explanation_submissions") is None and not p.get("explanation_started_at") for p in guided):
        if re.search(r"讲解后|听讲后|听完.{0,4}讲解|听讲解后|根据讲解|听讲后", "\n".join([report["summary"], *report["highlights"]])):
            warnings.append("未记录讲解时点，不能断言某次修改或通过发生在讲解之后。")
    from .knowledge import event
    target_event = event(payload["target_year"])
    if target_event and target_event["first_date"] < str(payload["reference_date"]):
        if re.search(r"(?:离|距|距离)第一轮|第一轮.{0,12}(?:还有|还剩|剩余)|为第一轮.{0,8}(?:准备|模拟)|安排.{0,12}第一轮模拟", text):
            warnings.append("资料日期时第一轮已结束，不能把第一轮备考安排成未来任务。")
    if re.search(r"独立比赛题|题分|作品证据|证据强度", "\n".join([report["summary"], *report["highlights"], *report["next_steps"]])):
        warnings.append("正文含内部分析用语，请使用“比赛题”等自然表达。")
    technical=re.findall(r"计数方式|初始条件|加入记录|反复计算|输入输出|字符串遍历|最大规模|高位|代码变量|变量范围|状态转移|核对状态|二分边界|左右边界|边界数据|边界情况|选边连网|判断连通|关系合并|合并关系|数据溢出|代码版本|代码快照|图论|动态规划|二分(?:法|题|答案)?|拓扑排序|并查集|最近公共祖先|单调栈|优先队列|(?<![A-Za-z])(?:AC|WA|TLE|DFS|BFS|DP|LCA)(?![A-Za-z])", "\n".join([report["summary"], *report["highlights"], *report["next_steps"]]))
    if technical:
        warnings.append("成果、能力表现或训练建议仍含解法细节（"+'、'.join(dict.fromkeys(technical))+"），请把这些词改写为家长能理解的具体能力表现。")
    code_details=re.findall(r"同一个位置|起点|终点|下标|(?:代码|数据)编号|输出|字符串|枚举|递归|复杂度|访问标记|程序.{0,12}(?:重复|绕圈|处理位置|标记)",prose)
    if code_details:
        warnings.append("正文仍在描述程序实现（"+'、'.join(dict.fromkeys(code_details))+"），请像A版汇报理解、思考、动手成果和具体修改收获，不解释代码怎么运行。")
    prose="\n".join([report["summary"], *report["highlights"]])
    classroom=[p for p in payload['problems'] if (p.get('source') or {}).get('kind')!='contest' and p.get('completion_context')!='independent_timed_contest']
    if classroom and not any(p.get('independent') is True and p.get('editorial_seen') is False for p in classroom):
        for sentence in re.split(r'[。！？；\n]',prose):
            if re.search(r'课堂|课内练习',sentence) and re.search(r'独立|自己(?:找出|找到|发现|改正)|自主',sentence):
                warnings.append("课堂练习未记录独立完成条件，不能称为独立完成或自主找错；请描述完成情况和可核实的修改。")
                break
    from .evidence import source_context
    if any((source_context(p) or {}).get("submission_semantics")=="final_submission" for p in payload["problems"]) and re.search(r"(?:只|仅|都).{0,5}提交.{0,5}(?:一次|1次)",prose):
        warnings.append("OI最终代码记录不代表实际仅提交一次，请删除这种次数结论。")
    if re.search(r"(?:一次|一份).{0,25}(?:说明|可见|体现|因此|表明).{0,30}(?:检查|想清|认真|仔细|规划)",prose):
        warnings.append("不能从提交次数推断提前想清楚、认真或检查习惯。")
    if payload["problems"] and not any(o.strip() for o in observations) and all(len({s["code"] for s in p.get("submissions",[]) if s.get("code")})<=1 for p in payload["problems"]):
        if re.search(r"(?:继续|反复|多次|不断|主动).{0,5}(?:尝试|调整|修改|检查)|没有放弃|这种坚持|检查习惯",prose):
            warnings.append("没有修改过程或明确讲师观察，不能虚构继续尝试、反复调整或检查习惯；请肯定作品实际体现的理解、思考和实现能力。")
    if "稳" in text:
        warnings.append("含有“稳”类程度词，建议改成具体成果与能力表现。")
    if re.search(r"二分.{0,12}(每次|一半)|动态规划.{0,12}(记住|小问题)|就像|好比|相当于(安排|整理|寻找)", text):
        warnings.append("正文可能包含算法讲解或生活类比，请改为成果汇报。")
    return warnings

def anonymize(value, name):
    if isinstance(value, str):
        return value.replace(name, "{{student}}") if name else value
    if isinstance(value, dict):
        return {key: anonymize(item, name) for key, item in value.items()}
    if isinstance(value, list):
        return [anonymize(item, name) for item in value]
    return value
