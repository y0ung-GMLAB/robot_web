"""부팅 뒤 첫 그룹 시작 · 준비 검사가 미리 지은 재샘플을 그대로 쓴다 · 단계별 시간이 남는다 · 수정 목록 174

NY 실물 2026-11-05 · PC 재부팅 뒤 첫 그룹 시작에서 그 PC 가 빠졌다 ·
「준비 거절 · 로컬 Web Bridge 응답 없음: timed out」 · 다음 회차에 복귀(913 s 나레이션이면 15분 쉼) ·
스케줄이면 매일 아침 전원을 켤 때마다 되풀이된다. 164 의 미리 읽기는 파일만 읽었고 가장 무거운
20 ms 재샘플 · 속도 검사는 준비 검사가 처음 했다. 어느 단계가 느렸는지 기록도 없었다.

여기서 지키는 것:

    실행 허용(부팅 · 매핑 저장)이 서면 재생 목록 1번의 재샘플을 뒤에서 짓는다 · 준비 검사 · 그룹 준비는 캐시
    키는 모터 번호 · 한계(설정)만 본다 · 알람 · 서보 · 위치가 그때와 달라도 같은 키
    재생 목록은 캐시 칸만큼 · 1번이 가장 최근(가장 늦게 버려짐)
    실행 스레드가 돌면 안 짓는다 · 짓는 도중 시작되면 그만둔다 · 누가 그 값을 기다리면 끝까지
    도는 중에 새 실행 허용이 오면 끝나고 마지막 것을 다시
    준비 검사가 느리거나(1 s) 실패하면 단계별 시간 한 줄 · 답에 `timing_ms`
"""

import json
import math
import threading
import time
from unittest import mock

import pytest
import yaml

from motion_common import units
from motion_runtime import motion_run_rules, plan_builder as plan_builder_mod
from motion_runtime.group_session import GroupSession
from motion_runtime.motion_player import MotionPlayer
from motion_runtime.motion_run_manager import MotionRunManager
from motion_runtime.plan_builder import PlanBuilder
from motion_runtime.plan_cache import SingleFlightCache

PROJECT = 'proj'
JOINTS = ('neck_pitch', 'neck_yaw', 'eye_pitch', 'eye_yaw_r', 'eye_yaw_l')
MINE = tuple(f'f1_{joint}' for joint in JOINTS)
ROBOTS = 4


@pytest.fixture(autouse=True)
def _patched_rules():
    mock.patch.object(motion_run_rules, '_target_range_limit_error', lambda _m, _l, _h: '').start()
    mock.patch.object(motion_run_rules, '_motor_type', lambda _motor: 'ac_servo').start()
    mock.patch.object(
        motion_run_rules, '_motors_for_ref',
        lambda ref, motors: [m for m in motors if m.get('motor_ref') == ref],
    ).start()
    yield
    mock.patch.stopall()


def _write_motion(path, frames, phase=0.0):
    header = {
        'title': path.stem, 'type': 'motion_header', 'rotation_unit': 'rad',
        'fields': ['frame', 'time_sec', 'id', 'value'],
    }
    lines = [json.dumps(header)]
    for frame in range(1, frames + 1):
        t = round(frame * 0.02, 4)
        row = [frame, t]
        for robot in range(1, ROBOTS + 1):
            for index, joint in enumerate(JOINTS):
                row += [f'f{robot}_{joint}', round(0.2 * math.sin(0.3 * t + robot + index + phase), 9)]
        lines.append(json.dumps(row))
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def _mapping(names=('a.json',)):
    mapping = {
        'motion_file_id': names[0],
        'mappings': [
            {
                'motion_id': motion_id, 'enabled': True, 'motor_ref': f'ac:{index}',
                'reference_enabled': True, 'reference_position_deg': 3.0,
                'motion_lower_deg': -10.0, 'motion_upper_deg': 10.0, 'range_confirmed': True,
                'initial_mode': 'first_frame', 'initial_move_time_sec': 5.0,
                'invert': False, 'offset_deg': 0.0, 'scale': 1.0, 'gear_ratio': 50.0,
                'max_velocity_deg_s': 2000.0, 'max_acceleration_deg_s2': 200000.0,
            }
            for index, motion_id in enumerate(MINE)
        ],
    }
    if len(names) > 1:
        mapping['motion_playlist'] = list(names)
    return mapping


