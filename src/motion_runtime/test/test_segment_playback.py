"""구간 재생 · 재생 목록 1번을 m:ss 부터 (끝까지) · 계획 자르기 · 1회 · 연속 · 그룹 (2026-10-16)

계획(20 ms 재샘플)을 [시작, 끝] 으로 자르고 0 부터 다시 센다 · 초기 위치는 구간 시작 자세 ·
범위 자르기 · 속도·가속 검사는 잘린 구간만 본다 · 구간이면 재생 목록 2번부터는 쓰지 않는다.
"""

import math
import threading
import time
from unittest import mock

import pytest

from motion_runtime import motion_run_rules
from motion_runtime.group_session import GroupSession
from motion_runtime.motion_player import MotionPlayer
from motion_runtime.motion_run_manager import MotionRunManager
from motion_runtime.plan_builder import PlanBuilder


@pytest.fixture(autouse=True)
def _restore_patched_rules():
    yield
    mock.patch.stopall()


def _patch_rule(name, value):
    mock.patch.object(motion_run_rules, name, value).start()


def _row(motion_id, motor_ref, **overrides):
    row = {
        'motion_id': motion_id,
        'enabled': True,
        'motor_ref': motor_ref,
        'reference_enabled': True,
        'reference_position_deg': 0.0,
        'motion_lower_deg': -180.0,
        'motion_upper_deg': 180.0,
        'range_confirmed': True,
        'initial_mode': 'first_frame',
        'initial_move_time_sec': 5.0,
        'invert': False,
        'offset_deg': 0.0,
        'scale': 1.0,
        'gear_ratio': 1.0,
    }
    row.update(overrides)
    return row


#: 4 s 애니메이션 · 0.02 에서 시작(파일 frame 1) · 값 = sin · 1-2 는 반대 부호
def _wave(motion_ids=('1-1', '1-2'), length=4.0, spike_at=None):
    count = int(round(length / 0.02)) + 1
    records = []
    for index in range(count):
        t = 0.02 + index * 0.02
        value = 0.3 * math.sin(t)
        if spike_at is not None and abs(t - (0.02 + spike_at)) < 1e-9:
            value += 0.5   # 한 프레임 튐 · 속도 상한을 넘게
        for sign, motion_id in zip((1.0, -1.0), motion_ids):
            records.append({'motion_id': motion_id, 'time_sec': t, 'value': sign * value, 'frame': index + 1})
    return records


def _manager(mapping, records_by_file):
    manager = MotionRunManager.__new__(MotionRunManager)
    manager._player = MotionPlayer(manager)
    manager._plan_builder = PlanBuilder(manager)
    manager._run_lock = threading.RLock()
    manager.period_sec = 0.02
    manager._mapping_file_path = lambda _file_id: None
    manager._load_mapping = lambda _path: mapping
    manager._motion_file_path = lambda file_id: file_id
    manager._load_motion_records = lambda path: [dict(r) for r in records_by_file[path]]
    refs = [row['motor_ref'] for row in mapping['mappings']]
    manager._current_motors = lambda: [
        {'axis': index, 'controller_index': index, 'motor_ref': ref} for index, ref in enumerate(refs)
    ]
    manager._motor_for_axis = lambda axis, motors: next(
        (motor for motor in motors if motor['controller_index'] == axis), None
    )
    _patch_rule('_motor_ready_error', lambda _motor: '')
    _patch_rule('_target_range_limit_error', lambda _motor, _low, _high: '')
    _patch_rule('_motor_type', lambda _motor: 'ac_servo')
    _patch_rule('_motors_for_ref', lambda ref, motors: [m for m in motors if m.get('motor_ref') == ref])
    return manager


def _mapping(playlist=('a.json',), **row_overrides):
    mapping = {
        'motion_file_id': playlist[0],
        'mappings': [_row('1-1', 'ac:0', **row_overrides), _row('1-2', 'ac:1', **row_overrides)],
    }
    if len(playlist) > 1:
        mapping['motion_playlist'] = list(playlist)
    return mapping


def _build(manager, *, init=False, **payload):
    return manager._plan_builder.build(
        {'motion_file_id': 'a.json', 'mapping_file_id': 'm.yaml', **payload}, initialization_only=init,
    )


def _value(samples, index, motion_id='1-1'):
    return samples[index]['motion_values'][motion_id]


def test_whole_file_plan_is_unchanged_without_a_segment():
    manager = _manager(_mapping(), {'a.json': _wave()})
    plan = _build(manager)
    assert plan['segment_start_sec'] == 0.0 and plan['segment_end_sec'] == 0.0
    assert plan['summary']['duration_sec'] == pytest.approx(4.0)
    assert len(plan['samples']) == 201


