from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class StudentInput(StrictModel):
    name: str = Field(min_length=1, max_length=50)
    age: int | None = Field(default=None, ge=5, le=25)
    grade: str = Field(default="", max_length=30)
    note: str = Field(default="", max_length=3000)
    background: str = Field(default="", max_length=12000)
    acgo_user_id: str = Field(default="", max_length=30, pattern=r"^\d*$")

class SubmissionInput(StrictModel):
    id: str = Field(min_length=1, max_length=40)
    submitted_at: datetime
    result: str = Field(max_length=2000)
    language: Literal["cpp", "python", "text"]
    code: str = Field(default="", max_length=100000)
    score: float | None = None
    cpu_ms: float | None = Field(default=None, ge=0)
    memory_bytes: int | None = Field(default=None, ge=0)
    gap_seconds: float | None = Field(default=None, ge=0)

class UnverifiedSubmission(StrictModel):
    id: str = Field(min_length=1,max_length=40)
    code: str = Field(max_length=100000)
    language: Literal["cpp","python","text"] = "cpp"
    source_file: str = Field(max_length=1000)
    note: str = Field(default="提交时间与逐次评测未核实，不作为本期能力证据",max_length=500)

class MaterialSource(StrictModel):
    platform: Literal["acgo", "csp_exam"] = "acgo"
    kind: Literal["homework", "contest"]
    task_id: str = Field(min_length=1, max_length=30)
    team_id: str = Field(min_length=1, max_length=80)
    user_id: str = Field(min_length=1, max_length=30)
    question_id: str = Field(min_length=1, max_length=30)
    contest_question_id: str = Field(default="", max_length=30)
    task_url: str = Field(max_length=1000)
    problem_url: str = Field(max_length=1000)
    fetched_at: datetime
    selected_submission_id: str = Field(max_length=40)
    period_start: date
    period_end: date
    tags: list[str] = Field(default_factory=list, max_length=40)
    warnings: list[str] = Field(default_factory=list, max_length=30)
    history_count: int = Field(ge=0)
    task_title: str = Field(default="", max_length=200)
    history_complete: bool = True
    reported_submission_count: int | None = Field(default=None,ge=0)
    practice_archive_id: str = Field(default="", max_length=100)
    assessment_tags: list[str] = Field(default_factory=list,max_length=16)
    contest_format: Literal["oi_csp","ioi","unknown"] = "unknown"
    submission_semantics: Literal["final_submission","online_history","unknown"] = "unknown"
    contest_duration_minutes: int | None = Field(default=None,ge=1,le=100000)

