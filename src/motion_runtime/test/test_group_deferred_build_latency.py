"""재생 목록 뒤 짓기가 그룹 예약 확인 · 재생 틱을 굶기지 않는다 · 수정 목록 171 · 208

NY 실물 2026-11-03 · 그룹 시작 「floating1 자신의 예약 확인 늦음 · start_at · 400 ms 안에 답 없음」 ·
진행 PC 가 재생 목록 2번(920 s × 20 조인트)을 뒤에서 짓는 동안(164) 제 `start_at` 확인을 못 했다.

171 은 짓기를 1회차 시작 1.5 s 뒤로 미루고 짓는 스레드를 쉬어 가게(`background_pacing`) 했다 ·
208 은 짓기를 디스크 변환본 읽기로 바꿨다 · 변환본이 없으면 자식 프로세스가 변환한다 · 미루기 ·
쉬어 가기는 뺐다.

여기서 지키는 것:

    재생 목록 2번부터는 1회차가 시작되면 바로 짓는다 · 준비 · 초기 위치 이동 · 「모션 시작 대기」 ·
    `start_at` 확인 동안은 짓지 않는다
    1회차가 짧으면 · 다 짓기 전에는 회차 끝(장벽)을 알리지 않는다
    정지가 먼저 오면 짓지 않는다 · 짓는 도중이면 남은 파일은 안 짓는다
    변환본을 자식 프로세스가 만드는 동안 `group_start_at` 답이 빠르다
"""

import json
import socket
import threading
import time

import pytest

from motion_runtime import group_session as group_session_mod, motion_run_rules, plan_artifact
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
    assert not hasattr(group_session_mod, 'DEFERRED_BUILD_DELAY_SEC'), '171 의 미루기가 남았습니다(208)'
    return manager


def _start(manager):
    payload = {**_group_payload(), 'initialize_monotonic': time.monotonic() + 0.05}
    worker = threading.Thread(target=manager._group._run, args=(payload, manager.motors), daemon=True)
    worker.start()
    return worker


def _builds(manager, *names):
    return [event for event in manager.events if event[0] == 'build' and event[1] in names]


def test_playlist_items_are_built_when_cycle_one_starts(tmp_path, monkeypatch):
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
    assert motion_at >= start_at and first_build >= start_at
    # 1회차 시작에 바로 · 171 의 1.5 s 미루기는 없다(208)
    assert first_build - motion_at < 0.3, f'1회차 시작 뒤 {first_build - motion_at:.2f} s 에 지었습니다'
    manager._group.cancel({'execution_id': 'exec-164'})
    worker.join(timeout=5.0)


def test_short_first_cycle_reports_the_cycle_end_after_the_build(tmp_path, monkeypatch):
    """1회차(0.05 s)가 2번 짓기(0.5 s)보다 짧다 · 다 지은 뒤에 회차 끝을 알린다"""
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
    assert min(event[2] for event in builds) - motion_at < 0.5 + 0.3
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


def test_stop_before_the_build_starts_builds_nothing():
    stop = threading.Event()
    built = []
    playlist = DeferredPlaylist(('p0', 'i0'), 2, lambda: built.append(1) or [], stop_event=stop)
    stop.set()
    playlist.start()
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
    # 2번(느린 파일 · 1회차 시작에 바로 짓기 시작)을 짓는 중에 정지
    _wait_until(lambda: any(event[0] == 'motion' for event in manager.events))
    time.sleep(0.1)
    manager._stop_event.set()
    worker.join(timeout=10.0)
    time.sleep(0.5)
    assert _builds(manager, 'c.json') == [], '정지 뒤에도 남은 재생 목록을 지었습니다'


def test_wait_starts_the_build_when_not_started():
    playlist = DeferredPlaylist(('p0', 'i0'), 2, lambda: [('p0', 'i0'), ('p1', 'i1')])
    assert not playlist.started()
    started = time.monotonic()
    assert playlist[1] == ('p1', 'i1')
    assert playlist.started()
    assert time.monotonic() - started < 1.0


