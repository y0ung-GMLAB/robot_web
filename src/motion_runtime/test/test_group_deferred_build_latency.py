"""재생 목록 뒤 짓기가 그룹 예약 확인 · 재생 틱을 굶기지 않는다 · 수정 목록 171

NY 실물 2026-11-03 · 그룹 시작 「floating1 자신의 예약 확인 늦음 · start_at · 400 ms 안에 답 없음」 ·
진행 PC 가 재생 목록 2번(920 s × 20 조인트)을 뒤에서 짓는 동안(164) 제 `start_at` 확인을 못 했다.

여기서 지키는 것:

    재생 목록 2번부터는 1회차가 시작되고(`DEFERRED_BUILD_DELAY_SEC` 뒤) 짓는다 · 준비 · 초기 위치 이동 ·
    「모션 시작 대기」 · `start_at` 확인 동안은 짓지 않는다
    1회차가 짧으면 회차 끝에서 바로 짓고 · 다 짓기 전에는 회차 끝(장벽)을 알리지 않는다
    정지가 먼저 오면 짓지 않는다 · 짓는 도중이면 남은 파일은 안 짓는다
    뒤에서 짓는 스레드(재생 목록 · 준비 검사)는 GIL 을 나눠 쓴다 · 그동안 `group_start_at` 답이 빠르다
"""

import json
import socket
import threading
import time

import pytest

from motion_runtime import background_pacing, group_session as group_session_mod, motion_run_rules
from motion_runtime.deferred_playlist import DeferredPlaylist

from test_group_prepare_long_file import (  # noqa: F401 · `_patched_rules` 는 자동 고정물
    _group_payload, _manager, _mapping, _Msg, _node, _patched_rules, _write_motion,
)

NAMES = ('a.json', 'b.json', 'c.json')


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError('condition timeout')


def _heavy_python(seconds):
    """계획 짓기 대역 · 사전 · 목록을 쉬지 않고 만드는 파이썬 계산(GIL 을 쥔다)"""
    end = time.perf_counter() + seconds
    kept = []
    while time.perf_counter() < end:
        kept.append([
            {'time_sec': index * 0.02, 'positions': {axis: float(axis) for axis in range(5)}}
            for index in range(500)
        ])
        if len(kept) > 50:
            kept.clear()
    return kept


# --------------------------------------------------------------------------- #
# 그룹 실행 · 언제 짓나
# --------------------------------------------------------------------------- #

def _group_run_manager(tmp_path, monkeypatch, *, cycle_sec=0.05, slow_files=(), slow_sec=0.0):
    """실제 파일 · 실제 계획 · 재생과 마감 기다림만 대역 · 일어난 순서를 `events` 에"""
    for index, name in enumerate(NAMES):
        _write_motion(tmp_path / name, 200, phase=index)
    manager = _manager(tmp_path, _mapping(names=NAMES))
    session = manager._group = group_session_mod.GroupSession(manager, run_lock=manager._run_lock)
    session.session = {
        'active': True, 'execution_id': 'exec-164', 'state': 'preparing',
        'cycle_number': 0, 'next_cycle_number': 0, 'next_start_at': 0.0,
        'next_initialize_at': 0.0, 'next_initialize_cycle_number': 0, 'stop_after_cycle': False,
    }
    manager._status = {}
    manager.status = lambda: dict(manager._status)
    manager._set_status = lambda value: setattr(manager, '_status', dict(value))
    manager._update_status = lambda value: manager._status.update(dict(value))
    manager.get_logger = lambda: type('Logger', (), {'error': lambda self, _m: None})()
    events = []
    manager.events = events
    real_build = manager._plan_builder.build

    def build(payload, **kwargs):
        name = payload.get('motion_file_id')
        if name in slow_files and not kwargs.get('initialization_only'):
            time.sleep(slow_sec)
        plan = real_build(payload, **kwargs)
        events.append(('build', name, time.monotonic(), dict(session.session).get('state')))
        return plan

    manager._plan_builder.build = build

    def wait_deadline(scheduled, *, phase, **_kwargs):
        events.append(('deadline', phase, time.monotonic(), None))
        while time.monotonic() < scheduled:
            if manager._stop_event.is_set():
                raise InterruptedError()
            time.sleep(0.005)

    manager._wait_group_deadline = wait_deadline
    manager._player._run_initialization = lambda _plan: manager._status.update({
        'state': 'initialized', 'phase': 'initialized',
    })

    def run_motion(plan):
        events.append(('motion', plan.get('motion_file_id'), time.monotonic(), None))
        end = time.monotonic() + cycle_sec
        while time.monotonic() < end and not manager._stop_event.is_set():
            time.sleep(0.005)
        manager._status.update({
            'state': 'completed', 'phase': 'completed',
            'lifecycle': {'motion_started_at': time.time()},
        })

    manager._player._run_motion = run_motion
    monkeypatch.setattr(group_session_mod, 'DEFERRED_BUILD_DELAY_SEC', 0.3)
    return manager