class ProblemInput(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    problem_id: str = Field(default="", max_length=80)
    statement: str = Field(default="", max_length=60000)
    code: str = Field(default="", max_length=100000)
    language: Literal["cpp", "python", "text"] = "cpp"
    independent: bool | None = None
    editorial_seen: bool | None = None
    minutes: int | None = Field(default=None, ge=1, le=100000)
    judge_result: str = Field(default="", max_length=2000)
    observation: str = Field(default="", max_length=4000)
    source: MaterialSource | None = None
    submissions: list[SubmissionInput] = Field(default_factory=list)
    unverified_submissions: list[UnverifiedSubmission] = Field(default_factory=list)
    completion_context: Literal["unspecified", "practice_then_explanation", "independent_timed_contest"] = "unspecified"
    pre_explanation_submissions: int | None = Field(default=None, ge=0)
    explanation_started_at: datetime | None = None
    submission_state: Literal["submitted", "no_submission", "no_submission_in_period", "unverified_time"] = "submitted"
    non_submission_reason: Literal["unknown", "not_yet_understood", "time_limit", "not_required", "other"] = "unknown"

    @model_validator(mode="after")
    def valid_attempt_context(self):
        if self.pre_explanation_submissions is not None and self.pre_explanation_submissions > len(self.submissions):
            raise ValueError("讲解前提交次数不能超过已有提交记录数")
        if self.explanation_started_at and self.explanation_started_at.tzinfo is None:
            raise ValueError("讲解时间必须包含时区")
        if self.submission_state != "submitted" and (self.code or self.submissions):
            raise ValueError("没有本期提交的题目不能带入代码作品，请核对状态")
        return self

class ACGOImportInput(StrictModel):
    student_id: str = Field(min_length=1, max_length=100)
    user_id: str = Field(min_length=1, max_length=30, pattern=r"^\d+$")
    team: str = Field(min_length=1, max_length=1000)
    kind: Literal["homework", "contest"]
    task: str = Field(min_length=1, max_length=20000)
    start_date: date
    end_date: date
    submission_mode: Literal["latest_history", "latest_only", "accepted_history"] = "latest_history"
    cdp_port: int = Field(default=9223, ge=1024, le=65535)
    contest_independent: bool = True
    concurrency: int = Field(default=3, ge=1, le=8)

    @model_validator(mode="after")
    def valid_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("学习结束日期不能早于开始日期")
        if self.end_date > datetime.now(ZoneInfo("Asia/Shanghai")).date():
            raise ValueError("导入学习时段不能包含未来日期")
        return self

class ACGOArchiveInput(StrictModel):
    name: str = Field(min_length=1, max_length=50)
    student_id: str = Field(default="", max_length=100)
    user_id: str = Field(default="", max_length=30, pattern=r"^\d*$")
    team: str = Field(default="", max_length=1000)
    homework: str = Field(default="", max_length=20000)
    contest: str = Field(default="", max_length=20000)
    start_date: date | None = None
    end_date: date | None = None
    age: int | None = Field(default=None, ge=5, le=25)
    grade: str = Field(default="", max_length=30)
    contest_independent: bool = True
    concurrency: int = Field(default=3, ge=1, le=8)
    csp_contests: list[str] = Field(default_factory=list)
    csp_exam_number: str = Field(default="", max_length=30)

    @model_validator(mode="after")
    def valid_archive(self):
        if not self.homework.strip() and not self.contest.strip() and not self.csp_contests:
            raise ValueError("请至少填写作业或比赛之一")
        if (self.homework.strip() or self.contest.strip()) and (not self.user_id or not self.team.strip()):
            raise ValueError("采集 ACGO 任务需要学生 ACGO ID 和团队 ID")
        if bool(self.start_date) != bool(self.end_date):
            raise ValueError("日期范围请同时填写开始和结束，或都留空自动按提交日期整理")
        if self.start_date and (self.start_date > self.end_date or self.end_date > datetime.now(ZoneInfo("Asia/Shanghai")).date()):
            raise ValueError("日期范围无效，不能包含未来日期")
        return self

class ZhouOJImportInput(StrictModel):
    student_id: str = Field(min_length=1,max_length=100)
    contests: str = Field(min_length=1,max_length=20000)
    exam_number: str = Field(default="",max_length=30)
    start_date: date
    end_date: date
    contest_independent: bool = True
    concurrency: int = Field(default=3,ge=1,le=8)

    @model_validator(mode="after")
    def valid_dates(self):
        if self.end_date<self.start_date or self.end_date>datetime.now(ZoneInfo("Asia/Shanghai")).date():
            raise ValueError("学习日期范围无效，不能包含未来日期")
        return self

class FeedbackInput(StrictModel):
    student_id: str
    start_date: date
    end_date: date
    tracks: list[Literal["J", "S"]] = Field(min_length=1, max_length=2)
    target_year: int = Field(ge=2019, le=2040)
    reference_date: date = Field(default_factory=lambda: datetime.now(ZoneInfo("Asia/Shanghai")).date())
    eligible: bool | None = None
    weekly_hours: float | None = Field(default=None, gt=0, le=60)
    topics: str = Field(default="", max_length=16000)
    supplements: str = Field(default="", max_length=12000)
    focus_score: int | None = Field(default=None, ge=1, le=100)
    focus_observation: str = Field(default="", max_length=3000)
    subjective_observation: str = Field(default="", max_length=5000)
    admissions: bool = False
    admissions_year: int | None = Field(default=None, ge=2020, le=2040)
    target_schools: list[str] = Field(default_factory=list, max_length=10)
    problems: list[ProblemInput] = Field(default_factory=list)
    mode: Literal["live", "demo"] = "live"

    @model_validator(mode="after")
    def validate_period(self):
        if self.end_date < self.start_date:
            raise ValueError("学习结束日期不能早于开始日期")
        if self.end_date > self.reference_date:
            raise ValueError("学习结束日期不能晚于资料基准日期")
        self.tracks = list(dict.fromkeys(self.tracks))
        if not self.topics.strip() and not self.problems and not self.supplements.strip():
            raise ValueError("请至少提供一项本期学习成果")
        for problem in self.problems:
            if problem.source and (problem.source.period_start != self.start_date or problem.source.period_end != self.end_date):
                raise ValueError("平台材料的采集时段与反馈时段不一致，请重新采集")
            for submission in problem.submissions:
                if submission.submitted_at.tzinfo is None:
                    raise ValueError("平台提交时间必须包含时区")
                day = submission.submitted_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
                if not self.start_date <= day <= self.end_date:
                    raise ValueError("平台提交记录不在本期学习时段内，请重新采集")
        return self

class TopicScore(StrictModel):
    id: str
    score: int | None = Field(default=None, ge=1, le=100)
    evidence: list[str] = Field(default_factory=list)
    reason: str = Field(max_length=1000)
    scope: str = Field(default="", max_length=400)

class AbilityScore(StrictModel):
    id: Literal["A01", "A02", "A03", "A04", "A05", "A06"]
    score: int | None = Field(default=None, ge=1, le=100)
    evidence: list[str] = Field(default_factory=list)
    reason: str = Field(max_length=1000)
    source: Literal["api", "teacher", "demo"] = "api"

class Analysis(StrictModel):
    topic_scores: list[TopicScore]
    abilities: list[AbilityScore]

class Diagnosis(StrictModel):
    problem_index: int
    solution: str
    correctness: str
    efficiency: str
    implementation: str
    readability: str
    observed_behaviors: list[str]
    parent_observations: list[str] = Field(default_factory=list, max_length=4)
    topic_ids: list[str]
    evidence: list[str]
    limitations: list[str]
    early_attempts: str = Field(default="", max_length=3000)
    changes: str = Field(default="", max_length=3000)
    completion_basis: str = Field(default="", max_length=1500)

class TaskForecast(StrictModel):
    problem_id: str
    lower: float = Field(ge=0, le=100)
    upper: float = Field(ge=0, le=100)
    reason: str
    evidence: list[str]

class PaperForecast(StrictModel):
    track: Literal["J", "S"]
    year: int
    tasks: list[TaskForecast]
    assumptions: list[str]

class Forecasts(StrictModel):
    papers: list[PaperForecast]
    limitations: list[str]

class TrainingItem(StrictModel):
    title: str = Field(min_length=1, max_length=80)
    activity: str = Field(min_length=1, max_length=600)
    success: str = Field(min_length=1, max_length=300)
    evidence: list[str] = Field(default_factory=list)
    collection_id: str = Field(default="", max_length=30)
    practice_mode: Literal["new", "review"] = "new"

class Training(StrictModel):
    horizon: str
    recent: list[TrainingItem] = Field(min_length=1)
    phases: list[dict] = Field(default_factory=list, max_length=6)

class ParentCopy(StrictModel):
    summary: str = Field(min_length=1, max_length=240)
    highlights: list[str] = Field(min_length=1, max_length=6)
    next_steps: list[str] = Field(min_length=1, max_length=3)

class Position(StrictModel):
    track: Literal["J", "S"]
    label: str = Field(min_length=1, max_length=160)
    basis: str = Field(default="", max_length=400)

class PracticeQuestion(StrictModel):
    id: str
    title: str
    url: str

class PracticeRecommendation(StrictModel):
    collection_id: str
    title: str
    url: str
    questions: list[PracticeQuestion] = Field(default_factory=list, max_length=6)
    practice_mode: Literal["new", "review"] = "new"

class ParentReport(ParentCopy):
    # Teachers may expand an audited draft; long reports retain pagination.
    summary: str = Field(min_length=1, max_length=1200)
    title: str = Field(default="", max_length=120)
    positions: list[Position] = Field(max_length=2)
    admissions_text: str = Field(default="", max_length=1200)
    admissions_sources: list[dict] = Field(default_factory=list)
    teacher: str = Field(default="", max_length=50)
    topic_scores: list[TopicScore]
    abilities: list[AbilityScore]
    practice_recommendations: list[PracticeRecommendation] = Field(default_factory=list)

class ReviewInput(StrictModel):
    revision: int
    report: ParentReport

class MaterialsEdit(StrictModel):
    revision: int = Field(ge=0)
    input: FeedbackInput

class SettingsInput(StrictModel):
    api_key: str | None = Field(default=None, max_length=1000)
    base_url: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=100)
    analysis_concurrency: int | None = Field(default=None, ge=1, le=8)
