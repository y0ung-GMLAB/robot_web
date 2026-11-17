"""시간표 재생 · 이 PC 혼자 시간표대로 · 수정 목록 186 (2026-11-09)

가짜 로컬 재생 관리자(그룹 실행 규칙만 흉내)로 시간을 흘려 본다 · 핵심은 「모든 PC 의 회차 시작 = 시간표 시각」 ·
늦게 켠 PC 는 다음 경계 · 문제는 그 PC 만 · 운영시간 끝은 주차 · 정지는 바로.
"""

from typing import Any, Dict, List, Mapping, Optional

import pytest

from motion_common import timed_cycle
from motion_common.run_state import GROUP_CYCLE_SKIPPED_PHASE
from motion_coordination.clock_driver import ClockDriver
from motion_coordination.clock_grid import Timeline
from motion_coordination.timetable import Choice

#: 실제 계획 짓기 여유(10 s · NY 실측 2026-11-16) · 아래 시나리오 시각은 45 s 일 때 짰다
REAL_BUILD_SEC = ClockDriver.BUILD_SEC


@pytest.fixture(autouse=True)
def _scenario_build_sec(monkeypatch):
    """시나리오 시각(들어가는 틱 · 쉬는 회차)을 45 s 로 짰다 · 규칙 시험이라 값과 상관없음 · 실제 값은
    `test_a_pc_that_boots_mid_window_joins_an_earlier_boundary_with_the_real_build_sec` 가 본다"""
    monkeypatch.setattr(ClockDriver, 'BUILD_SEC', 45.0)


class Clock:
    def __init__(self, wall: float) -> None:
        self.wall_value = float(wall)
        self.mono_value = 1000.0

    def wall(self) -> float:
        return self.wall_value

    def mono(self) -> float:
        return self.mono_value

    def advance(self, seconds: float) -> None:
        self.wall_value += seconds
        self.mono_value += seconds


class FakeRuntime:
    """`group_session` 의 순서 규칙만 · 초기 이동 실제 `init` 초 · 클립 `clip` 초

    실제 재생 관리자처럼 상태가 바뀔 때마다 표시(`status_stamp` · 단조)를 달고 명령 응답에 그 상태를 싣는다 · 수정 목록 199

    수정 목록 206 · 시간표 회차 명령(`group_cycle_at` · 「k 회차를 S 에 · 다음 회차 N」)을 받아 초기 이동 시작을 제 계획
    시간(`plan_init` · 기본 `init` · 조인트 매핑 값)에서 거꾸로 세고 · 늦게 시작 · 쉼은 재생 관리자와 같은 규칙
    (`motion_common.timed_cycle`)으로 정한다 · `late` = 회차별로 초기 이동이 계획보다 더 걸리는 초 {회차: 초}.
    복귀(`group_join`)는 회차 명령이 합류 확정을 겸한다 · 옛 길(`group_initialize_at` · `group_start_at`)은 이제 안 쓴다.
    """

    def __init__(
        self, clock: Clock, *, init: float = 5.0, clip: float = 80.0,
        plan_init: Optional[float] = None, late: Optional[Mapping[int, float]] = None,
    ) -> None:
        self.clock = clock
        self.init = init
        self.clip = clip
        self.plan_init = float(init if plan_init is None else plan_init)
        self.late = dict(late or {})
        self._seq = 0
        self.status: Dict[str, Any] = {'state': 'stopped', 'phase': 'stopped', 'status_stamp': self.stamp()}
        self.session: Dict[str, Any] = {}
        self.starts: List[tuple] = []
        self.skips: List[tuple] = []
        self.calls: List[str] = []
        self.busy = False

    def stamp(self) -> float:
        """재생 관리자 `status_stamp` · 같은 틱 안에서도 늘어난다"""
        self._seq += 1
        return self.clock.mono() + self._seq * 1e-6

    def set_status(self, **fields: Any) -> None:
        """실제 재생 관리자가 새 상태를 낸 것 · 표시를 단다"""
        self.status = {**fields, 'status_stamp': self.stamp()}

    def _ok(self, **extra: Any) -> Dict[str, Any]:
        return {'success': True, 'status': dict(self.status), **extra}

    def control(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        command = payload['command']
        self.calls.append(command)
        now = self.clock.mono()
        s = self.session
        if command in {'group_prepare', 'group_join'}:
            if self.busy or s:
                return {'success': False, 'message': '다른 실행 중'}
            join = int(payload.get('join_cycle_number') or 0)
            if command == 'group_prepare' and float(payload['initialize_monotonic']) <= now:
                return {'success': False, 'message': '그룹 초기 위치 이동 예약 트리거가 이미 지났습니다'}
            self.session = {'id': payload['execution_id'], 'cycle': join, 'join': join, 'timed': None,
                            'state': 'join_ready' if join else 'preparing'}
            self._show(state='join_ready' if join else 'preparing',
                       phase='group_join_ready' if join else 'group_preparing')
            return self._ok()
        if command == 'group_cycle_at':
            if not s or s['id'] != payload['execution_id']:
                return {'success': False, 'message': '활성 그룹 실행 세션이 일치하지 않습니다'}
            cycle = int(payload['cycle_number'])
            if s['timed'] and s['timed']['cycle'] == cycle:
                return self._ok(duplicate=True)
            if s['state'] == 'join_ready':
                expected = s['join'] + 1
            elif s['state'] == 'preparing' and s['cycle'] == 0:
                expected = 1
            elif s['state'] == 'motion_completed':
                expected = s['cycle'] + 1
            else:
                return {'success': False, 'message': '그룹 회차 명령을 수신할 수 있는 상태가 아닙니다'}
            if cycle != expected:
                return {'success': False, 'message': f'그룹 모션 회차가 일치하지 않습니다: 예상 {expected}'}
            start = float(payload['start_monotonic'])
            following = float(payload.get('next_start_monotonic') or 0.0)
            s['timed'] = {'cycle': cycle, 'start': start, 'next': following if following > start else 0.0}
            if s['state'] == 'join_ready':
                s.update(state='motion_completed', cycle=s['join'])     # 합류 확정을 겸함
                self._show(state='motion_completed', phase='group_join_committed')
            else:
                self.set_status(**{**self.status, 'timed_cycle': cycle})
            return self._ok()
        if command in {'group_cancel', 'stop_now'}:
            self.session = {}
            self.set_status(state='stopped', phase='stopped')
            return self._ok()
        return {'success': False, 'message': f'모르는 명령 {command}'}

    def _latest(self, timed: Mapping[str, Any]) -> float:
        return timed_cycle.latest_start(timed['start'], timed['next'], self.clip, self.plan_init)

    def _skipped(self, timed: Mapping[str, Any], ready: float, *, moved: bool) -> bool:
        s = self.session
        decision = timed_cycle.decide(
            cycle=timed['cycle'], start=timed['start'], ready_at=ready, latest=self._latest(timed), moved=moved,
        )
        if not decision.skip:
            return False
        s.update(state='motion_completed', cycle=timed['cycle'])
        self.skips.append((timed['cycle'], decision.skip))
        self._show(state='motion_completed', phase=GROUP_CYCLE_SKIPPED_PHASE, cycle_skip_reason=decision.skip,
                   timed_cycle=timed['cycle'])
        return True

    def step(self) -> None:
        """한 틱 · 같은 순간에 이어지는 일은 한 번에(초기 이동이 늦게 끝나면 그 자리에서 시작 · 실제 재생 관리자와 같음)"""
        for _ in range(4):
            if not self._step_once():
                return

    def _step_once(self) -> bool:
        s = self.session
        now = self.clock.mono()
        if not s:
            return False

        def due(at: float) -> bool:
            # 시험 시계는 0.1 s 를 더해 가며 흘러 부동소수 오차가 쌓인다(유닉스 초 크기면 수 ms) · 반 틱 안은 그 틱으로 본다
            return now + 0.05 >= at

        timed = s.get('timed')
        if s['state'] in {'preparing', 'motion_completed'} and timed and timed['cycle'] == s['cycle'] + 1:
            init_at = timed_cycle.initialize_at(timed['start'], self.plan_init)
            if self._skipped(timed, max(now, init_at) + self.plan_init, moved=False):
                return True
            s.update(state='init_wait', init_at=init_at)
            self._show(state='waiting', phase='group_cycle_initialize_scheduled', timed_cycle=timed['cycle'])
            return True
        if s['state'] == 'init_wait' and due(s['init_at']):
            began = max(now, s['init_at'])
            s.update(state='initializing', init_end=began + self.init + self.late.get(timed['cycle'], 0.0))
            self._show(state='initializing', phase='initializing', timed_cycle=timed['cycle'])
            return True
        if s['state'] == 'initializing' and due(s['init_end']):
            ended = max(now, s['init_end'])
            if self._skipped(timed, ended, moved=True):
                return True
            s.update(state='start_wait', start_at=max(timed['start'], ended),
                     late_sec=max(ended - timed['start'], 0.0))
            self._show(state='waiting', phase='group_start_scheduled', timed_cycle=timed['cycle'])
            return True
        if s['state'] == 'start_wait' and due(s['start_at']):
            s.update(state='running', cycle=timed['cycle'], ends=max(now, s['start_at']) + self.clip)
            self.starts.append((s['cycle'], round(self.clock.wall(), 3)))
            self._show(state='running', phase='group_running', timed_cycle=timed['cycle'],
                       cycle_start_late_sec=round(s['late_sec'], 3))
            return True
        if s['state'] == 'running' and now >= s['ends']:   # `_BlinkRuntime` 과 같은 잣대(그쪽이 먼저 가로챈다)
            s['state'] = 'motion_completed'
            self._show(phase='group_motion_completed')
            return True
        return False

    def _show(self, phase: str = '', *, state: str = '', **extra: Any) -> None:
        s = self.session
        self.set_status(
            group_execution=True, execution_id=s['id'], state=state or s['state'],
            phase=phase or f'group_{s["state"]}', current_cycle=s['cycle'], group_cycle_number=s['cycle'], **extra,
        )


def _run(driver: ClockDriver, runtime: FakeRuntime, clock: Clock, choice_of, seconds: float, *, view=None) -> None:
    steps = int(seconds / 0.1)
    for _ in range(steps):
        clock.advance(0.1)
        runtime.step()
        driver.tick(choice_of(clock.wall()), {'status': runtime.status, 'init_sec': runtime.init, **(view or {})})


def _pc(wall: float, *, clip: float = 80.0, init: float = 5.0, plan_init: Optional[float] = None, late=None):
    clock = Clock(wall)
    runtime = FakeRuntime(clock, clip=clip, init=init, plan_init=plan_init, late=late)
    finished: List[tuple] = []
    notes: List[str] = []
    driver = ClockDriver(
        runtime.control, info=notes.append, warn=notes.append, wall=clock.wall, mono=clock.mono,
        finish=lambda plan, park, why: (finished.append((plan, park)), runtime.control({'command': 'group_cancel'})),
    )
    return clock, runtime, driver, finished, notes


TIMELINE = Timeline('tt-s100000', anchor_unix=100_060.0, period_sec=100.0, end_unix=100_600.0)


def _always(choice: Choice):
    return lambda now: choice


def test_every_pc_starts_every_cycle_at_the_timetable_time():
    clock, runtime, driver, finished, _ = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 700.0)
    assert runtime.starts == [(k, 100_060.0 + (k - 1) * 100.0) for k in range(1, 7)], '1~6회차 · 시간표 시각에(6회차 100560 < 끝 100600)'
    assert finished == [('tt-s100000', True)], '운영시간 끝 · 마지막 회차 끝까지 → 주차'


