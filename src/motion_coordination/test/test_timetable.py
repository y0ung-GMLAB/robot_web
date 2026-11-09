"""시간표 재생 · 그룹 설정 묶음 · 수정 목록 186 (2026-11-09)

입력은 마스터 한 곳 · 나머지는 받아서 저장 · 높은 버전이 이긴다 · 운영 중 변경은 다음 경계부터 ·
사람 정지도 묶음의 한 칸(끊긴 PC 는 다시 붙어 받는 순간 따른다).
"""

from dataclasses import replace
from datetime import datetime

from motion_coordination import clock_grid, timetable
from motion_coordination.timetable import (
    MODE_CLOCK, TimetableConfig, accept, choose, issue, resume_schedule, stop_plan,
)


def _ts(text: str) -> float:
    return datetime.strptime(text, '%Y-%m-%d %H:%M:%S').timestamp()


DAILY = {
    'schedule_id': 's1', 'schedule_name': '운영', 'start_time': '10:00:00', 'stop_time': '18:00:00',
    'repeat_type': 'daily', 'enabled': True,
}


def _clock(**fields) -> TimetableConfig:
    base = TimetableConfig(
        version=3, issued_by='floating1', mode=MODE_CLOCK, auto_period_sec=930.0,
        schedule_enabled=True, schedules=(DAILY,),
    )
    return replace(base, **fields)


# --------------------------------------------------------------------------- #
# 버전 · 충돌 · 저장
# --------------------------------------------------------------------------- #

def test_a_higher_version_wins_and_an_older_one_is_ignored():
    current = _clock()
    assert accept(current, replace(current, version=4, period_sec=1000.0))
    assert not accept(current, replace(current, version=2, period_sec=1000.0))
    assert not accept(current, current), '같은 내용은 다시 저장하지 않는다'


def test_two_masters_with_the_same_version_resolve_to_the_first_name():
    current = _clock(issued_by='floating2')
    other = replace(current, issued_by='floating1', period_sec=1000.0)
    assert accept(current, other), '이름이 앞인 마스터'
    assert not accept(other, replace(other, issued_by='floating3', period_sec=1200.0))


def test_the_bundle_survives_a_reboot(tmp_path):
    path = timetable.default_path(tmp_path)
    config = _clock(stop={'plan_id': 'tt-s1', 'mode': 'now'}, playlist=('a.json',))
    timetable.save(path, config)
    assert timetable.load(path) == config
    assert timetable.load(tmp_path / 'none.json') == TimetableConfig(), '없으면 신호 재생 · 버전 0'
    path.write_text('{broken', encoding='utf-8')
    assert timetable.load(path).version == 0


def test_unknown_or_broken_fields_fall_back_to_defaults():
    config = timetable.from_body({'version': '7', 'mode': 'weird', 'period_sec': 'x', 'schedules': [1, DAILY]})
    assert config.version == 7 and config.mode == timetable.MODE_SIGNAL
    assert config.period_sec == 0.0 and config.schedules == (DAILY,)


# --------------------------------------------------------------------------- #
# 어느 시간표를 따르나
# --------------------------------------------------------------------------- #

def test_inside_the_window_every_schedule_pc_follows_the_same_timeline():
    now = _ts('2026-11-09 13:00:00')
    choice = choose(_clock(), now, operation_mode='schedule')
    assert choice.timeline is not None
    assert choice.timeline.anchor_unix == _ts('2026-11-09 10:01:00')
    assert choice.timeline.end_unix == _ts('2026-11-09 18:00:00')
    assert choice.timeline.period_sec == 930.0


def test_signal_mode_off_mode_and_manual_mode_do_not_follow_the_schedule():
    now = _ts('2026-11-09 13:00:00')
    assert choose(_clock(mode='lockstep'), now, operation_mode='schedule').timeline is None
    assert choose(_clock(), now, operation_mode='off').reason == '오프 모드'
    assert choose(_clock(), now, operation_mode='manual').reason == '수동 모드'
    assert choose(_clock(schedule_enabled=False), now, operation_mode='schedule').reason == '마스터 스케줄 꺼짐'
    tomorrow = choose(_clock(), _ts('2026-11-09 20:00:00'), operation_mode='schedule').timeline
    assert tomorrow.anchor_unix == _ts('2026-11-10 10:01:00'), '운영시간 밖이면 다음 운영시간 시간표(표시 · 미리 준비)'
    weekly = {**DAILY, 'repeat_type': 'weekly', 'repeat_days': []}
    assert choose(_clock(schedules=(weekly,)), _ts('2026-11-09 20:00:00'), operation_mode='schedule').reason == '운영시간 아님'
    assert choose(_clock(auto_period_sec=0.0), now, operation_mode='schedule').reason == '회차 간격 모름'


def test_a_stop_now_reaches_pcs_with_no_timeline():
    """마스터를 수동으로 바꿔 따를 시간표가 없어도 아직 회차를 도는 PC 를 세운다 · 회차 후 정지는 할 일 없음"""
    now = _ts('2026-11-09 13:00:00')
    config = _clock(schedule_enabled=False)
    assert stop_plan(config, issuer='floating1', after_cycle=False, now_unix=now) == (config, ''), '도는 PC 없음'
    assert stop_plan(config, issuer='floating1', after_cycle=True, now_unix=now, held_plan_id='tt-s5') == (config, '')
    stopped, plan_id = stop_plan(config, issuer='floating1', after_cycle=False, now_unix=now, held_plan_id='tt-s5')
    assert plan_id == 'tt-s5' and stopped.stop == {'plan_id': 'tt-s5', 'mode': 'now'}
    for mode in ('schedule', 'manual', 'off'):
        assert choose(stopped, now, operation_mode=mode).stopped_plan_id == 'tt-s5'


