"""수동 조그 · 목표 이동이 끝났나 · 목표 근처 출렁임(헌팅) · 실물 R-11 · R-14 (2026-10-13)

조그 · 목표 이동은 궤적을 다 보낸 뒤 **실제 위치**가 목표(0.05° 안)에 서야 끝난다 · 그 전에는
같은 축의 다음 조작을 「이전 조그가 아직 돌고 있습니다」 로 거절한다.

R-11 · 2번 축(눈 상하 · 관성비 93)이 +50° 조그 뒤 목표 ±2.4° 에서 1 분 넘게 출렁였다 · 감독 노드는
이미 다 보냈고 드라이브가 혼자 흔들렸다 · 조그는 120 초 시간 제한까지 안 끝나 다음 조그가 다 막혔다 ·
R-14 · 앞 이동이 끝나고 2 초 뒤 「이전 동작이 아직 돌고 있습니다」.

    자리 잡기 시간(settle)   다 보낸 뒤 이만큼은 기다린다 · 조그 3 s · 목표 이동 2 s(예전 그대로)
    도착                     목표 0.05° 안 · 멈춤 · 또는 자리 잡기 뒤에도 목표 0.05° 안에서만 떨림
    출렁임(hunting)           자리 잡기 뒤에도 움직이는데 목표 근처(AC 모터 10°)를 못 벗어남 →
                             끝내고 「게인(강성)을 확인하세요」 알림
    못 미침(short)            자리 잡기 뒤 멈췄는데 목표에서 떨어짐 → 끝내고 알림
    시간 초과(timeout)        전체 제한 시간 · 예전 그대로
    넘겨받기(take over)       다 보냈고 목표 근처면 다음 조작이 앞 조작을 끝내고 시작한다
                             (자리 잡기를 기다리며 거절하지 않는다 · 새 궤적은 지금 위치에서 시작)

순수 계산만 · 값은 모두 모터 rad · rad/s · 시험은 이것을 본다 · 발행·기록은 supervisor.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

#: 조그 · 다 보낸 뒤 자리 잡기를 기다리는 시간 · 초
JOG_SETTLE_SEC = 3.0
#: AC 서보 · 이 안에서 출렁이면 「목표 근처」 · 모터 deg · R-11 은 ±2.4°(p-p 4.8°)
AC_NEAR_DEG = 10.0
#: 알림을 화면에 남겨 두는 시간 · 초
NOTICE_KEEP_SEC = 300.0

WAIT = 'wait'
ARRIVED = 'arrived'
HUNTING = 'hunting'
SHORT = 'short'
TIMEOUT = 'timeout'
#: 끝냈지만 알릴 일이 있는 판정
NOTICE_VERDICTS = (HUNTING, SHORT, TIMEOUT)


#: 이만큼 계속 멈춰 있어야 「섰다」 · 출렁임의 꺾이는 점(속도 0 순간)을 멈춤으로 보지 않게 · 초
STOP_HOLD_SEC = 0.5


def _quiet(velocity: Optional[float], done_velocity: float) -> bool:
    return velocity is None or abs(float(velocity)) <= done_velocity


def observe(
    active: Dict[str, Any],
    position: Optional[float],
    velocity: Optional[float],
    done_velocity: float,
    now: float,
) -> None:
    """다 보낸 뒤 목표와 가장 멀었던 거리 · 마지막으로 움직인 시각을 적는다 ·
    출렁임은 한 번 본 값으로 판정하면 안 된다(목표를 지나가는 순간엔 도착 · 꺾이는 순간엔 멈춤처럼 보인다)"""
    if active.get('commands_sent_at') is None:
        return
    if position is not None:
        error = abs(float(position) - float(active['target_position']))
        active['settle_peak_error'] = max(float(active.get('settle_peak_error') or 0.0), error)
    if not _quiet(velocity, done_velocity):
        active['settle_moving_at'] = float(now)


def verdict(
    *,
    position: Optional[float],
    velocity: Optional[float],
    target: float,
    tolerance: float,
    done_velocity: float,
    commands_sent_at: Optional[float],
    peak_error: Optional[float],
    moving_at: Optional[float],
    near: float,
    settle_sec: float,
    now: float,
    timed_out: bool,
) -> str:
    """지금 끝낼까 · WAIT · ARRIVED · HUNTING · SHORT · TIMEOUT · 시각은 모두 같은 시계(time.time)"""
    error = None if position is None else abs(float(position) - float(target))
    quiet = _quiet(velocity, done_velocity)
    if error is not None and error <= tolerance and quiet:
        return ARRIVED
    if timed_out:
        return TIMEOUT
    if commands_sent_at is None or error is None or now - float(commands_sent_at) < settle_sec:
        return WAIT
    if quiet:
        # 방금 섰다(또는 출렁임이 꺾이는 순간) · 조금 더 보고 정한다
        return SHORT if moving_at is None or now - float(moving_at) >= STOP_HOLD_SEC else WAIT
    peak = max(float(peak_error or 0.0), error)
    if peak <= tolerance:
        return ARRIVED   # 목표 안에서만 떨린다 · 다 왔다
    if peak <= near:
        return HUNTING
    return WAIT   # 목표에서 먼 곳을 움직이는 중 · 전체 제한 시간까지 지켜본다


def can_take_over(active: Dict[str, Any], position: Optional[float], near: float, tolerance: float) -> bool:
    """다음 조작이 이 조작을 끝내고 시작해도 되나 · 다 보냈고 목표 근처일 때만"""
    if active.get('commands_sent_at') is None or position is None:
        return False
    return abs(float(position) - float(active['target_position'])) <= max(float(near), float(tolerance))


def near_for(is_ac_servo: bool) -> float:
    """목표 근처 · rad · 다이나믹셀은 0(출렁임 판정 · 넘겨받기를 도착 오차로만)"""
    return math.radians(AC_NEAR_DEG) if is_ac_servo else 0.0


def notice_text(axis: int, kind: str, *, position: Optional[float], target: float, peak_error: Optional[float] = None) -> str:
    """사람에게 보일 한 줄 · 모터 deg"""
    target_deg = math.degrees(float(target))
    if position is None:
        where = '위치 못 읽음'
        error_deg = None
    else:
        where = f'지금 {math.degrees(float(position)):.2f}°'
        error_deg = math.degrees(abs(float(position) - float(target)))
    if kind == HUNTING:
        swing = math.degrees(max(float(peak_error or 0.0), math.radians(error_deg or 0.0)))
        return (
            f'{axis}번 모터가 목표 근처에서 출렁입니다(목표 {target_deg:.2f}° · {where} · '
            f'최대 ±{swing:.2f}° 모터) · 게인(강성)을 확인하세요'
        )
    if kind == SHORT:
        gap = f'차이 {error_deg:.2f}° 모터' if error_deg is not None else where
        return f'{axis}번 모터가 목표에 못 미치고 섰습니다({gap}) · 기구 걸림 · 토크 한계를 확인하세요'
    if kind == TIMEOUT:
        return f'{axis}번 모터가 제한 시간 안에 목표에 서지 않아 조작을 끝냈습니다(목표 {target_deg:.2f}° · {where})'
    return ''


def recent_notices(notices: Dict[int, Dict[str, Any]], now: float) -> list:
    """화면에 실을 알림 · 축 순서 · 오래된 것은 뺀다"""
    return [
        dict(notices[axis])
        for axis in sorted(notices)
        if now - float(notices[axis].get('stamp') or 0.0) <= NOTICE_KEEP_SEC
    ]