def test_a_pc_that_boots_mid_window_joins_at_a_boundary_with_the_right_cycle_number():
    clock, runtime, driver, _, _ = _pc(100_215.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 400.0)
    # 100215 + 준비(45 + 5 + 1) → 4회차(100360)부터 · 로컬 회차 번호 = 시간표 회차 번호(재생 목록 순서)
    assert runtime.starts[0] == (4, 100_360.0)
    # 복귀 길 · 회차 명령 하나가 합류 확정을 겸하고 같은 틱에 · 초기 이동 · 시작 예약을 따로 보내지 않는다 · 수정 목록 206
    assert runtime.calls[:2] == ['group_join', 'group_cycle_at']
    assert 'group_join_commit' not in runtime.calls and 'group_start_at' not in runtime.calls


def test_a_pc_that_boots_mid_window_joins_an_earlier_boundary_with_the_real_build_sec(monkeypatch):
    """BUILD_SEC 45 → 10 s(NY 실측 첫 변환 최대 1.4 s · 사용자 2026-11-16) · 같은 PC 가 한 회차 일찍 들어온다"""
    monkeypatch.setattr(ClockDriver, 'BUILD_SEC', REAL_BUILD_SEC)
    assert REAL_BUILD_SEC == 10.0
    clock, runtime, driver, _, _ = _pc(100_215.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 400.0)
    # 100215 + 준비(10 + 5 + 1) = 100231 → 3회차(100260)부터 · 45 s 였으면 4회차(100360)
    assert runtime.starts[0] == (3, 100_260.0)
    assert runtime.calls[:2] == ['group_join', 'group_cycle_at']


def test_a_clip_longer_than_the_period_makes_only_this_pc_skip_and_come_back():
    clock, runtime, driver, _, notes = _pc(100_000.0, clip=97.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 560.0)
    started = [cycle for cycle, _ in runtime.starts]
    assert started[0] == 1 and 2 not in started, '1회차 끝이 2회차 초기 이동 시각을 넘김 · 2회차를 돌면 3회차 준비도 먹음 · 쉼'
    assert all(at == 100_060.0 + (k - 1) * 100.0 for k, at in runtime.starts), '돌아와도 시간표 시각'
    # 쉼은 재생 관리자가 정해 알린다 · 실행은 놓지 않고 다음 회차 명령을 이어서(전에는 놓고 다음 경계 복귀 길) · 수정 목록 206
    assert any(note.startswith('시간표 재생 · 2회차 생략: 현재 초기 이동을 시작해도') for note in notes), notes
    assert runtime.calls.count('group_prepare') == 1 and 'group_join' not in runtime.calls


def test_stop_now_stops_right_away_and_does_not_come_back():
    clock, runtime, driver, _, _ = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 120.0)
    assert runtime.status['state'] == 'running'
    _run(driver, runtime, clock, _always(Choice(reason='정지 상태', stopped_plan_id=TIMELINE.plan_id)), 1.0)
    assert runtime.calls[-1] == 'stop_now' and runtime.status['state'] == 'stopped'
    assert driver.report()['note'] == '정지 상태'