def test_stop_now_and_stop_after_cycle():
    now = _ts('2026-11-09 13:00:00')
    config = _clock()
    timeline = choose(config, now, operation_mode='schedule').timeline
    stopped, plan_id = stop_plan(config, issuer='floating1', after_cycle=False, now_unix=now)
    assert plan_id == timeline.plan_id
    choice = choose(stopped, now, operation_mode='schedule')
    assert choice.timeline is None and choice.stopped_plan_id == plan_id
    after, _ = stop_plan(config, issuer='floating1', after_cycle=True, now_unix=now)
    cut = choose(after, now, operation_mode='schedule').timeline
    running = clock_grid.running_cycle(timeline, now)
    assert cut.has_cycle(running) and not cut.has_cycle(running + 1), '도는 회차까지만'


def test_the_schedule_resumes_after_a_human_stop_like_before():
    now = _ts('2026-11-09 13:00:00')
    stopped, _ = stop_plan(_clock(), issuer='floating1', after_cycle=False, now_unix=now)
    resumed = resume_schedule(stopped, issuer='floating1', now_unix=now)
    assert resumed.stop == {} and resumed.version == stopped.version + 1
    assert choose(resumed, now, operation_mode='schedule').timeline is not None
    assert resume_schedule(resumed, issuer='floating1', now_unix=now) is resumed, '바꿀 것이 없으면 그대로'


# --------------------------------------------------------------------------- #
# 운영 중 변경 · 다음 경계부터
# --------------------------------------------------------------------------- #

def test_a_period_change_mid_operation_applies_from_the_next_boundary():
    now = _ts('2026-11-09 13:00:00')
    config = _clock()
    before = choose(config, now, operation_mode='schedule').timeline
    changed = issue(config, issuer='floating1', now_unix=now, period_sec=1200.0)
    after = choose(changed, now, operation_mode='schedule').timeline
    boundary, cycle = clock_grid.rebase_point(before, now)
    assert (changed.rebase_unix, changed.rebase_cycle) == (boundary, cycle)
    assert after.plan_id == before.plan_id, '실행 번호 그대로'
    assert after.start_of(cycle) == boundary and after.start_of(cycle + 1) == boundary + 1200.0
    nxt = clock_grid.next_slot(after, now, prep_sec=30.0)
    assert nxt.cycle == cycle and nxt.start_unix == boundary, '도는 회차는 끝까지 · 경계부터 새 간격'


def test_nothing_changes_without_a_real_change():
    config = _clock()
    assert issue(config, issuer='floating1', period_sec=0.0) is config


def test_schedule_windows_follow_the_schedule_rules():
    now = _ts('2026-11-09 13:00:00')
    windows = timetable.schedule_windows([DAILY, {**DAILY, 'schedule_id': 's2', 'enabled': False}], now)
    assert (_ts('2026-11-09 10:00:00'), _ts('2026-11-09 18:00:00')) in windows
    assert len(windows) == 3, '어제 · 오늘 · 내일'


# --------------------------------------------------------------------------- #
# 수정 목록 188 · 마지막 즉시 정지는 스케줄이 다시 시작해도 남는다 · 끊겨서 정지를 못 받은 PC 가 세울 수 있게
# --------------------------------------------------------------------------- #

def test_the_last_stop_now_survives_the_schedule_resume_and_a_reboot(tmp_path):
    now = _ts('2026-11-09 13:00:00')
    stopped, plan_id = stop_plan(_clock(), issuer='floating1', after_cycle=False, now_unix=now)
    assert stopped.halt == {'plan_id': plan_id, 'at_unix': now}
    resumed = resume_schedule(stopped, issuer='floating1', now_unix=now + 18.0)
    assert resumed.stop == {} and resumed.halt == stopped.halt, '정지는 지워도 기록은 남김'
    choice = choose(resumed, now + 60.0, operation_mode='schedule')
    assert choice.timeline is not None
    assert (choice.halt_plan_id, choice.halt_at_unix) == (plan_id, now)
    assert timetable.from_body(timetable.to_body(resumed)).halt == stopped.halt
    after, _ = stop_plan(_clock(), issuer='floating1', after_cycle=True, now_unix=now)
    assert after.halt == {}, '회차 후 정지는 도는 회차를 세우지 않는다'


# --------------------------------------------------------------------------- #
# 수정 목록 189 · 첫 회차 전에 바꾼 스케줄은 기준에 묶지 않는다 · 실물 NY 2026-11-09 08:39 · 08:41
# --------------------------------------------------------------------------- #

def test_a_schedule_change_before_the_first_cycle_is_not_rebased():
    now = _ts('2026-11-09 09:50:00')
    stale = _clock(rebase_unix=_ts('2026-11-09 10:21:00'), rebase_cycle=1)   # 앞서 바꾸며 남은 기준
    earlier = {**DAILY, 'start_time': '09:55:00'}
    changed = issue(stale, issuer='floating1', now_unix=now, schedules=(earlier,))
    assert (changed.rebase_unix, changed.rebase_cycle) == (0.0, 0)
    timeline = choose(changed, now, operation_mode='schedule').timeline
    assert timeline.first_cycle == 1
    assert timeline.anchor_unix == _ts('2026-11-09 09:55:00') + 60.0, '당긴 시작이 그대로 · 1회차 준비 길'


def test_a_schedule_change_after_the_first_cycle_still_waits_for_the_boundary():
    now = _ts('2026-11-09 10:05:00')
    config = _clock()
    changed = issue(config, issuer='floating1', now_unix=now, schedules=({**DAILY, 'start_time': '09:30:00'},))
    assert changed.rebase_unix > now and changed.rebase_cycle == 2, '1회차가 도는 중 · 다음 경계부터'