def _motors(position_deg=0.0, alarm=False):
    """모터 상태 · 번호 · 한계는 설정 값 · 위치 · 알람은 지금 상태"""
    return [
        {
            'axis': index, 'controller_index': index, 'motor_ref': f'ac:{index}',
            'lower_rad': units.deg_to_rad(-600.0), 'upper_rad': units.deg_to_rad(600.0),
            'position_rad': units.deg_to_rad(position_deg + index),
            'alarm': alarm,
        }
        for index in range(len(MINE))
    ]


def _motor_ready_error(motor):
    return '알람 상태' if motor.get('alarm') else ''


def _manager(tmp_path, mapping, frames=300, names=('a.json',)):
    """실제 프로젝트 폴더 · 실제 경로 함수 · 실제 매핑 읽기 · 노드 없이"""
    projects = tmp_path / 'motion_projects'
    project_dir = projects / PROJECT
    (project_dir / 'motions').mkdir(parents=True)
    (project_dir / 'motion_axis_matching').mkdir()
    (project_dir / 'project.json').write_text('{}', encoding='utf-8')
    for index, name in enumerate(names):
        _write_motion(project_dir / 'motions' / name, frames, phase=index)
    (project_dir / 'motion_axis_matching' / 'map.yaml').write_text(
        yaml.safe_dump(mapping, allow_unicode=True), encoding='utf-8',
    )
    manager = MotionRunManager.__new__(MotionRunManager)
    manager.motion_projects_dir = projects
    manager.motion_files_dir = project_dir / 'motions'
    manager.mappings_dir = project_dir / 'motion_axis_matching'
    manager._run_lock = threading.RLock()
    manager._stop_event = threading.Event()
    manager._graceful_stop_event = threading.Event()
    manager._run_thread = None
    manager.period_sec = 0.02
    manager._player = MotionPlayer(manager)
    manager._plan_builder = PlanBuilder(manager)
    manager.motors = _motors()
    manager._current_motors = lambda: list(manager.motors)
    manager._multiturn_clear_state = lambda: {}
    manager._status = motion_run_rules._empty_status()
    manager._status_epoch = 0
    manager.status = lambda: dict(manager._status)
    manager._publish_status = lambda: None
    manager.logger = mock.Mock()
    manager.get_logger = lambda: manager.logger
    manager.WARM_MOTOR_POLL_SEC = 0.01
    return manager


def _readiness_payload(name='a.json'):
    """브리지 `local_motion_readiness` 가 보내는 것 그대로(`_request_motion_run` 이 붙이는 칸 포함)"""
    return {
        'motion_file_id': name, 'mapping_file_id': 'map.yaml',
        'initial_move_time_sec': None, 'run_mode': 'once', 'request_source': 'network_readiness',
        'segment_start_sec': 0.0, 'segment_end_sec': 0.0,
        'project_id': PROJECT, 'project_generation': 0, 'context_id': 'ctx-1',
    }


def _group_payload(name='a.json'):
    return {
        'motion_file_id': name, 'mapping_file_id': 'map.yaml', 'run_mode': 'continuous',
        'repeat_mode': 'reinitialize', 'execution_id': 'exec-174', 'project_id': PROJECT,
        'request_source': 'network_control', 'initial_move_time_sec': None,
    }


def _count_sampling(monkeypatch):
    calls = []
    real = plan_builder_mod._sample_plan

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(plan_builder_mod, '_sample_plan', counted)
    return calls


def _alive_thread():
    release = threading.Event()
    thread = threading.Thread(target=release.wait, args=(5.0,), daemon=True)
    thread.start()
    return thread, release