def test_stop_after_cycle_finishes_the_cycle_without_parking():
    clock, runtime, driver, finished, _ = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 120.0)
    cut = Timeline(TIMELINE.plan_id, TIMELINE.anchor_unix, 100.0, end_unix=TIMELINE.start_of(2) - 1e-3)
    _run(driver, runtime, clock, _always(Choice(timeline=cut, stop_after=True)), 100.0)
    assert [cycle for cycle, _ in runtime.starts] == [1]
    assert finished == [(TIMELINE.plan_id, False)]


def test_a_busy_pc_skips_that_cycle_and_takes_the_next():
    clock, runtime, driver, _, notes = _pc(100_000.0)
    runtime.busy = True
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 30.0)
    runtime.busy = False
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 200.0)
    assert runtime.starts[0] == (2, 100_160.0)
    assert any('1회차 생략' in note for note in notes)


def test_a_restarted_node_takes_over_the_running_cycle():
    clock, runtime, driver, _, _ = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 100.0)
    fresh = ClockDriver(runtime.control, info=lambda _: None, warn=lambda _: None, wall=clock.wall, mono=clock.mono)
    _run(fresh, runtime, clock, _always(Choice(timeline=TIMELINE)), 200.0)
    assert [cycle for cycle, _ in runtime.starts] == [1, 2, 3], '재시작한 노드가 이어받아 회차가 끊기지 않는다'


def test_the_start_blocker_is_shown_and_nothing_starts():
    clock, runtime, driver, _, _ = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 30.0, view={'start_blocker': '실행 준비 안 됨 · 모터 끊김'})
    assert runtime.calls == [] and driver.report()['note'] == '실행 준비 안 됨 · 모터 끊김'


def test_two_pcs_with_different_boot_times_play_the_same_cycles_together():
    a = _pc(100_000.0)
    b = _pc(100_000.0)
    _run(a[2], a[1], a[0], _always(Choice(timeline=TIMELINE)), 250.0)
    _run(b[2], b[1], b[0], _always(Choice(timeline=TIMELINE)), 50.0)   # b 는 늦게 시작한 셈(같은 시계)
    b[0].wall_value = a[0].wall_value
    _run(b[2], b[1], b[0], _always(Choice(timeline=TIMELINE)), 300.0)
    _run(a[2], a[1], a[0], _always(Choice(timeline=TIMELINE)), 300.0)
    common = set(a[1].starts) & set(b[1].starts)
    assert len(common) >= 2, '겹치는 회차는 같은 시각'


TOMORROW = Timeline('tt-s186400', anchor_unix=186_460.0, period_sec=100.0, end_unix=187_000.0)


def test_after_the_window_the_next_day_timeline_means_finish_and_park():
    clock, runtime, driver, finished, _ = _pc(100_000.0, clip=90.0)
    # 끝(100600) 뒤에는 다음 운영시간 시간표가 골라진다 · 6회차(100560)는 100650 에 끝남
    def choice_of(now):
        return Choice(timeline=TIMELINE if now < TIMELINE.end_unix else TOMORROW)

    _run(driver, runtime, clock, choice_of, 700.0)
    assert [cycle for cycle, _ in runtime.starts] == [1, 2, 3, 4, 5, 6]
    assert finished == [(TIMELINE.plan_id, True)], '운영시간 끝 · 도는 회차 끝까지 → 주차'


def test_switching_the_master_to_manual_stops_without_parking():
    clock, runtime, driver, finished, _ = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 120.0)
    _run(driver, runtime, clock, _always(Choice(reason='마스터 스케줄 OFF')), 100.0)
    assert [cycle for cycle, _ in runtime.starts] == [1]
    assert finished == [(TIMELINE.plan_id, False)], '도는 회차 끝까지 · 그 자리 정지'


# ---------------------------------------------------------------------- #
# 수정 목록 188 · 실제 재생 관리자는 정지 뒤에도 실행 번호를 남긴다 · 끝난 실행 때문에 쉬지 않는다
# ---------------------------------------------------------------------- #

def test_a_stopped_signal_run_left_in_the_runtime_does_not_block_the_timetable():
    """실물 NY 2026-11-09 03:49 · 신호 재생 그룹을 즉시 정지 → 시간표 재생 · 4대 모두 「다른 재생 중으로 해당 회차 생략」"""
    clock, runtime, driver, _, notes = _pc(100_000.0)
    runtime.status = {'group_execution': True, 'execution_id': 'exec-old', 'state': 'stopped', 'phase': 'stopped'}
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 200.0)
    assert runtime.starts and runtime.starts[0] == (1, 100_060.0)
    assert not any('다른 재생 중' in note for note in notes)


def test_a_stopped_timetable_run_is_not_adopted_again_and_again():
    """시간표 실행을 세운 뒤 남은 `tt-` 번호 · 틱마다 이어받기 → 취소를 되풀이하지 않는다"""
    clock, runtime, driver, _, _ = _pc(100_000.0)
    runtime.status = {
        'group_execution': True, 'execution_id': TIMELINE.plan_id, 'state': 'stopped', 'phase': 'stopped',
        'group_cycle_number': 1,
    }
    _run(driver, runtime, clock, _always(Choice(reason='정지 상태', stopped_plan_id=TIMELINE.plan_id)), 5.0)
    assert runtime.calls.count('group_cancel') == 0


def test_a_live_other_run_still_makes_the_pc_skip():
    clock, runtime, driver, _, notes = _pc(100_000.0)
    runtime.status = {'group_execution': True, 'execution_id': 'exec-other', 'state': 'running', 'phase': 'running'}
    runtime.busy = True
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 3.0)   # 1회차 들어갈 때(준비 54 s 전)
    assert runtime.starts == [] and 'group_prepare' not in runtime.calls
    assert driver.report()['note'] == '다른 재생 중으로 해당 회차 생략'



# ---------------------------------------------------------------------- #
# 수정 목록 188 · 시간 예산 · 실측(NY 2026-11-09 04:04) 조건에서도 매 회차 시간표 시각에 시작
# 초기 이동이 예정보다 늦게 끝나고(최대 0.8 s) · 그것을 늦게 본다(0.5 s 마다 읽음 + 왕복) · 전에는 3대가 놓쳤다
# ---------------------------------------------------------------------- #

def _run_seen_late(driver, runtime, clock, choice_of, seconds, *, late, init_sec):
    """로컬 상태를 `late` 초 늦게 본다 · 연동 노드가 읽는 간격 + 웹 · ROS 왕복"""
    history = []
    for _ in range(int(seconds / 0.1)):
        clock.advance(0.1)
        runtime.step()
        history.append((clock.mono(), dict(runtime.status)))
        seen = next((status for at, status in reversed(history) if at <= clock.mono() - late), {})
        driver.tick(choice_of(clock.wall()), {'status': seen, 'init_sec': init_sec})


