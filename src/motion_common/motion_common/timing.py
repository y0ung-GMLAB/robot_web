"""제어 주기 상수 단일 정의.

모션 데이터 샘플 간격 20ms가 네 곳에 따로 적혀 있었다 (스튜디오·MIDI 는 그 뒤 삭제).

    motion_run_manager.py           DEFAULT_PERIOD_SEC
    web_bridge/bridge_helpers.py    MOTION_DATA_PERIOD_SEC
    (삭제됨) 스튜디오 constants.py  DEFAULT_PERIOD_SEC
    (삭제됨) MIDI 노드              MIDI_COMMAND_PERIOD_SEC

같은 값이지만 이름이 달라 한 곳만 바꾸면 어긋난다. 모션 파일의 프레임 간격과
명령 발행 주기가 갈라지면 재생 속도가 틀어지므로, 한 군데서만 정의한다.
"""

from __future__ import annotations

__all__ = [
    'CONTROL_PERIOD_SEC', 'JOG_COMMAND_PERIOD_SEC', 'period_matches',
    'INITIAL_MOVE_TIME_OPTIONS_SEC', 'INITIAL_MOVE_FALLBACK_SEC', 'initial_move_sec',
]

#: 모션 데이터 샘플 간격이자 명령 발행 주기 · 50Hz
CONTROL_PERIOD_SEC = 0.02

#: 수동 조그 명령 주기 · 조그는 연속 재생보다 성기게 보낸다
JOG_COMMAND_PERIOD_SEC = 0.04

#: 주기 비교 허용 오차 · 부동소수 표현 차이를 흡수한다
PERIOD_TOLERANCE_SEC = 0.001


#: 초기 위치 이동 시간 선택지 · 조인트 매핑 · 재생 화면 · 런타임 검사가 같이 쓴다
INITIAL_MOVE_TIME_OPTIONS_SEC = (5.0, 7.0, 10.0)

#: 이 PC 의 초기 이동 시간을 아무도 알려 주지 않았을 때 · 선택지 중 가장 긴 값 · 수정 목록 205
#: 전에는 브리지 5 s · 연동 노드 · 시간표 구동부 10 s 로 따로 짐작했다 · 짧게 짐작하면 초기 이동이 늦게 출발해 회차
#: 시작을 놓친다(184 A) · 길게 잡으면 일찍 서서 기다릴 뿐 · 실제 값은 조인트 매핑에서 로컬 상태로 온다(`initial_move_sec`)
INITIAL_MOVE_FALLBACK_SEC = max(INITIAL_MOVE_TIME_OPTIONS_SEC)


def initial_move_sec(*candidates) -> float:
    """초기 이동 시간 · 앞에서부터 0 보다 큰 첫 값(정한 값 → 보고된 값 순) · 하나도 없으면 `INITIAL_MOVE_FALLBACK_SEC`"""
    for value in candidates:
        try:
            number = float(value or 0.0)
        except (TypeError, ValueError):
            continue
        if number == number and 0.0 < number < float('inf'):
            return number
    return INITIAL_MOVE_FALLBACK_SEC


def period_matches(interval_sec: float, period_sec: float = CONTROL_PERIOD_SEC) -> bool:
    """간격이 기준 주기와 같은지 판정한다 · 부동소수 오차를 감안한다."""
    try:
        return abs(float(interval_sec) - float(period_sec)) <= PERIOD_TOLERANCE_SEC
    except (TypeError, ValueError):
        return False