def test_no_thread_is_marked_for_pacing_any_more(tmp_path):
    """171 의 쉬어 가기는 뺐다(모듈째 없음) · 검사 작업 스레드는 그대로 돈다 · 208"""
    with pytest.raises(ImportError):
        from motion_runtime import background_pacing  # noqa: F401
    manager = _node(tmp_path)
    try:
        assert manager._background_executor().submit(lambda: 'ok').result(5.0) == 'ok'
    finally:
        manager._background_executor().shutdown(wait=True)


# --------------------------------------------------------------------------- #
# 뒤에서 짓는 동안 · 실행기 답 · 재생 틱
# --------------------------------------------------------------------------- #

def _project_node(tmp_path, frames, names=('a.json', 'b.json')):
    """프로젝트 폴더(`motions/` · `project.json`)에 둔 애니 · 변환본 자리가 생긴다 · 208"""
    project_dir = tmp_path / 'proj'
    (project_dir / 'motions').mkdir(parents=True)
    (project_dir / 'project.json').write_text('{}', encoding='utf-8')
    for index, name in enumerate(names):
        _write_motion(project_dir / 'motions' / name, frames[index], phase=float(index))
    manager = _node(tmp_path)
    manager.mapping = _mapping(names=names)
    manager._motion_file_path = lambda file_id: project_dir / 'motions' / file_id
    manager._group.session = {
        'active': True, 'execution_id': 'exec-171', 'state': 'armed',
        'cycle_number': 0, 'next_cycle_number': 0, 'next_start_at': 0.0,
    }
    return manager, project_dir


def _round_trips_while(manager, playlist, start_at):
    """진행 PC 제 `start_at` 확인 대역 · 실행기는 소켓에서 깨어(GIL 을 놓았다 다시 잡는다) 답한다 ·
    재생 틱 스레드도 같이 돈다(GIL 을 기다리는 스레드가 여럿 · 실물과 같은 모양)"""
    server, client = socket.socketpair()
    manager._publish_response = lambda response: server.sendall(b'x')
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
    return round_trips


def test_group_start_at_answers_quickly_while_the_playlist_compiles(tmp_path):
    """재생 목록 2번 변환본이 없다 · 자식 프로세스가 변환하는 동안 이 프로세스는 기다리기만 한다"""
    manager, project_dir = _project_node(tmp_path, (300, 12000))
    *_, playlist = manager._group._prepare_plans(_group_payload(), manager.motors)
    assert isinstance(playlist, DeferredPlaylist) and not playlist.started()
    round_trips = _round_trips_while(manager, playlist, time.monotonic() + 60.0)
    assert len(playlist.wait()) == 2
    assert manager._group.session['state'] == 'start_scheduled'
    artifacts = [path.name for path in (project_dir / 'runtime').rglob('*.rwplan')]
    assert any(name.startswith('samples-') for name in artifacts), artifacts
    assert len(round_trips) >= 5
    # 확인 마감 0.4 s · 171 전 데스크톱 최대 0.15~0.42 s(미니 PC 약 두 배)
    assert max(round_trips) < 0.2, f'start_at 답이 {max(round_trips) * 1000:.0f} ms 걸렸습니다'


@pytest.mark.slow
def test_real_size_playlist_compile_keeps_start_at_answers_fast(tmp_path):
    """46000 프레임 × 20 조인트 · 변환본 없음 · 자식 프로세스 변환 · 위와 같은 재기"""
    manager, _project_dir = _project_node(tmp_path, (3000, 46000))
    *_, playlist = manager._group._prepare_plans(_group_payload(), manager.motors)
    round_trips = _round_trips_while(manager, playlist, time.monotonic() + 120.0)
    assert len(playlist.wait()) == 2
    assert plan_artifact.COMPILE_IN_SUBPROCESS is True
    assert max(round_trips) < 0.2, f'start_at 답이 {max(round_trips) * 1000:.0f} ms 걸렸습니다'
