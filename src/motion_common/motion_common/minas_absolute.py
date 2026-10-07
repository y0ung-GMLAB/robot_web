"""MINAS 앱솔루트 확인 · 판정 하나 · 수정 목록 62

연결된 MINAS 드라이브 **전부**가 앱솔루트(Pr0.15 = 0)로 확인돼야 모터를 움직인다 ·
프로젝트 등록·조인트 매핑·「사용」 여부와 무관 · 다이나믹셀은 대상 아님(Pr0.15 없음).

    값을 읽는 쪽   motion_state_monitor (`absolute_check`) · motion_state 의 `minas_absolute`
    막는 쪽       motion_supervisor (모든 동작 명령 · `commands_blocked`) · web_bridge (검사·초기 이동·화면)

판정은 여기 하나다 · 같은 질문에 두 답이 생기지 않게 막는 쪽은 이 함수만 부른다.

막는 경우 · Pr0.15 ≠ 0 · 읽기 실패(「확인 불가」 · 마지막 값으로 대체하지 않음) ·
Err40(다회전 무효) · 확인 중 · 확인 정보 자체가 없음.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

#: Panasonic(MINAS) EtherCAT vendor id
MINAS_VENDOR_ID = 0x066F

#: Pr0.15 값 · 매뉴얼 SX-DSV03241 p.176 · 허용은 0 하나(사용자 결정 2026-10-07)
ABSOLUTE_MODE_OK = 0
ABSOLUTE_MODE_NAMES = {
    0: '절대', 1: '인크리멘털', 2: '절대 · 다회전 넘침 무시', 3: '절대 · 한 바퀴만', 4: '절대 · 연속 회전',
}

#: 0x603F 의 Err40(앱솔루트 시스템 다운 · 다회전 무효)
#: 실물 2026-10-07 · Err80.0 = 0xFF50 · Err88.0 = 0xFF58 → 아래 바이트 = 주 번호(10진) ·
#: 그래서 Err40 = 0xFF28 로 본다 (매뉴얼 표 미확인 · 두 실측에서 추론)
ERR40_CODE = 0xFF28

# 드라이브 하나의 판정
DRIVE_OK = 'ok'
DRIVE_NOT_ABSOLUTE = 'not_absolute'
DRIVE_UNKNOWN = 'unknown'
DRIVE_MULTITURN_INVALID = 'multiturn_invalid'

# 전체 판정
STATE_NONE = 'none'          # 보이는 MINAS 드라이브 없음 · 막지 않음
STATE_CHECKING = 'checking'  # 드라이브 구성이 바뀌어 읽는 중 · 막음
STATE_OK = 'ok'
STATE_BLOCKED = 'blocked'

MISSING_MESSAGE = '앱솔루트 확인 정보 없음 · 모터 상태 프로그램 확인 필요'
CHECKING_MESSAGE = '앱솔루트 확인 중 · 잠시 후 다시 시도하세요'


def classify_drive(
    absolute_mode: Optional[int], error_code: Optional[int], read_error: str = '',
) -> str:
    """드라이브 하나 · Pr0.15 · 0x603F · 읽기 오류 → 판정"""
    if read_error or absolute_mode is None:
        return DRIVE_UNKNOWN
    if int(absolute_mode) != ABSOLUTE_MODE_OK:
        return DRIVE_NOT_ABSOLUTE
    if error_code is not None and int(error_code) == ERR40_CODE:
        return DRIVE_MULTITURN_INVALID
    return DRIVE_OK


def drive_label(drive: Mapping[str, Any]) -> str:
    axis = drive.get('axis')
    if axis is not None:
        return f'{int(axis)}번 모터'
    position = drive.get('slave_position')
    master = int(drive.get('master_index') or 0)
    where = f'마스터 {master} 슬레이브 {position}' if master else f'슬레이브 {position}'
    return f'{where}(미등록)'


def drive_problem(drive: Mapping[str, Any]) -> str:
    status = str(drive.get('status') or '')
    if status == DRIVE_NOT_ABSOLUTE:
        value = drive.get('absolute_mode')
        return f'Pr0.15={value}({ABSOLUTE_MODE_NAMES.get(value, "?")})'
    if status == DRIVE_MULTITURN_INVALID:
        return 'Err40 다회전 무효'
    if status == DRIVE_UNKNOWN:
        return '확인 불가'
    return ''


def blocked_message(drives: Iterable[Mapping[str, Any]]) -> str:
    parts = [
        f'{drive_label(drive)} {drive_problem(drive)}'
        for drive in drives
        if str(drive.get('status') or '') != DRIVE_OK
    ]
    if not parts:
        return ''
    return '앱솔루트 미확인 · ' + ' · '.join(parts) + ' · 모터 관리에서 앱솔루트 설정'


def summary(drives: List[Dict[str, Any]], *, checked_at: Optional[float]) -> Dict[str, Any]:
    """읽은 드라이브 목록 → motion_state 의 `minas_absolute`"""
    message = blocked_message(drives)
    if not drives:
        state = STATE_NONE
    elif message:
        state = STATE_BLOCKED
    else:
        state = STATE_OK
    return {
        'state': state,
        'drives': [dict(drive) for drive in drives],
        'checked_at': checked_at,
        'message': message,
    }


def checking_summary(previous_drives: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """구성이 바뀌어 다시 읽는 중 · 옛 판정은 쓰지 않는다(표시용 목록만 둔다)"""
    return {
        'state': STATE_CHECKING,
        'drives': [dict(drive) for drive in (previous_drives or [])],
        'checked_at': None,
        'message': CHECKING_MESSAGE,
    }


def block_reason(minas_absolute: Any) -> str:
    """막을 이유 · 막지 않으면 빈 문자열 · motion_state 의 `minas_absolute` 를 그대로 받는다"""
    if not isinstance(minas_absolute, Mapping):
        return MISSING_MESSAGE
    state = str(minas_absolute.get('state') or '')
    if state in (STATE_NONE, STATE_OK):
        return ''
    if state == STATE_CHECKING:
        return CHECKING_MESSAGE
    if state == STATE_BLOCKED:
        return str(minas_absolute.get('message') or '앱솔루트 미확인')
    return MISSING_MESSAGE