def _start(manager):
    payload = {**_group_payload(), 'initialize_monotonic': time.monotonic() + 0.05}
    worker = threading.Thread(target=manager._group._run, args=(payload, manager.motors), daemon=True)
    worker.start()
    return worker


def _builds(manager, *names):
    return [event for event in manager.events if event[0] == 'build' and event[1] in names]


def test_playlist_items_are_not_built_before_cycle_one_starts(tmp_path, monkeypatch):
    manager = _group_run_manager(tmp_path, monkeypatch, cycle_sec=1.0)
    worker = _start(manager)
    _wait_until(lambda: manager._group.session.get('state') == 'armed')
    # 초기 위치 이동 · 「모션 시작 대기」 동안 짓지 않는다
    time.sleep(0.4)
    assert _builds(manager, 'b.json', 'c.json') == [], '1회차 시작 전에 재생 목록을 지었습니다'

    start_at = time.monotonic() + 0.2
    reply = manager._group.schedule_cycle({
        'execution_id': 'exec-164', 'cycle_number': 1, 'start_monotonic': start_at,
    })
    assert reply['success'] is True
    _wait_until(lambda: len(_builds(manager, 'b.json', 'c.json')) == 4)
    motion_at = next(event[2] for event in manager.events if event[0] == 'motion')
    first_build = min(event[2] for event in _builds(manager, 'b.json', 'c.json'))
    assert motion_at >= start_at
    # 1회차가 시작되고 시작 보고 여유가 지난 뒤
    assert first_build - motion_at >= 0.3 - 0.02
    manager._group.cancel({'execution_id': 'exec-164'})
    worker.join(timeout=5.0)


def test_short_first_cycle_builds_at_once_and_reports_the_cycle_end_after_the_build(tmp_path, monkeypatch):
    """1회차(0.05 s)가 짓기 여유(0.3 s)보다 짧고 2번 짓기가 길다(0.5 s) · 회차 끝에서 바로 짓고 다 지은 뒤 알린다"""
    manager = _group_run_manager(
        tmp_path, monkeypatch, cycle_sec=0.05, slow_files=('b.json',), slow_sec=0.5,
    )
    worker = _start(manager)
    _wait_until(lambda: manager._group.session.get('state') == 'armed')
    manager._group.schedule_cycle({
        'execution_id': 'exec-164', 'cycle_number': 1, 'start_monotonic': time.monotonic() + 0.05,
    })
    _wait_until(lambda: manager._group.session.get('state') == 'motion_completed')
    completed_at = time.monotonic()
    motion_at = next(event[2] for event in manager.events if event[0] == 'motion')
    builds = _builds(manager, 'b.json', 'c.json')
    assert len(builds) == 4, '회차 끝을 알리기 전에 재생 목록을 다 짓지 않았습니다'
    assert all(event[2] <= completed_at for event in builds)
    # 회차 끝(0.05 s)에서 바로 짓기 시작 · 여유(0.3 s)를 기다리지 않았다 · 2번 0.5 s
    assert min(event[2] for event in builds) - motion_at < 0.3 + 0.5
    # 장벽 보고 이후 · 다음 회차 초기 위치는 2번의 첫 프레임으로
    manager._group.schedule_initialization({
        'execution_id': 'exec-164', 'cycle_number': 1, 'initialize_monotonic': time.monotonic() + 0.05,
    })
    _wait_until(lambda: manager._group.session.get('state') == 'cycle_ready')
    manager._group.schedule_cycle({
        'execution_id': 'exec-164', 'cycle_number': 2, 'start_monotonic': time.monotonic() + 0.05,
    })
    _wait_until(lambda: [event[1] for event in manager.events if event[0] == 'motion'] == ['a.json', 'b.json'])
    manager._group.cancel({'execution_id': 'exec-164'})
    worker.join(timeout=5.0)
    assert not worker.is_alive()


