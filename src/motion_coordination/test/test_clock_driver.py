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
    assert not any('쉼' in note for note in notes)


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
    skipped = [note for note in notes if '회차 쉼' in note]
    assert skipped == [
        '시간표 재생 · 1회차 쉼 · 다른 재생 중(exec-other)',
        '시간표 재생 · 2회차 쉼 · 다른 재생 중(exec-other)',
    ], '회차마다 한 줄 · 틱마다 되풀이하지 않는다'
    assert driver.report()['note'] == '다른 재생 중 · 이 회차 쉼', '다음 회차 들어갈 때 전까지 남는다'


def test_the_start_blocker_is_logged_when_a_cycle_is_skipped_for_it():
    clock, runtime, driver, _, notes = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 30.0, view={'start_blocker': '실행 준비 안 됨 · 모터 끊김'})
    assert notes == ['시간표 재생 · 1회차 쉼 · 실행 준비 안 됨 · 모터 끊김']


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
    runtime.status = {
        'group_execution': True, 'execution_id': TIMELINE.plan_id, 'state': 'stopped', 'phase': 'stopped',
        'group_cycle_number': 1,
    }
    _run(driver, runtime, clock, _always(Choice(reason='운영시간 아님')), 2.0)
    assert driver.holding == ''
    assert finished == [(TIMELINE.plan_id, True)], '운영시간 끝 · 주차'


def test_a_dropped_cycle_is_logged_as_a_skipped_cycle():
    """실물 NY 2026-11-09 · 「1회차 로컬 실행이 끝남」 이 「회차 쉼」 으로 안 찾아졌다(D)"""
    clock, runtime, driver, _, notes = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 40.0)
    assert driver.holding == TIMELINE.plan_id
    runtime.session = {}
    runtime.status = {'state': 'initialized', 'phase': 'initialized'}
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 5.0)
    skipped = [note for note in notes if '회차 쉼' in note]
    assert skipped and skipped[0].startswith('시간표 재생 · 1회차 쉼 · 로컬 실행이 끝남')
    assert len(skipped) == 1


# ---------------------------------------------------------------------- #
# 수정 목록 193 (사용자 2026-11-11) · 그룹 정지로 선 PC 도 운영시간 끝에 주차 → 서보 OFF
# ---------------------------------------------------------------------- #

def _ticks(driver, clock, choice, seconds):
    for _ in range(int(seconds / 0.1)):
        clock.advance(0.1)
        driver.tick(choice, {'status': {'state': 'stopped', 'phase': 'stopped'}, 'init_sec': 5.0})


def test_a_pc_standing_by_a_group_stop_parks_once_when_the_operating_hours_end():
    clock, runtime, driver, finished, notes = _pc(100_000.0)
    _ticks(driver, clock, Choice(reason='정지됨', stopped_plan_id='tt-s100000'), 60.0)
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


def test_no_park_if_the_stop_was_lifted_or_not_seen_for_a_while():
    clock, runtime, driver, finished, notes = _pc(100_000.0)
    _ticks(driver, clock, Choice(reason='정지됨', stopped_plan_id='tt-s100000'), 5.0)
    _ticks(driver, clock, Choice(reason='마스터 스케줄 꺼짐'), 200.0)      # 마스터 수동으로 오래
    _ticks(driver, clock, Choice(reason='운영시간 아님'), 5.0)
    assert finished == [], '사람이 만지는 중 · 주차 안 함'
    clock, runtime, driver, finished, notes = _pc(100_000.0)
    _ticks(driver, clock, Choice(reason='정지됨', stopped_plan_id='tt-s100000'), 5.0)
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
    runtime.status = {
        'group_execution': True, 'execution_id': plan_id, 'state': 'stopped', 'phase': 'stopped',
        'group_cycle_number': 1, 'message': '즉시 정지',
    }


def test_a_pc_stopped_by_a_person_lets_go_and_rejoins_at_the_next_boundary():
    """A2 · 정지 뒤 {stopped · 같은 번호} 를 매 틱 쥐고 있어 그 운영시간 끝까지 안 돌아왔다(f2 00:02)"""
    clock, runtime, driver, finished, notes = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 100.0)
    assert runtime.starts == [(1, 100_060.0)]
    _human_stop(runtime, TIMELINE.plan_id)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 4.0)
    assert 'group_cancel' not in runtime.calls, '끝남이 5 s 이어져야 놓는다(195)'
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 3.0)
    cancel = runtime.calls.index('group_cancel')
    assert 'group_join' in runtime.calls[cancel:], '놓고 바로 다음 경계(2회차) 복귀 길'
    assert any(note.startswith('시간표 재생 · 1회차 쉼 · 로컬 실행이 끝남 · 즉시 정지') for note in notes)
    assert finished == [], '주차하지 않는다(운영시간 안)'
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 200.0)
    assert [cycle for cycle, _ in runtime.starts][1:3] == [2, 3], '다음 경계부터 복귀 길로 다시 돈다'
    assert all(at == 100_060.0 + (k - 1) * 100.0 for k, at in runtime.starts)


