"""긴 다로봇 애니로 그룹 시작 · 준비 검사가 실행기를 막지 않고 · 계획 재료는 한 번만 · 수정 목록 164

NY 실물 2026-11-03 · 920 s(46000 프레임) × 20 조인트(4대 × 5) 파일로 그룹 시작 →
「준비 거절 · motion_run_manager response timeout」 · 1분 파일로는 「그룹 예약 시작시각을 놓쳤습니다」.

    준비 검사(`check`)가 단일 실행기에서 계획을 통째로 지어 그동안 다른 요청이 줄을 섰다
    그룹 준비 작업 스레드가 같은 요청으로 계획을 세 번 + 재생 목록 전부를 예약 시각 전에 지었다
    PC 마다 남의 조인트 15개까지 읽어 레코드를 만들고 버렸다

여기서 지키는 것:

    검사는 작업 스레드 · 그동안 `status` 같은 요청에 바로 답한다 · 검사 답은 끝나면 간다
    늦게 끝난 검사가 실행 상태를 「준비 완료」 로 덮지 않는다
    읽으면서 거른 레코드 · 그것으로 지은 계획이 옛 길(다 읽고 거르기)과 같다
    같은 파일 · 같은 매핑 · 같은 모터 한계면 재샘플은 한 번 · 하나라도 바뀌면 다시
    그룹 준비는 1회차 계획 + 초기 위치 계획만 · 재생 목록 2번부터는 뒤에서
"""

import json
import math
import os
import threading
import time
from unittest import mock

import pytest

from motion_common import joint_mapping, units
from motion_runtime import motion_run_rules, plan_builder as plan_builder_mod
from motion_runtime.deferred_playlist import DeferredPlaylist
from motion_runtime.group_session import GroupSession
from motion_runtime.motion_player import MotionPlayer
from motion_runtime.motion_run_manager import MotionRunManager
from motion_runtime.plan_builder import PlanBuilder

ROBOTS = 4
JOINTS = ('neck_pitch', 'neck_yaw', 'eye_pitch', 'eye_yaw_r', 'eye_yaw_l')
MINE = tuple(f'f1_{joint}' for joint in JOINTS)


@pytest.fixture(autouse=True)
def _patched_rules():
    mock.patch.object(motion_run_rules, '_motor_ready_error', lambda _motor: '').start()
    mock.patch.object(motion_run_rules, '_target_range_limit_error', lambda _m, _l, _h: '').start()
    mock.patch.object(motion_run_rules, '_motor_type', lambda _motor: 'ac_servo').start()
    mock.patch.object(
        motion_run_rules, '_motors_for_ref',
        lambda ref, motors: [m for m in motors if m.get('motor_ref') == ref],
    ).start()
    yield
    mock.patch.stopall()


def _write_motion(path, frames, *, robots=ROBOTS, unit='rad', phase=0.0):
    """Blender 내보내기와 같은 모양 · 머리 줄 + 프레임마다 `[frame, time, id, v, ...]`"""
    header = {
        'title': path.stem, 'type': 'motion_header', 'rotation_mode': 'relative',
        'rotation_unit': unit, 'fields': ['frame', 'time_sec', 'id', 'value'],
    }
    scale = 1.0 if unit == 'rad' else 180.0 / math.pi
    lines = [json.dumps(header)]
    for frame in range(1, frames + 1):
        t = round(frame * 0.02, 4)
        row = [frame, t]
        for robot in range(1, robots + 1):
            for index, joint in enumerate(JOINTS):
                value = 0.2 * math.sin(0.3 * t + robot + index + phase)
                row += [f'f{robot}_{joint}', round(value * scale, 9)]
        lines.append(json.dumps(row))
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def _row(motion_id, motor_ref, **overrides):
    row = {
        'motion_id': motion_id, 'enabled': True, 'motor_ref': motor_ref,
        'reference_enabled': True, 'reference_position_deg': 3.0,
        'motion_lower_deg': -10.0, 'motion_upper_deg': 10.0, 'range_confirmed': True,
        'initial_mode': 'first_frame', 'initial_move_time_sec': 5.0,
        'invert': True, 'offset_deg': 0.0, 'scale': 1.0, 'gear_ratio': 50.0,
        'max_velocity_deg_s': 2000.0, 'max_acceleration_deg_s2': 200000.0,
    }
    row.update(overrides)
    return row


