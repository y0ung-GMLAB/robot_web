"""범위 미확인 줄이 있으면 재생·초기 이동을 안 한다 · 수정 목록 97

자동 생성 줄의 −180 ~ 180° 는 기계 범위가 아니다 · 그대로 두면 매핑 범위도
드라이브 소프트 리밋(±36000 모터 deg)도 막는 것이 없다 · 잘못된 파일·부호·
기준점이 그대로 모터로 간다. 매장 PC 는 사람 없이 돌아 화면 경고는 아무도
못 본다 · 그래서 막는다 · 그룹 재생에서는 이 PC 가 준비 확인에서 빠진다.
"""

import threading
from unittest import mock

import pytest

from motion_runtime import motion_run_rules
from motion_runtime.motion_mapping_manager import MotionMappingManager
from motion_runtime.motion_player import MotionPlayer
from motion_runtime.motion_run_manager import MotionRunManager
from motion_runtime.plan_builder import PlanBuilder


@pytest.fixture(autouse=True)
def _restore_patched_rules():
    yield
    mock.patch.stopall()


def _row(motion_id, axis, **overrides):
    row = {
        'motion_id': motion_id,
        'enabled': True,
        'motor_axis': axis,
        'reference_enabled': True,
        'reference_position_deg': 0.0,
        'motion_lower_deg': -180.0,
        'motion_upper_deg': 180.0,
        'initial_mode': 'first_frame',
        'initial_move_time_sec': 5.0,
        'invert': False,
        'offset_deg': 0.0,
        'scale': 1.0,
        'gear_ratio': 1.0,
    }
    row.update(overrides)
    return row


def _manager(rows):
    manager = MotionRunManager.__new__(MotionRunManager)
    manager._player = MotionPlayer(manager)
    manager._plan_builder = PlanBuilder(manager)
    manager._run_lock = threading.RLock()
    manager.period_sec = 0.02
    manager._mapping_file_path = lambda _file_id: None
    manager._load_mapping = lambda _path: {'motion_file_id': 'motion.json', 'mappings': rows}
    manager._motion_file_path = lambda _file_id: 'motion.json'
    motors = [{'axis': index, 'controller_index': index} for index in range(len(rows))]
    manager._current_motors = lambda: motors
    manager._motor_for_axis = lambda axis, _motors: motors[axis]
    for name, value in (
        ('_motor_ready_error', lambda _motor: ''),
        ('_target_range_limit_error', lambda _motor, _low, _high: ''),
        ('_motor_type', lambda _motor: 'ac_servo'),
    ):
        mock.patch.object(motion_run_rules, name, value).start()
    manager._load_motion_records = lambda _path: [
        {'motion_id': row['motion_id'], 'time_sec': time_sec, 'value': 0.0}
        for time_sec in (0.02, 0.04)
        for row in rows
    ]
    return manager


def _build(manager, **kwargs):
    return manager._plan_builder.build({
        'motion_file_id': 'motion.json',
        'mapping_file_id': 'mapping.yaml',
    }, **kwargs)


def test_auto_generated_range_blocks_playback():
    manager = _manager([
        _row('Neck_Yaw', 0, motion_lower_deg=-15.0, motion_upper_deg=15.0),
        _row('Neck_Pitch', 1),                         # 자동 생성 그대로
    ])

    with pytest.raises(ValueError, match=r'^조인트 범위 미확인 · Neck_Pitch · '):
        _build(manager)


def test_auto_generated_range_blocks_the_initial_move_too():
    """초기 이동도 모터를 움직인다 · 매핑의 「사용」 축 전부를 옮긴다"""
    manager = _manager([_row('Neck_Pitch', 0, range_confirmed=False, motion_lower_deg=-10.0)])

    with pytest.raises(ValueError, match='조인트 범위 미확인 · Neck_Pitch'):
        _build(manager, initialization_only=True)


def test_confirmed_ranges_play():
    manager = _manager([
        _row('Neck_Yaw', 0, motion_lower_deg=-15.0, motion_upper_deg=15.0),
        # 진짜 ±180 인 축 · 사람이 체크했다
        _row('Turntable', 1, range_confirmed=True),
    ])

    plan = _build(manager)

    assert sorted(axis['motion_id'] for axis in plan['axes']) == ['Neck_Yaw', 'Turntable']


def test_an_unchecked_axis_does_not_block():
    """「사용」 을 끈 줄은 재생도 안 쓴다 · 범위도 안 본다"""
    manager = _manager([
        _row('Neck_Yaw', 0, range_confirmed=True),
        _row('Spare', 1, enabled=False),
    ])

    plan = _build(manager)

    assert [axis['motion_id'] for axis in plan['axes']] == ['Neck_Yaw']


def _mapping_manager():
    return MotionMappingManager.__new__(MotionMappingManager)


def test_old_mapping_files_get_the_flag_from_their_range():
    mapping = _mapping_manager()._normalize_mapping({
        'name': 'old',
        'mappings': [
            _row('Neck_Yaw', 0, motion_lower_deg=-15.0, motion_upper_deg=15.0),
            _row('Neck_Pitch', 1),
        ],
    })

    flags = {row['motion_id']: row['range_confirmed'] for row in mapping['mappings']}
    assert flags == {'Neck_Yaw': True, 'Neck_Pitch': False}


def test_unchecking_is_kept_even_with_a_real_range():
    mapping = _mapping_manager()._normalize_mapping({
        'name': 'm',
        'mappings': [_row('Neck_Yaw', 0, motion_lower_deg=-15.0, motion_upper_deg=15.0, range_confirmed=False)],
    })

    assert mapping['mappings'][0]['range_confirmed'] is False


def test_saving_an_unconfirmed_mapping_is_allowed_with_a_warning():
    """설치 중에는 범위를 모르는 채로 저장해야 한다 · 재생만 막는다"""
    manager = _mapping_manager()
    mapping = manager._normalize_mapping({
        'name': 'm',
        'mappings': [_row('Neck_Pitch', 0), _row('Spare', 1, enabled=False)],
    })

    validation = manager._validate_mapping(mapping, include_motion_file=False)

    assert validation['valid'] is True
    assert validation['rows']['Neck_Pitch']['status'] == 'warning'
    assert any('범위 미확인' in message for message in validation['warnings'])
    # 꺼 둔 줄은 경고도 없다
    assert validation['rows']['Spare']['status'] == 'ok'
