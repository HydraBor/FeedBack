"""Import a private roster's materials and generate review drafts through the local API.

The JSON config and progress remain private. Re-run with the same state file to
resume; this script never confirms reports or copies another student's profile.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import fcntl
import json
from pathlib import Path
import time
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx


def write_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.chmod(0o600)
    temporary.replace(path)


def build_report(archive, config):
    content = archive['content']
    problems = deepcopy(content['problems'])
    for problem in problems:
        if problem.get('source'):
            problem['source']['practice_archive_id'] = archive['id']
    # Preserve all source identities, incomplete histories and unsubmitted work.
    return {'student_id': archive['student_id'], 'start_date': content['start_date'],
            'end_date': content['end_date'], 'reference_date': config['reference_date'],
            'tracks': config['tracks'], 'target_year': config['target_year'],
            'problems': problems, 'mode': 'live'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--state', required=True, type=Path)
    args = parser.parse_args()
    args.state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = args.state.with_suffix('.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('This batch is already being processed') from None
    config = json.loads(args.config.read_text())
    base_url = config.get('base_url', 'http://127.0.0.1:8765')
    if urlparse(base_url).hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Only the local feedback service is allowed')
    members = [dict(m) for m in config['members'] if m['user_id'] not in config.get('skip_user_ids', [])]
    if any(not m['name'].strip() for m in members) or len({m['user_id'] for m in members}) != len(members):
        raise ValueError('Roster must have real remark names and unique ACGO IDs')
    state = json.loads(args.state.read_text()) if args.state.exists() else {'config': config, 'students': members}
    if state['config'] != config:
        raise ValueError('Config changed: use another state file to avoid mixing batches')
    for member in state['students']:
        member.setdefault('phase', 'pending')
        member.setdefault('analysis_retries', 0)
    previous = None
    with httpx.Client(base_url=base_url, trust_env=False, timeout=60) as client:
        def request(method, path, body=None):
            response = client.request(method, path, **({'json': body} if body is not None else {}))
            if not response.is_success:
                raise RuntimeError(f'{method} {path}: HTTP {response.status_code}: {response.text[:400]}')
            return response.json()

        request('GET', '/api/health')
        while True:
            summaries = {r['id']: r for r in request('GET', '/api/reports')}
            for member in state['students']:
                report_id = member.get('report_id')
                if not report_id:
                    continue
                report = summaries.get(report_id)
                if not report:
                    raise RuntimeError('A saved report disappeared; batch stopped to prevent duplicates')
                member['stage'] = report['stage']
                if report['status'] in ('review', 'confirmed'):
                    if member['phase'] != 'completed':
                        detail = request('GET', f'/api/reports/{report_id}')
                        member.update(phase='completed', warnings=detail.get('warnings', []),
                                      report_url=f'{base_url}/?report={report_id}')
                        member.pop('error', None)
                elif report['status'] == 'failed':
                    member['error'] = report['error']
                    if member['analysis_retries'] < 3:
                        member['analysis_retries'] += 1
                        request('POST', f'/api/reports/{report_id}/generate', {})
                        member['phase'] = 'analyzing'
                    else:
                        member['phase'] = 'analysis_failed'
                elif report['status'] == 'draft':
                    request('POST', f'/api/reports/{report_id}/generate', {})
                    member['phase'] = 'analyzing'
                else:
                    member['phase'] = 'analyzing'

            importing = next((m for m in state['students'] if m['phase'] == 'importing'), None)
            if importing:
                response = client.get('/api/practice-archives/imports/' + importing['import_id'])
                if response.status_code == 404:
                    importing.update(phase='import_failed', error='Import task expired; inspect existing archives before restarting')
                else:
                    response.raise_for_status()
                    job = response.json()
                    importing['stage'] = job['progress']
                    if job['status'] == 'completed':
                        result = job['result']
                        importing.update(archive_id=result['archive_id'], student_id=result['student_id'])
                        archive = request('GET', '/api/practice-archives/' + result['archive_id'])
                        content = archive['content']
                        importing.update(problem_count=len(content['problems']),
                                         submission_count=sum(len(p['submissions']) for p in content['problems']),
                                         unsubmitted_count=sum(p['submission_state'] != 'submitted' for p in content['problems']),
                                         failed_tasks=content['failed_tasks'], failed_questions=content['failed_questions'])
                        if content['failed_tasks'] or content['failed_questions']:
                            importing.update(phase='import_failed', error='Some source tasks/questions failed; inspect before generating')
                        else:
                            report = request('POST', '/api/reports', build_report(archive, config))
                            importing.update(report_id=report['id'], phase='analyzing')
                            write_private(args.state, state)
                            request('POST', '/api/reports/' + report['id'] + '/generate', {})
                    elif job['status'] in ('failed', 'cancelled'):
                        importing.update(phase='import_failed', error=job['error'])

            if not any(m['phase'] == 'importing' for m in state['students']):
                pending = next((m for m in state['students'] if m['phase'] == 'pending'), None)
                if pending:
                    payload = {'name': pending['name'], 'user_id': pending['user_id'],
                               'team': config['team_id'], 'homework': config['homework'],
                               'csp_contests': config['zhou_contests'], 'start_date': config['start_date'],
                               'end_date': config['end_date'], 'contest_independent': True, 'concurrency': 3}
                    job = request('POST', '/api/practice-archives/imports', payload)
                    pending.update(import_id=job['id'], phase='importing')

            state['updated_at'] = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
            write_private(args.state, state)
            progress = [(m['name'], m['phase'], m.get('stage', '')) for m in state['students']]
            if progress != previous:
                print(json.dumps({'at': state['updated_at'], 'students': progress}, ensure_ascii=False), flush=True)
                previous = progress
            if all(m['phase'] in ('completed', 'import_failed', 'analysis_failed') for m in state['students']):
                return 0 if all(m['phase'] == 'completed' for m in state['students']) else 1
            time.sleep(5)


if __name__ == '__main__':
    raise SystemExit(main())