def _mapping(names=('a.json',), **row_overrides):
    mapping = {
        'motion_file_id': names[0],
        'mappings': [_row(motion_id, f'ac:{index}', **row_overrides) for index, motion_id in enumerate(MINE)],
    }
    if len(names) > 1:
        mapping['motion_playlist'] = list(names)
    return mapping


def _motors(upper_deg=300.0):
    return [
        {
            'axis': index, 'controller_index': index, 'motor_ref': f'ac:{index}',
            'lower_rad': units.deg_to_rad(-upper_deg), 'upper_rad': units.deg_to_rad(upper_deg),
        }
        for index in range(len(MINE))
    ]


def _manager(tmp_path, mapping, motors=None):
    """실제 파일 읽기 · 실제 계획 · 노드 없이"""
    manager = MotionRunManager.__new__(MotionRunManager)
    manager._run_lock = threading.RLock()
    manager._stop_event = threading.Event()
    manager._graceful_stop_event = threading.Event()
    manager._run_thread = None
    manager.period_sec = 0.02
    manager._player = MotionPlayer(manager)
    manager._plan_builder = PlanBuilder(manager)
    manager._mapping_file_path = lambda _file_id: tmp_path / 'map.yaml'
    manager._load_mapping = lambda _path: manager.mapping
    manager._motion_file_path = lambda file_id: tmp_path / file_id
    manager.mapping = mapping
    manager.motors = motors or _motors()
    manager._current_motors = lambda: list(manager.motors)
    manager._motor_for_axis = lambda axis, motors: next(
        (motor for motor in motors if motor['controller_index'] == axis), None,
    )
    manager._multiturn_clear_state = lambda: {}
    return manager


def _check_payload(name='a.json', **extra):
    return {
        'motion_file_id': name, 'mapping_file_id': 'map.yaml', 'run_mode': 'once',
        'request_source': 'network_readiness', 'initial_move_time_sec': None, **extra,
    }


def _group_payload(name='a.json', **extra):
    return {
        'motion_file_id': name, 'mapping_file_id': 'map.yaml', 'run_mode': 'continuous',
        'repeat_mode': 'reinitialize', 'execution_id': 'exec-164',
        'request_source': 'network_control', 'initial_move_time_sec': None, **extra,
    }


def _strip(plan):
    """비교용 · 실행마다 다른 칸(요청 출처 등)은 빼지 않는다 · 같은 요청끼리만 견준다"""
    return json.loads(json.dumps(plan, sort_keys=True, default=str))


# --------------------------------------------------------------------------- #
# 읽으면서 거르기 · 옛 길과 같은 답
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('unit', ['rad', 'deg'])
def test_filtered_parsing_keeps_exactly_the_mapped_records(tmp_path, unit):
    path = _write_motion(tmp_path / 'a.json', 300, unit=unit)
    manager = MotionRunManager.__new__(MotionRunManager)
    everything = manager._parse_motion_records(path)
    mine = manager._parse_motion_records(path, frozenset(MINE))

    expected = [record for record in everything if record['motion_id'] in MINE]
    assert len(everything) == 300 * ROBOTS * len(JOINTS)
    assert len(mine) == 300 * len(JOINTS)
    key = lambda r: (r['frame'], r['time_sec'], r['motion_id'], r['value'])  # noqa: E731
    assert [key(r) for r in mine] == [key(r) for r in expected]