def test_every_cycle_starts_on_time_when_the_initial_move_runs_long_and_is_seen_late():
    """수정 목록 206 · 초기 이동이 실측 최대(0.8 s)만큼 길고 로컬 상태를 0.6 s 늦게 봐도 매 회차 시간표 시각에

    시작은 재생 관리자가 제 시계로 하므로 늦게 보는 것은 시작과 상관없다(전에는 그 왕복 때문에 여유 4 s) · 남은 여유는
    초기 이동이 늦게 끝나는 몫(`timed_cycle.INITIAL_MOVE_SETTLE_SEC`) 하나.
    """
    from motion_coordination.clock_grid import auto_period
    period = auto_period([80.0 + 5.0])                         # 클립 80 + 초기 이동 5 → 회차 사이 포함
    assert period == 90.0, '85 + 회차 끝 0.5 + 시작 여유 1 = 86.5 → 90(188 은 85 + 2 + 4 + 2 = 93 → 100)'
    timeline = Timeline('tt-s100000', anchor_unix=100_060.0, period_sec=period, end_unix=100_060.0 + period * 5)
    clock, runtime, driver, _, notes = _pc(100_000.0, clip=80.0, init=5.8, plan_init=5.0)   # 초기 이동이 0.8 s 길다
    _run_seen_late(driver, runtime, clock, _always(Choice(timeline=timeline)), period * 5, late=0.6, init_sec=5.0)
    assert [cycle for cycle, _ in runtime.starts] == [1, 2, 3, 4, 5], notes
    assert all(at == 100_060.0 + (k - 1) * period for k, at in runtime.starts)
    assert not any('생략' in note or '늦게 시작' in note for note in notes), notes
    assert 'group_start_at' not in runtime.calls and 'group_initialize_at' not in runtime.calls


# ---------------------------------------------------------------------- #
# 수정 목록 188 · 끊긴 동안 즉시 정지가 있었고 다시 붙었을 때는 스케줄이 이미 다시 시작(정지 지워짐)
# 실물 NY 2026-11-09 05:48 시험 4 · floating2 가 다시 붙은 뒤에도 그 회차를 계속 돌았다
# ---------------------------------------------------------------------- #

def test_a_pc_that_missed_a_stop_now_stops_on_reconnect_and_rejoins_at_the_next_boundary():
    clock, runtime, driver, _, notes = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 120.0)   # 1회차 도는 중(끊김)
    assert runtime.status['state'] == 'running'
    halt_at = clock.wall() - 40.0                                             # 끊긴 동안 다른 PC 들은 섰다
    missed = Choice(timeline=TIMELINE, halt_plan_id=TIMELINE.plan_id, halt_at_unix=halt_at)
    _run(driver, runtime, clock, _always(missed), 1.0)                        # 다시 붙음 · 받은 것은 정지가 지워진 버전
    assert runtime.calls[-1] == 'stop_now' and runtime.status['state'] == 'stopped'
    assert any('놓친 즉시 정지' in note for note in notes)
    _run(driver, runtime, clock, _always(missed), 200.0)
    assert [cycle for cycle, _ in runtime.starts][1:] == [3], '쉬던 회차 다음 경계부터 다른 PC 와 같이'


def test_a_run_entered_after_the_stop_is_not_stopped_again():
    clock, runtime, driver, _, _ = _pc(100_000.0)
    earlier = Choice(timeline=TIMELINE, halt_plan_id=TIMELINE.plan_id, halt_at_unix=99_000.0)
    _run(driver, runtime, clock, _always(earlier), 200.0)
    assert [cycle for cycle, _ in runtime.starts] == [1, 2]
    assert 'stop_now' not in runtime.calls


def test_after_a_stop_now_is_lifted_by_the_schedule_the_pc_comes_back_at_the_next_boundary():
    """즉시 정지 → 스케줄이 다시 시작(정지 지움) · 전에는 그날 끝까지 「정지됨」 (NY 2026-11-09 05:55) · 수정 목록 188"""
    clock, runtime, driver, _, _ = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 120.0)
    stopped = Choice(reason='정지 상태', stopped_plan_id=TIMELINE.plan_id)
    _run(driver, runtime, clock, _always(stopped), 18.0)
    assert runtime.status['state'] == 'stopped' and driver.report()['note'] == '정지 상태'
    resumed = Choice(timeline=TIMELINE, halt_plan_id=TIMELINE.plan_id, halt_at_unix=100_120.0)
    _run(driver, runtime, clock, _always(resumed), 300.0)
    started = [cycle for cycle, _ in runtime.starts]
    assert started[0] == 1 and started[1:] and started[1] == 3, '2회차는 준비 시간이 모자라 쉬고 3회차부터'
    assert all(at == 100_060.0 + (k - 1) * 100.0 for k, at in runtime.starts)


# ---------------------------------------------------------------------- #
# 수정 목록 189 · 운영 종료 주차 뒤 남은 「초기 위치 이동 완료」 · 다음 운영 1회차부터 매 회차 조용히 쉬었다
# 실물 NY 2026-11-09 08:31 · 4대 서보 OFF 그대로 · 재생 0 · 로그 0줄
# ---------------------------------------------------------------------- #

PARKED = {
    'group_execution': False, 'execution_id': '', 'state': 'initialized', 'phase': 'initialized',
    'request_source': 'schedule_end', 'message': '초기 위치 이동 완료',
}


def test_the_first_cycle_after_a_schedule_end_park_prepares_and_plays():
    clock, runtime, driver, _, notes = _pc(100_000.0)
    runtime.status = dict(PARKED)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 200.0)
    assert runtime.calls[0] == 'group_prepare', '준비 길 · 서보 복구도 여기서'
    assert [cycle for cycle, _ in runtime.starts] == [1, 2]
    assert not any('생략' in note for note in notes)


def test_a_stale_group_initialized_execution_is_cancelled_once_and_the_cycle_is_entered():
    """수정 목록 193 ④ (사용자 2026-11-11) · 끝내기를 놓친 옛 그룹 실행(시작 전 · 연동 노드엔 없음)은 정리하고 들어간다

    189 때는 바쁜 것으로 보고 회차마다 쉬었다 · 그룹 초기 위치 뒤 cancel_before_start 를 놓친 PC 가 운영시간 내내 쉬었다
    (NY 엣지 ④ · WSL 재현) · 시간표 구동부는 연동 노드에 도는 신호 재생 실행이 있으면 돌지 않으므로 여기 온 것은 옛 실행.
    """
    clock, runtime, driver, _, notes = _pc(100_000.0)
    runtime.status = {'group_execution': True, 'execution_id': 'exec-other', 'state': 'initialized', 'phase': 'group_armed'}
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 200.0)
    assert runtime.calls[:2] == ['group_cancel', 'group_prepare']
    assert runtime.calls.count('group_cancel') == 1
    assert [cycle for cycle, _ in runtime.starts] == [1, 2]
    assert any('끝내기를 놓친 옛 그룹 실행(exec-other' in note for note in notes)


def test_a_running_group_execution_of_another_kind_is_not_touched():
    """도는 재생(`running`)은 옛 실행이 아니다 · 손대지 않고 회차를 쉰다"""
    clock, runtime, driver, _, notes = _pc(100_000.0)
    status = {'group_execution': True, 'execution_id': 'exec-other', 'state': 'running', 'phase': 'group_running'}
    for _ in range(300):
        clock.advance(0.1)
        driver.tick(Choice(timeline=TIMELINE), {'status': status, 'init_sec': runtime.init})
    assert runtime.calls == []
    assert any('다른 재생 중(exec-other)' in note for note in notes)


