"""재생 노드 쪽 정지 표지 · 재생 세션 · 수정 목록 200 · 203

감독 정지(표지 증가) = 이 PC 재생 정지 · 전에는 재생기가 safety 상태의 「정지 처리 중」(0.5 s)을 프레임
틱에서 볼 때까지 돌았고, 대기 · 장벽 · 카운트다운처럼 프레임을 안 보내는 동안에는 알아채지 못했다 ·
이제는 표지가 바뀌는 순간 「정지」 와 같은 길로 세우고, 세션 · 본 표지를 상태로 알린다 ·
감독은 그것으로 프레임을 받고(세션) 「정지 정리 끝」 을 정한다.

rclpy 노드 없이 돈다.
"""

import json
import threading

from std_msgs.msg import String

from motion_runtime.motion_run_manager import MotionRunManager


class AliveThread:
    def __init__(self, alive=True):
        self.alive = alive

    def is_alive(self):
        return self.alive


def _manager(*, run_marker=('boot', 0), seen=('boot', 0), state='running'):
    manager = MotionRunManager.__new__(MotionRunManager)
    manager._run_lock = threading.RLock()
    manager._run_thread = AliveThread()
    manager._run_task_done = False
    manager._run_stop_marker = run_marker
    manager._seen_stop_marker = seen
    manager._supervisor_stopped_marker = None
    manager._stop_event = threading.Event()
    manager._safety_status_lock = threading.Lock()
    manager._latest_safety_status = None
    manager._latest_safety_status_at = None
    manager._status = {'state': state}
    manager.stops = []
    manager._handle_stop = lambda: manager.stops.append(True)
    return manager


def _safety(manager, payload):
    manager._safety_status_callback(String(data=json.dumps(payload)))


def test_a_new_stop_marker_stops_only_the_run_taken_before_it_through_the_stop_path():
    """프레임을 안 보내는 동안(장벽 · 대기 · 카운트다운)이어도 그 순간 선다 · 같은 정지로 두 번 세우지 않는다"""
    manager = _manager()

    _safety(manager, {'stop_boot': 'boot', 'stop_epoch': 1, 'stop_settled': False})
    _safety(manager, {'stop_boot': 'boot', 'stop_epoch': 1, 'stop_settled': False})

    assert manager.stops == [True]
    assert manager._seen_stop_marker == ('boot', 1), '본 표지를 상태로 알린다'

    # 정지 직후의 주차 · 초기 이동 · 실행을 잡을 때 이미 새 표지였다 · 세우지 않는다
    after = _manager(run_marker=('boot', 1))
    _safety(after, {'stop_boot': 'boot', 'stop_epoch': 1, 'stop_settled': False})
    assert after.stops == [] and after._seen_stop_marker == ('boot', 1)

    # 알람 · 긴급 · 앱솔루트와 함께 온 정지는 「정지」 로 덮지 않는다 · 재생기가 이유를 남기고 오류로 끝낸다
    alarm = _manager()
    _safety(alarm, {
        'stop_boot': 'boot', 'stop_epoch': 1, 'servo_alarm_grade': 2,
        'message': '2등급 서보 에러 · 전체 모터 동작 차단',
    })
    assert alarm.stops == [] and alarm._seen_stop_marker == ('boot', 1)


def test_no_run_means_nothing_to_stop_but_the_marker_is_seen():
    manager = _manager()
    manager._run_thread = AliveThread(alive=False)

    _safety(manager, {'stop_boot': 'boot', 'stop_epoch': 1})

    assert manager.stops == []
    assert manager._seen_stop_marker == ('boot', 1)


def test_the_playback_session_tells_the_supervisor_what_to_accept():
    manager = _manager(run_marker=('boot', 3), seen=('boot', 3), state='running')
    with manager._run_lock:
        session = manager._playback_session()
    assert session == {
        'active': True, 'streaming': True,
        'stop_boot': 'boot', 'stop_epoch': 3,
        'seen_stop_boot': 'boot', 'seen_stop_epoch': 3,
    }

    # 회차 사이(도달 확인)는 세션은 열려 있고 프레임은 안 흘린다 · 1등급 축 복구 대기가 풀리는 자리
    manager._status = {'state': 'verifying'}
    with manager._run_lock:
        session = manager._playback_session()
    assert session['active'] is True and session['streaming'] is False

    # 정지 요청 · 오류 · 실행 끝 → 세션 닫힘 · 감독이 축을 바로 놓는다
    for change in (
        lambda: manager._stop_event.set(),
        lambda: manager._status.update(state='error'),
        lambda: setattr(manager, '_run_task_done', True),
    ):
        manager._stop_event.clear()
        manager._status = {'state': 'running'}
        manager._run_task_done = False
        change()
        with manager._run_lock:
            assert manager._playback_session()['active'] is False