# --------------------------------------------------------------------------- #
# 미리 짓기 → 준비 검사 · 그룹 준비는 캐시
# --------------------------------------------------------------------------- #

def test_readiness_check_after_warm_up_is_a_cache_hit(tmp_path, monkeypatch):
    monkeypatch.setattr(motion_run_rules, '_motor_ready_error', _motor_ready_error)
    manager = _manager(tmp_path, _mapping())
    samplings = _count_sampling(monkeypatch)

    manager._warm_motion_cache_now(PROJECT, 'map.yaml')
    assert len(samplings) == 1, '미리 짓기가 재샘플을 안 했습니다'

    response = manager._handle_check(_readiness_payload())
    assert response['success'] is True, response['message']
    assert len(samplings) == 1, '준비 검사가 재샘플을 다시 했습니다(키가 다름)'
    assert response['timing_ms']['samples_cached'] is True

    session = GroupSession(manager, run_lock=manager._run_lock)
    _, _, plan, _, _ = session._prepare_plans(_group_payload(), manager.motors)
    assert len(samplings) == 1, '그룹 준비가 재샘플을 다시 했습니다'
    assert len(plan['samples']) == 300


def test_the_key_ignores_live_motor_state(tmp_path, monkeypatch):
    """미리 짓는 때 알람 · 다른 위치 · 검사 때 정상 · 키는 같다(번호 · 한계만 든다)"""
    monkeypatch.setattr(motion_run_rules, '_motor_ready_error', _motor_ready_error)
    manager = _manager(tmp_path, _mapping())
    samplings = _count_sampling(monkeypatch)
    manager.motors = _motors(position_deg=-40.0, alarm=True)

    manager._warm_motion_cache_now(PROJECT, 'map.yaml')
    assert len(samplings) == 1, '알람 중이라 미리 짓기를 안 했습니다'

    manager.motors = _motors(position_deg=25.0, alarm=False)
    assert manager._handle_check(_readiness_payload())['success'] is True
    assert len(samplings) == 1


def test_changed_motor_limits_are_not_hidden_by_the_warm_up(tmp_path, monkeypatch):
    """장비에 적용으로 모터 한계가 바뀌면 키가 바뀐다 · 미리 지은 옛 것을 쓰지 않는다"""
    monkeypatch.setattr(motion_run_rules, '_motor_ready_error', _motor_ready_error)
    manager = _manager(tmp_path, _mapping())
    samplings = _count_sampling(monkeypatch)
    manager._warm_motion_cache_now(PROJECT, 'map.yaml')
    for motor in manager.motors:
        motor['upper_rad'] = units.deg_to_rad(700.0)
    response = manager._handle_check(_readiness_payload())
    assert response['success'] is True
    assert len(samplings) == 2
    assert response['timing_ms']['samples_cached'] is False


def test_playlist_warm_up_keeps_the_first_entry_newest(tmp_path, monkeypatch):
    monkeypatch.setattr(motion_run_rules, '_motor_ready_error', _motor_ready_error)
    names = ('a.json', 'b.json', 'c.json')
    manager = _manager(tmp_path, _mapping(names), names=names)
    samplings = _count_sampling(monkeypatch)

    manager._warm_motion_cache_now(PROJECT, 'map.yaml')
    cache = manager._plan_builder._samples_cache
    assert len(samplings) == plan_builder_mod.SAMPLES_CACHE_SIZE == 2
    assert len(cache) == 2
    # 마지막에 넣은 것(가장 늦게 버려짐) = 1번
    assert cache.keys()[-1][0][0][0].endswith('a.json')

    assert manager._handle_check(_readiness_payload('a.json'))['success'] is True
    assert manager._handle_check(_readiness_payload('b.json'))['success'] is True
    assert len(samplings) == 2, '재생 목록 1 · 2번이 캐시에 없었습니다'


