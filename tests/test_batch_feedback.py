from copy import deepcopy

from backend.models import FeedbackInput
from scripts.batch_feedback import build_report, write_private


def test_batch_preserves_student_work_and_archive_source_without_copying_a_profile(tmp_path):
    archive = {'id': 'archive-a', 'student_id': 'student-a', 'content': {
        'start_date': '2026-10-01', 'end_date': '2026-10-05', 'problems': [{
            'title': '未提交的课堂题目', 'code': '', 'submission_state': 'no_submission',
            'source': {'platform': 'acgo', 'kind': 'homework', 'task_id': '101', 'team_id': '200',
                       'user_id': '300', 'question_id': '400', 'task_url': 'https://www.acgo.cn/homework/101',
                       'problem_url': 'https://www.acgo.cn/problemset/info/400',
                       'fetched_at': '2026-10-09T10:00:00+08:00', 'selected_submission_id': '',
                       'period_start': '2026-10-01', 'period_end': '2026-10-05', 'history_count': 0}}]}}
    original = deepcopy(archive)
    config = {'reference_date': '2026-10-09', 'tracks': ['J', 'S'], 'target_year': 2026,
              'age': 13, 'background': '其他学生的获奖经历', 'eligible': True,
              'subjective_observation': '其他学生的观察'}
    payload = FeedbackInput.model_validate(build_report(archive, config))
    assert payload.student_id == 'student-a'
    assert payload.problems[0].source.practice_archive_id == 'archive-a'
    assert payload.problems[0].submission_state == 'no_submission'
    assert payload.subjective_observation == '' and payload.eligible is None
    assert archive == original
    path = tmp_path / 'private/state.json'
    write_private(path, {'report_id': 'report-a'})
    assert path.stat().st_mode & 0o777 == 0o600
    assert not path.with_suffix('.tmp').exists()