def test_segment_plan_starts_at_zero_and_matches_the_file_read_from_the_start_time():
    manager = _manager(_mapping(), {'a.json': _wave()})
    whole = _build(manager)
    plan = _build(manager, segment={'start_sec': 1.0, 'end_sec': 2.5})

    assert plan['segment_start_sec'] == 1.0
    assert plan['segment_end_sec'] == 2.5
    assert plan['source_duration_sec'] == pytest.approx(4.0)
    assert plan['summary']['duration_sec'] == pytest.approx(1.5)
    assert plan['summary']['segment_start_sec'] == 1.0
    samples = plan['samples']
    assert samples[0]['time_sec'] == 0.0
    assert samples[-1]['time_sec'] == pytest.approx(1.5)
    assert len(samples) == 76   # 1.5 s / 20 ms + 1 · 20 ms 칸 그대로
    # 1.0 s = 50 칸 · 같은 시각의 통째 계획 값과 같다 (보간점만 더했다)
    for index in (0, 1, 37, 75):
        assert _value(samples, index) == pytest.approx(_value(whole['samples'], 50 + index))
        assert _value(samples, index, '1-2') == pytest.approx(_value(whole['samples'], 50 + index, '1-2'))
        assert samples[index]['positions'][0] == pytest.approx(whole['samples'][50 + index]['positions'][0])


def test_off_grid_start_interpolates_the_exact_first_frame():
    manager = _manager(_mapping(), {'a.json': _wave()})
    plan = _build(manager, segment_start_sec=1.013)
    # 파일 시각 1.033 · 1.02 와 1.04 칸 사이 선형 (재생 보간과 같은 규칙)
    low, high = 0.3 * math.sin(1.02), 0.3 * math.sin(1.04)
    assert _value(plan['samples'], 0) == pytest.approx(low + (high - low) * 0.65, abs=1e-9)
    assert plan['summary']['duration_sec'] == pytest.approx(4.0 - 1.013)
    assert plan['segment_end_sec'] == pytest.approx(4.0)   # 끝까지 · 실제 끝(파일 시각)


def test_initial_position_is_the_pose_at_the_segment_start():
    manager = _manager(_mapping(), {'a.json': _wave()})
    init = _build(manager, init=True, segment={'start_sec': 2.0, 'end_sec': 0})
    expected = 0.3 * math.sin(2.02)
    by_id = {axis['motion_id']: axis for axis in init['axes']}
    assert by_id['1-1']['initial_motion_position_rad'] == pytest.approx(expected)
    assert by_id['1-2']['initial_motion_position_rad'] == pytest.approx(-expected)
    assert by_id['1-1']['initial_motor_target_rad'] == pytest.approx(expected)


def test_reference_initial_mode_blends_into_the_segment_first_frame():
    """기준점 초기 방식 · 초기 위치는 0° · 첫 프레임 잇기는 구간 첫 프레임으로 (13-1 그대로)"""
    manager = _manager(_mapping(initial_mode='reference'), {'a.json': _wave()})
    init = _build(manager, init=True, segment_start_sec=2.0)
    axis = next(a for a in init['axes'] if a['motion_id'] == '1-1')
    assert axis['initial_motion_position_rad'] == 0.0
    assert axis['first_frame_motor_target_rad'] == pytest.approx(0.3 * math.sin(2.02))
    assert axis['loop_start_motion_rad'] == pytest.approx(0.3 * math.sin(2.02))


@pytest.mark.parametrize('segment, words', [
    ({'start_sec': 192}, '구간 시작 3:12 이 애니메이션 길이 0:04 보다 깁니다'),
    ({'start_sec': 4.0}, '구간 시작 0:04 이 애니메이션 길이 0:04 보다 깁니다'),
    ({'start_sec': 2.0, 'end_sec': 1.0}, '구간 끝 0:01 이 구간 시작 0:02 보다 뒤여야 합니다'),
    ({'start_sec': -1}, '0초 이상'),
])
def test_refusal_reasons(segment, words):
    manager = _manager(_mapping(), {'a.json': _wave()})
    with pytest.raises(ValueError, match=words):
        _build(manager, segment=segment)
    with pytest.raises(ValueError, match=words):
        _build(manager, init=True, segment=segment)


def test_end_past_the_file_plays_to_the_end_with_a_warning():
    manager = _manager(_mapping(), {'a.json': _wave()})
    plan = _build(manager, segment={'start_sec': 3.0, 'end_sec': 9.0})
    assert plan['summary']['duration_sec'] == pytest.approx(1.0)
    assert any('끝까지 재생합니다' in warning for warning in plan['warnings'])


