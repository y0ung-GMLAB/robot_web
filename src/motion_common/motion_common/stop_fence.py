"""정지 표지 · 재생 세션 · 시간 창이 아니라 상태로 · 수정 목록 200 · 203

**전에는 시간으로 덮었다.**

- 감독(supervisor)은 정지 뒤 0.5 s 동안 모든 명령을 거절했다(「전체 동작 정지 처리 중」) ·
  그 0.5 s 가 지키던 것은 **정지 전에 돌던 재생이 아직 보내는 프레임**이다 · 재생기는 safety 상태에서
  「막힘」 을 보고서야 스스로 멈췄다 · 재생 틱이 0.5 s 넘게 늦으면(GIL · 실측 419 ms 까지 · 171) 차단이
  풀린 뒤 프레임을 보내 **정지한 축이 다시 움직일 수 있었다** · 반대로 정지 직후의 주차 · 초기 이동은
  거절돼 1 s 간격으로 다시 보내야 했다(191 ⑤).
- 재생 소유권은 프레임마다 0.15 s 임대였다 · 틱이 150 ms 넘게 늦으면 「재생 중」 이 꺼졌다 켜졌다(203).

**이제는 표지와 세션이다.**

    감독      정지마다 표지 (boot, epoch) 를 하나 올린다 · safety 상태에 싣는다
    재생 노드  실행을 잡을 때(`_claim_run_slot`) 그때 표지를 적고 · 상태(`/motion_run/status`)의
              `playback_session` 에 「세션 살아 있음 · 내 표지 · 내가 본 마지막 표지」 를 싣는다
    감독      **지금 표지로 열린 세션의 프레임만** 받는다 · 세션이 닫히면(정지 · 끝 · 오류) 그 축을 바로 놓는다 ·
              재생 노드가 지금 표지를 봤고 옛 표지의 세션이 없으면 「정지 정리 끝」(`stop_settled`)

정지 뒤 늦게 온 옛 프레임은 세션이 없어 버려진다 · 새 실행(주차 · 초기 이동)은 새 표지로 세션을 열어
바로 받는다 · 기다릴 시간이 없다.

표지에 boot 를 넣는 까닭 · 감독이 다시 켜지면 epoch 가 0 부터 다시 센다 · boot 가 다르면 다른 표지다
(감독이 다시 켜진 것도 「그 앞의 재생은 끝」).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, Optional, Tuple

#: (boot, epoch) · 감독 한 번 켜짐 안에서 epoch 만 오른다
Marker = Tuple[str, int]

#: 재생이 프레임을 흘리는 단계 · 서보 알람 1등급 축의 「복구 대기」 를 이 단계에서만 쌓는다 ·
#: 회차 사이(도달 확인 · 대기 · 카운트다운 · 장벽)에서는 풀려 다음 초기 이동에서 다시 합류한다 · 203
STREAMING_STATES = frozenset({'initializing', 'running'})

#: 실행 스레드가 살아 있어도 세션은 끝난 상태 · 이 뒤로 이 실행은 프레임을 보내지 않는다 ·
#: `completed` 는 넣지 않는다 · 그룹은 회차 사이에도 그 상태를 쓴다(스레드가 끝나면 닫힌다)
SESSION_ENDED_STATES = frozenset({'idle', 'ready', 'stopped', 'stopping', 'error', 'blocked'})


def marker(payload: Any, prefix: str = 'stop_') -> Optional[Marker]:
    """상태 JSON 의 표지 · 없으면 None(옛 감독 · 아직 못 받음)"""
    if not isinstance(payload, Mapping):
        return None
    boot = payload.get(f'{prefix}boot')
    epoch = payload.get(f'{prefix}epoch')
    if boot is None or epoch is None:
        return None
    try:
        return str(boot), int(epoch)
    except (TypeError, ValueError):
        return None


def marker_fields(value: Optional[Marker], prefix: str = 'stop_') -> Dict[str, Any]:
    """표지를 JSON 칸 둘로 · 없으면 None 둘"""
    if value is None:
        return {f'{prefix}boot': None, f'{prefix}epoch': None}
    return {f'{prefix}boot': str(value[0]), f'{prefix}epoch': int(value[1])}


def session_payload(
    *, active: bool, streaming: bool,
    run_marker: Optional[Marker], seen_marker: Optional[Marker],
) -> Dict[str, Any]:
    """재생 노드 상태에 싣는 `playback_session` 한 칸"""
    return {
        'active': bool(active),
        'streaming': bool(active and streaming),
        **marker_fields(run_marker),
        **marker_fields(seen_marker, 'seen_stop_'),
    }


def stopped_since(run_marker: Optional[Marker], safety: Any) -> bool:
    """이 실행을 잡은 뒤 감독 정지가 있었나 · 표지가 바뀌었으면 참

    실행 표지나 지금 표지를 모르면(옛 감독) 거짓 · 지금까지대로 둔다.
    """
    current = marker(safety)
    if run_marker is None or current is None:
        return False
    return tuple(current) != tuple(run_marker)


def hard_block_reason(safety: Any) -> str:
    """정지 표지와 함께 온 **진짜 차단** · 있으면 재생은 「정지」 가 아니라 「오류」 로 끝난다

    긴급 정지 · 서보 알람 2등급 이상 · 3등급 잠김 · 앱솔루트 미확인 · 사람 정지만이면 빈 글자.
    """
    if not isinstance(safety, Mapping):
        return ''
    if safety.get('emergency_latched'):
        return '긴급정지 잠김 상태입니다. 상위 프로그램 재시작이 필요합니다'
    try:
        grade = int(safety.get('servo_alarm_grade') or 0)
    except (TypeError, ValueError):
        grade = 0
    if grade >= 2 or safety.get('servo_alarm_grade3_latched') or safety.get('minas_absolute_blocked'):
        return str(safety.get('message') or '모터 명령이 차단된 상태입니다')
    return ''


def settled_for(safety: Any, value: Optional[Marker]) -> bool:
    """이 정지(표지)의 정리가 끝났나 · 감독이 다시 켜졌으면(boot 다름) 그 정지는 이미 지나갔다"""
    current = marker(safety)
    if value is None or current is None:
        return False
    if current[0] != value[0]:
        return True
    return current[1] >= value[1] and bool(safety.get('stop_settled'))