def test_stop_before_cycle_one_builds_nothing(tmp_path, monkeypatch):
    manager = _group_run_manager(tmp_path, monkeypatch)
    worker = _start(manager)
    _wait_until(lambda: manager._group.session.get('state') == 'armed')
    manager._group.cancel({'execution_id': 'exec-164'})
    worker.join(timeout=5.0)
    time.sleep(0.4)
    assert _builds(manager, 'b.json', 'c.json') == []


def test_stop_during_the_build_delay_builds_nothing():
    stop = threading.Event()
    built = []
    playlist = DeferredPlaylist(('p0', 'i0'), 2, lambda: built.append(1) or [], stop_event=stop)
    playlist.start(0.3)
    assert playlist.started() and not playlist.done()
    stop.set()
    _wait_until(playlist.done, timeout=1.0)
    assert built == []
    with pytest.raises(InterruptedError):
        playlist[1]


def test_stop_during_the_build_skips_the_rest(tmp_path, monkeypatch):
    manager = _group_run_manager(tmp_path, monkeypatch, cycle_sec=5.0, slow_files=('b.json',), slow_sec=0.3)
    worker = _start(manager)
    _wait_until(lambda: manager._group.session.get('state') == 'armed')
    manager._group.schedule_cycle({
        'execution_id': 'exec-164', 'cycle_number': 1, 'start_monotonic': time.monotonic() + 0.05,
    })
    # 2번(느린 파일)을 짓는 중에 정지
    _wait_until(lambda: any(event[0] == 'motion' for event in manager.events))
    time.sleep(0.3 + 0.1)
    manager._stop_event.set()
    worker.join(timeout=10.0)
    time.sleep(0.5)
    assert _builds(manager, 'c.json') == [], '정지 뒤에도 남은 재생 목록을 지었습니다'


def test_wait_starts_a_delayed_build_at_once():
    playlist = DeferredPlaylist(('p0', 'i0'), 2, lambda: [('p0', 'i0'), ('p1', 'i1')])
    assert not playlist.started()
    playlist.start(30.0)
    started = time.monotonic()
    assert playlist[1] == ('p1', 'i1')
    assert time.monotonic() - started < 1.0


def test_the_build_thread_is_paced():
    seen = []
    playlist = DeferredPlaylist(('p0', 'i0'), 1, lambda: seen.append(background_pacing.is_paced()) or [('p0', 'i0')])
    playlist.wait()
    assert seen == [True]
    assert not background_pacing.is_paced(), '부른 스레드까지 표시했습니다'


def test_the_check_worker_is_paced(tmp_path):
    manager = _node(tmp_path)
    try:
        assert manager._background_executor().submit(background_pacing.is_paced).result(5.0) is True
    finally:
        manager._background_executor().shutdown(wait=True)


# --------------------------------------------------------------------------- #
# 뒤에서 짓는 동안 · 실행기 답 · 재생 틱
# --------------------------------------------------------------------------- #

def test_a_paced_thread_rests_and_an_unmarked_thread_does_not(monkeypatch):
    """표시한 스레드만 `RUN_SEC` 마다 쉰다 · 쉰 횟수를 센다"""
    rests = []
    real_time = background_pacing.time

    class _CountingTime:
        monotonic = staticmethod(real_time.monotonic)

        @staticmethod
        def sleep(seconds):
            rests.append(threading.current_thread().name)
            real_time.sleep(seconds)

    monkeypatch.setattr(background_pacing, 'time', _CountingTime)
    flags = {}

    def heavy(paced):
        if paced:
            background_pacing.pace_current_thread()
        flags[paced] = background_pacing.is_paced()
        _heavy_python(0.5)

    for paced in (True, False):
        thread = threading.Thread(target=heavy, args=(paced,), name=f'heavy-{paced}', daemon=True)
        thread.start()
        thread.join(10.0)
    assert flags == {True: True, False: False}
    # 0.5 s ÷ (10 ms 일 + 2 ms 쉼) ≈ 40 번
    assert rests.count('heavy-True') >= 10, f'쉰 횟수 {rests.count("heavy-True")}'
    assert rests.count('heavy-False') == 0


