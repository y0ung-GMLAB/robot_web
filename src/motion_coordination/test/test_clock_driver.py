"""시간표 재생 · 이 PC 혼자 시간표대로 · 수정 목록 186 (2026-11-09)

가짜 로컬 재생 관리자(그룹 실행 규칙만 흉내)로 시간을 흘려 본다 · 핵심은 「모든 PC 의 회차 시작 = 시간표 시각」 ·
늦게 켠 PC 는 다음 경계 · 문제는 그 PC 만 · 운영시간 끝은 주차 · 정지는 바로.
"""

from typing import Any, Dict, List, Mapping

from motion_coordination.clock_driver import ClockDriver
from motion_coordination.clock_grid import Timeline
from motion_coordination.timetable import Choice


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
    """`group_session` 의 순서 규칙만 · 초기 이동 `init` 초 · 클립 `clip` 초"""

    def __init__(self, clock: Clock, *, init: float = 5.0, clip: float = 80.0) -> None:
        self.clock = clock
        self.init = init
        self.clip = clip
        self.status: Dict[str, Any] = {'state': 'stopped', 'phase': 'stopped'}
        self.session: Dict[str, Any] = {}
        self.starts: List[tuple] = []
        self.calls: List[str] = []
        self.busy = False

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
            self.session = {'id': payload['execution_id'], 'cycle': join, 'state': 'join_ready' if join else 'preparing',
                            'init_at': None if join else float(payload['initialize_monotonic'])}
            self._show()
            return {'success': True}
        if command == 'group_join_commit':
            if s.get('state') != 'join_ready':
                return {'success': False, 'message': '복귀 준비 안 됨'}
            s.update(state='motion_completed', cycle=int(payload['cycle_number']))
            self._show(phase='group_join_committed')
            return {'success': True}
        if command == 'group_initialize_at':
            if s.get('state') != 'motion_completed' or int(payload['cycle_number']) != s['cycle']:
                return {'success': False, 'message': '회차 초기화 번호가 일치하지 않습니다'}
            if float(payload['initialize_monotonic']) <= now:
                return {'success': False, 'message': '트리거가 이미 지났습니다'}
            s.update(state='cycle_initialize_scheduled', init_at=float(payload['initialize_monotonic']))
            self._show()
            return {'success': True}
        if command == 'group_start_at':
            if s.get('state') not in {'armed', 'cycle_ready'} or int(payload['cycle_number']) != s['cycle'] + 1:
                return {'success': False, 'message': '시작 예약 불가'}
            if float(payload['start_monotonic']) <= now:
                return {'success': False, 'message': '그룹 모션 시작 트리거가 이미 지났습니다'}
            s.update(state='start_scheduled', start_at=float(payload['start_monotonic']), next=int(payload['cycle_number']))
            self._show()
            return {'success': True}
        if command in {'group_cancel', 'stop_now'}:
            self.session = {}
            self.status = {'state': 'stopped', 'phase': 'stopped'}
            return {'success': True}
        return {'success': False, 'message': f'모르는 명령 {command}'}

    def step(self) -> None:
        s = self.session
        now = self.clock.mono()
        if not s:
            return
        if s['state'] == 'preparing' and now >= s['init_at'] + self.init:
            s['state'] = 'armed'
            self._show(phase='group_armed')
        elif s['state'] == 'cycle_initialize_scheduled' and now >= s['init_at'] + self.init:
            s['state'] = 'cycle_ready'
            self._show(phase='group_cycle_initialized')
        elif s['state'] == 'start_scheduled' and now >= s['start_at']:
            s.update(state='running', cycle=s['next'], ends=now + self.clip)
            self.starts.append((s['cycle'], round(self.clock.wall(), 3)))
            self._show(phase='group_running')
        elif s['state'] == 'running' and now >= s['ends']:
            s['state'] = 'motion_completed'
            self._show(phase='group_motion_completed')

    def _show(self, phase: str = '') -> None:
        s = self.session
        self.status = {
            'group_execution': True, 'execution_id': s['id'], 'state': s['state'],
            'phase': phase or f'group_{s["state"]}', 'current_cycle': s['cycle'], 'group_cycle_number': s['cycle'],
        }


def _run(driver: ClockDriver, runtime: FakeRuntime, clock: Clock, choice_of, seconds: float, *, view=None) -> None:
    steps = int(seconds / 0.1)
    for _ in range(steps):
        clock.advance(0.1)
        runtime.step()
        driver.tick(choice_of(clock.wall()), {'status': runtime.status, 'init_sec': runtime.init, **(view or {})})


