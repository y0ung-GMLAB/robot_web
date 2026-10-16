"""이 PC 의 모션이 지금 돌고 있는가 · 이 판단의 주인 · §6-136

스케줄 점검은 1분마다 "돌아야 하는데 안 도나 · 멈춰야 하는데 도나" 를 본다 ·
그러려면 **돌고 있다**의 뜻이 하나여야 한다.

돌고 있는 상태를 늘어놓으면 목록이 길고, 새 단계가 생길 때마다 여기를 고쳐야
한다 · 빠뜨리면 점검이 "안 돈다"로 잘못 읽고 이미 도는 모션을 또 시작시킨다.

그래서 **멈춰 있는 상태만** 적는다 · 이쪽이 짧고 잘 안 늘어난다 · 모르는
상태는 "돌고 있다"로 본다 · 또 시작시키는 것보다 가만두는 쪽이 안전하다.

그룹 실행도 이 PC 의 모션 실행을 쓴다 (`local_execution_blocker` 참고) ·
그래서 연동이든 단독이든 여기 한 곳으로 답이 나온다.
"""

from collections.abc import Mapping

#: 아무것도 돌지 않는 상태 · 여기 없으면 도는 중으로 본다
#:
#: 빈 값은 여기 **없다** · 「멈춰 있다」가 아니라 「못 읽었다」이고, 못 읽었으면
#: 가만두는 쪽이 안전하다 · 실제로 멈춰 있으면 `idle` 이 온다.
IDLE_STATES = frozenset({
    'idle',
    'off',
    'ready',
    'stopped',
    'completed',
    'motion_completed',
    'error',
    'blocked',
    # 초기 위치 이동이 끝나 서 있다 · 수동 「초기 위치 이동」 과 스케줄 끝 기준점
    # 주차가 여기서 멈춘다 · 전에는 도는 중으로 읽혀 다음 스케줄이 시작을 못 했다 ·
    # 수정 목록 36
    'initialized',
})


def is_running(state) -> bool:
    """이 상태를 「돌고 있다」로 볼 것인가.

    모르는 상태는 돌고 있는 것으로 본다 · 도는 모션을 또 시작시키면
    "previous motion run task is still running" 으로 막히거나, 더 나쁘면
    모터가 두 명령을 받는다.
    """
    return str(state or '').strip().lower() not in IDLE_STATES


def is_idle(state) -> bool:
    return not is_running(state)


#: 지금 **축이 실제로 움직이는** 상태 · §6-165
#:
#: `is_running` 과 다르다 · 저것은 「멈춰 있지 않다」라서 `initializing`(초기
#: 위치로 가는 중)과 `countdown`(녹화 카운트다운)도 포함한다 · 여기는 **모션
#: 자체가 재생되는 동안**만이다.
#:
#: 화면 표시와 스튜디오 진행이 이 구분을 쓴다 · 초기 이동 중에 「모션 동작
#: 중」이라고 하면 사람이 잘못 읽고, 테이크 시계가 초기 이동 시간까지 세면
#: 재생 길이가 틀린다.
#:
#: 전에는 이 목록이 **다섯 파일에 손으로** 적혀 있었다 · `bridge_helpers`,
#: `midi_control_node`, `playback_session`(둘), `recording_session` · 새 상태가
#: 하나 생기면 다섯 곳을 고쳐야 했고, 빠뜨린 곳만 조용히 틀렸다.
MOVING_STATES = frozenset({
    'running',
    'verifying',
})


def is_moving(state) -> bool:
    """지금 축이 실제로 움직이는가.

    「멈춰 있지 않다」(`is_running`)보다 **좁다** · 초기 위치 이동과 카운트다운은
    여기 들지 않는다 · 모르는 상태는 움직이지 **않는** 것으로 본다 (`is_running`
    과 반대다) · 이 판정은 표시와 시계에 쓰이므로, 모를 때 「움직인다」고 하면
    없는 진행을 그린다.
    """
    return str(state or '').strip().lower() in MOVING_STATES


