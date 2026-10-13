"""스케줄 노드가 고르는 길 · rclpy 없이 시험한다 · 수정 목록 115 · 124

노드는 여기 답을 그대로 쓴다 · 판단을 노드 안에 두면 rclpy 없는 PC 에서 시험할 수 없다.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from motion_common.run_state import group_is_active

GROUP_ROUTE = 'group'
LOCAL_ROUTE = 'local'

#: 시작을 보냈는데 다음 점검까지 재생으로 이어지지 않았을 때 · 이유를 모를 때 쓰는 말
START_WENT_NOWHERE = '시작을 보냈지만 재생이 시작되지 않았습니다'


def stop_route(group_execution: Optional[Mapping[str, Any]], *, joined: bool) -> str:
    """구간 밖 「회차 후 정지」 를 어느 길로 보내나 · 수정 목록 115

    **지금 도는 것이 그룹 실행일 때만** 그룹 길 · 전에는 연동이 켜져 있고 묶여 있으면 무조건
    그룹 길로 보냈다 · 사람이 켠 단독 연속 재생은 「활성 그룹 실행이 없습니다」 로 거절당해 4회차
    넘게 안 멈췄다(실물 R-43 · 2026-10-13 14:17).
    """
    if joined and group_is_active(dict(group_execution or {})):
        return GROUP_ROUTE
    return LOCAL_ROUTE


def start_blocker(schedule_status: Optional[Mapping[str, Any]]) -> Optional[str]:
    """브리지가 말하는 「지금 시작하면 안 되는 이유」 · 못 읽었으면 None(직전 값 유지) · 수정 목록 124

    재부팅 직후에는 앱솔루트 확인 · 모터 상태 · 실행 설정이 아직 준비 중이다 · 그때 시작을
    보내면 거절당하고, 전에는 그 거절이 그룹 오류(2등급)로 잠겨 사람이 풀 때까지 안 돌았다.
    """
    if not isinstance(schedule_status, Mapping) or 'start_blocker' not in schedule_status:
        return None
    return str(schedule_status.get('start_blocker') or '').strip()


def start_failure_message(
    coordination_runtime: Optional[Mapping[str, Any]],
    local_status: Optional[Mapping[str, Any]],
) -> str:
    """지난 시작이 재생으로 이어지지 않은 이유 · 연동 노드가 남긴 마지막 시작 실패 → 로컬 오류 글 순"""
    runtime = coordination_runtime if isinstance(coordination_runtime, Mapping) else {}
    failure = runtime.get('last_start_failure')
    if isinstance(failure, Mapping) and str(failure.get('message') or '').strip():
        return str(failure['message']).strip()
    local = local_status if isinstance(local_status, Mapping) else {}
    if str(local.get('state') or '') == 'error' and str(local.get('message') or '').strip():
        return str(local['message']).strip()
    return START_WENT_NOWHERE