def test_a_file_with_only_other_robots_is_not_an_empty_file(tmp_path):
    """남의 조인트만 있으면 빈 목록 · 「쓸 수 있는 줄이 없음」 은 정말 빈 파일일 때만"""
    path = _write_motion(tmp_path / 'a.json', 10)
    manager = MotionRunManager.__new__(MotionRunManager)
    assert manager._parse_motion_records(path, frozenset({'f9_neck_yaw'})) == []
    empty = tmp_path / 'empty.json'
    empty.write_text('{"type":"motion_header","fields":["frame","time_sec","id","value"]}\n', encoding='utf-8')
    with pytest.raises(ValueError, match='no valid records'):
        manager._parse_motion_records(empty, frozenset(MINE))


def test_plan_from_filtered_parsing_equals_plan_from_full_parsing(tmp_path):
    _write_motion(tmp_path / 'a.json', 600)
    filtered = _manager(tmp_path, _mapping())
    full = _manager(tmp_path, _mapping())
    # 옛 길 · 다 읽고 계획이 거른다(읽는 함수를 갈아 끼우면 계획 캐시도 안 쓴다)
    full._load_motion_records = lambda path, **_kw: MotionRunManager._load_motion_records(full, path)

    for init in (False, True):
        a = filtered._plan_builder.build(_check_payload(), initialization_only=init)
        b = full._plan_builder.build(_check_payload(), initialization_only=init)
        assert _strip(a) == _strip(b)
    assert len(a['axes']) == len(MINE)


def test_prepared_sampling_is_the_same_formula_as_motor_target(tmp_path):
    """축마다 미리 풀어 둔 식 · 모터 한계 자르기 · 샘플마다 옛 함수로 다시 계산한 값과 비트까지 같다"""
    _write_motion(tmp_path / 'a.json', 400)
    mapping = _mapping(offset_deg=1.5, gear_ratio=37.0, scale=1.1, motion_lower_deg=-8.0, motion_upper_deg=8.0)
    # 모터 한계를 조인트 범위 끝(반올림 차이 안쪽)에 둔다 · 자르기가 실제로 일어나게
    motors = _motors(upper_deg=8.0 * 37.0 * 1.1 + 3.0 - 1e-9)
    manager = _manager(tmp_path, mapping, motors)
    plan = manager._plan_builder.build(_check_payload())
    for sample in plan['samples']:
        for axis in plan['axes']:
            value = sample['motion_values'][axis['motion_id']]
            expected = motion_run_rules._clamp_to_motor_limits(
                joint_mapping.motor_target(axis['row'], value, units.RAD),
                axis['motor_for_limits'],
            )
            assert sample['positions'][int(axis['motor_axis'])] == expected


# --------------------------------------------------------------------------- #
# 계획 재료 캐시 · 다시 쓰기 · 버리기
# --------------------------------------------------------------------------- #

def _count_sampling(monkeypatch):
    calls = []
    real = plan_builder_mod._sample_plan
    monkeypatch.setattr(plan_builder_mod, '_sample_plan', lambda *a, **k: calls.append(1) or real(*a, **k))
    return calls


def test_group_prepare_reuses_what_the_readiness_check_built(tmp_path, monkeypatch):
    _write_motion(tmp_path / 'a.json', 500)
    manager = _manager(tmp_path, _mapping())
    parses = []
    real_parse = MotionRunManager._parse_motion_records
    monkeypatch.setattr(
        MotionRunManager, '_parse_motion_records',
        lambda self, path, *rest: parses.append(path) or real_parse(self, path, *rest),
    )
    samplings = _count_sampling(monkeypatch)

    check = manager._plan_builder.build(_check_payload())
    session = GroupSession(manager, run_lock=manager._run_lock)
    _, _, plan, init, playlist = session._prepare_plans(_group_payload(), manager.motors)

    assert len(parses) == 1, '그룹 준비가 파일을 다시 읽었습니다'
    assert len(samplings) == 1, '그룹 준비가 재샘플을 다시 했습니다'
    assert plan['samples'] is check['samples']
    assert init['samples'] == [] and playlist == []
    assert plan['request_source'] == 'group_control' and plan['group_execution'] is True


