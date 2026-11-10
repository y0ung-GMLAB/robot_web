"""스케줄 노드가 고르는 길 · rclpy 없이 시험한다 · 수정 목록 115 · 124

노드는 여기 답을 그대로 쓴다 · 판단을 노드 안에 두면 rclpy 없는 PC 에서 시험할 수 없다.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from motion_common.run_state import group_is_active
from motion_common.schedule_store import SCHEDULE_MODE

GROUP_ROUTE = 'group'
LOCAL_ROUTE = 'local'

#: 시작을 보냈는데 다음 점검까지 재생으로 이어지지 않았을 때 · 이유를 모를 때 쓰는 말
START_WENT_NOWHERE = '시작을 보냈지만 재생이 시작되지 않았습니다'


#: 시간표 재생(연동 노드 clock_driver) 실행 이름 앞 글자 · 동기 방식 · `motion_coordination.clock_driver.PLAN_PREFIX` ·
#: `timetable.MODE_CLOCK` 과 같은 글자(스케줄 패키지는 연동 패키지를 가져오지 않는다)
TIMETABLE_PLAN_PREFIX = 'tt-'
TIMETABLE_SYNC_MODE = 'clock'
_LOCAL_FINISHED_STATES = frozenset({'', 'idle', 'ready', 'stopped', 'completed'})


def timetable_owns(
    local_status: Optional[Mapping[str, Any]], group_execution: Optional[Mapping[str, Any]],
) -> bool:
    """지금 「도는」 것이 시간표 재생인가 · 창 시작 · 끝은 연동 노드(clock_driver)가 맡는다 · 수정 목록 191

    시간표는 운영시간 시작 24~29 s 전부터 준비(로컬 `waiting`)에 들어가고, 창이 끝나면 도는 회차를 마친 뒤 PC 마다
    스스로 주차한다 · 스케줄 노드의 「구간 밖인데 돌고 있다 → 회차 후 정지」 가 그 위에 끼어들어 마스터에게만 단독
    정지를 보냈다 · 창 시작 전이면 마스터만 주차 → 서보 OFF → 1회차 빠짐(실물 NY 2026-11-09 21:44 · 22:54 · A) ·
    마지막 창 끝이면 마스터 로컬이 `stopped` 로 실행을 쥔 채 남아 4대 주차 교착(23:27 · B).

    로컬 상태가 시간표 실행(`tt-` · 그룹 실행 · 끝나지 않음)이거나, 연동 상태의 실행 보기가 시간표(`clock`)면 참.
    """
    status = dict(local_status or {})
    if (
        status.get('group_execution')
        and str(status.get('execution_id') or '').startswith(TIMETABLE_PLAN_PREFIX)
        and str(status.get('state') or '').strip() not in _LOCAL_FINISHED_STATES
    ):
        return True
    execution = dict(group_execution or {})
    return group_is_active(execution) and str(execution.get('sync_mode') or '') == TIMETABLE_SYNC_MODE


def stop_route(group_execution: Optional[Mapping[str, Any]], *, joined: bool) -> str:
    """구간 밖 「회차 후 정지」 를 어느 길로 보내나 · 수정 목록 115

    **지금 도는 것이 그룹 실행일 때만** 그룹 길 · 전에는 연동이 켜져 있고 묶여 있으면 무조건
    그룹 길로 보냈다 · 사람이 켠 단독 연속 재생은 「활성 그룹 실행이 없습니다」 로 거절당해 4회차
    넘게 안 멈췄다(실물 R-43 · 2026-10-13 14:17).
    """
    if joined and group_is_active(dict(group_execution or {})):
        return GROUP_ROUTE
    return LOCAL_ROUTE


#: 구간 끝에 멈춰 있던 로봇 · 기준점 주차 → 서보 OFF 를 보낸다 · 사용자 2026-10-13
IDLE_PARK = 'idle_park'
#: 구간 끝을 이미 다른 길(회차 후 정지)로 처리했거나 할 일이 없다
WINDOW_END_DONE = 'done'
#: 아직 구간 안 · 끝을 기다린다
WINDOW_END_WAIT = 'wait'


def window_end_step(
    *, pending: bool, in_window: bool, running: bool, run_mode: str,
) -> str:
    """운영 구간이 끝날 때 멈춰 있던 로봇도 주차하나 · 구간 끝마다 한 번 · 사용자 2026-10-13

    전에는 돌고 있던 재생만 「회차 후 정지 → 기준점 주차 → 서보 OFF」 했다 · 구간이 끝날 때
    이미 멈춰 있으면 서보가 켠 채 밤을 샜다(수정 목록 36 「안 한 것」).

    `pending` = 구간 안을 본 뒤 아직 끝을 처리하지 않았다 · 노드가 구간 안에서 켜고
    여기 답이 `wait` 가 아니면 끈다 · 그래서 구간 끝마다 한 번 · 노드가 구간 밖에서
    켜졌으면(재부팅) 보내지 않는다.

        구간 안                         wait
        구간 밖 · 돌고 있다             done (회차 후 정지 길이 맡는다 · 수동 모드 사람 재생은 그대로)
        구간 밖 · 멈춤 · 스케줄 모드    idle_park
        구간 밖 · 멈춤 · 수동 · 끔      done (사람이 만지는 중일 수 있다)
    """
    if in_window:
        return WINDOW_END_WAIT
    if not pending or running:
        return WINDOW_END_DONE
    return IDLE_PARK if str(run_mode or '') == SCHEDULE_MODE else WINDOW_END_DONE


def start_blocker(schedule_status: Optional[Mapping[str, Any]]) -> Optional[str]:
    """브리지가 말하는 「지금 시작하면 안 되는 이유」 · 못 읽었으면 None(직전 값 유지) · 수정 목록 124

    재부팅 직후에는 앱솔루트 확인 · 모터 상태 · 실행 설정이 아직 준비 중이다 · 그때 시작을
    보내면 거절당하고, 전에는 그 거절이 그룹 오류(2등급)로 잠겨 사람이 풀 때까지 안 돌았다.
    """
    if not isinstance(schedule_status, Mapping) or 'start_blocker' not in schedule_status:
        return None
    return str(schedule_status.get('start_blocker') or '').strip()


def start_blocker_kind(schedule_status: Optional[Mapping[str, Any]]) -> Optional[str]:
    """`start_blocker` 의 갈래 · `motor` · `setup` · 빈 값 · 못 읽었으면 None · 옛 브리지는 칸이 없다 · 끊김 시험 H"""
    if not isinstance(schedule_status, Mapping) or 'start_blocker_kind' not in schedule_status:
        return None
    return str(schedule_status.get('start_blocker_kind') or '').strip()


def master_sits_out(*, kind: str, coordination: bool, master: bool) -> bool:
    """마스터 자기 모터 문제 · 그룹 시작은 보내고 마스터만 빠지나 · 끊김 시험 H (사용자 2026-11-08 「그렇게 해」)

    연동을 쓰는 마스터에서 이유가 이 PC 모터 쪽일 때만 · 공통 이유(실행 설정)와 단독 PC 는 지금처럼 미룬다.
    """
    return bool(coordination and master and str(kind or '') == 'motor')


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
