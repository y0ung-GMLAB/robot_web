"""MINAS 앱솔루트 판정 하나 · 수정 목록 62"""

from motion_common import minas_absolute as ma


def _drive(status, *, axis=0, position=0, mode=0, code=0):
    return {
        'master_index': 0, 'slave_position': position, 'axis': axis,
        'absolute_mode': mode, 'error_code': code, 'status': status,
    }


def test_only_pr015_zero_without_err40_is_ok():
    assert ma.classify_drive(0, 0) == ma.DRIVE_OK
    assert ma.classify_drive(0, None) == ma.DRIVE_OK          # 오류 코드를 못 읽은 것만으로는 막지 않음
    assert ma.classify_drive(1, 0) == ma.DRIVE_NOT_ABSOLUTE
    assert ma.classify_drive(2, 0) == ma.DRIVE_NOT_ABSOLUTE   # 0 하나만 허용(사용자 결정)
    assert ma.classify_drive(0, 0xFF28) == ma.DRIVE_MULTITURN_INVALID
    assert ma.classify_drive(None, 0) == ma.DRIVE_UNKNOWN
    assert ma.classify_drive(0, 0, 'SDO 실패') == ma.DRIVE_UNKNOWN


def test_summary_states():
    assert ma.summary([], checked_at=1.0)['state'] == ma.STATE_NONE
    assert ma.summary([_drive(ma.DRIVE_OK)], checked_at=1.0)['state'] == ma.STATE_OK
    blocked = ma.summary([
        _drive(ma.DRIVE_OK, axis=0, position=0),
        _drive(ma.DRIVE_NOT_ABSOLUTE, axis=1, position=1, mode=1),
        _drive(ma.DRIVE_UNKNOWN, axis=None, position=3, mode=None),
    ], checked_at=1.0)
    assert blocked['state'] == ma.STATE_BLOCKED
    assert blocked['message'].startswith('앱솔루트 미확인 · ')
    assert '1번 모터 Pr0.15=1(인크리멘털)' in blocked['message']
    assert '슬레이브 3(미등록) 확인 불가' in blocked['message']
    assert '0번 모터' not in blocked['message']


def test_block_reason_blocks_everything_but_none_and_ok():
    assert ma.block_reason({'state': ma.STATE_NONE}) == ''
    assert ma.block_reason({'state': ma.STATE_OK}) == ''
    assert ma.block_reason(ma.checking_summary()) == ma.CHECKING_MESSAGE
    assert ma.block_reason({'state': ma.STATE_BLOCKED, 'message': '앱솔루트 미확인 · 1번 모터'}) == (
        '앱솔루트 미확인 · 1번 모터'
    )
    # 확인 정보가 없으면 막는다 · 마지막 값으로 대체하지 않는다
    assert ma.block_reason(None) == ma.MISSING_MESSAGE
    assert ma.block_reason({'state': 'weird'}) == ma.MISSING_MESSAGE


def test_unregistered_drive_on_another_master_is_named_by_master_and_position():
    drive = _drive(ma.DRIVE_UNKNOWN, axis=None, position=2)
    drive['master_index'] = 1
    assert ma.drive_label(drive) == '마스터 1 슬레이브 2(미등록)'