def test_changing_the_mapping_row_resamples(tmp_path, monkeypatch):
    _write_motion(tmp_path / 'a.json', 200)
    manager = _manager(tmp_path, _mapping())
    samplings = _count_sampling(monkeypatch)
    first = manager._plan_builder.build(_check_payload())
    manager.mapping = _mapping(gear_ratio=100.0)
    second = manager._plan_builder.build(_check_payload())
    assert len(samplings) == 2
    assert first['samples'][10]['positions'] != second['samples'][10]['positions']


def test_changing_the_motor_limits_resamples(tmp_path, monkeypatch):
    _write_motion(tmp_path / 'a.json', 200)
    manager = _manager(tmp_path, _mapping())
    samplings = _count_sampling(monkeypatch)
    manager._plan_builder.build(_check_payload())
    manager.motors = _motors(upper_deg=400.0)
    manager._plan_builder.build(_check_payload())
    assert len(samplings) == 2


def test_a_changed_file_is_read_and_sampled_again(tmp_path, monkeypatch):
    path = _write_motion(tmp_path / 'a.json', 200)
    manager = _manager(tmp_path, _mapping())
    samplings = _count_sampling(monkeypatch)
    first = manager._plan_builder.build(_check_payload())
    stat = path.stat()
    _write_motion(path, 200, phase=0.5)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    second = manager._plan_builder.build(_check_payload())
    assert len(samplings) == 2
    assert first['samples'][5]['motion_values'] != second['samples'][5]['motion_values']


def test_a_different_segment_is_a_different_plan(tmp_path, monkeypatch):
    _write_motion(tmp_path / 'a.json', 500)
    manager = _manager(tmp_path, _mapping())
    samplings = _count_sampling(monkeypatch)
    whole = manager._plan_builder.build(_check_payload())
    part = manager._plan_builder.build(_check_payload(segment_start_sec=4.0))
    assert len(samplings) == 2
    assert len(part['samples']) < len(whole['samples'])


def test_the_sample_cache_is_bounded(tmp_path):
    manager = _manager(tmp_path, _mapping())
    for index in range(plan_builder_mod.SAMPLES_CACHE_SIZE + 3):
        name = f'm{index}.json'
        _write_motion(tmp_path / name, 50, phase=index)
        manager.mapping = _mapping(names=(name,))
        manager._plan_builder.build(_check_payload(name))
    assert len(manager._plan_builder._samples_cache) <= plan_builder_mod.SAMPLES_CACHE_SIZE


def test_two_threads_asking_for_the_same_plan_sample_once(tmp_path, monkeypatch):
    """검사 스레드와 그룹 준비 스레드가 겹쳐도 같은 계산을 두 번 하지 않는다"""
    _write_motion(tmp_path / 'a.json', 800)
    manager = _manager(tmp_path, _mapping())
    samplings = _count_sampling(monkeypatch)
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(manager._plan_builder.build(_check_payload())))
        for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(samplings) == 1
    assert results[0]['samples'] is results[1]['samples'] is results[2]['samples']


# --------------------------------------------------------------------------- #
# 준비 검사는 실행기 밖에서
# --------------------------------------------------------------------------- #

class _Msg:
    def __init__(self, data):
        self.data = data


def _node(tmp_path):
    manager = _manager(tmp_path, _mapping())
    manager._project_generation = 0
    manager._group = GroupSession(manager, run_lock=manager._run_lock)
    manager._status = motion_run_rules._empty_status()
    manager._status_epoch = 0
    manager._require_execution_context = lambda payload: None
    # 세대 · 실행 컨텍스트 관문은 다른 시험이 본다 · 여기는 실행기 밖 처리만
    manager._validate_request_generation = lambda command, generation, payload: 0
    manager.responses = []
    manager._publish_response = lambda response: manager.responses.append((time.monotonic(), response))
    manager._publish_status = lambda: None
    manager.status = lambda: dict(manager._status)
    manager.get_logger = lambda: mock.Mock()
    return manager


def _send(manager, command, request_id, payload=None):
    manager._request_callback(_Msg(json.dumps({
        'request_id': request_id, 'command': command, 'project_generation': 0,
        'payload': payload or {},
    })))


