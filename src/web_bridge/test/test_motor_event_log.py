from pathlib import Path

from motion_web_bridge.motor_event_log import MotorEventLog
from motion_web_bridge.project_repository import ProjectRepository


class _Logger:
    def error(self, message):
        pass

    def warn(self, message):
        pass


def event_log_bridge(tmp_path: Path, repository=None) -> MotorEventLog:
    """노드 없이 로그 서비스만 세운다 · §6-17로 노드에서 떨어져 나왔다."""
    return MotorEventLog(
        log_dir=tmp_path,
        retention_days=30,
        max_bytes=100 * 1024 * 1024,
        max_records=5000,
        max_files=30,
        repository=repository,
        workspace_root=tmp_path,
        runtime_project_id=lambda: '',
        logger=_Logger,
    )


def test_records_motor_error_transition_once(tmp_path):
    bridge = event_log_bridge(tmp_path)
    state = {
        'motors': [{
            'controller_index': 2,
            'display_name': 'Axis motor',
            'motor_type_label': 'AC Servo',
            'fault': True,
            'errorcode': 0x2310,
            'errorcode_hex': '0x2310',
            'error_text': 'Over current',
            'statusword': 0x0008,
        }],
    }

    bridge.record_motor_error_transitions(state)
    bridge.record_motor_error_transitions(state)

    events = bridge.events()['events']
    assert len(events) == 1
    assert events[0]['category'] == 'error'
    assert events[0]['details']['axis'] == 2


def test_records_motion_lifecycle_transitions(tmp_path):
    bridge = event_log_bridge(tmp_path)
    base = {
        'motion_file_id': 'sample.json',
        'mapping_file_id': 'sample_mapping.yaml',
        'axes': [{'motor_axis': 0}, {'motor_axis': 2}],
        'run_mode': 'once',
    }

    bridge.record_motion_run_transition({**base, 'state': 'idle'})
    bridge.record_motion_run_transition({**base, 'state': 'initializing'})
    bridge.record_motion_run_transition({**base, 'state': 'initialized'})
    bridge.record_motion_run_transition({**base, 'state': 'running'})
    bridge.record_motion_run_transition({**base, 'state': 'running'})

    events = list(reversed(bridge.events()['events']))
    assert [event['event_type'] for event in events] == [
        'initial_position_started',
        'initial_position_completed',
        'single_motion_started',
    ]
    assert events[-1]['content'].startswith('1회 재생 시작')
    assert events[-1]['details']['run_mode'] == 'once'


def test_records_continuous_motion_start_separately(tmp_path):
    bridge = event_log_bridge(tmp_path)
    base = {
        'motion_file_id': 'sample.json',
        'mapping_file_id': 'sample_mapping.yaml',
        'axes': [{'motor_axis': 0}],
        'run_mode': 'continuous',
    }

    bridge.record_motion_run_transition({**base, 'state': 'initialized'})
    bridge.record_motion_run_transition({**base, 'state': 'running'})

    event = bridge.events()['events'][0]
    assert event['event_type'] == 'continuous_motion_started'
    assert event['content'].startswith('연속 재생 시작')
    assert event['details']['run_mode'] == 'continuous'


def test_clear_motor_events_removes_log_files(tmp_path):
    bridge = event_log_bridge(tmp_path)
    bridge.append('motion', 'motion_started', 'sample.json', '모션 시작')

    result = bridge.clear()

    assert result['success'] is True
    assert result['deleted_files'] == 1
    assert bridge.events()['events'] == []


def test_project_logs_are_stored_in_runtime_project(tmp_path):
    repository = ProjectRepository(tmp_path / 'motion_projects')
    runtime_id = repository.create_project('runtime')['project']['project_id']
    selected_id = repository.create_project('selected')['project']['project_id']
    bridge = event_log_bridge(tmp_path / 'legacy_logs', repository=repository)
    bridge.workspace_root = tmp_path
    bridge.runtime_project_id = lambda: runtime_id

    bridge.append('motion', 'motion_started', 'sample.json', '모션 시작')

    assert bridge.events()['project_id'] == selected_id
    assert bridge.events()['events'] == []
    repository.select_project(runtime_id)
    result = bridge.events()
    assert result['project_id'] == runtime_id
    assert len(result['events']) == 1
    assert list((tmp_path / 'motion_projects' / runtime_id / 'logs').glob('*.jsonl'))