def test_a_skipped_cycle_is_logged_once_per_cycle_and_stays_on_screen_until_the_next_try():
    clock, runtime, driver, _, notes = _pc(100_000.0)
    runtime.status = {'group_execution': True, 'execution_id': 'exec-other', 'state': 'running', 'phase': 'running'}
    runtime.busy = True
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 120.0)
    skipped = [note for note in notes if '회차 생략' in note]
    assert skipped == [
        '시간표 재생 · 1회차 생략: 다른 재생 중(exec-other)',
        '시간표 재생 · 2회차 생략: 다른 재생 중(exec-other)',
    ], '회차마다 한 줄 · 틱마다 되풀이하지 않는다'
    assert driver.report()['note'] == '다른 재생 중으로 해당 회차 생략', '다음 회차 들어갈 때 전까지 남는다'


def test_the_start_blocker_is_logged_when_a_cycle_is_skipped_for_it():
    clock, runtime, driver, _, notes = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 30.0, view={'start_blocker': '실행 준비 안 됨 · 모터 끊김'})
    assert notes == ['시간표 재생 · 1회차 생략: 실행 준비 안 됨 · 모터 끊김']


# ---------------------------------------------------------------------- #
# 수정 목록 191 · 로컬이 끝난 시간표 실행은 장벽을 기다리지 않고 놓는다 · 회차 버림도 「N회차 쉼」 으로
# ---------------------------------------------------------------------- #

def test_a_run_whose_local_ended_stopped_is_let_go_and_parked_at_the_last_window_end():
    """실물 NY 2026-11-09 23:27 · 마스터만 단독 회차 후 정지로 `stopped` · 다음 24 h 창 없음 → 영영 쥐어 4대 주차 교착(B)"""
    clock, runtime, driver, finished, _ = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 100.0)
    assert runtime.starts == [(1, 100_060.0)] and driver.holding == TIMELINE.plan_id
    # 회차가 끝나며 장벽이 아니라 그 자리 정지로 끝남 · 같은 실행 번호가 남는다
    runtime.session = {}
    runtime.set_status(
        group_execution=True, execution_id=TIMELINE.plan_id, state='stopped', phase='stopped', group_cycle_number=1,
    )
    _run(driver, runtime, clock, _always(Choice(reason='운영시간 아님')), 2.0)
    assert driver.holding == ''
    assert finished == [(TIMELINE.plan_id, True)], '운영시간 끝 · 주차'


def test_a_dropped_cycle_is_logged_as_a_skipped_cycle():
    """실물 NY 2026-11-09 · 「1회차 로컬 실행 종료」 이 「회차 쉼」 으로 안 찾아졌다(D)"""
    clock, runtime, driver, _, notes = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 40.0)
    assert driver.holding == TIMELINE.plan_id
    runtime.session = {}
    runtime.set_status(state='initialized', phase='initialized')
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 5.0)
    skipped = [note for note in notes if '회차 생략' in note]
    assert skipped and skipped[0].startswith('시간표 재생 · 1회차 생략: 로컬 실행 종료')
    assert len(skipped) == 1


# ---------------------------------------------------------------------- #
# 수정 목록 193 (사용자 2026-11-11) · 그룹 정지로 선 PC 도 운영시간 끝에 주차 → 서보 OFF
# ---------------------------------------------------------------------- #

def _ticks(driver, clock, choice, seconds, *, mode=''):
    for _ in range(int(seconds / 0.1)):
        clock.advance(0.1)
        driver.tick(choice, {'status': {'state': 'stopped', 'phase': 'stopped'}, 'init_sec': 5.0, 'operation_mode': mode})


def test_a_pc_standing_by_a_group_stop_parks_once_when_the_operating_hours_end():
    clock, runtime, driver, finished, notes = _pc(100_000.0)
    _ticks(driver, clock, Choice(reason='정지 상태', stopped_plan_id='tt-s100000'), 60.0)
    assert finished == []
    _ticks(driver, clock, Choice(reason='운영시간 아님'), 5.0)
    assert finished == [('tt-s100000', True)]


def test_a_stop_after_cycle_cut_timeline_parks_at_the_end_too():
    clock, runtime, driver, finished, notes = _pc(100_000.0)
    cut = Timeline('tt-s100000', anchor_unix=99_000.0, period_sec=100.0, end_unix=99_500.0)
    _ticks(driver, clock, Choice(timeline=cut, stop_after=True), 30.0)
    tomorrow = Timeline('tt-s186400', anchor_unix=186_460.0, period_sec=100.0, end_unix=190_000.0)
    _ticks(driver, clock, Choice(timeline=tomorrow), 1.0)
    assert finished == [('tt-s100000', True)]


def test_no_park_if_the_stop_was_lifted():
    """수정 목록 201 · 옛 시험의 앞 절반(마스터 수동으로 정지를 2분 넘게 못 봄 → 주차 안 함)은 사용자 결정으로 뒤집혔다 ·
    `test_a_group_stop_parks_at_its_window_end_even_when_the_stop_is_not_seen` 으로 · 여기는 정지가 풀린 경우만"""
    clock, runtime, driver, finished, notes = _pc(100_000.0)
    _ticks(driver, clock, Choice(reason='정지 상태', stopped_plan_id='tt-s100000'), 5.0)
    _ticks(driver, clock, Choice(reason='수동 모드', stopped_plan_id='tt-s100000'), 5.0)
    assert driver._stopped_window == 'tt-s100000'
    _ticks(driver, clock, Choice(timeline=TIMELINE), 0.2)                  # 수동 → 스케줄 · 다시 돎
    assert driver._stopped_window == ''


def test_a_manual_pc_never_remembers_a_group_stop():
    clock, runtime, driver, finished, notes = _pc(100_000.0)
    _ticks(driver, clock, Choice(reason='수동 모드', stopped_plan_id='tt-s100000'), 5.0)
    _ticks(driver, clock, Choice(reason='운영시간 아님'), 5.0)
    assert finished == []


# ---------------------------------------------------------------------- #
# 수정 목록 194 · 실물 NY 2026-11-11 193 시험 결과
# ---------------------------------------------------------------------- #

def _human_stop(runtime, plan_id):
    """사람이 이 PC 만 정지(`/api/motion-run/stop`) · 실제 재생 관리자는 같은 실행 번호를 남긴 채 `stopped`"""
    runtime.session = {}
    runtime.set_status(
        group_execution=True, execution_id=plan_id, state='stopped', phase='stopped',
        group_cycle_number=1, message='즉시 정지',
    )


def test_a_pc_stopped_by_a_person_lets_go_and_rejoins_at_the_next_boundary():
    """A2 · 정지 뒤 {stopped · 같은 번호} 를 매 틱 쥐고 있어 그 운영시간 끝까지 안 돌아왔다(f2 00:02)

    수정 목록 199 · 정상 회차 끝에 끝난 상태가 안 나오므로 사람 정지는 다음 틱에 놓는다(195 의 5 s 확인 없음) ·
    고치기 전에는 그 뒤 몇 초 동안 쥐고 있어 이 시험이 실패한다.
    """
    clock, runtime, driver, finished, notes = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 100.0)
    assert runtime.starts == [(1, 100_060.0)]
    _human_stop(runtime, TIMELINE.plan_id)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 0.1)
    assert driver.holding == '' and 'group_cancel' in runtime.calls, '다음 틱에 놓는다 · 시간 기다림 없음'
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 7.0)
    cancel = runtime.calls.index('group_cancel')
    assert 'group_join' in runtime.calls[cancel:], '놓고 바로 다음 경계(2회차) 복귀 길'
    assert any(note.startswith('시간표 재생 · 1회차 생략: 로컬 실행 종료: 즉시 정지') for note in notes)
    assert finished == [], '주차하지 않는다(운영시간 안)'
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 200.0)
    assert [cycle for cycle, _ in runtime.starts][1:3] == [2, 3], '다음 경계부터 복귀 길로 다시 돈다'
    assert all(at == 100_060.0 + (k - 1) * 100.0 for k, at in runtime.starts)


