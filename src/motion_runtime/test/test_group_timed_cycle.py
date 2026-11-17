"""시간표 재생 · 회차 하나 = 시각이 박힌 명령 하나 · 재생 관리자가 제 시계로 초기 이동 → 시작 · 수정 목록 206 (2026-11-16)

실물 NY 2026-11-09 04:04 · 연동 노드가 초기 이동 예약 → 끝 확인 → 시작 예약을 따로 보내 그 왕복(최대 1.4 s)과 늦게 끝난
초기 이동(0.2~0.8 s)이 시작 여유 2 s 를 넘었다 · 4대 중 3대 「트리거가 이미 지났습니다」 로 회차를 쉼 · 188 은 여유를 4 s 로.

사용자 결정 2026-11-16 · 초기 이동이 늦게 끝나도 잘못이 아니다 · 끝나는 대로 시작(생략 아님 · 기록) · 다음 회차는 다시
시간표대로 · 너무 늦어 다음 회차 준비를 먹을 때만 그 회차를 쉰다(이유 기록).

진짜 `GroupSession` · 진짜 예약 기다림(`_wait_group_deadline`) · 초기 이동 · 재생만 가짜(시간만 흘림) · 여유를 짧게 줄여 빨리 돈다.
"""

import threading
import time

import pytest

from motion_common import timed_cycle
from motion_common.run_state import GROUP_CYCLE_SKIPPED_PHASE
from motion_runtime.group_session import GroupSession
from motion_runtime.motion_player import MotionPlayer
from motion_runtime.motion_run_manager import MotionRunManager
from motion_runtime.plan_builder import PlanBuilder

SETTLE = 0.05
END = 0.02
MOVE = 0.15
CLIP = 0.2
PERIOD = 0.8                      # 클립 0.2 + 초기 이동 0.15 + 여유 0.05 + 회차 끝 0.02 = 0.42 · 늦어도 0.38 s 까지 돈다
TOLERANCE = 0.05


@pytest.fixture(autouse=True)
def _short_margins(monkeypatch):
    monkeypatch.setattr(timed_cycle, 'INITIAL_MOVE_SETTLE_SEC', SETTLE)
    monkeypatch.setattr(timed_cycle, 'CYCLE_END_SEC', END)


class _Log:
    def __init__(self):
        self.lines = []

    def warning(self, text):
        self.lines.append(text)

    warn = info = error = warning


def _wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError('condition timeout')


def _manager(*, extra_init=None, session=None):
    """시간표 실행 하나 · 초기 이동은 계획 `MOVE` + 회차별 `extra_init` · 재생은 `CLIP`"""
    manager = MotionRunManager.__new__(MotionRunManager)
    manager._player = MotionPlayer(manager)
    manager._plan_builder = PlanBuilder(manager)
    manager._run_lock = threading.RLock()
    manager._group = GroupSession(manager, run_lock=manager._run_lock)
    manager._group.session = {
        'active': True, 'execution_id': 'tt-s1', 'state': 'preparing', 'cycle_number': 0,
        'join_cycle_number': 0, 'join_committed_cycle': 0, 'next_cycle_number': 0, 'next_start_at': 0.0,
        'next_initialize_at': 0.0, 'next_initialize_cycle_number': 0, 'stop_after_cycle': False,
        **(session or {}),
    }
    manager._stop_event = threading.Event()
    manager._graceful_stop_event = threading.Event()
    manager.period_sec = 0.001
    manager._status = {}
    manager.status = lambda: dict(manager._status)
    manager._set_status = lambda value: setattr(manager, '_status', dict(value))
    manager._update_status = lambda value: manager._status.update(dict(value))
    log = _Log()
    manager.get_logger = lambda: log

    def build(payload, *, initialization_only=False, motors_snapshot=None):
        if initialization_only:
            return {
                'axes': [{
                    'motor_axis': 0, 'motion_id': 'j', 'initial_move_time_sec': MOVE,
                    'initial_motor_target_rad': 0.0, 'first_frame_motor_target_rad': 0.0,
                }],
                'summary': {'duration_sec': 0.0},
            }
        return {
            'run_mode': 'once', 'repeat_mode': 'reinitialize', 'axes': [], 'group_execution': True,
            'summary': {'duration_sec': CLIP}, 'capabilities': {'continuous_run': {'available': True}},
        }

    manager._plan_builder.build = build
    extra = dict(extra_init or {})
    inits, runs = [], []

    def run_initialization(plan):
        cycle = int(plan.get('timed_cycle') or 0)
        inits.append((cycle, time.monotonic()))
        time.sleep(MOVE + extra.get(cycle, 0.0))
        manager._status.update({'state': 'initialized', 'phase': 'initialized'})

    def run_motion(plan):
        runs.append((int(plan['group_cycle_number']), time.monotonic(), float(plan.get('cycle_start_late_sec') or 0.0)))
        manager._status.update({'state': 'running', 'phase': 'running', 'group_cycle_number': plan['group_cycle_number']})
        time.sleep(CLIP)
        manager._status.update({'state': 'motion_completed', 'phase': 'group_motion_finishing'})

    manager._player._run_initialization = run_initialization
    manager._player._run_motion = run_motion
    return manager, inits, runs, log