def test_the_run_task_closes_its_session_and_says_so_at_once():
    """단독 실행 끝 · 상태를 바로 낸다 · 감독은 0.15 s 임대가 끝나길 기다리지 않고 축을 놓는다 · 203"""
    manager = _manager()
    published = []
    manager._status_pub = object()
    manager._publish_status = lambda: published.append(manager._run_task_done)
    manager._player = type('Player', (), {'_prepare_and_run': lambda *_args: None})()
    manager._run_thread = threading.current_thread()

    manager._run_task('run', {}, [])

    assert manager._run_task_done is True
    assert published == [True]


def test_claiming_a_run_records_the_marker_and_a_run_number():
    """실행 표지 · 번호 · 주차가 「이번 실행의 상태」 를 시각 비교 없이 가린다 · 수정 목록 36 · 200"""
    manager = _manager()
    manager._run_thread = None
    manager._graceful_stop_event = threading.Event()
    manager._playback_ownership_error = lambda axes=None: ''
    manager._current_motors = lambda: [{'controller_index': 0}]
    manager._latest_safety_status = {'stop_boot': 'boot', 'stop_epoch': 5}

    manager._claim_run_slot()
    first = manager._run_seq
    manager._claim_run_slot()

    assert manager._run_stop_marker == ('boot', 5)
    assert manager._run_task_done is False
    assert manager._run_seq == first + 1


def _group_run_manager():
    """그룹 실행 스레드만 돌리는 관리자 · 계획 · 대기 · 재생은 갈아 끼운다"""
    from motion_runtime.group_session import GroupSession

    manager = _manager(state='preparing')
    manager._graceful_stop_event = threading.Event()
    manager._group = GroupSession(manager, run_lock=manager._run_lock)
    manager._group.session = {'active': True, 'execution_id': 'exec-a', 'state': 'preparing'}
    manager.status = lambda: dict(manager._status)
    manager._update_status = lambda values: manager._status.update(dict(values))
    manager._wait_group_deadline = lambda *_args, **_kwargs: None
    manager.get_logger = lambda: type('Logger', (), {'error': lambda self, _message: None})()
    manager._status_pub = object()
    published = []

    def publish():
        with manager._run_lock:
            published.append(manager._playback_session()['active'])

    manager._publish_status = publish
    manager._player = type('Player', (), {
        '_run_initialization': staticmethod(lambda _plan: manager._status.update(state='initialized')),
    })()
    group = manager._group
    group._prepare_plans = lambda _payload, _motors: (True, True, {}, {}, [])
    cycles = iter([(1, 0.0)])
    group._wait_cycle = lambda _execution_id: next(cycles, None)
    return manager, published


def test_the_group_run_thread_closes_its_session_and_says_so_at_once():
    """그룹 실행 스레드가 정상으로 끝나도(`completed`) 세션을 바로 닫고 알린다 · 수정 목록 203 뒤처리

    각자 재생이 목표 회차를 다 돌면 상태는 `completed`(세션 끝 상태가 아님) · 전에는 스레드가 끝난 뒤
    다음 0.5 s 상태 틱에야 세션이 닫힌 것이 나가 감독이 재생이 쥔 축을 늦게 놓았다.
    """
    manager, published = _group_run_manager()
    seen_while_running = []

    def run_independent(*_args):
        manager._status.update(state='completed', phase='completed')
        with manager._run_lock:
            # 스레드가 아직 살아 있는 동안은 세션이 열려 있다 · 이 자리가 옛 틈
            seen_while_running.append(manager._playback_session()['active'])

    manager._group._run_independent = run_independent
    worker = threading.Thread(
        target=manager._group._run,
        args=({'execution_id': 'exec-a', 'initialize_monotonic': 0.0}, []),
        daemon=True,
    )
    manager._run_thread = worker
    worker.start()
    worker.join(timeout=2.0)

    assert not worker.is_alive()
    assert seen_while_running == [True]
    assert manager._run_task_done is True
    assert published == [False], '스레드 끝에서 한 번 · 세션 닫힘으로'


def test_a_late_group_thread_does_not_close_a_newer_session():
    """늦게 끝난 옛 그룹 스레드는 새 실행(다른 스레드)의 세션을 닫지 않는다"""
    manager, published = _group_run_manager()
    manager._group._run_independent = lambda *_args: manager._status.update(state='completed')
    worker = threading.Thread(
        target=manager._group._run,
        args=({'execution_id': 'exec-a', 'initialize_monotonic': 0.0}, []),
        daemon=True,
    )
    newer = AliveThread()
    manager._run_thread = newer
    worker.start()
    worker.join(timeout=2.0)

    assert manager._run_task_done is False
    assert manager._run_thread is newer
    assert published == [True], '알리기는 하지만 새 실행의 세션은 그대로'
