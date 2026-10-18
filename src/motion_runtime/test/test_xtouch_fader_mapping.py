"""조인트 매핑 「X-Touch 페이더」 칸 · 수정 목록 156 (2026-10-17)

줄마다 페이더 번호 1 ~ 8 · 비우면 칸 없음(옛 파일 모양) · 「사용」 줄 둘이 같은 번호면 저장 거절 ·
저장 → 다시 읽기에서 남는다(프로젝트와 함께 백업).
"""

from motion_common import joint_mapping
from motion_runtime.motion_mapping_manager import MotionMappingManager


def _manager():
    return MotionMappingManager.__new__(MotionMappingManager)


def _row(motion_id='neck_yaw', axis=0, **overrides):
    row = {
        'motion_id': motion_id, 'enabled': True, 'motor_ref': '', 'motor_axis': axis,
        'reference_enabled': True, 'reference_position_deg': 0.0,
        'motion_lower_deg': -15.0, 'motion_upper_deg': 15.0, 'range_confirmed': True,
        'initial_mode': 'reference', 'initial_motion_position_deg': 0.0, 'initial_move_time_sec': 5.0,
        'invert': False, 'offset_deg': 0.0, 'scale': 1.0, 'gear_ratio': 100.0,
    }
    row.update(overrides)
    return row


def test_fader_number_reads_only_one_to_eight():
    assert joint_mapping.fader_number({'xtouch_fader': 3}) == 3
    assert joint_mapping.fader_number({'xtouch_fader': '8'}) == 8
    for bad in (0, 9, 2.5, '', None, 'x', -1):
        assert joint_mapping.fader_number({'xtouch_fader': bad}) is None
    assert joint_mapping.fader_number({}) is None


def test_rate_limits_set_needs_both_velocity_and_acceleration():
    assert joint_mapping.rate_limits_set({'max_velocity_deg_s': 9, 'max_acceleration_deg_s2': 14})
    assert joint_mapping.rate_limits_set({'max_velocity_rad_s': 0.1, 'max_acceleration_rad_s2': 0.2})
    assert not joint_mapping.rate_limits_set({'max_velocity_deg_s': 9})
    assert not joint_mapping.rate_limits_set({'max_acceleration_deg_s2': 14})
    assert not joint_mapping.rate_limits_set({})


def test_fader_field_is_kept_only_when_set():
    manager = _manager()
    mapping = manager._normalize_mapping({'name': 'm', 'mappings': [
        _row(xtouch_fader=2), _row('neck_pitch', axis=1), _row('eye', axis=2, xtouch_fader=0),
    ]})
    rows = mapping['mappings']
    assert rows[0]['xtouch_fader'] == 2
    assert 'xtouch_fader' not in rows[1]
    assert 'xtouch_fader' not in rows[2]


def test_two_enabled_rows_on_one_fader_are_rejected():
    manager = _manager()
    mapping = manager._normalize_mapping({'name': 'm', 'mappings': [
        _row(xtouch_fader=1), _row('neck_pitch', axis=1, xtouch_fader=1),
    ]})
    validation = manager._validate_mapping(mapping, include_motion_file=False)
    assert validation['valid'] is False
    assert any('X-Touch 페이더 1' in message for message in validation['errors'] + [
        text for status in validation['rows'].values() for text in status.get('messages', [])
    ])


def test_a_disabled_row_does_not_hold_its_fader():
    manager = _manager()
    mapping = manager._normalize_mapping({'name': 'm', 'mappings': [
        _row(xtouch_fader=1), _row('old', axis=1, xtouch_fader=1, enabled=False),
    ]})
    assert manager._validate_mapping(mapping, include_motion_file=False)['valid'] is True


def test_fader_survives_save_and_load(tmp_path):
    manager = _manager()
    manager.mappings_dir = tmp_path / 'p' / 'motion_axis_matching'
    manager.motion_files_dir = tmp_path / 'p' / 'motions'
    manager.mappings_dir.mkdir(parents=True)
    manager.motion_files_dir.mkdir(parents=True)
    saved = manager._save_mapping({'mapping': {'name': 'faders', 'mappings': [_row(xtouch_fader=4)]}})
    assert saved['success'] is True
    loaded = manager._load_mapping('faders.yaml')
    assert loaded['mapping']['mappings'][0]['xtouch_fader'] == 4
    assert 'xtouch_fader: 4' in (manager.mappings_dir / 'faders.yaml').read_text(encoding='utf-8')