def _start(manager, payload):
    worker = threading.Thread(target=manager._group._run, args=(payload, [{}]), daemon=True)
    worker.start()
    return worker


def _cycle(manager, cycle, start):
    return manager._group.schedule_timed_cycle({
        'execution_id': 'tt-s1', 'cycle_number': cycle,
        'start_monotonic': start, 'next_start_monotonic': start + PERIOD,
    })


def _at_barrier(manager, cycle):
    return lambda: (
        manager._group.session.get('state') == 'motion_completed'
        and int(manager._group.session.get('cycle_number') or 0) == cycle
    )


def _stop(manager, worker):
    manager._group.cancel({'execution_id': 'tt-s1'})
    worker.join(timeout=2.0)
    assert not worker.is_alive()


def test_one_timed_command_per_cycle_moves_back_from_its_start_and_starts_on_its_own_clock():
    """준비 뒤 회차 명령 하나 · 초기 이동은 이 PC 계획 시간으로 거꾸로(연동 노드의 짐작은 너무 늦었다) · 시작 명령 없음

    고치기 전에는 회차 명령이 없다(`schedule_timed_cycle`) · 시작은 연동 노드가 끝을 보고 따로 보내야 했다.
    """
    manager, inits, runs, log = _manager()
    now = time.monotonic()
    first = now + 0.6
    # 연동 노드의 짐작(초기 이동을 짧게 앎) · 이 시각에 출발하면 시작을 넘긴다
    worker = _start(manager, {'execution_id': 'tt-s1', 'initialize_monotonic': first - 0.05})
    assert _cycle(manager, 1, first)['success'] is True
    _wait_until(lambda: len(runs) == 1)
    assert inits and abs(inits[0][1] - (first - MOVE - SETTLE)) < TOLERANCE, '제 초기 이동 시간에서 거꾸로 센 시각'
    assert runs[0][0] == 1 and abs(runs[0][1] - first) < TOLERANCE and runs[0][2] == 0.0
    _wait_until(_at_barrier(manager, 1))
    second = first + PERIOD
    assert _cycle(manager, 2, second)['success'] is True
    _wait_until(lambda: len(runs) == 2)
    assert runs[1][0] == 2 and abs(runs[1][1] - second) < TOLERANCE, '2회차도 시각 명령 하나로'
    assert abs(inits[1][1] - (second - MOVE - SETTLE)) < TOLERANCE
    assert manager.status().get('timed_cycle') == 2
    _stop(manager, worker)
    assert not any('늦게' in line or '회차 생략' in line for line in log.lines), log.lines


def test_an_initial_move_that_ends_late_starts_late_without_skipping_and_the_next_cycle_is_on_time():
    """2회차 초기 이동이 0.1 s 늦게 끝남 · 끝나는 대로 시작 · 늦음 기록 · 3회차는 다시 시간표 시각

    고치기 전에는 시작 시각을 넘긴 시작 예약은 「트리거가 이미 지났습니다」 로 거절 · 그 회차를 쉬었다.
    """
    manager, inits, runs, log = _manager(extra_init={2: 0.15})
    now = time.monotonic()
    first = now + 0.4
    worker = _start(manager, {'execution_id': 'tt-s1', 'initialize_monotonic': first - MOVE - SETTLE})
    _cycle(manager, 1, first)
    _wait_until(_at_barrier(manager, 1))
    second = first + PERIOD
    _cycle(manager, 2, second)
    _wait_until(lambda: len(runs) == 2)
    late = runs[1][2]
    assert runs[1][0] == 2 and 0.06 < late < 0.16, runs
    assert abs(runs[1][1] - (second + late)) < TOLERANCE, '초기 이동이 끝난 그 자리에서'
    assert any(line.startswith('시간표 재생 · 2회차 0.1') and '늦게 시작' in line for line in log.lines), log.lines
    _wait_until(_at_barrier(manager, 2))
    third = second + PERIOD
    _cycle(manager, 3, third)
    _wait_until(lambda: len(runs) == 3)
    assert abs(runs[2][1] - third) < TOLERANCE and runs[2][2] == 0.0, '다음 회차는 다시 시간표대로'
    _stop(manager, worker)
    assert not any('회차 생략' in line for line in log.lines), log.lines


