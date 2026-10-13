"""한 회차가 끝나면 어떻게 잇는가 · 이 낱말의 주인 · §6-135

같은 기본값이 여덟 곳에 적혀 있었고 답이 **두 가지**였다.

    화면 선택칸 · 화면 저장 · 실행 설정 저장   `reinitialize`
    스케줄 노드 · 저장 형식 기본값 · 그 외      `direct`

그래서 화면에는 「초기 위치 이동 후 다음」이 골라져 보이는데, 스케줄이 발화하면
`direct` 로 나갔다 · `direct` 는 끝값에서 시작값으로 **곧바로 튀므로** 둘이
5° 이상 벌어져 있으면 실행을 거부한다 · 화면에서 손으로 누르면 되는 모션이
스케줄로는 "모션 시작·종료값 차이가 5°를 초과합니다" 로 죽었다.

기본값은 `reinitialize` 다 · 초기 위치로 옮긴 뒤 다시 재생하므로 시작값과
끝값이 달라도 된다 · 사람이 보고 있지 않은 자리에서 더 안전하기도 하다.
"""

DIRECT = 'direct'
DWELL = 'dwell'
REINITIALIZE = 'reinitialize'
DWELL_REINITIALIZE = 'dwell_reinitialize'

REPEAT_MODES = frozenset({DIRECT, DWELL, REINITIALIZE, DWELL_REINITIALIZE})

DEFAULT_REPEAT_MODE = REINITIALIZE

#: 초기 위치로 돌아가지 않고 이어 붙이는 방식 · 시작값과 끝값이 맞아야 한다
LOOPS_WITHOUT_REINITIALIZE = frozenset({DIRECT, DWELL})


#: 쓰는 방식 · 늘 초기 위치를 거친다 (사용자 결정 2026-10-12 · 서버도 2026-10-13)
#: 「바로 다음 회차」(direct) · 「대기 후 다음 회차」(dwell) 는 끝값에서 시작값으로 바로 이어
#: 안전상 쓰지 않는다 · 저장돼 있던 값은 초기 위치 방식으로 바꿔 읽고, 새로 보내면 거절한다.
ALLOWED_REPEAT_MODES = frozenset({REINITIALIZE, DWELL_REINITIALIZE})
SAFE_REPLACEMENT = {DIRECT: REINITIALIZE, DWELL: DWELL_REINITIALIZE}

UNSAFE_MODE_MESSAGE = (
    '초기 위치를 거치지 않는 반복(바로 다음 회차 · 대기 후 다음 회차)은 안전을 위해 쓰지 않습니다 · '
    '「초기 위치로 돌아간 뒤 다음 회차」 를 고르세요'
)


def normalize_repeat_mode(value, default: str = DEFAULT_REPEAT_MODE) -> str:
    """빈 값·모르는 값은 기본값으로 · 옛 direct·dwell 은 초기 위치 방식으로 · 판정은 여기서만 한다."""
    mode = str(value or '').strip().lower()
    if mode not in REPEAT_MODES:
        return default
    return SAFE_REPLACEMENT.get(mode, mode)


def request_repeat_mode_error(value) -> str:
    """새로 들어온 요청의 반복 방식 · 받으면 안 되는 이유 · 괜찮으면 빈 글 · 수정 목록 112 라

    받은 뒤 준비 단계에서 「지원하지 않는 자동 반복 방식」 으로 죽지 않게 받기 전에 거절한다.
    빈 값은 저장된 설정 · 기본값을 쓰라는 뜻이라 괜찮다.
    """
    mode = str(value or '').strip().lower()
    if not mode or mode in ALLOWED_REPEAT_MODES:
        return ''
    if mode in SAFE_REPLACEMENT:
        return UNSAFE_MODE_MESSAGE
    return f'지원하지 않는 반복 방식입니다: {mode}'


def needs_loop_value_match(repeat_mode, *, unknown_needs_match: bool = True) -> bool:
    """이 방식으로 이으려면 모션 시작값과 끝값이 맞아야 하는가.

    **설정 기본값과는 다른 질문이다.** 안 적힌 값을 설정에서는 `reinitialize`
    로 읽지만(사람이 화면에서 보는 것과 같게), 여기서는 모르면 **검사하는
    쪽**이 안전하다 · 검사를 건너뛴 채로 시작하면 모터가 끝값에서 시작값으로
    튄다.

    계획(`plan_builder`)은 언제나 값을 정규화해 실어 주므로, 실제로 모르는
    값이 여기까지 오는 일은 없어야 한다.
    """
    mode = str(repeat_mode or '').strip().lower()
    if mode not in REPEAT_MODES:
        return unknown_needs_match
    return mode in LOOPS_WITHOUT_REINITIALIZE


# -- 그룹 PC 사이 맞춤 · 수정 목록 35 (2026-10-06) ---------------------------- #
#
# 회차 맞춤 · 매 회차 모든 PC 가 끝나야 다 같이 초기 위치 → 다음 회차 (옛 방식)
# 각자 재생 · 처음 초기 위치 이동과 1회차 시작만 같이 · 그 뒤로는 PC 마다 제
#             재생 목록을 제 속도로 돈다 · 정지·회차 후 정지는 그대로 그룹 전체
GROUP_LOCKSTEP = 'lockstep'
GROUP_INDEPENDENT = 'independent'

GROUP_SYNC_MODES = frozenset({GROUP_LOCKSTEP, GROUP_INDEPENDENT})

DEFAULT_GROUP_SYNC_MODE = GROUP_LOCKSTEP


def normalize_group_sync_mode(value, default: str = DEFAULT_GROUP_SYNC_MODE) -> str:
    """빈 값·모르는 값은 회차 맞춤 · 옛 PC 가 칸 없이 보내도 옛 동작 그대로."""
    mode = str(value or '').strip().lower()
    return mode if mode in GROUP_SYNC_MODES else default
