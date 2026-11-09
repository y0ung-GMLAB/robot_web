"""지금 어느 스케줄 구간 안인가 · §6-137

**「시각을 지나갔나」가 아니라 「지금 구간 안인가」를 본다.**

전에는 시작 시각을 지나고 5분 안에만 시작했고, 종료 시각을 지나고 60초
안에만 정지했다 · 그 창을 놓치면 그날은 끝이었다.

    09:00~18:00 스케줄 · 13:00 에 재부팅  →  그날 하루 종일 안 돌았다
    18:00 에 서비스 재시작 중              →  종료 명령을 못 받아 계속 돌았다

지금은 상태를 본다 · 구간 안이면 돌아야 하고, 밖이면 멈춰야 한다 · 그래서
재부팅해도, 놓쳐도, 어긋나도 다음 점검에서 스스로 맞춘다.

정지 방식은 **지정 시각 하나**다 · 유지시간(초)은 없앴다 · 시작한 순간부터
세는 값이라 프로그램이 재시작하면 카운트가 사라져, 상태로 보는 방식과
원리적으로 맞지 않았다.
"""

from datetime import datetime, timedelta
from typing import List, Optional

from motion_common.schedule_models import ScheduleItem

from motion_common.schedule_window import (  # noqa: F401 · 옛 이름 그대로 내보냄 · 규칙은 한 곳(수정 목록 186)
    DAY_ABBREVIATIONS, _at, _day_matches, parse_time_of_day, window_of,
)


def unreadable_schedules(schedules: List[ScheduleItem]) -> List[str]:
    """시각을 못 읽어 **영영 안 도는** 스케줄의 이름 · §6-285

    못 읽는 시각은 구간이 없는 것과 같아서 조용히 건너뛴다 · 사람 눈에는
    「켜 뒀는데 안 돈다」로만 보인다 · 이름을 돌려주어 말이라도 하게 한다.
    """
    broken = []
    for item in schedules:
        if not item.enabled:
            continue
        if (
            parse_time_of_day(item.start_time) is None
            or parse_time_of_day(item.stop_time) is None
        ):
            broken.append(
                f'{item.schedule_name or item.schedule_id} '
                f'({item.start_time}~{item.stop_time})'
            )
    return broken


def active_schedule(
    now: datetime, schedules: List[ScheduleItem],
) -> Optional[ScheduleItem]:
    """지금 돌아야 하는 스케줄 · 없으면 None.

    어제 시작해 자정을 넘긴 구간도 본다 · 여러 개가 겹치면 **먼저 시작한**
    것을 고른다 · 순서가 늘 같아야 점검이 흔들리지 않는다.
    """
    found = []
    for item in schedules:
        if not item.enabled:
            continue
        for day in (now - timedelta(days=1), now):
            if not _day_matches(item, day):
                continue
            window = window_of(item, day)
            if window is None:
                continue
            starts_at, ends_at = window
            if starts_at <= now < ends_at:
                found.append((starts_at, item))
                break
    if not found:
        return None
    found.sort(key=lambda pair: (pair[0], str(pair[1].schedule_id)))
    return found[0][1]


def operating_until(
    now: datetime, schedules: List[ScheduleItem],
) -> Optional[datetime]:
    """지금 운영시간이 이어서 끝나는 시각 · 운영시간 밖이면 None · 수정 목록 182

    겹치거나 맞닿은 구간은 하나로 본다 · 10:00~14:00 과 14:00~18:00 이면 18:00 ·
    진행 PC 가 이 값을 그룹 명령에 실어 보내고, 진행 PC 가 안 보이는 참가 PC 는 이 시각까지만 스스로 잇는다.
    """
    windows = []
    for item in schedules:
        if not item.enabled:
            continue
        for day in (now - timedelta(days=1), now, now + timedelta(days=1)):
            if not _day_matches(item, day):
                continue
            window = window_of(item, day)
            if window is not None:
                windows.append(window)
    current = [ends_at for starts_at, ends_at in windows if starts_at <= now < ends_at]
    if not current:
        return None
    end = max(current)
    grown = True
    while grown:
        grown = False
        for starts_at, ends_at in windows:
            if starts_at <= end < ends_at:
                end = ends_at
                grown = True
    return end


class ScheduleEngine:
    """상태를 보는 엔진 · 기억하는 것이 없다.

    전에는 「오늘 이 스케줄을 발화했나」를 메모리에 들고 있었다 · 프로그램이
    재시작하면 사라져서, 같은 구간에 두 번 시작하거나 영영 안 시작했다.
    지금은 아무것도 기억하지 않는다 · 매번 시각만 보고 답한다.
    """

    def active(
        self, now: datetime, schedules: List[ScheduleItem],
    ) -> Optional[ScheduleItem]:
        return active_schedule(now, schedules)