def _response(manager, request_id, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for at, response in list(manager.responses):
            if response.get('request_id') == request_id:
                return at, response
        time.sleep(0.005)
    raise AssertionError(f'{request_id} 응답 없음')


def test_check_does_not_block_the_executor(tmp_path):
    manager = _node(tmp_path)

    def busy_build(_payload, **_kw):
        # 파이썬 계산처럼 GIL 을 쥐고 1 s
        end = time.perf_counter() + 1.0
        while time.perf_counter() < end:
            pass
        return {'summary': {'ok': True}, 'axes': [], 'warnings': [], 'capabilities': {}}

    manager._plan_builder = mock.Mock(build=busy_build)
    started = time.monotonic()
    _send(manager, 'check', 'check-1', _check_payload())
    returned = time.monotonic() - started
    _send(manager, 'status', 'status-1')
    status_at, _ = _response(manager, 'status-1')
    check_at, check = _response(manager, 'check-1')

    assert returned < 0.2, f'검사 요청이 실행기를 {returned:.2f} s 막았습니다'
    assert status_at - started < 0.5, '검사 도중 상태 요청이 줄을 섰습니다'
    assert check_at > status_at
    assert check['success'] is True and check['summary'] == {'ok': True}


def test_a_failed_check_still_answers(tmp_path):
    manager = _node(tmp_path)
    manager._plan_builder = mock.Mock(build=mock.Mock(side_effect=ValueError('움직일 조인트가 없습니다')))
    _send(manager, 'check', 'check-2', _check_payload())
    _, response = _response(manager, 'check-2')
    assert response['success'] is False and '움직일 조인트가 없습니다' in response['message']
    assert manager._status['state'] == 'error'


def test_a_late_check_does_not_overwrite_a_started_run(tmp_path):
    manager = _node(tmp_path)
    release = threading.Event()

    def slow_build(_payload, **_kw):
        release.wait(5.0)
        return {'summary': {}, 'axes': [], 'warnings': [], 'capabilities': {}}

    manager._plan_builder = mock.Mock(build=slow_build)
    _send(manager, 'check', 'check-3', _check_payload())
    time.sleep(0.05)
    # 검사 도중 그룹 준비가 상태 표를 바꿨다
    manager._set_status({**motion_run_rules._empty_status(), 'state': 'preparing', 'phase': 'group_preparing'})
    release.set()
    _, response = _response(manager, 'check-3')
    assert response['success'] is True
    assert manager._status['phase'] == 'group_preparing', '늦은 검사가 실행 상태를 덮었습니다'


def test_a_check_with_nothing_in_between_writes_its_status(tmp_path):
    manager = _node(tmp_path)
    manager._plan_builder = mock.Mock(build=lambda _p, **_k: {
        'summary': {}, 'axes': [], 'warnings': [], 'capabilities': {},
    })
    _send(manager, 'check', 'check-4', _check_payload())
    _response(manager, 'check-4')
    assert manager._status['state'] == 'ready'


# --------------------------------------------------------------------------- #
# 그룹 준비 · 재생 목록은 뒤에서
# --------------------------------------------------------------------------- #

def test_deferred_playlist_first_entry_is_immediate_and_others_wait():
    gate = threading.Event()

    def build():
        gate.wait(5.0)
        return [('p0', 'i0'), ('p1', 'i1'), ('p2', 'i2')]

    playlist = DeferredPlaylist(('p0', 'i0'), 3, build)
    assert len(playlist) == 3 and bool(playlist)
    assert playlist[0] == ('p0', 'i0')
    assert not playlist.done()
    threading.Timer(0.1, gate.set).start()
    assert playlist[2] == ('p2', 'i2')
    assert playlist[-1] == ('p2', 'i2')
    assert [entry[0] for entry in playlist.map(lambda e: (e[0] + '!', e[1]))] == ['p0!', 'p1!', 'p2!']


def test_deferred_playlist_reports_the_build_error_where_it_is_used():
    def build():
        raise ValueError('재생 목록 2번 b.json: motion file has no valid records')

    playlist = DeferredPlaylist(('p0', 'i0'), 2, build)
    assert playlist[0] == ('p0', 'i0')
    with pytest.raises(ValueError, match='재생 목록 2번'):
        playlist[1]
    assert isinstance(playlist.failed(), ValueError)


def test_deferred_playlist_wait_ends_on_stop():
    stop = threading.Event()
    playlist = DeferredPlaylist(('p0', 'i0'), 2, lambda: time.sleep(5.0) or [], stop_event=stop)
    threading.Timer(0.1, stop.set).start()
    started = time.monotonic()
    with pytest.raises(InterruptedError):
        playlist[1]
    assert time.monotonic() - started < 1.0


def test_group_prepare_builds_only_the_first_playlist_entry_before_returning(tmp_path):
    names = ('a.json', 'b.json', 'c.json')
    for index, name in enumerate(names):
        _write_motion(tmp_path / name, 300, phase=index)
    manager = _manager(tmp_path, _mapping(names=names))
    real_build = manager._plan_builder.build
    gate = threading.Event()
    built = []

    def gated_build(payload, **kwargs):
        if payload.get('motion_file_id') != 'a.json':
            gate.wait(5.0)
        built.append(payload.get('motion_file_id'))
        return real_build(payload, **kwargs)

    manager._plan_builder.build = gated_build
    session = GroupSession(manager, run_lock=manager._run_lock)
    started = time.monotonic()
    continuous, independent, plan, init, playlist = session._prepare_plans(_group_payload(), manager.motors)
    assert time.monotonic() - started < 2.0
    assert continuous and not independent
    assert built == ['a.json', 'a.json'], '예약 시각 전에 목록 2번 이후를 지었습니다'
    assert isinstance(playlist, DeferredPlaylist) and len(playlist) == 3
    assert plan['playlist_index'] == 0 and init['playlist_index'] == 0
    assert plan['motion_playlist'] == list(names)

    gate.set()
    entries = playlist.wait()
    assert [entry[0]['motion_file_id'] for entry in entries] == list(names)
    assert [entry[0]['playlist_index'] for entry in entries] == [0, 1, 2]
    # 1번은 앞에서 지은 그 계획 그대로(샘플을 같이 쓴다)
    assert entries[0][0]['samples'] is plan['samples']


def test_group_prepare_without_playlist_is_not_deferred(tmp_path):
    _write_motion(tmp_path / 'a.json', 100)
    manager = _manager(tmp_path, _mapping())
    session = GroupSession(manager, run_lock=manager._run_lock)
    *_, playlist = session._prepare_plans(_group_payload(), manager.motors)
    assert playlist == []
    *_, once_playlist = session._prepare_plans(_group_payload(run_mode='once'), manager.motors)
    assert once_playlist == []


# --------------------------------------------------------------------------- #
# 실제 크기 · 46000 프레임 × 20 조인트
# --------------------------------------------------------------------------- #

@pytest.mark.slow
def test_real_size_file_check_in_background_then_group_prepare_is_fast(tmp_path, monkeypatch):
    _write_motion(tmp_path / 'a.json', 46000)
    manager = _node(tmp_path)
    samplings = _count_sampling(monkeypatch)

    started = time.monotonic()
    _send(manager, 'check', 'big-check', _check_payload())
    _send(manager, 'status', 'big-status')
    status_at, _ = _response(manager, 'big-status')
    check_at, check = _response(manager, 'big-check', timeout=60.0)
    assert check['success'] is True, check
    assert status_at - started < 0.5, '큰 파일 검사 도중 상태 요청이 줄을 섰습니다'

    session = GroupSession(manager, run_lock=manager._run_lock)
    prepare_started = time.monotonic()
    _, _, plan, init, _ = session._prepare_plans(_group_payload(), manager.motors)
    prepare_sec = time.monotonic() - prepare_started
    assert len(samplings) == 1
    assert len(plan['samples']) == 46000
    assert prepare_sec < 1.0, f'검사 뒤 그룹 준비가 {prepare_sec:.2f} s'