def test_a_stopped_pc_with_its_servo_off_shows_why_it_skips():
    """A2 · 정지 → 서보 OFF · 다음 경계에 「N회차 생략: 서보 꺼짐」 이유가 남는다"""
    clock, runtime, driver, _, notes = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 100.0)
    _human_stop(runtime, TIMELINE.plan_id)
    off = {'start_blocker': '0번 모터 서보가 꺼져 있습니다'}
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 100.0, view=off)
    assert '시간표 재생 · 2회차 생략: 0번 모터 서보가 꺼져 있습니다' in notes
    assert [cycle for cycle, _ in runtime.starts] == [1]


def test_the_normal_cycle_barrier_is_not_mistaken_for_a_finished_run():
    """`stopped` · `completed` 만 끝으로 본다 · 회차 끝 장벽(motion_completed)은 그대로 다음 회차로"""
    clock, runtime, driver, _, notes = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 400.0)
    assert [cycle for cycle, _ in runtime.starts] == [1, 2, 3, 4]
    assert not any('회차 생략' in note for note in notes)


def test_a_dropped_cycle_reason_stays_on_screen_until_the_next_try():
    """C · 웹 서비스 재시작으로 로컬 실행이 사라짐 · 로그에만 있고 화면 note 는 다음 틱에 빈 값이었다(f4 00:48)

    수정 목록 199 · 다시 뜬 재생 관리자가 새 상태(빈 실행 · 새 표시)를 내면 바로 놓는다 · 고치기 전 시험은 빈 상태({})를
    3 s 뒤 「끝남」 으로 봤다 · 빈 상태는 「못 읽음」 이라 이제 그것만으로는 놓지 않는다(`test_a_status_that_never_follows…`)
    """
    clock, runtime, driver, _, notes = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 65.0)
    assert driver.holding == TIMELINE.plan_id
    runtime.session = {}
    runtime.set_status(state='idle', phase='idle', message='', group_execution=False, execution_id='')
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 0.2)
    assert driver.holding == ''
    assert driver.report()['note'] == '1회차 로컬 실행 종료: idle'
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 7.0)
    assert driver.report()['note'] == '1회차 로컬 실행 종료: idle', '다음 회차 들어갈 때까지 남는다'
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 100.0)
    assert driver.report()['note'] == '' and [cycle for cycle, _ in runtime.starts] == [1, 2]


def test_a_held_group_stop_says_so_instead_of_timetable_end():
    """E · 그룹 정지 유지 중 note 가 「시간표 끝」 이었다"""
    clock, runtime, driver, _, _ = _pc(100_200.0)
    cut = Timeline(TIMELINE.plan_id, TIMELINE.anchor_unix, 100.0, end_unix=TIMELINE.start_of(2) - 1e-3)
    _ticks(driver, clock, Choice(timeline=cut, stop_after=True), 5.0)
    assert driver.report()['note'] == '그룹 정지 유지 (운영 시간 종료까지)'


class _BlinkRuntime(FakeRuntime):
    """실제 플레이어처럼 회차 끝에 장벽 전 틈 · 수정 목록 199 부터 {motion_completed · group_motion_finishing}

    그룹 세션이 다음 재생 목록 항목을 짓는 동안(164) · 920 s 목록이면 몇 초 · 여기서는 `BLINK_SEC`.
    """

    BLINK_SEC = 1.0

    def step(self) -> None:
        s = self.session
        now = self.clock.mono()
        if s and s['state'] == 'running' and now >= s['ends']:
            s['state'] = 'blink'
            s['blink_until'] = now + self.BLINK_SEC
            self.set_status(**{
                **self.status, 'state': 'motion_completed', 'phase': 'group_motion_finishing',
                'message': f'그룹 모션 {s["cycle"]}회차 재생 끝 · 회차 끝 알림 준비',
            })
            return
        if s and s['state'] == 'blink':
            if now >= s['blink_until']:
                s['state'] = 'motion_completed'
                self._show(phase='group_motion_completed')
            return
        super().step()


def test_the_brief_completed_before_the_cycle_barrier_is_not_a_stop():
    """실물 NY 2026-11-11 14:31 · f2 23회차 끝 0.68 s 뒤 「23회차 생략: 로컬 실행 종료: 모션 실행 완료」 → 24회차 생략: 수정 목록 195

    199 · 그 틈은 이제 끝난 상태가 아니다 · 틈이 길어도(다음 항목 짓기 8 s) 쉼 없음 · 기다림 시간 기준 없음.
    """
    clock = Clock(100_000.0)
    runtime = _BlinkRuntime(clock, clip=80.0, init=5.0)
    runtime.BLINK_SEC = 8.0
    notes = []
    driver = ClockDriver(runtime.control, info=notes.append, warn=notes.append, wall=clock.wall, mono=clock.mono,
                         finish=lambda plan, park, why: runtime.control({'command': 'group_cancel'}))
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 500.0)
    assert [cycle for cycle, _ in runtime.starts] == [1, 2, 3, 4, 5]
    assert not any('회차 생략' in note for note in notes)


SERVO_OFF_MESSAGE = (
    '그룹 모션 실행 실패: Motion ID f2_neck_pitch: 0번 모터 서보가 꺼져 있습니다; '
    'Motion ID f2_neck_yaw: 1번 모터 서보가 꺼져 있습니다; Motion ID f2_eye_pitch: 2번 모터 서보가 꺼져 있습니다; '
    'Motion ID f2_eye_yaw_r: 3번 모터 서보가 꺼져 있습니다; Motion ID f2_eye_yaw_l: 4번 모터 서보가 꺼져 있습니다'
)


def test_the_servo_off_reason_is_short_and_only_for_servo_off():
    from motion_coordination.clock_driver import servo_off_reason

    assert servo_off_reason(SERVO_OFF_MESSAGE) == '서보가 꺼져 있습니다(0~4번 모터)'
    assert servo_off_reason('Motion ID a: 0번 모터 서보가 꺼져 있습니다; Motion ID b: 3번 모터 서보가 꺼져 있습니다') \
        == '서보가 꺼져 있습니다(0, 3번 모터)'
    mixed = 'Motion ID a: 0번 모터 서보가 꺼져 있습니다; Motion ID b: 1번 모터에 에러가 있습니다'
    assert servo_off_reason(mixed) == '', '다른 이유가 섞이면 오류 그대로'
    assert servo_off_reason('') == ''


def test_a_servo_off_pc_that_was_let_in_rests_instead_of_erroring():
    """NY 2026-11-12 00:32 · f2 정지 → 서보 OFF · 들어가기는 받아지고 로컬 검사에서 error · note 가 「오류」 였다 · 수정 목록 197"""
    clock, runtime, driver, _, notes = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 100.0)
    _human_stop(runtime, TIMELINE.plan_id)
    real = runtime.control

    def servo_off_control(payload):
        result = real(payload)
        if payload['command'] in {'group_join', 'group_prepare'} and result.get('success'):
            runtime.session = {}
            runtime.set_status(
                group_execution=True, execution_id=payload['execution_id'], state='error',
                phase='error', message=SERVO_OFF_MESSAGE,
            )
        return result

    runtime.control = servo_off_control
    driver._control = servo_off_control
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 100.0)
    assert '시간표 재생 · 2회차 생략: 서보가 꺼져 있습니다(0~4번 모터)' in notes
    assert not any('회차 오류' in note for note in notes)
    note = driver.report()['note']
    assert note.endswith('회차 생략: 서보가 꺼져 있습니다(0~4번 모터)'), note
    assert [cycle for cycle, _ in runtime.starts] == [1]


