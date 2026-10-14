"""그룹 실행에 넣을 PC 를 고르는 규칙 · 시작 · 시작 전 미리 보기 · 복귀가 같은 규칙 · 수정 목록 122

운전 모드의 뜻은 **누가 시작하나** 다 (사용자 결정 2026-10-13 · 실물 S-10 뒤)

    수동      사람이 시작한다 · 단독 · 그룹 둘 다
    스케줄    시간에 맞춰 저절로 시작한다
    끔        움직이지 않는다

그래서 그룹 재생에서 빼는 PC 는 시작한 쪽에 따라 다르다

    사람이 누른 그룹 재생    끔 PC 만 뺀다 · 수동 PC 도 넣는다(사람 조작 중이면 뺀다)
    스케줄이 켠 그룹 재생    스케줄 PC 만 · 수동 PC 는 사람이 만지는 중일 수 있어 뺀다

전에는 시작한 쪽과 상관없이 수동 PC 를 뺐다 · 4대 모두 수동인데 사람이 그룹 1회를
누르면 마스터 혼자 돌고 「그룹 실행 완료」 가 떴다(실물 S-10).

rclpy 없이 시험한다 · 노드는 여기 답을 그대로 쓴다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from motion_common import run_state

#: 그룹 재생을 누가 시작했나 · 사람(재생 화면) · 스케줄(스케줄 노드)
STARTED_BY_HUMAN = 'human'
STARTED_BY_SCHEDULE = 'schedule'

#: 그 PC 가 지금 **단독으로** 움직이는 단계 · 하트비트 `motion_phase` · 그룹 단계(`group_*`)는 여기 없다 ·
#: 빈 값 · `idle` · `stopped` · `completed` · `initialized`(초기 위치에서 대기) 는 쉬는 중
SOLO_BUSY_PHASES = frozenset({
    'preparing', 'initializing', 'countdown', 'running', 'verifying',
    'waiting', 'repeat_waiting', 'recovering', 'stopping',
})

#: 끔 PC 를 뺄 때 이유 · 화면 글자와 같게(`끔`)
OFF_REASON = '끔 모드'
MANUAL_REASON = '수동 모드'   # 스케줄이 켠 그룹 재생에서만
SOLO_BUSY_REASON = '단독 재생 중'


def normalize_started_by(value: Any) -> str:
    """모르면 스케줄로 본다 · 수동 PC 를 빼는 쪽이 안전하다(사람이 만지는 중일 수 있다)"""
    return STARTED_BY_HUMAN if str(value or '').strip().lower() == STARTED_BY_HUMAN else STARTED_BY_SCHEDULE


def solo_busy(motion_phase: Any) -> bool:
    """하트비트 단계로 본 「단독으로 도는 중」 · 그룹 단계는 아니다"""
    return str(motion_phase or '').strip().lower() in SOLO_BUSY_PHASES


def exclusion_reason(
    member: Optional[Any],
    link_state: str,
    *,
    protocol_version: int,
    started_by: str,
) -> str:
    """그룹 실행에 넣을 수 없는 이유 · 비면 넣어도 된다.

    `member` 는 하트비트로 받은 PC (`group_execution.Member`) · `link_state` 는
    `MemberRegistry.status` 답(online · warning · offline).
    """
    if member is None or not getattr(member, 'joined', False) or link_state == 'offline':
        return '통신 단절'
    if link_state != 'online':
        return '응답 지연'
    grade = int(getattr(member, 'alarm_grade', 0) or 0)
    if grade > 0:
        return f'Servo 알람 {grade}등급'
    if int(getattr(member, 'protocol_version', 0) or 0) != int(protocol_version):
        return '버전 불일치 · 그 PC 에서 bash scripts/install.sh'
    mode = str(getattr(member, 'operation_mode', '') or '').strip().lower()
    if mode == 'off':
        return OFF_REASON
    if mode == 'manual' and normalize_started_by(started_by) == STARTED_BY_SCHEDULE:
        return MANUAL_REASON
    # 그 PC 에서 단독 재생 중(사람이 켰거나 스케줄 끝 주차) · 그 PC 만 뺀다
    if solo_busy(getattr(member, 'motion_phase', '')):
        return SOLO_BUSY_REASON
    # 그 PC 가 하트비트에 실은 「지금 시작 못 함」(설정 없음 · 모터 끊김 · 조그 · 페이더) · 준비 단계까지
    # 가서 거절되면 그 늦은 거절이 정리와 겹쳐 전체 정지가 됐다(실물 V-4 · 수정 목록 136 ⑤)
    blocker = str(getattr(member, 'start_blocker', '') or '').strip()
    if blocker:
        return blocker
    return ''


def self_exclusion_reason(
    motion_run_status: Optional[Any],
    safety_status: Optional[Any],
    start_blocker: Any = '',
) -> str:
    """진행 PC(마스터) 자신을 넣을 수 없는 이유 · 다른 PC 와 같은 규칙 · 수정 목록 136 ①

    전에는 마스터를 늘 넣었다 · 단독 재생 · 조그 중인 마스터는 제 준비 답에서야 「사람 조작 중」 이
    보여 그룹 시작을 통째로 취소했고, 그 정리 길이 마스터의 단독 재생 · 조그까지 세웠다(실물 V-4 · V-5) ·
    이제 빼고 나머지로 돈다 · 운전 모드는 보지 않는다(시작을 누른 PC 다 · 끔은 시작 자체가 막힌다).
    """
    if run_state.solo_running(motion_run_status):
        return SOLO_BUSY_REASON
    busy = run_state.human_operation_reason(motion_run_status, safety_status)
    if busy:
        return busy
    return str(start_blocker or '').strip()


def local_start_blocker(local_status: Optional[Any]) -> str:
    """이 PC 의 하트비트 `start_blocker` · 로컬 상태 한 장에서 · 사람 조작이 먼저 · 수정 목록 136 ⑤"""
    status = local_status if isinstance(local_status, Mapping) else {}
    busy = run_state.human_operation_reason(
        status.get('motion_run_status'), status.get('safety_status'),
    )
    return (busy or str(status.get('start_blocker') or '').strip())[:200]


#: 스케줄 구간 끝 · PC 마다 기준점 주차 → 서보 OFF · 수정 목록 36
SCHEDULE_END_REASON = 'schedule_end'


def idle_park_wanted(*, after_cycle: bool, reason: str, execution_id: str) -> bool:
    """도는 그룹 없이 구간이 끝났다 · 그래도 PC 마다 주차를 전하나 · 사용자 2026-10-13

    전에는 그룹 실행이 없으면 「활성 그룹 실행이 없습니다」 로 거절했다 · 그래서 구간 끝에
    멈춰 있던 PC 들은 서보를 켠 채 밤을 샜다 · 받을 PC 는 시작과 같은 규칙(스케줄이 켠 그룹)으로 고른다.
    """
    return bool(after_cycle) and str(reason or '') == SCHEDULE_END_REASON and not str(execution_id or '')


def start_summary(participants, excluded) -> str:
    """시작 응답 · 알림 글 · 참가 N대 · 빠진 PC 와 이유"""
    count = len(tuple(participants or ()))
    text = f'참가 {count}대'
    rows = sorted((str(pc), str(reason)) for pc, reason in dict(excluded or {}).items())
    if rows:
        text += ' · 빠짐 ' + ', '.join(f'{pc}({reason})' for pc, reason in rows)
    return text
