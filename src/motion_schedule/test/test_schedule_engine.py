

# --------------------------------------------------------------------------- #
# 「24:00」은 자정이다 · §6-285
#
# 사람은 「21시부터 24시까지」라고 쓴다 · 그런데 24 는 시각 범위(0~23) 밖이라
# 못 읽는 값이 됐고, 그러면 구간이 아예 없는 것이 되어 그 스케줄은 **아무 말
# 없이 영영 안 돌았다** · 실측으로 21:00~24:00 스케줄이 21:21 에도 「구간 밖」
# 이었다.
# --------------------------------------------------------------------------- #

def test_twenty_four_hundred_is_midnight():
    from motion_schedule.schedule_engine import parse_time_of_day

    assert parse_time_of_day('24:00') == (0, 0, 0)
    assert parse_time_of_day('24:00:00') == (0, 0, 0)


def test_a_time_past_midnight_is_still_refused():
    """24 시만 자정으로 본다 · 25시나 24:30 은 여전히 못 읽는 값이다."""
    from motion_schedule.schedule_engine import parse_time_of_day

    assert parse_time_of_day('25:00') is None
    assert parse_time_of_day('24:30') is None
    assert parse_time_of_day('24:00:30') is None


def test_a_window_that_ends_at_24_runs_until_midnight():
    from datetime import datetime

    from motion_common.schedule_models import ScheduleItem
    from motion_schedule.schedule_engine import active_schedule

    item = ScheduleItem(
        schedule_id='s1', schedule_name='밤 근무',
        start_time='21:00:00', stop_time='24:00:00',
        repeat_type='daily',
        repeat_days=['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'],
    )

    assert active_schedule(datetime(2026, 9, 21, 21, 21), [item]) is item
    assert active_schedule(datetime(2026, 9, 21, 23, 59), [item]) is item
    assert active_schedule(datetime(2026, 9, 22, 0, 1), [item]) is None


def test_a_schedule_we_cannot_read_is_named():
    """못 읽는 시각은 조용히 넘어가지 않는다 · 이름을 돌려준다."""
    from motion_common.schedule_models import ScheduleItem
    from motion_schedule.schedule_engine import unreadable_schedules

    good = ScheduleItem(
        schedule_id='a', schedule_name='정상',
        start_time='09:00:00', stop_time='18:00:00', repeat_type='daily',
    )
    bad = ScheduleItem(
        schedule_id='b', schedule_name='이상한 시각',
        start_time='09:00:00', stop_time='25:00:00', repeat_type='daily',
    )
    off = ScheduleItem(
        schedule_id='c', schedule_name='꺼둔 것',
        start_time='09:00:00', stop_time='25:00:00', repeat_type='daily',
        enabled=False,
    )

    assert unreadable_schedules([good, bad, off]) == ['이상한 시각 (09:00:00~25:00:00)']


# --------------------------------------------------------------------------- #
# 수정 목록 182 · 이어지는 운영시간이 끝나는 시각 · 진행 PC 가 그룹 명령에 싣는다
# --------------------------------------------------------------------------- #

def _daily(schedule_id, start, stop, **kwargs):
    from motion_common.schedule_models import ScheduleItem

    return ScheduleItem(
        schedule_id=schedule_id, schedule_name=schedule_id,
        start_time=start, stop_time=stop, repeat_type='daily', **kwargs,
    )


def test_operating_until_is_the_end_of_the_current_window():
    from datetime import datetime

    from motion_schedule.schedule_engine import operating_until

    schedules = [_daily('day', '10:00:00', '18:00:00')]
    assert operating_until(datetime(2026, 11, 8, 12, 0), schedules) == datetime(2026, 11, 8, 18, 0)
    assert operating_until(datetime(2026, 11, 8, 9, 59), schedules) is None
    assert operating_until(datetime(2026, 11, 8, 18, 0), schedules) is None


def test_back_to_back_and_overlapping_windows_count_as_one():
    from datetime import datetime

    from motion_schedule.schedule_engine import operating_until

    schedules = [
        _daily('am', '10:00:00', '14:00:00'),
        _daily('pm', '14:00:00', '18:00:00'),
        _daily('late', '17:00:00', '20:00:00'),
    ]
    assert operating_until(datetime(2026, 11, 8, 11, 0), schedules) == datetime(2026, 11, 8, 20, 0)


def test_operating_until_crosses_midnight_and_ignores_disabled_items():
    from datetime import datetime

    from motion_schedule.schedule_engine import operating_until

    schedules = [_daily('night', '21:00:00', '01:00:00'), _daily('off', '00:00:00', '23:00:00', enabled=False)]
    assert operating_until(datetime(2026, 11, 8, 23, 30), schedules) == datetime(2026, 11, 9, 1, 0)
    assert operating_until(datetime(2026, 11, 9, 0, 30), schedules) == datetime(2026, 11, 9, 1, 0)
    assert operating_until(datetime(2026, 11, 8, 12, 0), schedules) is None