# ---------------------------------------------------------------------- #
# 수정 목록 199 · 로컬 상태는 보낸 명령의 응답 표시 이상일 때만 그 명령 뒤의 것 · 시간으로 짐작하지 않는다
# ---------------------------------------------------------------------- #

def test_a_local_status_seen_late_right_after_entering_does_not_end_the_run():
    """명령 뒤 3.2 s 동안 그 앞 상태(실행 없음)가 보인다 · 전에는 3 s(`STATUS_GRACE_SEC`) 뒤 「로컬 실행 종료」 으로 1회차를 쉼"""
    clock, runtime, driver, _, notes = _pc(100_000.0)
    _run_seen_late(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 250.0, late=3.2, init_sec=5.0)
    assert [cycle for cycle, _ in runtime.starts] == [1, 2], notes
    assert all(at == 100_060.0 + (k - 1) * 100.0 for k, at in runtime.starts)
    assert not any('생략' in note for note in notes), notes


def test_a_status_that_never_follows_the_command_is_a_failure_only_after_the_echo_timeout():
    """응답은 받았는데 로컬 상태가 그 뒤로 안 바뀐다(웹 · 재생 관리자 멈춤) · 실패 감지 한도 전에는 아무것도 정하지 않는다"""
    clock, runtime, driver, _, notes = _pc(100_000.0)
    frozen = dict(runtime.status)                                   # 명령 앞 상태 · 끝까지 이것만 보인다

    def tick(seconds):
        for _ in range(int(round(seconds / 0.1))):
            clock.advance(0.1)
            runtime.step()
            driver.tick(Choice(timeline=TIMELINE), {'status': frozen, 'init_sec': 5.0})

    tick(0.1)
    # 들어가기 + 그 회차 명령(같은 틱 · 수정 목록 206)
    assert runtime.calls == ['group_prepare', 'group_cycle_at'] and driver.holding == TIMELINE.plan_id
    tick(5.0)
    assert driver.holding == TIMELINE.plan_id, '옛 코드는 3 s 뒤 「로컬 실행 종료」 으로 놓았다'
    assert runtime.calls == ['group_prepare', 'group_cycle_at']
    tick(ClockDriver.ECHO_TIMEOUT_SEC - 5.0 + 0.2)
    assert driver.holding == '' and runtime.calls[-1] == 'group_cancel'
    assert any('명령 후 로컬 상태 변화 없음' in note for note in notes), notes


def test_an_error_left_by_the_previous_try_does_not_fold_the_new_try():
    """앞 시도(서보 꺼짐)의 오류 상태가 다시 들어간 직후 아직 보인다 · 그것으로 새 시도를 접지 않는다 · 새 상태의 오류만 본다

    전에는 오류는 기다림 없이 바로 봐 다시 들어가자마자 「N회차 생략: 서보가 꺼져 있습니다」 로 또 쉬었다.
    """
    clock, runtime, driver, _, notes = _pc(100_000.0)
    runtime.set_status(
        group_execution=True, execution_id=TIMELINE.plan_id, state='error', phase='error',
        message=SERVO_OFF_MESSAGE,
    )
    old_error = dict(runtime.status)
    # 앞 시도는 이미 놓았다 · 들어갈 때 보인 상태는 그 앞(정지) · 들어간 뒤 늦게 읽은 것이 앞 시도의 오류
    runtime.status = {'state': 'stopped', 'phase': 'stopped', 'status_stamp': old_error['status_stamp'] - 1.0}
    clock.advance(0.1)
    driver.tick(Choice(timeline=TIMELINE), {'status': runtime.status, 'init_sec': 5.0})
    assert runtime.calls == ['group_prepare', 'group_cycle_at'] and driver.holding == TIMELINE.plan_id
    for _ in range(3):                           # 늦게 읽은 로컬 상태 · 앞 시도의 오류
        clock.advance(0.1)
        driver.tick(Choice(timeline=TIMELINE), {'status': old_error, 'init_sec': 5.0})
    assert driver.holding == TIMELINE.plan_id and 'group_cancel' not in runtime.calls, notes
    runtime.set_status(**{**old_error, 'message': SERVO_OFF_MESSAGE})   # 새 시도의 진짜 오류(새 표시)
    clock.advance(0.1)
    driver.tick(Choice(timeline=TIMELINE), {'status': runtime.status, 'init_sec': 5.0})
    assert driver.holding == '' and runtime.calls[-1] == 'group_cancel'


def test_a_restarted_node_in_the_gap_before_the_cycle_barrier_takes_the_cycle_over():
    """장벽 전 틈({motion_completed · group_motion_finishing})에 연동 노드가 다시 떴다 · 도는 회차다 · 이어받는다

    전에는 「준비 단계」 로 보고 놓아(`group_cancel`) 그 PC 만 다음 회차를 쉬었다 · 수정 목록 199
    """
    clock = Clock(100_000.0)
    runtime = _BlinkRuntime(clock, clip=80.0, init=5.0)
    runtime.BLINK_SEC = 8.0
    first = ClockDriver(runtime.control, info=lambda _: None, warn=lambda _: None, wall=clock.wall, mono=clock.mono)
    _run(first, runtime, clock, _always(Choice(timeline=TIMELINE)), 142.0)     # 1회차 끝 100140 · 틈 100148 까지
    assert runtime.status['phase'] == 'group_motion_finishing'
    calls = len(runtime.calls)
    fresh = ClockDriver(runtime.control, info=lambda _: None, warn=lambda _: None, wall=clock.wall, mono=clock.mono)
    _run(fresh, runtime, clock, _always(Choice(timeline=TIMELINE)), 120.0)
    assert 'group_cancel' not in runtime.calls[calls:]
    assert [cycle for cycle, _ in runtime.starts] == [1, 2, 3]


def test_a_run_just_cancelled_is_not_taken_over_again_from_the_status_before_the_cancel():
    """놓은 직후 그 앞 상태(같은 실행 · 오류)가 한 번 더 보인다 · 다시 이어받아 두 번 취소하며 쉰 이유를 덮지 않는다 · 수정 목록 199"""
    clock, runtime, driver, _, notes = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 40.0)
    assert driver.holding == TIMELINE.plan_id
    runtime.set_status(**{**runtime.status, 'state': 'error', 'phase': 'error', 'message': SERVO_OFF_MESSAGE})
    before_cancel = dict(runtime.status)
    clock.advance(0.1)
    driver.tick(Choice(timeline=TIMELINE), {'status': before_cancel, 'init_sec': 5.0})
    assert driver.holding == '' and runtime.calls.count('group_cancel') == 1
    for _ in range(3):                                   # 늦게 읽은 로컬 상태 · 취소 앞
        clock.advance(0.1)
        driver.tick(Choice(timeline=TIMELINE), {'status': before_cancel, 'init_sec': 5.0})
    assert runtime.calls.count('group_cancel') == 1, runtime.calls
    assert driver.report()['note'] == '1회차 생략: 서보가 꺼져 있습니다(0~4번 모터)'


