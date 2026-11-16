"""그룹 로컬 명령 → 재생 관리자(motion_run_manager) 요청 본문 · 한 곳 · 수정 목록 209 · 207

연동 노드가 받은 그룹 명령은 이 PC 에서 「로컬 명령」(`{'command': 'group_start_at', ...}`)이 되고, 그것이
재생 관리자 요청(`/motion_run/request`)이 된다 · 전에는 이 바꾸기를 웹(브리지 `local_motion_control`)만 했다 ·
연동 노드 → HTTP → 웹 → ROS → 재생 관리자 · 웹이 바쁘면 그룹 예약 확인이 늦어 PC 가 빠졌다(130 · 153 · 171 · 179).

이제 연동 노드도 재생 관리자에 로컬 DDS 로 바로 보낸다(`motion_coordination.local_link`) · 두 길이 **같은
본문** 을 쓰게 여기에 둔다 · 웹 길은 되돌리기 · 연동 노드의 로컬 연결이 없을 때 그대로 쓴다.

웹만 아는 일은 여기 없다 · 준비 검사(실행 컨텍스트 맞추기 · 서보 켜기 · 파일 고르기) · 운영 종료 주차 ·
운영 로그 기록은 웹 길 그대로.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional

from . import motion_segment, repeat_policy

#: 재생 관리자 요청 출처 · 웹 길과 같은 값 · 재생 관리자 로그 · 상태에 남는다
REQUEST_SOURCE = 'network_control'

#: 「이미 놓은 세션」 · 풀기를 두 번 받은 것 · 실패가 아니다
SESSION_MISMATCH_TEXT = '그룹 실행 세션이 일치하지 않습니다'
#: 「회차가 이미 끝남」 · 회차 후 정지가 늦게 온 것 · 실패가 아니다
NO_ACTIVE_GROUP_TEXT = '활성 그룹 실행이 없습니다'


def initial_move_time(payload: Mapping[str, Any]) -> Optional[float]:
    """마스터 재생 화면에서 고른 이동 시간 · 0 · 틀린 값이면 None(PC 마다 조인트 매핑 값) · 2026-10-12"""
    try:
        value = float(payload.get('initial_move_time_sec') or 0.0)
    except (TypeError, ValueError):
        return None
    return value if value > 0.0 else None


def segment(payload: Mapping[str, Any]) -> Dict[str, float]:
    """구간 재생 · 틀린 값(옛 · 깨진 명령)은 통째로 · 검사는 진행 PC 에서 이미 했다 · 2026-10-16"""
    try:
        start, end = motion_segment.parse(payload)
    except ValueError:
        start, end = 0.0, 0.0
    return motion_segment.fields(start, end)


def base_request(selection: Mapping[str, Any], payload: Mapping[str, Any]) -> Dict[str, Any]:
    """모든 그룹 재생 요청의 앞부분 · 재생 파일(있으면) · 출처 · 그룹 명령 번호"""
    return {
        **dict(selection or {}),
        'initial_move_time_sec': None,
        'run_mode': 'once',
        'request_source': REQUEST_SOURCE,
        'network_operation_id': str(payload.get('network_operation_id') or ''),
    }


def prepare_request(
    command: str,
    payload: Mapping[str, Any],
    selection: Mapping[str, Any],
    *,
    automation: Optional[Callable[[], Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """`group_prepare` · `group_join` 본문 · 반복 방식이 비면 재생 관리자의 자동 반복 설정 · 30-3

    `automation` · 반복 방식이 빌 때만 부른다(웹 길에서는 재생 관리자에 상태를 한 번 묻는다).
    `group_join` 인데 복귀 회차가 없으면 `ValueError`.
    """
    request = base_request(selection, payload)
    repeat_mode = str(payload.get('repeat_mode') or '').strip()
    dwell_sec = payload.get('dwell_sec')
    initialization_only = bool(payload.get('initialization_only'))
    run_mode = str(payload.get('run_mode') or 'once').strip().lower()
    if not repeat_mode:
        current = automation() if callable(automation) else {}
        current = current if isinstance(current, Mapping) else {}
        repeat_mode = repeat_policy.normalize_repeat_mode(current.get('repeat_mode'))
        dwell_sec = float(current.get('dwell_sec') or 0.0)
    request.update({
        'execution_id': str(payload.get('execution_id') or ''),
        'initialize_monotonic': payload.get('initialize_monotonic'),
        'group_execution': True,
        'initialization_only': initialization_only,
        'repeat_mode': repeat_mode,
        'dwell_sec': float(dwell_sec or 0.0),
        'sync_mode': repeat_policy.normalize_group_sync_mode(payload.get('sync_mode')),
        'target_cycle_count': int(payload.get('target_cycle_count') or 0),
        'initial_move_time_sec': initial_move_time(payload),
        **segment(payload),
        # Direct repetition must use the same continuity validation as a
        # local continuous run. Reinitializing policies deliberately
        # bypass that check because every cycle returns to the start pose.
        'run_mode': 'once' if initialization_only else run_mode,
    })
    if command == 'group_join':
        # 도는 그룹에 복귀 · 계획만 만들고 서 있다가 합류 확정을 기다린다 · 30-3
        request.pop('initialize_monotonic', None)
        request['join_cycle_number'] = int(payload.get('join_cycle_number') or 0)
        if request['join_cycle_number'] < 1:
            raise ValueError('복귀 회차 번호가 필요합니다')
    return request


def schedule_request(
    command: str, payload: Mapping[str, Any], selection: Mapping[str, Any],
) -> Dict[str, Any]:
    """`group_start_at` · `group_initialize_at` 본문 · 이 PC 시계(monotonic) 의 예약 시각"""
    request = base_request(selection, payload)
    key = 'start_monotonic' if command == 'group_start_at' else 'initialize_monotonic'
    request.update({
        'execution_id': str(payload.get('execution_id') or ''),
        'cycle_number': payload.get('cycle_number'),
        key: payload.get(key),
        'group_execution': True,
    })
    return request


def cycle_request(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """`group_cycle_at` 본문 · 시간표 재생 회차 명령 「k 회차를 S 에 시작 · 다음 회차 N」 · 수정 목록 206

    이미 서 있는 그룹 세션에 보낸다 · 재생 파일(매핑 · 애니) 고르기는 없다 · 초기 이동 시각은 재생 관리자가
    이 PC 초기 이동 계획 시간으로 센다(`motion_common.timed_cycle`) · 시각은 이 PC 시계(monotonic) ·
    다음 회차 시각 0 = 운영시간 마지막 회차(늦은 시작 한도 없음).
    """
    return {
        'execution_id': str(payload.get('execution_id') or ''),
        'cycle_number': payload.get('cycle_number'),
        'start_monotonic': payload.get('start_monotonic'),
        'next_start_monotonic': payload.get('next_start_monotonic'),
        'network_operation_id': str(payload.get('network_operation_id') or ''),
        'group_execution': True,
    }


def join_commit_request(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """도는 그룹에 복귀한 PC · 합류 확정 · 그대로 재생하던 PC 를 다시 합침(`merge` · 183) · 30-3"""
    commit = {
        'execution_id': str(payload.get('execution_id') or ''),
        'cycle_number': payload.get('cycle_number'),
    }
    if payload.get('merge') is True:
        commit['merge'] = True
    return commit


def stop_after_cycle_request(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """회차 후 정지 · 이유(구간 끝 · 141) · 그룹 전체(회차 맞춤은 장벽에서 풀기를 기다림 · 154)"""
    reason = str(payload.get('reason') or '')
    request: Dict[str, Any] = {'reason': reason} if reason else {}
    if payload.get('group_wide') is True:
        request['group_wide'] = True
    return request


def cancel_result(result: Mapping[str, Any]) -> Dict[str, Any]:
    """풀기 답 · 이미 정리된 세션은 성공(`already_released`) · 연동 노드가 실패로 읽어 그룹 오류를 띄우지 않게"""
    result = dict(result or {})
    if result.get('success') is False and SESSION_MISMATCH_TEXT in str(result.get('message') or ''):
        return {
            'success': True,
            'already_released': True,
            'message': '이미 정리된 그룹 실행 세션입니다',
        }
    return result


def stop_after_cycle_result(result: Mapping[str, Any]) -> Dict[str, Any]:
    """회차 후 정지 답 · 회차가 이미 끝났으면 성공(`already_completed`)"""
    result = dict(result or {})
    if result.get('success') is False and NO_ACTIVE_GROUP_TEXT in str(result.get('message') or ''):
        return {
            'success': True,
            'already_completed': True,
            'message': '현재 그룹 회차가 이미 완료되어 다음 회차를 시작하지 않습니다',
        }
    return result
