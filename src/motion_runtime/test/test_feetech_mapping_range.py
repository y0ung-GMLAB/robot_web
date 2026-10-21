"""Feetech 조인트 매핑 · 모터 범위가 한 바퀴(−180~+180 모터 deg · raw 2048 중심) 밖이면 저장 거부 · 수정 목록 158

다이나믹셀(Extended Position) · AC 서보 줄은 이 검사와 무관 · 전과 같다.
"""

from motion_runtime.motion_mapping_manager import MotionMappingManager

FEETECH_REF = 'feetech:port:%2Fdev%2FttyUSB1:id:3'
DXL_REF = 'dynamixel:port:%2Fdev%2FttyUSB0:id:3'


def _row(ref, **overrides):
    row = {
        'motion_id': 'j',
        'enabled': True,
        'motor_ref': ref,
        'reference_enabled': True,
        'reference_position_deg': 0.0,
        'motion_lower_deg': -90.0,
        'motion_upper_deg': 90.0,
        'range_confirmed': True,
        'initial_mode': 'reference',
        'initial_move_time_sec': 5.0,
        'invert': False,
        'offset_deg': 0.0,
        'scale': 1.0,
        'gear_ratio': 2.0,
    }
    row.update(overrides)
    return row


def _validate(row):
    manager = MotionMappingManager.__new__(MotionMappingManager)
    mapping = manager._normalize_mapping({'name': 'm', 'mappings': [row]})
    return manager._validate_mapping(mapping, include_motion_file=False)


def test_feetech_motor_ref_is_valid():
    assert MotionMappingManager._valid_motor_ref(FEETECH_REF)
    assert not MotionMappingManager._valid_motor_ref('feetech:id:3')   # 옛 이름 꼴 없음


def test_feetech_range_inside_one_turn_is_saved():
    assert _validate(_row(FEETECH_REF))['valid'] is True     # ±90 × 2 = ±180


def test_feetech_range_outside_one_turn_is_refused_with_a_reason():
    result = _validate(_row(FEETECH_REF, reference_position_deg=20.0))
    assert result['valid'] is False
    assert any('한 바퀴' in error for error in result['errors'])


def test_dynamixel_row_with_the_same_range_is_unchanged():
    assert _validate(_row(DXL_REF, reference_position_deg=20.0, gear_ratio=50.0))['valid'] is True