def test_a_stopped_pc_with_its_servo_off_shows_why_it_skips():
    """A2 · 정지 → 서보 OFF · 다음 경계에 「N회차 쉼 · 서보 꺼짐」 이유가 남는다"""
    clock, runtime, driver, _, notes = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 100.0)
    _human_stop(runtime, TIMELINE.plan_id)
    off = {'start_blocker': '0번 모터 서보가 꺼져 있습니다'}
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 100.0, view=off)
    assert '시간표 재생 · 2회차 쉼 · 0번 모터 서보가 꺼져 있습니다' in notes
    assert [cycle for cycle, _ in runtime.starts] == [1]


def test_the_normal_cycle_barrier_is_not_mistaken_for_a_finished_run():
    """`stopped` · `completed` 만 끝으로 본다 · 회차 끝 장벽(motion_completed)은 그대로 다음 회차로"""
    clock, runtime, driver, _, notes = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 400.0)
    assert [cycle for cycle, _ in runtime.starts] == [1, 2, 3, 4]
    assert not any('회차 쉼' in note for note in notes)


def test_a_dropped_cycle_reason_stays_on_screen_until_the_next_try():
    """C · 웹 서비스 재시작으로 로컬 상태가 사라짐 · 로그에만 있고 화면 note 는 다음 틱에 빈 값이었다(f4 00:48)"""
    clock, runtime, driver, _, notes = _pc(100_000.0)
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 65.0)
    assert driver.holding == TIMELINE.plan_id
    runtime.session = {}
    runtime.status = {}
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 4.0)
    assert driver.holding == ''
    assert driver.report()['note'] == '1회차 로컬 실행이 끝남 · 상태 없음'
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 3.0)
    assert driver.report()['note'] == '1회차 로컬 실행이 끝남 · 상태 없음', '다음 회차 들어갈 때까지 남는다'
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 100.0)
    assert driver.report()['note'] == '' and [cycle for cycle, _ in runtime.starts] == [1, 2]


def test_a_held_group_stop_says_so_instead_of_timetable_end():
    """E · 그룹 정지 유지 중 note 가 「시간표 끝」 이었다"""
    clock, runtime, driver, _, _ = _pc(100_200.0)
    cut = Timeline(TIMELINE.plan_id, TIMELINE.anchor_unix, 100.0, end_unix=TIMELINE.start_of(2) - 1e-3)
    _ticks(driver, clock, Choice(timeline=cut, stop_after=True), 5.0)
    assert driver.report()['note'] == '그룹 정지 유지 · 운영시간 끝까지'


class _BlinkRuntime(FakeRuntime):
    """실제 플레이어처럼 회차 끝에 장벽 전 잠깐 {completed · completed}(「모션 실행 완료」)"""

    BLINK_SEC = 1.0

    def step(self) -> None:
        s = self.session
        now = self.clock.mono()
        if s and s['state'] == 'running' and now >= s['ends']:
            s['state'] = 'blink'
            s['blink_until'] = now + self.BLINK_SEC
            self.status = {**self.status, 'state': 'completed', 'phase': 'completed', 'message': '모션 실행 완료'}
            return
        if s and s['state'] == 'blink':
            if now >= s['blink_until']:
                s['state'] = 'motion_completed'
                self._show(phase='group_motion_completed')
            return
        super().step()


def test_the_brief_completed_before_the_cycle_barrier_is_not_a_stop():
    """실물 NY 2026-11-11 14:31 · f2 23회차 끝 0.68 s 뒤 「23회차 쉼 · 로컬 실행이 끝남 · 모션 실행 완료」 → 24회차 쉼 · 수정 목록 195"""
    clock = Clock(100_000.0)
    runtime = _BlinkRuntime(clock, clip=80.0, init=5.0)
    notes = []
    driver = ClockDriver(runtime.control, info=notes.append, warn=notes.append, wall=clock.wall, mono=clock.mono,
                         finish=lambda plan, park, why: runtime.control({'command': 'group_cancel'}))
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 500.0)
    assert [cycle for cycle, _ in runtime.starts] == [1, 2, 3, 4, 5]
    assert not any('회차 쉼' in note for note in notes)


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
            runtime.status = {
                'group_execution': True, 'execution_id': payload['execution_id'], 'state': 'error',
                'phase': 'error', 'message': SERVO_OFF_MESSAGE,
            }
        return result

    runtime.control = servo_off_control
    driver._control = servo_off_control
    _run(driver, runtime, clock, _always(Choice(timeline=TIMELINE)), 100.0)
    assert '시간표 재생 · 2회차 쉼 · 서보가 꺼져 있습니다(0~4번 모터)' in notes
    assert not any('회차 오류' in note for note in notes)
    note = driver.report()['note']
    assert note.endswith('회차 쉼 · 서보가 꺼져 있습니다(0~4번 모터)'), note
    assert [cycle for cycle, _ in runtime.starts] == [1]
