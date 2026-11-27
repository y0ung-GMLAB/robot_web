

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


# --------------------------------------------------------------------------- #
# 수정 목록 218 · 특정일(특정일 운영 · 휴무일)이 그날 정기 운영보다 우선
#
# 전에는 모든 구간을 합쳐서 11/18 09~18 특정일 + 수요일 10~20 이 09~20 으로 돌았다 · 요청은 09~18.
# 2026-11-18 은 수요일이다.
# --------------------------------------------------------------------------- #

def _item(schedule_id, start, stop, repeat_type, **kwargs):
    from motion_common.schedule_models import ScheduleItem

    return ScheduleItem(
        schedule_id=schedule_id, schedule_name=schedule_id,
        start_time=start, stop_time=stop, repeat_type=repeat_type, **kwargs,
    )


def _wednesday():
    return _item('wed', '10:00:00', '20:00:00', 'weekly', repeat_days=['WED'])


def test_a_dated_schedule_replaces_the_weekly_one_on_that_date():
    from datetime import datetime

    from motion_schedule.schedule_engine import active_schedule, operating_until

    special = _item('special', '09:00:00', '18:00:00', 'once', run_date='2026-11-18')
    schedules = [_wednesday(), special]
    assert active_schedule(datetime(2026, 11, 18, 9, 30), schedules) is special
    assert operating_until(datetime(2026, 11, 18, 9, 30), schedules) == datetime(2026, 11, 18, 18, 0)
    assert active_schedule(datetime(2026, 11, 18, 19, 0), schedules) is None, '수요일 10~20 은 그날 빠짐'
    assert active_schedule(datetime(2026, 11, 25, 19, 0), schedules).schedule_id == 'wed', '다음 주 수요일은 정기 운영'


def test_a_holiday_removes_every_window_that_starts_that_day():
    from datetime import datetime

    from motion_schedule.schedule_engine import active_schedule, operating_until, unreadable_schedules

    holiday = _item('closed', None, None, 'holiday', run_date='2026-11-18')
    daily = _item('daily', '09:00:00', '18:00:00', 'daily')
    schedules = [_wednesday(), daily, holiday]
    assert active_schedule(datetime(2026, 11, 18, 12, 0), schedules) is None
    assert operating_until(datetime(2026, 11, 18, 12, 0), schedules) is None
    assert active_schedule(datetime(2026, 11, 19, 12, 0), schedules) is daily
    assert unreadable_schedules(schedules) == [], '휴무일은 시각이 없어도 오류가 아니다'


def test_a_holiday_wins_over_a_dated_operation_on_the_same_date():
    from datetime import datetime

    from motion_schedule.schedule_engine import active_schedule

    special = _item('special', '09:00:00', '18:00:00', 'once', run_date='2026-11-18')
    holiday = _item('closed', None, None, 'holiday', run_date='2026-11-18')
    assert active_schedule(datetime(2026, 11, 18, 12, 0), [special, holiday]) is None
    holiday.enabled = False
    assert active_schedule(datetime(2026, 11, 18, 12, 0), [special, holiday]) is special, '꺼 둔 휴무일은 없는 것'


def test_a_window_from_the_night_before_still_runs_into_a_holiday():
    """구간은 시작한 날짜의 것 · 화 22:00~02:00 은 수요일이 휴무일이어도 02:00 까지"""
    from datetime import datetime

    from motion_schedule.schedule_engine import active_schedule, operating_until

    night = _item('night', '22:00:00', '02:00:00', 'weekly', repeat_days=['TUE', 'WED'])
    holiday = _item('closed', None, None, 'holiday', run_date='2026-11-18')
    schedules = [night, holiday]
    assert active_schedule(datetime(2026, 11, 18, 1, 0), schedules) is night
    assert operating_until(datetime(2026, 11, 18, 1, 0), schedules) == datetime(2026, 11, 18, 2, 0)
    assert active_schedule(datetime(2026, 11, 18, 23, 0), schedules) is None, '수요일 밤 구간은 빠짐'


def test_several_dated_windows_on_one_date_all_apply():
    from datetime import datetime

    from motion_schedule.schedule_engine import active_schedule

    am = _item('am', '09:00:00', '12:00:00', 'once', run_date='2026-11-18')
    pm = _item('pm', '14:00:00', '18:00:00', 'once', run_date='2026-11-18')
    schedules = [_wednesday(), am, pm]
    assert active_schedule(datetime(2026, 11, 18, 10, 0), schedules) is am
    assert active_schedule(datetime(2026, 11, 18, 13, 0), schedules) is None
    assert active_schedule(datetime(2026, 11, 18, 15, 0), schedules) is pm


def test_an_old_once_without_a_date_keeps_running_every_day():
    """날짜 없는 옛 「한 번」 은 전처럼 날마다 · 1단계로 보지 않는다(정기 운영을 빼지 않음)"""
    from datetime import datetime

    from motion_schedule.schedule_engine import active_schedule

    legacy = _item('legacy', '09:00:00', '11:00:00', 'once')
    schedules = [legacy, _wednesday()]
    assert active_schedule(datetime(2026, 11, 18, 10, 0), schedules) is legacy
    assert active_schedule(datetime(2026, 11, 18, 19, 0), schedules).schedule_id == 'wed'


def test_a_saved_holiday_reads_back_without_times():
    from motion_common.schedule_models import ScheduleItem

    item = ScheduleItem.from_dict({
        'schedule_id': 'h', 'schedule_name': '추수감사절', 'start_time': None, 'stop_time': None,
        'repeat_type': 'holiday', 'run_date': '2026-11-26', 'enabled': True,
    })
    assert (item.repeat_type, item.run_date, item.start_time, item.stop_time) == ('holiday', '2026-11-26', None, None)