def test_event_log_record_limit_keeps_latest_records(tmp_path):
    bridge = event_log_bridge(tmp_path)
    bridge.max_records = 3
    for index in range(5):
        bridge.append('motion', 'motion_started', str(index), f'기록 {index}')

    result = bridge.events(limit=10)

    assert result['max_records'] == 3
    assert [event['content'] for event in reversed(result['events'])] == [
        '기록 2', '기록 3', '기록 4',
    ]


def test_append_under_the_limits_does_not_reread_or_rewrite(tmp_path, monkeypatch):
    """수정 목록 130 · 전에는 한 줄마다 모든 파일을 읽고 오늘 파일을 통째로 다시 썼다(fsync) ·
    그동안 락을 쥐어 브리지 ROS 콜백(10 Hz 모터 상태)까지 섰고 그룹 기록이 2 s 를 넘겼다"""
    from motion_web_bridge import motor_event_log

    bridge = event_log_bridge(tmp_path)
    rewrites = []
    monkeypatch.setattr(
        motor_event_log.store, 'atomic_write_text',
        lambda path, text, **_kwargs: rewrites.append(path),
    )
    reads = []
    real_lines = motor_event_log._event_log_lines
    monkeypatch.setattr(
        motor_event_log, '_event_log_lines',
        lambda path: reads.append(path) or real_lines(path),
    )
    for index in range(50):
        bridge.append('motion', 'motion_started', str(index), f'기록 {index}')

    assert rewrites == []
    assert len(reads) <= 1, '처음 한 번만 센다'
    monkeypatch.setattr(motor_event_log, '_event_log_lines', real_lines)
    assert len(bridge.events(limit=100)['events']) == 50


def test_over_the_limit_trims_to_ninety_percent_then_appends_without_rewrite(tmp_path, monkeypatch):
    from motion_web_bridge import motor_event_log

    bridge = event_log_bridge(tmp_path)
    bridge.max_records = 20
    for index in range(21):
        bridge.append('motion', 'motion_started', str(index), f'기록 {index}')
    contents = [event['content'] for event in reversed(bridge.events(limit=100)['events'])]
    assert contents == [f'기록 {index}' for index in range(3, 21)]

    rewrites = []
    real_write = motor_event_log.store.atomic_write_text
    monkeypatch.setattr(
        motor_event_log.store, 'atomic_write_text',
        lambda path, text, **kwargs: rewrites.append(path) or real_write(path, text, **kwargs),
    )
    for index in range(21, 23):
        bridge.append('motion', 'motion_started', str(index), f'기록 {index}')
    assert rewrites == []
    assert len(bridge.events(limit=100)['events']) == 20
    bridge.append('motion', 'motion_started', '23', '기록 23')
    assert len(rewrites) == 1
    assert len(bridge.events(limit=100)['events']) == 18


def test_old_days_are_still_dropped_on_the_first_write(tmp_path):
    bridge = event_log_bridge(tmp_path)
    bridge.retention_days = 2
    (tmp_path / '2000-01-01.jsonl').write_text('{"content":"옛"}\n', encoding='utf-8')

    bridge.append('motion', 'motion_started', 'a', '오늘')

    assert not (tmp_path / '2000-01-01.jsonl').exists()


def test_delete_single_event_log_file(tmp_path):
    bridge = event_log_bridge(tmp_path)
    bridge.append('motion', 'motion_started', 'sample.json', '모션 시작')
    file_name = bridge.events()['files'][0]['name']

    result = bridge.delete_file(file_name)

    assert result['deleted_file'] == file_name
    assert bridge.events()['files'] == []
