"""회차별 모션 기록 조회 · 날짜 목록 · 회차 목록 · 그래프 자료 · 이름 검사."""

import json

import pytest

from motion_web_bridge.motion_trace_service import MAX_CHART_POINTS, MotionTraceService


class FakeRepository:
    def __init__(self, root, project_id='p1'):
        self.root = root
        self.project_id = project_id

    def selected_project_id(self):
        return self.project_id

    def project_logs_dir(self, project_id):
        path = self.root / project_id / 'logs'
        path.mkdir(parents=True, exist_ok=True)
        return path


def _write_day(root, date='2026-10-01', rows=3):
    day = root / 'p1' / 'logs' / 'motion_trace' / date
    day.mkdir(parents=True)
    lines = ['time_sec,1-1_target_deg,1-1_actual_deg,1-1_error_deg']
    lines += [f'{i * 0.02:.3f},{i:.4f},{i - 0.1:.4f},-0.1000' for i in range(rows)]
    (day / '100000_c0001_m.csv').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    records = [
        {'file': '100000_c0001_m.csv', 'started_at': 1.0, 'cycle': 1, 'result': 'completed'},
        {'file': '100500_c0002_m.csv', 'started_at': 2.0, 'cycle': 2, 'result': 'stopped'},
    ]
    (day / 'index.jsonl').write_text(
        '\n'.join(json.dumps(r) for r in records) + '\nnot json\n', encoding='utf-8'
    )
    return day


def test_days_and_runs_newest_first(tmp_path):
    _write_day(tmp_path)
    service = MotionTraceService(FakeRepository(tmp_path))
    days = service.days()
    assert [d['date'] for d in days['days']] == ['2026-10-01']
    assert days['days'][0]['cycle_count'] == 2
    runs = service.runs('2026-10-01')['runs']
    assert [r['cycle'] for r in runs] == [2, 1]
    assert [r['file_exists'] for r in runs] == [False, True]


def test_trace_returns_target_and_actual_per_axis(tmp_path):
    _write_day(tmp_path)
    trace = MotionTraceService(FakeRepository(tmp_path)).trace('2026-10-01', '100000_c0001_m.csv')
    assert trace['time'] == [0.0, 0.02, 0.04]
    axis = trace['axes'][0]
    assert axis['motion_id'] == '1-1'
    assert axis['target'] == [0.0, 1.0, 2.0]
    assert axis['actual'] == [-0.1, 0.9, 1.9]
    assert trace['record']['cycle'] == 1


def test_long_trace_is_decimated_but_keeps_the_last_sample(tmp_path):
    _write_day(tmp_path, rows=MAX_CHART_POINTS * 2 + 5)
    trace = MotionTraceService(FakeRepository(tmp_path)).trace('2026-10-01', '100000_c0001_m.csv')
    assert len(trace['time']) <= MAX_CHART_POINTS + 1
    assert trace['axes'][0]['target'][-1] == float(MAX_CHART_POINTS * 2 + 4)


@pytest.mark.parametrize('date,name', [
    ('../p2', '100000_c0001_m.csv'),
    ('2026-10-01', '../index.jsonl'),
    ('2026-10-01', 'index.jsonl'),
    ('2026-10-02', '100000_c0001_m.csv'),
])
def test_paths_outside_the_trace_folder_are_refused(tmp_path, date, name):
    _write_day(tmp_path)
    with pytest.raises(ValueError):
        MotionTraceService(FakeRepository(tmp_path)).file_path(date, name)


def test_no_project_selected_is_not_an_error(tmp_path):
    service = MotionTraceService(FakeRepository(tmp_path, project_id=''))
    assert service.days()['days'] == []
    assert service.runs('2026-10-01')['runs'] == []


def test_delete_day(tmp_path):
    day = _write_day(tmp_path)
    result = MotionTraceService(FakeRepository(tmp_path)).delete_day('2026-10-01')
    assert not day.exists()
    assert result['days'] == []