#: 그룹 실행이 살아 있는 단계 · §6-145
#:
#: 여기는 **살아 있는 쪽**을 적는다 · 로컬(`IDLE_STATES`)과 반대다 · 그룹은
#: `execution_id` 가 함께 와서 「없으면 안 도는 것」이 분명하기 때문이다.
#:
#: 전에는 이 목록이 두 곳에 따로 있었다 (`coordination_bridge.py` 와
#: `coordination.js`) · 스케줄 점검이 세 번째로 쓸 뻔했다.
GROUP_ACTIVE_STATES = frozenset({
    'preparing',
    'initializing',
    'armed',
    'start_scheduled',
    'waiting',
    'running',
    # 각자 재생 · 1회차 뒤로 PC 마다 제 목록을 돈다 · 수정 목록 35
    'running_independent',
    'waiting_cycle_ready',
    'cycle_ready',
    'stop_after_cycle',
    'releasing',
    # 회차 맞춤 장벽 · 회차 끝 → 다음 회차 초기화 · 진행 PC 의 실행 상태 · 수정 목록 155
    'motion_completed',
    'cycle_initializing',
    # 슬레이브 실행 상태 = 이 PC 런타임 상태(`_local_group_state`) · 회차 안팎의 짧은 단계와 복귀 대기 ·
    # 전에는 장벽(`motion_completed`)에서 「그룹 끝」 으로 읽혀 구간 끝 주차가 살아 있는 그룹 실행
    # 스레드에 막혔다(「previous motion run task is still running」 · 1분 뒤 다시) · 155 ·
    # 실행이 풀리면 `execution_id` 가 비므로 여기 적어도 「끝난 그룹」 을 살리지 않는다
    'verifying',
    'completed',
    'initialized',
    'join_ready',
})


def group_is_active(execution) -> bool:
    """그룹 실행이 지금 이 PC 의 모션 실행을 쓰고 있는가.

    **준비 단계도 포함한다** · 마스터가 신호를 보내고 각 PC 가 응답하고 시각을
    맞추는 동안, 이 PC 의 로컬 모션은 아직 `stopped` 다 · 그 틈을 「멈춤」으로
    읽으면 스케줄 점검이 이미 시작된 그룹 실행을 또 시작시킨다 · §6-145

    `execution_id` 가 비면 끝난 것이다 · 상태만 보고 판단하지 않는다.
    """
    if not isinstance(execution, dict):
        return False
    if not str(execution.get('execution_id') or '').strip():
        return False
    return str(execution.get('state') or '').strip().lower() in GROUP_ACTIVE_STATES


def solo_running(motion_run_status) -> bool:
    """그룹이 아닌 제 재생(초기 이동 포함)이 도는 중인가 · 수정 목록 136"""
    run = motion_run_status if isinstance(motion_run_status, Mapping) else {}
    state = str(run.get('state') or '').strip().lower()
    return bool(state) and not run.get('group_execution') and is_running(state)


#: 사람 조작 · 안전 상태 `manual_activity_modes` · `command_owner` 를 화면 글자로
_MANUAL_ACTIVITY_TEXT = {'jog': '조그 이동', 'action': '목표 위치 이동'}


def human_operation_reason(motion_run_status, safety_status) -> str:
    """이 PC 에서 사람이 지금 무언가 움직이는 중인가 · 그러면 그룹에 들어가지 않는다 · 수정 목록 122 (나)

    수동 모드 PC 도 사람이 누른 그룹 재생에 들어간다 · 그런데 그 PC 앞에서 누가 조그 ·
    페이더 · 단독 재생을 하고 있으면 그룹이 축을 빼앗는다 · 그 PC 만 빼고 이유를 남긴다 ·
    브리지(준비 검사 · 정지 거르기)와 연동 노드(선택 · 하트비트 · 마스터 자신)가 같은 판정을 쓴다 · 수정 목록 136
    """
    safety = safety_status if isinstance(safety_status, Mapping) else {}
    if solo_running(motion_run_status):
        return '사람 조작 중 · 단독 재생'
    modes = safety.get('manual_activity_modes')
    modes = {str(item) for item in modes} if isinstance(modes, (list, tuple, set)) else set()
    for mode in ('jog', 'action'):
        if mode in modes:
            return f'사람 조작 중 · {_MANUAL_ACTIVITY_TEXT[mode]}'
    if str(safety.get('command_owner') or '') == 'stream':
        return '사람 조작 중 · 페이더'
    return ''
