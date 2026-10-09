"""회차 단위 실패 표지 · 수정 목록 67 (사용자 결정 2026-10-07)

도달 확인 실패(초기 위치 · 첫 프레임 · 최종 위치)는 **그 회차만** 실패다 · 그룹 오류(2등급)로
잠그면 사람이 「그룹 오류 확인」 을 누르기 전까지 스케줄이 1분마다 시작해도 거절돼 무인
매장이 밤새 멈춘다(실물 2026-10-07 16:48 · 2번 모터 오차 3.5°).

그룹 사이에는 오류 글만 오간다(GroupEvent.message) · 그래서 런타임이 글 앞에 표지를 붙이고
그룹 코디네이터는 표지를 보고 잠그지 않는다 · 서보 알람 · 통신 끊김 같은 위험한 오류는
표지가 없어 지금처럼 잠긴다.
"""

from __future__ import annotations

TAG = '[회차 실패]'


def tagged(message: str) -> str:
    return f'{TAG} {message}'


def is_cycle_failure(text: object) -> bool:
    return TAG in str(text or '')