def test_speed_check_runs_on_the_slice_only():
    manager = _manager(_mapping(max_velocity_deg_s=60.0), {'a.json': _wave(spike_at=3.0)})
    with pytest.raises(ValueError, match='속도'):
        _build(manager)                                            # 통째 · 3.0 s 튐에서 거절
    plan = _build(manager, segment={'start_sec': 0.5, 'end_sec': 2.0})   # 튐 밖
    assert plan['summary']['duration_sec'] == pytest.approx(1.5)
    with pytest.raises(ValueError, match=r'속도.*\(0\.\d\d s\)'):
        _build(manager, segment={'start_sec': 2.5, 'end_sec': 3.5})   # 튐 안 · 시각은 구간 기준


def test_range_clipping_runs_on_the_slice():
    manager = _manager(_mapping(motion_lower_deg=-5.0, motion_upper_deg=5.0), {'a.json': _wave()})
    plan = _build(manager, segment={'start_sec': 1.0, 'end_sec': 1.5})
    limit = math.radians(5.0)
    assert all(abs(_value(plan['samples'], i)) <= limit + 1e-9 for i in range(len(plan['samples'])))
    assert any('제한' in warning for warning in plan['warnings'])


def test_schedule_runs_ignore_a_segment():
    manager = _manager(_mapping(), {'a.json': _wave()})
    plan = _build(manager, automation_run=True, segment={'start_sec': 1.0})
    assert plan['segment_start_sec'] == 0.0
    assert plan['summary']['duration_sec'] == pytest.approx(4.0)


def test_status_carries_the_segment():
    manager = _manager(_mapping(), {'a.json': _wave()})
    plan = _build(manager, segment={'start_sec': 1.0, 'end_sec': 2.5})
    status = motion_run_rules._status_from_plan('running', 'x', plan)
    assert (status['segment_start_sec'], status['segment_end_sec']) == (1.0, 2.5)
    assert status['source_duration_sec'] == pytest.approx(4.0)
    empty = motion_run_rules._empty_status()
    assert (empty['segment_start_sec'], empty['segment_end_sec']) == (0.0, 0.0)


def test_trace_meta_notes_the_segment(tmp_path):
    from motion_runtime.motion_trace import MotionTraceRecorder
    manager = _manager(_mapping(), {'a.json': _wave()})
    plan = _build(manager, segment={'start_sec': 1.0, 'end_sec': 2.5})
    recorder = MotionTraceRecorder.__new__(MotionTraceRecorder)
    recorder.enabled = True
    recorder.latest = lambda: (None, 0.0)
    trace = recorder.begin(plan, 1, tmp_path)
    assert (trace.meta['segment_start_sec'], trace.meta['segment_end_sec']) == (1.0, 2.5)


# -- 재생 목록 · 1회 · 연속 ------------------------------------------------------ #

def test_a_segment_plays_only_playlist_item_one():
    files = {'a.json': _wave(), 'b.json': _wave(length=2.0)}
    manager = _manager(_mapping(playlist=('a.json', 'b.json')), files)
    payload = {'motion_file_id': 'a.json', 'mapping_file_id': 'm.yaml', 'run_mode': 'continuous'}
    whole = manager._plan_builder.build(payload)
    whole_init = manager._plan_builder.build(payload, initialization_only=True)
    entries = manager._player._build_playlist_entries(payload, whole, whole_init, manager._current_motors())
    assert [entry[0]['motion_file_id'] for entry in entries] == ['a.json', 'b.json'], '구간이 없으면 목록 그대로'

    cut = {**payload, 'segment': {'start_sec': 1.0, 'end_sec': 2.0}}
    plan = manager._plan_builder.build(cut)
    init = manager._plan_builder.build(cut, initialization_only=True)
    assert manager._player._build_playlist_entries(cut, plan, init, manager._current_motors()) == []
    assert manager._player._build_playlist_entries(
        cut, plan, init, manager._current_motors(), require_continuous=False,
    ) == [], '그룹 회차 맞춤도 같다'


@pytest.mark.parametrize('run_mode', ['once', 'continuous'])
def test_local_start_runs_the_segment_once_or_repeats_it(run_mode):
    """1회 = 구간 한 번 · 연속 = 회차마다 구간 시작 자세로 초기화 후 구간 · 목록 없이"""
    files = {'a.json': _wave(), 'b.json': _wave(length=2.0)}
    manager = _manager(_mapping(playlist=('a.json', 'b.json')), files)
    manager._stop_event = threading.Event()
    manager._playback_ownership_error = lambda axes=None: ''
    seen = []
    manager._player._run_initialization_then_motion = lambda init, plan, playlist=None: seen.append((init, plan, playlist))
    manager._player._reset_override_resume = lambda: None
    error = manager._player._prepare_and_run_once('start', {
        'motion_file_id': 'a.json', 'mapping_file_id': 'm.yaml', 'run_mode': run_mode,
        'repeat_mode': 'reinitialize', 'segment_start_sec': 1.0, 'segment_end_sec': 2.0,
    }, manager._current_motors())
    assert error is None
    [(init, plan, playlist)] = seen
    assert playlist is None
    assert plan['motion_file_id'] == 'a.json' and plan['run_mode'] == run_mode
    assert plan['summary']['duration_sec'] == pytest.approx(1.0)
    first = next(a for a in init['axes'] if a['motion_id'] == '1-1')
    assert first['initial_motion_position_rad'] == pytest.approx(0.3 * math.sin(1.02))