def test_an_initial_move_so_late_it_would_eat_the_next_preparation_skips_only_that_cycle():
    """2회차 초기 이동이 0.6 s 더 걸림 · 돌면 3회차 초기 이동까지 먹는다 · 그 회차만 쉬고(이유) 3회차는 제때"""
    manager, inits, runs, log = _manager(extra_init={2: 0.6})
    now = time.monotonic()
    first = now + 0.4
    worker = _start(manager, {'execution_id': 'tt-s1', 'initialize_monotonic': first - MOVE - SETTLE})
    _cycle(manager, 1, first)
    _wait_until(_at_barrier(manager, 1))
    second = first + PERIOD
    _cycle(manager, 2, second)
    _wait_until(_at_barrier(manager, 2))
    status = manager.status()
    assert status['phase'] == GROUP_CYCLE_SKIPPED_PHASE and status['group_cycle_number'] == 2
    assert status['cycle_skip_reason'].startswith('초기 이동이 0.') and '3회차 준비 시각 초과' in status['cycle_skip_reason']
    assert [cycle for cycle, *_ in runs] == [1], '2회차는 돌지 않는다'
    assert any(line.startswith('시간표 재생 · 2회차 생략: 초기 이동이') for line in log.lines), log.lines
    third = second + PERIOD
    assert _cycle(manager, 3, third)['success'] is True, '쉰 회차 뒤에도 같은 세션 · 다음 회차 명령을 받는다'
    _wait_until(lambda: len(runs) == 2)
    assert runs[1][0] == 3 and abs(runs[1][1] - third) < TOLERANCE and runs[1][2] == 0.0
    _stop(manager, worker)


def test_a_rejoining_pc_needs_no_separate_commit_the_cycle_command_is_the_commit():
    """복귀 길 · 계획을 짓는 중에 회차 명령이 와도 받아 두고 · 다 지으면 그것으로 합류 확정 → 초기 이동 → 시작"""
    manager, inits, runs, log = _manager(session={'state': 'join_preparing', 'cycle_number': 3, 'join_cycle_number': 3})
    fourth = time.monotonic() + 0.5
    assert _cycle(manager, 4, fourth)['success'] is True, '복귀 준비 중에도 받는다'
    worker = _start(manager, {'execution_id': 'tt-s1', 'join_cycle_number': 3})
    _wait_until(lambda: len(runs) == 1)
    assert runs[0][0] == 4 and abs(runs[0][1] - fourth) < TOLERANCE
    assert manager._group.session['join_committed_cycle'] == 3
    _stop(manager, worker)


def test_the_planned_initial_move_is_the_shared_rule_the_web_need_uses():
    """재생 관리자의 회차 초기 이동 계획 시간 = 웹 자동 회차 간격 필요 시간과 같은 규칙(`timed_cycle`) · 206 뒤처리

    기준점(기본)이고 첫 프레임이 초기 위치와 다르면 같은 시간으로 두 번(13-1) · 웹은 한 번만 세어 자동 간격이 모자랐다 ·
    두 쪽의 기본 초기 방식 · 「같음」 허용 오차(관절)가 갈리면 필요 시간이 재생과 갈린다.
    """
    from motion_runtime import motion_run_constants

    assert timed_cycle.DEFAULT_INITIAL_MODE == motion_run_constants.DEFAULT_INITIAL_MODE
    assert timed_cycle.FIRST_FRAME_SAME_JOINT_DEG == motion_run_constants.AC_TARGET_TOLERANCE_JOINT_DEG
    manager, *_ = _manager()
    axis = {'motor_axis': 0, 'motion_id': 'j', 'initial_move_time_sec': 5.0, 'initial_motor_target_rad': 0.0}
    same = {'axes': [{**axis, 'first_frame_motor_target_rad': 0.0}]}
    differs = {'axes': [{**axis, 'first_frame_motor_target_rad': 0.5}]}
    assert manager._group._initial_move_seconds(same) == timed_cycle.planned_initial_move_sec(5.0, False) == 5.0
    assert manager._group._initial_move_seconds(differs) == timed_cycle.planned_initial_move_sec(5.0, True) == 10.0
    assert manager._group._initial_move_seconds(differs, blend=False) == 5.0, '「초기 위치 이동」 만이면 한 번'


def test_the_cycle_command_is_checked_against_the_session():
    manager, *_ = _manager(session={'state': 'motion_completed', 'cycle_number': 5})
    start = time.monotonic() + 10.0
    assert _cycle(manager, 6, start)['success'] is True
    assert _cycle(manager, 6, start + 0.001).get('duplicate') is True, '같은 회차를 다시 받음(연동 노드 재시작) · 처음 것 그대로'
    assert manager._group.session['timed']['start'] == start
    with pytest.raises(ValueError, match='예상 7'):
        manager._group.session.update(state='motion_completed', cycle_number=6)
        _cycle(manager, 9, start)
    manager._group.session.update(state='running')
    with pytest.raises(ValueError, match='수신할 수 있는 상태가 아닙니다'):
        _cycle(manager, 7, start)
    with pytest.raises(ValueError, match='세션이 일치하지 않습니다'):
        manager._group.schedule_timed_cycle({'execution_id': 'other', 'cycle_number': 7, 'start_monotonic': start})