def _armed_node(tmp_path):
    manager = _node(tmp_path)
    manager._group.session = {
        'active': True, 'execution_id': 'exec-171', 'state': 'armed',
        'cycle_number': 0, 'next_cycle_number': 0, 'next_start_at': 0.0,
    }
    return manager


def test_group_start_at_answers_quickly_while_the_playlist_builds(tmp_path):
    """진행 PC 제 `start_at` 확인 대역 · 실행기는 소켓에서 깨어(GIL 을 놓았다 다시 잡는다) 답한다 ·
    재생 틱 스레드도 같이 돈다(GIL 을 기다리는 스레드가 여럿 · 실물과 같은 모양)
    """
    manager = _armed_node(tmp_path)
    server, client = socket.socketpair()
    manager._publish_response = lambda response: server.sendall(b'x')
    start_at = time.monotonic() + 60.0
    finished = threading.Event()

    def executor():
        while server.recv(1) == b'q':
            manager._request_callback(_Msg(json.dumps({
                'request_id': 'start-at', 'command': 'group_start_at', 'project_generation': 0,
                'payload': {'execution_id': 'exec-171', 'cycle_number': 1, 'start_monotonic': start_at},
            })))

    def ticks():
        origin = time.monotonic()
        tick = 0
        while not finished.is_set():
            tick += 1
            motion_run_rules._sleep_until(origin + tick * 0.02)

    threading.Thread(target=executor, daemon=True).start()
    threading.Thread(target=ticks, daemon=True).start()
    playlist = DeferredPlaylist(('p0', 'i0'), 2, lambda: (_heavy_python(1.5), [('p0', 'i0'), ('p1', 'i1')])[1])
    playlist.start()
    round_trips = []
    try:
        _wait_until(lambda: playlist.started(), timeout=1.0)
        while not playlist.done():
            asked = time.perf_counter()
            client.sendall(b'q')
            client.recv(1)
            round_trips.append(time.perf_counter() - asked)
            time.sleep(0.02)
    finally:
        finished.set()
        client.sendall(b'e')
    playlist.wait()
    assert manager._group.session['state'] == 'start_scheduled'
    assert len(round_trips) >= 20
    # 확인 마감 0.4 s · 고치기 전 데스크톱 최대 0.15~0.42 s(미니 PC 약 두 배)
    assert max(round_trips) < 0.2, f'start_at 답이 {max(round_trips) * 1000:.0f} ms 걸렸습니다'


@pytest.mark.slow
def test_real_size_playlist_build_keeps_start_at_answers_fast(tmp_path):
    """46000 프레임 × 20 조인트 · 실제 계획 짓기 · 위와 같은 재기"""
    _write_motion(tmp_path / 'a.json', 3000)
    _write_motion(tmp_path / 'b.json', 46000, phase=1.0)
    manager = _armed_node(tmp_path)
    manager.mapping = _mapping(names=('a.json', 'b.json'))
    server, client = socket.socketpair()
    manager._publish_response = lambda response: server.sendall(b'x')
    start_at = time.monotonic() + 120.0

    def executor():
        while server.recv(1) == b'q':
            manager._request_callback(_Msg(json.dumps({
                'request_id': 'start-at', 'command': 'group_start_at', 'project_generation': 0,
                'payload': {'execution_id': 'exec-171', 'cycle_number': 1, 'start_monotonic': start_at},
            })))

    finished = threading.Event()

    def ticks():
        origin = time.monotonic()
        tick = 0
        while not finished.is_set():
            tick += 1
            motion_run_rules._sleep_until(origin + tick * 0.02)

    threading.Thread(target=executor, daemon=True).start()
    threading.Thread(target=ticks, daemon=True).start()
    *_, playlist = manager._group._prepare_plans(_group_payload(), manager.motors)
    assert isinstance(playlist, DeferredPlaylist) and not playlist.started()
    playlist.start()
    round_trips = []
    try:
        while not playlist.done():
            asked = time.perf_counter()
            client.sendall(b'q')
            client.recv(1)
            round_trips.append(time.perf_counter() - asked)
            time.sleep(0.02)
    finally:
        finished.set()
        client.sendall(b'e')
    assert len(playlist.wait()) == 2
    assert max(round_trips) < 0.2, f'start_at 답이 {max(round_trips) * 1000:.0f} ms 걸렸습니다'