def test_the_driver_says_whether_a_status_belongs_to_its_last_command():
    clock, runtime, driver, _, _ = _pc(100_000.0)
    assert driver.belongs({}) is True, '쥔 실행이 없으면 거르지 않는다'
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 0.1)
    assert driver.belongs(runtime.status) is True
    assert driver.belongs({**runtime.status, 'status_stamp': runtime.status['status_stamp'] - 1.0}) is False
    assert driver.belongs({}) is False, '빈 상태 = 못 읽음'


# ---------------------------------------------------------------------- #
# 수정 목록 201 · 그룹 정지로 선 PC 는 그 운영시간 끝에 주차 · 정지가 안 보여도(마스터 수동 · 끊김)
# ---------------------------------------------------------------------- #

WINDOW_END = 100_600.0


def test_a_group_stop_parks_at_its_window_end_even_when_the_stop_is_not_seen():
    """사용자 결정 「끊겨도 운영시간 끝에 스스로 선다」 · 전에는 정지를 2분 못 보면 기억을 버려 서보를 켠 채 밤을 샜다"""
    clock, runtime, driver, finished, notes = _pc(100_000.0)
    stopped = Choice(reason='정지 상태', stopped_plan_id='tt-s100000', window_end_unix=WINDOW_END)
    _ticks(driver, clock, stopped, 5.0)
    _ticks(driver, clock, Choice(reason='마스터 스케줄 OFF'), 300.0)     # 정지가 안 보임 · 2분 훨씬 넘게
    assert finished == [] and clock.wall() < WINDOW_END, '운영시간 안 · 아직'
    _ticks(driver, clock, Choice(reason='마스터 스케줄 OFF'), WINDOW_END - clock.wall() + 0.2)
    assert finished == [('tt-s100000', True)], '그 운영시간 끝 시각에 한 번'
    _ticks(driver, clock, Choice(reason='마스터 스케줄 OFF'), 30.0)
    assert len(finished) == 1


def test_a_group_stop_unseen_for_minutes_is_still_parked_when_the_hours_end():
    """정지를 2분 넘게 못 봤다고 기억을 버리지 않는다(옛 `STOPPED_FORGET_SEC`) · 운영시간 끝 시각 없이 본 정지여도
    운영시간이 끝났다고 보이면(「운영시간 아님」) 주차 · 고치기 전에는 이 시험이 실패한다(옛 시험은 그 반대를 확인)"""
    clock, runtime, driver, finished, notes = _pc(100_000.0)
    _ticks(driver, clock, Choice(reason='정지 상태', stopped_plan_id='tt-s100000'), 5.0)
    _ticks(driver, clock, Choice(reason='마스터 스케줄 OFF'), 300.0)
    _ticks(driver, clock, Choice(reason='운영시간 아님'), 1.0)
    assert finished == [('tt-s100000', True)]


def test_a_group_stop_does_not_park_a_pc_left_in_manual_at_the_window_end():
    clock, runtime, driver, finished, notes = _pc(100_000.0)
    stopped = Choice(reason='정지 상태', stopped_plan_id='tt-s100000', window_end_unix=WINDOW_END)
    _ticks(driver, clock, stopped, 5.0)
    _ticks(driver, clock, Choice(reason='수동 모드', stopped_plan_id='tt-s100000'), WINDOW_END - clock.wall() + 1.0,
           mode='manual')
    assert finished == [] and driver._stopped_window == '', '사람이 이 PC 를 맡음 · 기억만 버린다'
    # 수동이었다가 끝나기 전에 스케줄로 돌아오면 그대로 주차
    clock, runtime, driver, finished, notes = _pc(100_000.0)
    _ticks(driver, clock, stopped, 5.0)
    _ticks(driver, clock, Choice(reason='수동 모드', stopped_plan_id='tt-s100000'), 100.0, mode='manual')
    _ticks(driver, clock, stopped, WINDOW_END - clock.wall() - 1.0, mode='schedule')
    assert finished == []
    _ticks(driver, clock, Choice(reason='운영시간 아님'), 2.0, mode='schedule')
    assert finished == [('tt-s100000', True)]


def test_a_human_group_run_releases_the_window_end_park():
    """사람이 그룹 재생을 돌렸다 · 그 재생이 끝난 직후(운영시간 끝 뒤) 갑자기 주차하지 않는다"""
    clock, runtime, driver, finished, notes = _pc(100_000.0)
    _ticks(driver, clock, Choice(reason='정지 상태', stopped_plan_id='tt-s100000', window_end_unix=WINDOW_END), 5.0)
    driver.release_stopped_window('수동 그룹 재생 시작')
    clock.advance(WINDOW_END - clock.wall() + 600.0)
    _ticks(driver, clock, Choice(reason='마스터 스케줄 OFF'), 1.0)
    assert finished == []
    assert any('주차 기억 버림' in note for note in notes)


def test_a_web_still_turning_servos_on_does_not_make_the_first_cycle_skip(monkeypatch):
    """NY 2026-11-16 · 운영시간 첫 회차 준비 · 웹이 꺼진 서보를 켜는 동안 이 노드가 HTTP 를 쥐어 실행기가 2~4 s 섰다 ·
    이제 웹은 「켜는 중」(`pending`)으로 바로 답하고 이 노드는 쉬지 않고 잠시 뒤 다시 묻는다 · 수정 목록 217"""
    clock, runtime, driver, _, notes = _pc(100_000.0)
    real = runtime.control
    waking = {'left': 6}

    def control(payload):
        if payload['command'] == 'group_prepare' and waking['left'] > 0:
            waking['left'] -= 1
            runtime.calls.append('group_prepare(pending)')
            return {'success': False, 'pending': 'servo_wake', 'message': '운영시간 시작 · 꺼진 서보를 켜는 중'}
        return real(payload)

    driver._control = control
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 200.0)
    assert runtime.starts[0] == (1, 100_060.0), '켜는 동안 쉬지 않고 1회차를 제때'
    pending = [i for i, call in enumerate(runtime.calls) if call == 'group_prepare(pending)']
    assert len(pending) == 6
    assert runtime.calls[pending[-1] + 1] == 'group_prepare', '켜진 뒤 같은 회차 준비'
    assert not any('생략' in note for note in notes)


def test_pending_asks_again_only_after_the_poll_interval_and_a_missed_entry_is_a_skip():
    clock, runtime, driver, _, notes = _pc(100_000.0)
    asked = []

    def control(payload):
        asked.append(round(clock.mono(), 1))
        return {'success': False, 'pending': 'servo_wake', 'message': '켜는 중'}

    driver._control = control
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 5.0)
    gaps = {round(b - a, 1) for a, b in zip(asked, asked[1:])}
    assert asked and gaps <= {ClockDriver.PENDING_POLL_SEC, round(ClockDriver.PENDING_POLL_SEC + 0.1, 1)}
    assert driver._note == '1회차 준비: 켜는 중'
    # 켜기가 끝내 안 끝나 1회차 들어갈 때(시작 − 준비)를 넘김 · 조용히 넘어가지 않고 쉼으로 남긴다
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 25.0)
    assert driver._note == '1회차 생략: 서보 ON 미완료'
    assert any('1회차 생략: 서보 ON 미완료' in note for note in notes)