def test_confirming_the_context_warms_in_the_background(tmp_path, monkeypatch):
    monkeypatch.setattr(motion_run_rules, '_motor_ready_error', _motor_ready_error)
    manager = _manager(tmp_path, _mapping())
    samplings = _count_sampling(monkeypatch)

    manager._warm_motion_cache({'project_id': PROJECT, 'mapping_file_id': 'map.yaml'})
    manager._warm_thread.join(10.0)

    assert len(samplings) == 1
    lines = [str(call.args[0]) for call in manager.logger.info.call_args_list]
    assert any(line.startswith('[계획 미리 짓기] a.json') and '재샘플' in line for line in lines), lines
    assert getattr(manager, '_warm_thread', None) is None


def test_warm_up_waits_for_the_first_motor_state(tmp_path, monkeypatch):
    monkeypatch.setattr(motion_run_rules, '_motor_ready_error', _motor_ready_error)
    manager = _manager(tmp_path, _mapping())
    samplings = _count_sampling(monkeypatch)
    later = _motors()
    manager.motors = []
    threading.Timer(0.1, lambda: setattr(manager, 'motors', later)).start()

    manager._warm_motion_cache_now(PROJECT, 'map.yaml')

    assert len(samplings) == 1


# --------------------------------------------------------------------------- #
# 실행 중에는 안 짓는다 · 시작되면 그만둔다
# --------------------------------------------------------------------------- #

def test_no_warm_up_while_a_run_thread_is_alive(tmp_path, monkeypatch):
    manager = _manager(tmp_path, _mapping())
    samplings = _count_sampling(monkeypatch)
    manager._run_thread, release = _alive_thread()
    try:
        manager._warm_motion_cache({'project_id': PROJECT, 'mapping_file_id': 'map.yaml'})
        assert getattr(manager, '_warm_thread', None) is None, '재생 중에 미리 짓기 스레드를 띄웠습니다'
        manager._warm_motion_cache_now(PROJECT, 'map.yaml')
    finally:
        release.set()
    assert samplings == []
    assert len(manager._plan_builder._samples_cache) == 0


def test_a_run_starting_mid_sampling_cancels_the_warm_up(tmp_path, monkeypatch):
    monkeypatch.setattr(motion_run_rules, '_motor_ready_error', _motor_ready_error)
    monkeypatch.setattr(plan_builder_mod, 'SAMPLE_CANCEL_CHECK_EVERY', 50)
    manager = _manager(tmp_path, _mapping(), frames=2000)
    samplings = _count_sampling(monkeypatch)
    started = []
    release = threading.Event()
    real_alive = manager._warm_should_yield

    def run_starts_during_sampling():
        # 재샘플이 시작된 뒤 실행 스레드가 선다(그룹 준비 등)
        if samplings and not started:
            started.append(True)
            manager._run_thread = threading.Thread(target=release.wait, args=(5.0,), daemon=True)
            manager._run_thread.start()
        return real_alive()

    manager._warm_should_yield = run_starts_during_sampling
    try:
        manager._warm_motion_cache_now(PROJECT, 'map.yaml')
    finally:
        release.set()
    assert len(samplings) == 1
    assert len(manager._plan_builder._samples_cache) == 0, '그만둔 재샘플이 캐시에 남았습니다'
    lines = [str(call.args[0]) for call in manager.logger.info.call_args_list]
    assert any('그만둠' in line for line in lines), lines


def test_a_waiting_check_keeps_the_warm_up_going(tmp_path, monkeypatch):
    """실행이 시작돼도 그 값을 기다리는 스레드가 있으면 끝까지 · 그만두면 그쪽이 처음부터 다시 한다"""
    monkeypatch.setattr(motion_run_rules, '_motor_ready_error', _motor_ready_error)
    monkeypatch.setattr(plan_builder_mod, 'SAMPLE_CANCEL_CHECK_EVERY', 50)
    manager = _manager(tmp_path, _mapping(), frames=2000)
    samplings = _count_sampling(monkeypatch)
    monkeypatch.setattr(SingleFlightCache, 'waiting', lambda self, key: 1)

    payload = {k: v for k, v in _readiness_payload().items() if k not in ('context_id',)}
    result = manager._plan_builder.build(
        payload, warm_only=True, motors_snapshot=manager.motors, cancel=lambda: True,
    )
    assert result['sample_count'] == 2000
    assert len(samplings) == 1
    assert manager._handle_check(_readiness_payload())['timing_ms']['samples_cached'] is True


