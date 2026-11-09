"""스케줄 구간 규칙 · 시각 읽기 · 요일 · 그 날의 구간 · 수정 목록 186 (2026-11-09)

`motion_schedule.schedule_engine` 에 있던 것을 그대로 옮겼다 · 스케줄 노드와 연동 노드(시간표 재생)가
같은 규칙으로 운영시간을 계산해야 한다 · 패키지끼리 직접 import 하지 않는다(§7 규칙 4) · 그래서 공용 커널에.
"""

from datetime import datetime, timedelta
from typing import Optional

from motion_common.schedule_models import ScheduleItem

DAY_ABBREVIATIONS = ('MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN')


def parse_time_of_day(value) -> Optional[tuple]:
    """"HH:MM" · "HH:MM:SS" 를 (시, 분, 초) 로 · 못 읽으면 None.

    **24:00 은 자정이다** · §6-285

    사람은 「21시부터 24시까지」라고 쓴다 · 그런데 24 는 시각 범위(0~23)를
    벗어나서 못 읽는 값이 됐고, 그러면 `window_of` 가 구간을 못 만들어 그
    스케줄은 **아무 말 없이 영영 안 돌았다** · 실측으로 21:00~24:00 스케줄이
    21:21 에도 「구간 밖」이었다.

    24:00 은 00:00 으로 읽는다 · 끝 시각이면 `window_of` 가 "끝이 시작보다
    이르다" 로 보아 다음 날로 넘기므로 그날 자정이 된다.
    """
    parts = str(value or '').strip().split(':')
    if len(parts) < 2:
        return None
    try:
        numbers = [int(part) for part in parts[:3]]
    except ValueError:
        return None
    while len(numbers) < 3:
        numbers.append(0)
    hour, minute, second = numbers
    if hour == 24 and minute == 0 and second == 0:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        return None
    return hour, minute, second


def _at(day: datetime, time_of_day: tuple) -> datetime:
    hour, minute, second = time_of_day
    return day.replace(hour=hour, minute=minute, second=second, microsecond=0)


def day_matches(item: ScheduleItem, day: datetime) -> bool:
    """그 날짜에 이 스케줄이 시작하는가 · 시작 날짜 기준으로 본다."""
    repeat_type = str(item.repeat_type or 'daily')
    if repeat_type == 'daily':
        return True
    if repeat_type == 'once':
        if not item.run_date:
            return True
        return day.strftime('%Y-%m-%d') == str(item.run_date)
    if repeat_type == 'weekly':
        return DAY_ABBREVIATIONS[day.weekday()] in (item.repeat_days or ())
    return False


def window_of(item: ScheduleItem, start_day: datetime) -> Optional[tuple]:
    """그 날 시작하는 이 스케줄의 구간 · [시작, 종료) · 없으면 None.

    종료가 시작보다 이르면 **자정을 넘긴 것**으로 본다 · 23:00~01:00 은
    그날 23시부터 다음 날 1시까지다.
    """
    start_time = parse_time_of_day(item.start_time)
    stop_time = parse_time_of_day(item.stop_time)
    if start_time is None or stop_time is None:
        return None
    starts_at = _at(start_day, start_time)
    ends_at = _at(start_day, stop_time)
    if ends_at <= starts_at:
        ends_at += timedelta(days=1)
    return starts_at, ends_at


# 옛 이름 · 스케줄 엔진 안쪽에서 쓰던 이름 그대로
_day_matches = day_matches