def _pc(wall: float, *, clip: float = 80.0, init: float = 5.0):
    clock = Clock(wall)
    runtime = FakeRuntime(clock, clip=clip, init=init)
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
    # 100215 + 준비(45 + 5 + 2) → 4회차(100360)부터 · 로컬 회차 번호 = 시간표 회차 번호(재생 목록 순서)
    assert runtime.starts[0] == (4, 100_360.0)
    assert runtime.calls[:3] == ['group_join', 'group_join_commit', 'group_initialize_at']


def test_a_clip_longer_than_the_period_makes_only_this_pc_skip_and_come_back():
    clock, runtime, driver, _, notes = _pc(100_000.0, clip=97.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 560.0)
    started = [cycle for cycle, _ in runtime.starts]
    assert started[0] == 1 and 2 not in started, '1회차 끝이 2회차 초기 이동 시각을 넘김 · 2회차 쉼'
    assert all(at == 100_060.0 + (k - 1) * 100.0 for k, at in runtime.starts), '돌아와도 시간표 시각'
    assert any('놓침' in note for note in notes)


def test_stop_now_stops_right_away_and_does_not_come_back():
    clock, runtime, driver, _, _ = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 120.0)
    assert runtime.status['state'] == 'running'
    _run(driver, runtime, clock, _always(Choice(reason='정지됨', stopped_plan_id=TIMELINE.plan_id)), 1.0)
    assert runtime.calls[-1] == 'stop_now' and runtime.status['state'] == 'stopped'
    assert driver.report()['note'] == '정지됨'


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
    assert any('1회차 쉼' in note for note in notes)


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
    _run(driver, runtime, clock, _always(Choice(reason='마스터 스케줄 꺼짐')), 100.0)
    assert [cycle for cycle, _ in runtime.starts] == [1]
    assert finished == [(TIMELINE.plan_id, False)], '도는 회차 끝까지 · 그 자리 정지'


# ---------------------------------------------------------------------- #
# 수정 목록 188 · 실제 재생 관리자는 정지 뒤에도 실행 번호를 남긴다 · 끝난 실행 때문에 쉬지 않는다
# ---------------------------------------------------------------------- #

def test_a_stopped_signal_run_left_in_the_runtime_does_not_block_the_timetable():
    """실물 NY 2026-11-09 03:49 · 신호 재생 그룹을 즉시 정지 → 시간표 재생 · 4대 모두 「다른 재생 중 · 이 회차 쉼」"""
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
    _run(driver, runtime, clock, _always(Choice(reason='정지됨', stopped_plan_id=TIMELINE.plan_id)), 5.0)
    assert runtime.calls.count('group_cancel') == 0


def test_a_live_other_run_still_makes_the_pc_skip():
    clock, runtime, driver, _, notes = _pc(100_000.0)
    runtime.status = {'group_execution': True, 'execution_id': 'exec-other', 'state': 'running', 'phase': 'running'}
    runtime.busy = True
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 3.0)   # 1회차 들어갈 때(준비 54 s 전)
    assert runtime.starts == [] and 'group_prepare' not in runtime.calls
    assert driver.report()['note'] == '다른 재생 중 · 이 회차 쉼'



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
    from motion_coordination.clock_grid import auto_period
    period = auto_period([80.0 + 5.0])                         # 클립 80 + 초기 이동 5 → 회차 사이 포함
    timeline = Timeline('tt-s100000', anchor_unix=100_060.0, period_sec=period, end_unix=100_060.0 + period * 5)
    clock, runtime, driver, _, notes = _pc(100_000.0, clip=80.0, init=6.5)   # 초기 이동이 1.5 s 길다
    _run_seen_late(driver, runtime, clock, _always(Choice(timeline=timeline)), period * 5, late=0.6, init_sec=5.0)
    assert [cycle for cycle, _ in runtime.starts] == [1, 2, 3, 4, 5], notes
    assert all(at == 100_060.0 + (k - 1) * period for k, at in runtime.starts)
    assert not any('놓침' in note or '지났' in note for note in notes)


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
    stopped = Choice(reason='정지됨', stopped_plan_id=TIMELINE.plan_id)
    _run(driver, runtime, clock, _always(stopped), 18.0)
    assert runtime.status['state'] == 'stopped' and driver.report()['note'] == '정지됨'
    resumed = Choice(timeline=TIMELINE, halt_plan_id=TIMELINE.plan_id, halt_at_unix=100_120.0)
    _run(driver, runtime, clock, _always(resumed), 300.0)
    started = [cycle for cycle, _ in runtime.starts]
    assert started[0] == 1 and started[1:] and started[1] == 3, '2회차는 준비 시간이 모자라 쉬고 3회차부터'
    assert all(at == 100_060.0 + (k - 1) * 100.0 for k, at in runtime.starts)
