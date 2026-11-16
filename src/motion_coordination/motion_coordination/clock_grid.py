"""시간표 재생 · 회차 시각 계산 · 수정 목록 186 (2026-11-09)

사용자 결정(설계 `docs/설계_시계기준_재생.md` 7장) · 「시간표 재생」 = 모든 PC 가 같은 시간표를 갖고
자기 시계(chrony 로 맞춤)를 보다가 그 시각에 스스로 재생 · 지금 방식(lockstep)은 「신호 재생」.

- 회차 k 시작 = 기준 시각 + (k − 첫 회차) × 주기 · 벽시계(유닉스 초) · 첫 회차는 보통 1
- 기준 시각 · 그날 운영시간 시작 + 시작 여유 · 스케줄에만(사람이 누른 그룹 재생은 신호 재생) ·
  운영 중 설정 변경 = 다음 회차 경계(새 기준 시각 · Q7) · 회차 번호는 이어서 센다(그 경계 = 첫 회차) ·
  그래서 그룹 실행 번호 · 재생 목록 순서 · 각 PC 의 로컬 회차 번호가 끊기지 않는다
- 주기 · 자동 = 모든 PC 의 (가장 긴 클립 + 초기 이동) + 회차 사이 1.5 s 를 10 s 단위로 올림(206 · 188 은 회차 사이 6 s +
  여유 2 s) · 사람이 마스터에서 더 길게 입력 가능 · 자동보다 짧으면 거부(Q2)
- 재생 목록 · 회차 k → 항목 (k − 1) mod n · 각 PC 제 목록(파일은 PC 마다 · Q3-2)
- 운영시간 끝 · 끝 시각 이후 **시작**하는 회차는 없음 · 진행 중 회차는 끝까지(Q6)
- 회차 중간 합류 없음 · 늦게 켠 PC 는 다음 경계

같은 설정 · 같은 벽시계면 PC 끼리 통신 없이 같은 k 가 나온다 · ROS 를 모른다 · 계산만.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from motion_common import timed_cycle

from .cycle_grid import GRID_STEP_SEC, round_up_period

#: 운영시간 시작 뒤 1회차까지 · 서비스 기동 · 계획 짓기 · 초기 이동 시간 확보
DEFAULT_START_LEAD_SEC = 60.0
#: 초기 이동 예정 끝 → 회차 시작 · 초기 이동 끝 확인(정착)만 · 4 s → 1 s · 수정 목록 206
#:
#: 188 ⑥ 의 4 s 는 「초기 이동 끝」 확인 → 시작 예약 → 재생 관리자 도착 왕복(최대 1.4 s)을 담았다 · 이제 회차 하나가
#: 시각이 박힌 명령 하나라 재생 관리자가 제 시계로 시작한다 · 남은 것은 초기 이동이 계획보다 늦게 끝나는 몫(실측 0.2~0.8 s) ·
#: 넘으면 그 PC 만 늦게 시작(쉼 아님) · 값은 재생 관리자와 하나(`motion_common.timed_cycle`)
CYCLE_START_LEAD_SEC = timed_cycle.INITIAL_MOVE_SETTLE_SEC
#: 클립 끝 → 회차 끝 장벽(최종 위치 확인) → 이 PC 가 보고 다음 회차 명령이 재생 관리자에 닿기까지 · 2 → 0.5 s · 수정 목록 206
#:
#: 188 의 2 s(실측 약 1 s)는 로컬 상태를 0.5 s 마다 읽던 때 값 · 지금은 장벽 전 단계(199)가 바로 나가고 시간표 실행 중
#: 로컬 상태 50 ms · 회차 명령은 매핑을 안 읽는다 · 셈은 `motion_common.timed_cycle.CYCLE_END_SEC` · 넘으면 다음 회차만 늦게 시작
CYCLE_BARRIER_SEC = timed_cycle.CYCLE_END_SEC
#: 자동 주기 올림 전 여유 · 0 · 수정 목록 206
#:
#: 신호 재생 눈금(178 · `cycle_grid.GRID_MARGIN_SEC` 2 s 「회차 초기화 · 시계 맞춤이 조금 늦어도 눈금을 지키게」)을 그대로
#: 썼다 · 시간표 재생에서는 늦어도 끝나는 대로 시작(쉼 아님 · 다음 회차는 다시 시간표대로)이라 「조금 늦음」 을 시간으로 덮을 일이
#: 없다 · 회차 사이 시간은 모두 위 두 값(근거 있는 몫) · PC 사이 시계 차이(chrony · 100 ms 넘으면 표시)는 PC 마다 제 시간표라
#: 한 PC 안의 시간 예산과 상관없다 · 신호 재생 눈금(`aligned_start`)은 늦은 시작을 거절하고 주기를 늘리기만 하는 다른 규칙이라
#: 그 여유는 그대로 둔다
TIMETABLE_PERIOD_MARGIN_SEC = 0.0
#: 운영 중 설정 변경 · 새 기준 시각(다음 경계)까지 최소 · 끊기지 않은 PC 가 받을 시간
REBASE_MIN_LEAD_SEC = 30.0
#: 주기 상한 · 잘못 넣은 값(초 대신 밀리초 등) 막기 · 하루
MAX_PERIOD_SEC = 86400.0


@dataclass(frozen=True)
class Timeline:
    """하나의 시간표 · 회차 k 시작 = anchor + (k − first_cycle) × period · end 이후 시작 없음(0 = 끝 없음)

    `plan_id` = 그룹 실행 번호 · 운영시간 하나 · 운영 중 설정을 바꿔도 같다.
    """

    plan_id: str
    anchor_unix: float
    period_sec: float
    end_unix: float = 0.0
    kind: str = 'schedule'
    first_cycle: int = 1

    def start_of(self, cycle: int) -> float:
        return float(self.anchor_unix) + (int(cycle) - int(self.first_cycle)) * float(self.period_sec)

    def has_cycle(self, cycle: int) -> bool:
        if cycle < max(int(self.first_cycle), 1):
            return False
        return not self.end_unix or self.start_of(cycle) < float(self.end_unix)


@dataclass(frozen=True)
class Slot:
    """회차 하나 · 번호 · 시작(벽시계) · 재생 목록 항목 번호(0 부터)"""

    cycle: int
    start_unix: float
    item_index: int = 0


def auto_period(needs_sec: Iterable[float]) -> float:
    """자동 주기 · PC 마다 잰 (가장 긴 클립 + 초기 이동) 중 최댓값 + 회차 사이 시간 + 여유 → 10 s 올림 · 모르면 0

    회차 사이 시간 = 클립 끝 → 장벽(`CYCLE_BARRIER_SEC`) + 초기 이동 끝 → 시작(`CYCLE_START_LEAD_SEC`) · 수정 목록 188 ·
    전에는 빠져 있어 920 s 클립이면 930 s · 회차 사이가 3 s 뿐이라 시작 여유를 늘릴 수 없었다.
    수정 목록 206 · 회차 사이 6 → 1.5 s · 올림 전 여유 2 → 0 s · 920 s 클립 + 초기 이동 10 s · 올림 전 938 → 931.5 s ·
    올림 뒤 940 s 그대로(10 s 단위 · 사용자 2026-11-08) · 남는 8.5 s 가 초기 이동이 늦게 끝난 회차를 쉬지 않고 늦게라도
    시작할 수 있는 한도(`timed_cycle.latest_start` · 전에는 시작 시각을 넘기면 쉼) · 초기 이동 5 s 면 940 → 930 s.
    """
    values = [float(value) for value in needs_sec if value and float(value) > 0.0]
    if not values:
        return 0.0
    span = max(values) + CYCLE_BARRIER_SEC + CYCLE_START_LEAD_SEC
    return round_up_period(span, step=GRID_STEP_SEC, margin=TIMETABLE_PERIOD_MARGIN_SEC)


def period_error(period_sec: float, auto_sec: float) -> str:
    """사람이 넣은 주기 검사 · 문제 없으면 '' · 0 = 자동"""
    try:
        period = float(period_sec or 0.0)
    except (TypeError, ValueError):
        return '회차 간격이 숫자가 아닙니다'
    if period == 0.0:
        return ''
    if not math.isfinite(period) or period < 0.0:
        return '회차 간격이 올바르지 않습니다'
    if period > MAX_PERIOD_SEC:
        return f'회차 간격은 {MAX_PERIOD_SEC:.0f} s 이하여야 합니다'
    if auto_sec and period + 1e-6 < float(auto_sec):
        return f'회차 간격이 애니메이션보다 짧습니다 · 최소 {float(auto_sec):.0f} s'
    return ''


def effective_period(period_sec: float, auto_sec: float) -> float:
    """쓸 주기 · 사람이 넣은 값(자동 이상) · 없으면 자동 · 둘 다 없으면 0(시간표 없음)"""
    manual = float(period_sec or 0.0)
    auto = float(auto_sec or 0.0)
    if manual > 0.0 and not period_error(manual, auto):
        return manual
    return auto


def playlist_index(cycle: int, length: int) -> int:
    """회차 k → 재생 목록 항목 · 0 부터 · 목록이 없거나 하나면 0"""
    if int(length) <= 1:
        return 0
    return (int(cycle) - 1) % int(length)


def next_slot(
    timeline: Optional[Timeline], now_unix: float, *, prep_sec: float, playlist_length: int = 1,
) -> Optional[Slot]:
    """지금부터 `prep_sec` 뒤 이후에 시작하는 첫 회차 · 시간표가 끝났으면 None

    `prep_sec` = 이 PC 가 그 회차를 잡는 데 필요한 시간(계획 짓기 + 초기 이동 + 여유) · 그보다 가까운
    회차는 건너뛴다(회차 중간 합류 없음).
    """
    if timeline is None or float(timeline.period_sec) <= 0.0:
        return None
    earliest = float(now_unix) + max(float(prep_sec), 0.0)
    steps = math.ceil((earliest - float(timeline.anchor_unix)) / float(timeline.period_sec) - 1e-9)
    cycle = max(int(steps), 0) + int(timeline.first_cycle)
    if not timeline.has_cycle(cycle):
        return None
    return Slot(cycle, timeline.start_of(cycle), playlist_index(cycle, playlist_length))


def running_cycle(timeline: Optional[Timeline], now_unix: float) -> int:
    """지금 시간표상 도는 회차(시작한 마지막 회차) · 아직 첫 회차 전이면 0 · 표시용"""
    if timeline is None or float(timeline.period_sec) <= 0.0:
        return 0
    if float(now_unix) < float(timeline.anchor_unix):
        # 운영 중 설정 변경 · 새 기준(다음 경계) 전 · 그 앞 회차(옛 눈금)가 아직 도는 중 · 전에는 0 이라 화면 · 실행 표시 ·
        # 스케줄 노드가 「도는 것 없음」 으로 봤다(NY 2026-11-09 06:12 스케줄 끝을 바꾼 뒤 06:26:40 까지) · 수정 목록 188
        return int(timeline.first_cycle) - 1 if int(timeline.first_cycle) > 1 else 0
    cycle = int((float(now_unix) - float(timeline.anchor_unix)) // float(timeline.period_sec)) + int(timeline.first_cycle)
    while cycle >= int(timeline.first_cycle) and not timeline.has_cycle(cycle):
        cycle -= 1
    return cycle if cycle >= int(timeline.first_cycle) else 0


def rebase_point(
    timeline: Optional[Timeline], now_unix: float, *, min_lead_sec: float = REBASE_MIN_LEAD_SEC,
) -> Tuple[float, int]:
    """운영 중 설정 변경 · (새 기준 시각, 그 회차 번호) = 지금 시간표의 다음 경계(`min_lead_sec` 이후) · 없으면 (0, 0)

    그 경계 전까지는 도는 회차를 끝까지(어떤 PC 든 지금 회차를 끊지 않는다) · 그 경계부터 새 주기 · 회차 번호는
    이어서 · 첫 회차 전이면 기준 시각 그대로.
    """
    if timeline is None or float(timeline.period_sec) <= 0.0:
        return 0.0, 0
    if float(now_unix) + min_lead_sec <= float(timeline.anchor_unix):
        return float(timeline.anchor_unix), int(timeline.first_cycle)
    slot = next_slot(timeline, now_unix, prep_sec=min_lead_sec)
    if slot is not None:
        return slot.start_unix, slot.cycle
    return 0.0, 0


def window_timeline(
    window: Optional[Tuple[float, float]], period_sec: float, *,
    start_lead_sec: float = DEFAULT_START_LEAD_SEC, rebase: Optional[Tuple[float, int]] = None,
) -> Optional[Timeline]:
    """운영시간 하나 → 시간표 · 기준 시각 = 시작 + 여유 · 운영 중 바꾼 설정이면 그 경계(rebase = (시각, 회차))

    `rebase` 시각이 이 운영시간 안(1회차 시각 이후)이면 그 시각 · 그 회차 번호가 새 기준 · 밖이면(다른 날 ·
    다른 구간) 무시.
    """
    if window is None or float(period_sec) <= 0.0:
        return None
    starts_at, ends_at = float(window[0]), float(window[1])
    anchor = starts_at + max(float(start_lead_sec), 0.0)
    first = 1
    if rebase and rebase[0] and anchor <= float(rebase[0]) < ends_at:
        anchor, first = float(rebase[0]), max(int(rebase[1] or 1), 1)
    if anchor >= ends_at:
        return None
    return Timeline(
        plan_id=schedule_plan_id(starts_at), anchor_unix=anchor, period_sec=float(period_sec),
        end_unix=ends_at, kind='schedule', first_cycle=first,
    )


def pick_window(
    windows: Sequence[Tuple[float, float]], now_unix: float, *, horizon_sec: float = 86400.0,
) -> Optional[Tuple[float, float]]:
    """지금 운영시간 · 없으면 `horizon_sec` 안에 시작하는 가장 이른 운영시간 · 겹치거나 맞닿은 구간은 하나로

    겹친 구간을 합치는 규칙은 `schedule_engine.operating_until` 과 같다(10~14 + 14~18 = 10~18).
    """
    merged: List[List[float]] = []
    for starts_at, ends_at in sorted((float(a), float(b)) for a, b in windows if float(b) > float(a)):
        if merged and starts_at <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], ends_at)
        else:
            merged.append([starts_at, ends_at])
    now = float(now_unix)
    for starts_at, ends_at in merged:
        if starts_at <= now < ends_at:
            return starts_at, ends_at
    upcoming = [pair for pair in merged if now < pair[0] <= now + horizon_sec]
    if upcoming:
        return upcoming[0][0], upcoming[0][1]
    return None


def schedule_plan_id(window_start_unix: float) -> str:
    """스케줄 시간표 이름 · 운영시간 시작으로 · 모든 PC 가 같은 이름(그룹 실행 번호) · 운영 중 설정을 바꿔도 같다"""
    return f'tt-s{int(round(float(window_start_unix)))}'
