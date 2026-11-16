"""시간표 재생 · 회차 하나 = 시작 시각이 박힌 명령 하나 · 재생 관리자가 제 시계로 초기 이동 → 시작 · 수정 목록 206

전에는 시간표 구동부(연동 노드 `clock_driver`)가 회차마다 「초기 이동 예약」 을 보내고, 로컬 상태를 읽다가
초기 이동이 끝난 것을 본 뒤 「시작 예약」 을 따로 보냈다 · 그 확인 → 예약 왕복(최대 1.4 s)과 초기 이동 늦게 끝남
(0.2~0.8 s)이 시작 여유 2 s 를 넘어 4대 중 3대가 「트리거가 이미 지났습니다」 로 회차를 쉬었다 · 188 ⑥ 은 여유를
4 s 로 늘렸다(NY 2026-11-09 04:04).

이제 연동 노드는 회차마다 「k 회차를 S 에 시작 · 다음 회차는 N」 하나만 보낸다(`group_cycle_at`) · 재생 관리자
(`group_session`)가 이 PC 실제 초기 이동 시간으로 초기 이동 시작을 거꾸로 세어 둘 다 제 단조 시계로 한다.

늦음 · 사용자 결정 2026-11-16
- 초기 이동이 회차 시작 뒤에 끝나도 잘못이 아니다 · 끝나는 대로 바로 시작(회차 쉼 아님) · 늦음은 기록 ·
  다른 PC 는 기다리지 않는다 · 다음 회차는 다시 시간표대로
- 너무 늦어 그 회차를 돌면 다음 회차 준비(초기 이동)를 먹는 때만 그 회차를 쉰다(이유 기록)
- 스피커는 늘 시간표 시각에 음원(헤드 늦음과 상관없음)

ROS 를 모른다 · 계산만 · 재생 관리자 · 자동 회차 간격(`clock_grid.auto_period`) · 시험용 가짜 재생 관리자가 같은 값을 쓴다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

from . import joint_mapping, units

__all__ = [
    'INITIAL_MOVE_SETTLE_SEC', 'CYCLE_END_SEC', 'initialize_at', 'latest_start', 'Decision', 'decide',
    'DEFAULT_INITIAL_MODE', 'FIRST_FRAME_SAME_JOINT_DEG', 'planned_initial_move_sec', 'blends_to_first_frame',
]

#: 초기 이동 계획 끝 → 회차 시작 · 재생 관리자가 「시작 − 이 PC 초기 이동 시간 − 이 여유」 에 초기 이동을 시작한다
#:
#: 초기 이동은 계획 시간(조인트 매핑 · 묶음 값) 뒤에 도착 확인(`_wait_for_targets`)을 한다 · 실측 NY 2026-11-09 04:04 ·
#: 예정보다 0.2~0.8 s 늦게 끝남 · 이 여유를 넘겨 끝나면 그 PC 만 늦게 시작(쉼 아님 · 위 사용자 결정) · 실패 감지가
#: 아니라 「보통은 제때」 를 위한 여유다
#:
#: 전에는 4 s(188 ⑥ `CYCLE_START_LEAD_SEC`) · 「끝 확인 → 시작 예약 → 재생 관리자 도착」 왕복(최대 1.4 s)까지 담았다 ·
#: 이제 시작도 재생 관리자가 제 시계로 잡아 그 왕복이 없다. 시작 순간의 계획 적용(AC 운전 허가 + 설정값 비움
#: `_setpoint_clear_sec` 22 ms · 계획은 208 로 미리 지어 둠)은 회차 시작 **뒤** 이고 모든 PC 가 같아 여유에 넣지 않는다.
#:
#: NY 실측 2026-11-16(test/root-fix · 시간표 재생 9회차 × 4대) · 초기 이동 끝 → 시작 0.11~0.91 s 남음 · 늦게 시작 0 ·
#: 0.11 s 는 floating1 축 0 이 운전 한계 밖에서 출발한 회차(수정 목록 215) · 여유를 거의 다 쓴 회차가 있어 그대로 둔다
INITIAL_MOVE_SETTLE_SEC = 1.0

#: 클립 끝 → 다음 회차 명령이 재생 관리자에 닿기까지 · 자동 회차 간격에 들고 · 늦은 회차를 쉴지 가르는 기준에도 든다
#:
#: 다음 회차 명령은 회차 끝(장벽)을 본 뒤에 보낸다 · 회차 후 정지 · 운영시간 끝 · 정지는 그때의 시간표로 정하므로 미리 보내지
#: 않는다 · 그래서 남는 것(셈 · 2 → 0.5 s · 수정 목록 206)
#: - 최종 위치 확인 · 클립 끝 프레임 뒤 `_wait_for_targets`(0.05 s 마다 · 클립은 대개 멈춘 자세로 끝나 바로 · 한도 3 s 는 실패 감지)
#: - 회차 끝 알림 · 장벽 전 단계(`group_motion_finishing` · 199) → 다음 재생 목록 항목(208 변환본 · ms) → 장벽 상태는 바뀔 때 바로 냄
#: - 연동 노드가 봄 · 재생 관리자가 바뀔 때 바로 낸 상태를 로컬 DDS 로 직접(209 · 전 188 ⑥ 웹 50 ms) + 시간표 구동 0.1 s 틱
#: - 보냄 · 로컬 DDS 로 재생 관리자에 바로(209 · 연결이 없으면 로컬 웹 길) · 응답(수십 ms · 회차 명령은 매핑 읽기 안 함)
#:   로컬 연결이 없는 되돌리기 길에서는 웹 쪽 칸을 0.5 s 마다 읽어(209) 장벽을 최대 0.5 s 늦게 볼 수 있다 · 그때도 다음
#:   회차만 늦게 시작(쉼 아님)
#: 합 약 0.3 s · 188 의 실측 약 1 s 는 로컬 상태를 0.5 s 마다 읽던 때 값 · 넘으면 다음 회차만 늦게 시작(쉼 아님) ·
#: 실물 값은 재생 관리자 기록 「회차 끝 뒤 N ms」 로 본다(`group_session.schedule_timed_cycle`)
#: NY 실측 2026-11-16(test/root-fix) · 최대 94 ms · 줄여도 자동 간격이 10 s 단위로 올라가(`clock_grid`) 달라지는 것이
#: 없어 그대로 둔다
CYCLE_END_SEC = 0.5


def initialize_at(start: float, initial_move_sec: float) -> float:
    """초기 이동 시작 시각 · 회차 시작 − 이 PC 초기 이동 시간 − 여유 · 시계는 부르는 쪽 것 그대로(단조)"""
    return float(start) - max(float(initial_move_sec), 0.0) - INITIAL_MOVE_SETTLE_SEC


def latest_start(start: float, next_start: float, clip_sec: float, next_initial_move_sec: float) -> float:
    """늦게라도 이 회차를 시작해도 되는 마지막 시각 · 다음 회차가 없으면(운영시간 마지막 회차) 끝 없음

    이 회차를 그때 시작하면 클립 끝 + 회차 끝 보고(`CYCLE_END_SEC`)가 다음 회차 초기 이동 시작(`initialize_at`)에 닿는다 ·
    그보다 늦으면 이 회차를 돌수록 다음 회차까지 늦어진다 · 클립이 회차 간격보다 길어 제때 시작해도 넘치면 시작 시각이
    한도(제때는 늘 돈다 · 넘친 것은 다음 회차가 제 규칙으로 정한다).
    """
    start = float(start)
    if not next_start or float(next_start) <= start:
        return math.inf
    latest = (
        initialize_at(float(next_start), next_initial_move_sec)
        - CYCLE_END_SEC - max(float(clip_sec), 0.0)
    )
    return max(latest, start)


@dataclass(frozen=True)
class Decision:
    """회차 하나를 언제 시작하나 · `skip` 이 있으면 그 회차는 쉼(이유) · 아니면 `start_at` 에 · `late_sec` = 시작 − 시간표 시각"""

    start_at: float
    late_sec: float = 0.0
    skip: str = ''


def decide(*, cycle: int, start: float, ready_at: float, latest: float, moved: bool = True) -> Decision:
    """`ready_at` = 이 PC 가 시작할 수 있는 가장 이른 시각 · 초기 이동을 끝낸 시각(`moved`) · 아직 안 했으면 끝낼 시각

    - 시간표 시각 전 · 그 시각에 · 늦음 0
    - 시간표 시각 뒤 · `latest` 까지면 그때 바로(늦음 기록 · 쉼 아님)
    - `latest` 뒤 · 그 회차는 쉼(다음 회차 준비를 먹는다) · 이유에 늦은 만큼
    """
    start, ready_at = float(start), float(ready_at)
    if ready_at <= start:
        return Decision(start_at=start)
    late = ready_at - start
    if ready_at > float(latest):
        what = '초기 이동이' if moved else '지금 초기 이동을 시작해도'
        return Decision(
            start_at=ready_at, late_sec=late,
            skip=f'{what} {late:.1f} s 늦게 끝남 · 돌면 {int(cycle) + 1}회차 준비 시각을 넘김',
        )
    return Decision(start_at=ready_at, late_sec=late)


# --------------------------------------------------------------------------- #
# 회차 초기 이동 계획 시간 · 재생 관리자 · 자동 회차 간격(웹 `timetable_source`)이 같은 규칙 · 206 뒤처리
# --------------------------------------------------------------------------- #

#: 조인트 매핑 줄에 초기 방식이 없을 때 · 재생 관리자 `motion_run_constants.DEFAULT_INITIAL_MODE` 와 같다(시험이 붙잡는다)
DEFAULT_INITIAL_MODE = 'reference'

#: 첫 프레임 잇기(13-1)를 「없음」 으로 보는 관절 차이(deg)
#:
#: 재생 관리자는 초기 위치 · 첫 프레임의 **모터** 목표 차이가 도달 허용 오차를 넘으면 잇는다 · AC 서보 허용 오차 =
#: max(모터 바닥 0.1°, 관절 `ac_target_tolerance_joint_deg` 0.05° × |이득|) · 관절로 바꾸면 늘 0.05° 이상이다 · 그래서
#: 여기서 0.05° 를 넘을 때 「잇는다」 로 보면 재생 관리자가 잇는 회차는 빠짐없이 잇는 것으로 센다(자동 회차 간격이
#: 모자라지 않는 쪽 · 같거나 길게) · 값은 `motion_run_constants.AC_TARGET_TOLERANCE_JOINT_DEG` 기본값
FIRST_FRAME_SAME_JOINT_DEG = 0.05


def planned_initial_move_sec(longest_axis_sec: float, blends_to_first_frame: bool) -> float:
    """회차 하나의 초기 이동 계획 시간 · 축마다 이동 시간 중 가장 긴 것 · 첫 프레임이 초기 위치와 다르면 같은 시간으로
    한 번 더 잇는다(13-1 · 두 번) · 재생 관리자(`group_session._initial_move_seconds`)와 자동 회차 간격이 같이 쓴다"""
    longest = max(float(longest_axis_sec or 0.0), 0.0)
    return 2.0 * longest if blends_to_first_frame else longest


def _initial_joint_value(row: Mapping[str, Any], mode: str) -> float:
    """초기 위치(관절 rad) · 재생 관리자 `motion_run_rules._initial_motion_value` 와 같은 규칙(첫 프레임 방식 빼고)"""
    if mode == 'manual':
        return float(joint_mapping.angle(row, 'initial_motion_position', units.RAD))
    return 0.0   # 기준점 · 애니메이션과 상관없이 모션 0°(기준점 캡처한 자세)


def _clamp(value: float, lower: Optional[float], upper: Optional[float]) -> float:
    if lower is not None:
        value = max(value, float(lower))
    if upper is not None:
        value = min(value, float(upper))
    return value


def blends_to_first_frame(rows: Iterable[Any], first_values: Optional[Mapping[str, float]]) -> bool:
    """이 클립 앞 초기 이동이 첫 프레임까지 한 번 더 잇나(13-1) · 조인트 매핑 줄 + 클립 첫 프레임 값(관절 rad)

    재생 관리자(`plan_builder` · `motion_player._first_frame_targets`)와 같은 규칙 · 켠 줄만(`enabled` 거짓은 뺌) ·
    - 첫 프레임 방식 · 초기 위치 = 첫 프레임 · 잇지 않음(NY 플로팅)
    - 기준점(기본) · 직접 지정 · 그 값과 첫 프레임(둘 다 매핑 범위로 자름) 차이가 `FIRST_FRAME_SAME_JOINT_DEG` 를 넘으면 잇는다
    - 클립에 그 조인트 자료가 없으면 그 축은 빠진다(재생 관리자와 같음)
    `first_values` None = 첫 프레임을 못 읽음 · 기준점 · 직접 지정 줄이 하나라도 있으면 잇는 것으로(길게 잡는 쪽이 안전).
    """
    same = math.radians(FIRST_FRAME_SAME_JOINT_DEG)
    for row in rows or ():
        if not isinstance(row, Mapping) or row.get('enabled') is False:
            continue
        motion_id = str(row.get('motion_id') or '').strip()
        if not motion_id:
            continue
        mode = str(row.get('initial_mode') or DEFAULT_INITIAL_MODE)
        if mode not in {'reference', 'manual'}:
            # 첫 프레임 방식(그 밖의 글도 재생 관리자는 첫 프레임으로 읽는다) · 초기 위치 = 첫 프레임
            continue
        if first_values is None:
            return True
        if motion_id not in first_values:
            continue
        lower = joint_mapping.angle(row, 'motion_lower', units.RAD, default=None)
        upper = joint_mapping.angle(row, 'motion_upper', units.RAD, default=None)
        initial = _clamp(_initial_joint_value(row, mode), lower, upper)
        first = _clamp(float(first_values[motion_id]), lower, upper)
        if abs(first - initial) > same:
            return True
    return False