# -- 그룹 세션 ------------------------------------------------------------------ #

def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError('condition timeout')


def test_group_lockstep_repeats_item_one_segment_every_cycle():
    files = {'a.json': _wave(), 'b.json': _wave(length=2.0)}
    manager = _manager(_mapping(playlist=('a.json', 'b.json')), files)
    manager._group = GroupSession(manager, run_lock=manager._run_lock)
    manager._group.session = {
        'active': True, 'execution_id': 'exec-a', 'state': 'preparing',
        'cycle_number': 0, 'next_cycle_number': 0, 'next_start_at': 0.0, 'stop_after_cycle': False,
    }
    manager._stop_event = threading.Event()
    manager._graceful_stop_event = threading.Event()
    manager._status = {}
    manager.status = lambda: dict(manager._status)
    manager._set_status = lambda value: setattr(manager, '_status', dict(value))
    manager._update_status = lambda value: manager._status.update(dict(value))
    manager.get_logger = lambda: type('Logger', (), {'error': lambda self, _m: None})()
    manager._wait_group_deadline = lambda *_a, **_k: None
    inits, runs = [], []

    def run_initialization(plan):
        inits.append(plan)
        manager._status.update({'state': 'initialized', 'phase': 'initialized'})

    def run_motion(plan):
        runs.append(plan)
        manager._status.update({'state': 'completed', 'phase': 'completed', 'lifecycle': {}})

    manager._player._run_initialization = run_initialization
    manager._player._run_motion = run_motion
    worker = threading.Thread(target=manager._group._run, args=({
        'execution_id': 'exec-a', 'initialize_monotonic': time.monotonic() + 1.0,
        'motion_file_id': 'a.json', 'mapping_file_id': 'm.yaml',
        'run_mode': 'continuous', 'repeat_mode': 'reinitialize', 'sync_mode': 'lockstep',
        'segment_start_sec': 1.0, 'segment_end_sec': 2.0,
    }, manager._current_motors()))
    worker.start()
    for cycle in (1, 2):
        _wait_until(lambda: manager._group.session.get('state') in {'armed', 'cycle_ready'})
        assert manager._group.schedule_cycle({
            'execution_id': 'exec-a', 'cycle_number': cycle, 'start_monotonic': time.monotonic() + 1.0,
        })['success']
        _wait_until(lambda: manager._group.session.get('state') == 'motion_completed')
        assert manager._group.schedule_initialization({
            'execution_id': 'exec-a', 'cycle_number': cycle, 'initialize_monotonic': time.monotonic() + 1.0,
        })['success']
    _wait_until(lambda: len(inits) == 3)
    manager._group.cancel({'execution_id': 'exec-a'})
    worker.join(timeout=2.0)

    assert [plan['motion_file_id'] for plan in runs] == ['a.json', 'a.json'], '목록 2번(b.json)으로 넘어가지 않는다'
    assert all(plan['summary']['duration_sec'] == pytest.approx(1.0) for plan in runs)
    assert all(plan['segment_start_sec'] == 1.0 for plan in runs)
    starts = [next(a for a in plan['axes'] if a['motion_id'] == '1-1')['initial_motion_position_rad'] for plan in inits]
    assert starts == [pytest.approx(0.3 * math.sin(1.02))] * 3, '회차마다 구간 시작 자세로'


def test_group_prepare_refuses_when_item_one_is_shorter_than_the_segment():
    """이 PC 의 1번이 구간 시작보다 짧다 · 준비 검사(그룹 준비 확인)가 이유를 돌려준다 → 이 PC 만 빠짐"""
    manager = _manager(_mapping(), {'a.json': _wave(length=2.0)})
    with pytest.raises(ValueError, match='구간 시작 0:03 이 애니메이션 길이 0:02 보다 깁니다'):
        manager._plan_builder.build({
            'motion_file_id': 'a.json', 'mapping_file_id': 'm.yaml', 'run_mode': 'once',
            'request_source': 'network_readiness', 'segment_start_sec': 3.0, 'segment_end_sec': 0.0,
        })