def test_single_flight_cache_counts_waiters():
    cache = SingleFlightCache(2)
    gate = threading.Event()
    entered = threading.Event()

    def slow():
        entered.set()
        gate.wait(5.0)
        return 'value'

    owner = threading.Thread(target=lambda: cache.get_or_compute('k', slow))
    owner.start()
    entered.wait(5.0)
    waiter = threading.Thread(target=lambda: cache.get_or_compute('k', lambda: 'other'))
    waiter.start()
    deadline = time.monotonic() + 5.0
    while cache.waiting('k') < 1 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert cache.waiting('k') == 1 and cache.waiting('x') == 0 and cache.waiting(None) == 0
    gate.set()
    owner.join(5.0)
    waiter.join(5.0)
    assert cache.waiting('k') == 0


def test_a_new_context_during_warm_up_is_warmed_after_it(tmp_path):
    manager = _manager(tmp_path, _mapping())
    gate = threading.Event()
    calls = []

    def fake_now(project_id, mapping_file_id):
        calls.append(mapping_file_id)
        if len(calls) == 1:
            gate.wait(5.0)

    manager._warm_motion_cache_now = fake_now
    manager._warm_motion_cache({'project_id': PROJECT, 'mapping_file_id': 'old.yaml'})
    deadline = time.monotonic() + 5.0
    while not calls and time.monotonic() < deadline:
        time.sleep(0.005)
    manager._warm_motion_cache({'project_id': PROJECT, 'mapping_file_id': 'mid.yaml'})
    manager._warm_motion_cache({'project_id': PROJECT, 'mapping_file_id': 'new.yaml'})
    thread = manager._warm_thread
    gate.set()
    thread.join(5.0)
    assert calls == ['old.yaml', 'new.yaml'], '마지막 실행 허용만 이어서 지어야 합니다'


# --------------------------------------------------------------------------- #
# 단계별 시간
# --------------------------------------------------------------------------- #

def test_a_slow_check_logs_one_line_with_each_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(motion_run_rules, '_motor_ready_error', _motor_ready_error)
    manager = _manager(tmp_path, _mapping())
    manager.CHECK_SLOW_LOG_MS = 0.0

    response = manager._handle_check(_readiness_payload(), queued_ms=12.0)

    timing = response['timing_ms']
    assert response['success'] is True
    assert {'queued_ms', 'records_ms', 'samples_ms', 'samples_cached', 'build_ms'} <= set(timing)
    assert timing['samples_cached'] is False
    (line,), _ = manager.logger.info.call_args
    assert line.startswith('[준비 검사 시간] a.json · network_readiness · 대기 12 · 파일 ')
    assert '재샘플 ' in line and '(새로)' in line and line.endswith(' ms')


def test_a_fast_check_logs_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(motion_run_rules, '_motor_ready_error', _motor_ready_error)
    manager = _manager(tmp_path, _mapping())
    assert manager._handle_check(_readiness_payload())['success'] is True
    manager.logger.info.assert_not_called()
    manager.logger.warning.assert_not_called()


def test_a_failed_check_logs_how_far_it_got(tmp_path, monkeypatch):
    monkeypatch.setattr(motion_run_rules, '_motor_ready_error', _motor_ready_error)
    manager = _manager(tmp_path, _mapping())
    manager.motors = _motors(alarm=True)

    response = manager._handle_check(_readiness_payload())

    assert response['success'] is False and '알람 상태' in response['message']
    assert 'records_ms' in response['timing_ms'] and 'samples_ms' not in response['timing_ms']
    (line,), _ = manager.logger.warning.call_args
    assert line.startswith('[준비 검사 시간] a.json') and '파일 ' in line and '실패: ' in line
