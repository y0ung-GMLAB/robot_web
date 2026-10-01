"""회차별 모션 기록 · 목표·실제를 CSV 로 · 재생 루프는 붙이기만 한다.

지키는 것
- 실제 위치는 모션축 설정의 변환식을 거꾸로 돌려 조인트 deg 로 남긴다
- 오래된 실제 위치는 비워 둔다 (모터 노드가 멈췄을 때 엉뚱한 값을 남기지 않는다)
- 스튜디오 재생은 기록하지 않는다
- 보존 기간·용량을 넘으면 오래된 것부터 지운다
"""

import csv
import json
import os
import time

from motion_runtime.motion_trace import (
    INDEX_FILENAME,
    MotionTraceRecorder,
    joint_from_motor,
)

ROW = {
    'reference_position_deg': 1000.0,
    'offset_deg': 0.5,
    'scale': 1.0,
    'gear_ratio': 150.0,
    'invert': True,
}


def _plan(**over):
    plan = {
        'project_id': 'p1',
        'motion_file_id': 'clip A.json',
        'mapping_file_id': 'map.yaml',
        'request_source': 'motion_run',
        'run_mode': 'continuous',
        'repeat_mode': 'reinitialize',
        'axes': [{'motion_id': '1-1', 'motor_axis': 0, 'row': ROW}],
        'summary': {'period_sec': 0.02, 'duration_sec': 0.04},
    }
    plan.update(over)
    return plan


def _motor(joint):
    # motion_run_rules._motor_target 과 같은 식
    return 1000.0 + (joint + 0.5) * 1.0 * -1.0 * 150.0


def _recorder(**over):
    options = dict(decode=lambda raw: dict(raw), enabled=True)
    options.update(over)
    return MotionTraceRecorder(**options)


def test_joint_from_motor_inverts_the_mapping_formula():
    assert abs(joint_from_motor(ROW, _motor(3.25)) - 3.25) < 1e-9
    assert joint_from_motor({**ROW, 'reference_enabled': False}, -525.0) == 3.0


def test_cycle_is_written_as_csv_with_index(tmp_path):
    recorder = _recorder()
    trace = recorder.begin(_plan(), 3, tmp_path)
    for i, joint in enumerate((0.0, 1.0, 2.0)):
        recorder.on_motor_status({0: _motor(joint - 0.1)})   # 실제는 0.1° 늦다
        trace.add({'time_sec': i * 0.02, 'positions': {0: _motor(joint)}, 'motion_values': {'1-1': joint}})
    path = recorder.write(trace, 'completed')
    recorder.close()

    assert path.parent.parent.name == 'motion_trace'
    assert path.name.endswith('_c0003_clip_A.csv')
    rows = list(csv.reader(path.open(encoding='utf-8')))
    assert rows[0] == ['time_sec', '1-1_target_deg', '1-1_actual_deg', '1-1_error_deg']
    assert rows[2] == ['0.020', '1.0000', '0.9000', '-0.1000']

    record = json.loads((path.parent / INDEX_FILENAME).read_text(encoding='utf-8').splitlines()[-1])
    assert record['file'] == path.name
    assert record['result'] == 'completed'
    assert record['cycle'] == 3
    assert record['sample_count'] == 3
    assert record['axes'][0]['max_abs_error_deg'] == 0.1
    assert record['axes'][0]['rms_error_deg'] == 0.1


def test_target_falls_back_to_motor_position_when_motion_values_missing(tmp_path):
    recorder = _recorder()
    trace = recorder.begin(_plan(), 1, tmp_path)
    recorder.on_motor_status({0: _motor(2.0)})
    trace.add({'time_sec': 0.0, 'positions': {0: _motor(2.0)}})
    header, rows, _summary, _missing = recorder.build(trace)
    recorder.close()
    assert rows[0][1:] == ['2.0000', '2.0000', '0.0000']


def test_stale_actual_position_is_left_blank(tmp_path):
    recorder = _recorder(stale_sec=0.05)
    trace = recorder.begin(_plan(), 1, tmp_path)
    recorder._latest = ({0: _motor(1.0)}, time.monotonic() - 1.0)
    trace.add({'time_sec': 0.0, 'positions': {0: _motor(1.0)}, 'motion_values': {'1-1': 1.0}})
    _header, rows, summary, missing = recorder.build(trace)
    recorder.close()
    assert rows[0] == ['0.000', '1.0000', '', '']
    assert missing == 1
    assert summary[0]['max_abs_error_deg'] is None


def test_studio_playback_and_disabled_recorder_record_nothing(tmp_path):
    recorder = _recorder()
    assert recorder.begin(_plan(request_source='motion_studio'), 1, tmp_path) is None
    recorder.close()
    off = _recorder(enabled=False)
    assert off.begin(_plan(), 1, tmp_path) is None
    off.close()


def test_writer_thread_writes_finished_cycles(tmp_path):
    recorder = _recorder()
    trace = recorder.begin(_plan(), 1, tmp_path)
    recorder.on_motor_status({0: _motor(0.0)})
    trace.add({'time_sec': 0.0, 'positions': {0: _motor(0.0)}, 'motion_values': {'1-1': 0.0}})
    recorder.finish(trace, 'stopped', '회차 도중 정지')
    recorder.close()
    record = json.loads((trace.directory / INDEX_FILENAME).read_text(encoding='utf-8'))
    assert record['result'] == 'stopped'
    assert record['message'] == '회차 도중 정지'


def test_prune_drops_old_days_and_oldest_files_over_the_cap(tmp_path):
    root = tmp_path / 'motion_trace'
    (root / '2000-01-01').mkdir(parents=True)
    (root / '2000-01-01' / 'a.csv').write_text('x')
    today = time.strftime('%Y-%m-%d')
    (root / today).mkdir()
    for name in ('100000_c0001_m.csv', '110000_c0002_m.csv', '120000_c0003_m.csv'):
        (root / today / name).write_bytes(b'0' * (600 * 1024))

    recorder = _recorder(retention_days=7, max_bytes=1024 * 1024)
    recorder.prune(root, force=True)
    recorder.close()

    assert not (root / '2000-01-01').exists()
    assert sorted(os.listdir(root / today)) == ['120000_c0003_m.csv']
