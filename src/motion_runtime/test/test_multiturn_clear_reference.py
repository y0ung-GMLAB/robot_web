"""다회전 클리어 뒤 기준점 보호 · 재생 계획이 막고 · 조인트 매핑 저장이 기준점 지정 시각을 남긴다 · 수정 목록 140 ③

실물 S 3회차(2026-10-14) · 클리어로 엔코더 값이 모터 한 바퀴 밀렸는데 다른 프로젝트를 고르면 알림 없이 재생할 수
있었다(1:20 축 · 조인트 18° 어긋남 → 초기 위치 이동이 기계 범위 ±12° 를 넘음).
"""

import threading
from unittest import mock

import pytest
import yaml

from motion_common import multiturn_clear
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
        'motion_id': motion_id, 'enabled': True, 'motor_axis': axis, 'reference_enabled': True,
        'reference_position_deg': 0.0, 'motion_lower_deg': -10.0, 'motion_upper_deg': 10.0,
        'range_confirmed': True, 'initial_mode': 'first_frame', 'initial_move_time_sec': 5.0,
        'invert': False, 'offset_deg': 0.0, 'scale': 1.0, 'gear_ratio': 1.0,
    }
    row.update(overrides)
    return row


def _manager(rows, state):
    manager = MotionRunManager.__new__(MotionRunManager)
    manager._player = MotionPlayer(manager)
    manager._plan_builder = PlanBuilder(manager)
    manager._run_lock = threading.RLock()
    manager.period_sec = 0.02
    manager._mapping_file_path = lambda _file_id: None
    manager._load_mapping = lambda _path: {'motion_file_id': 'motion.json', 'mappings': rows}
    manager._motion_file_path = lambda _file_id: 'motion.json'
    manager._multiturn_clear_state = lambda: state
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
        for time_sec in (0.02, 0.04) for row in rows
    ]
    return manager


def _build(manager, **kwargs):
    return manager._plan_builder.build({'motion_file_id': 'motion.json', 'mapping_file_id': 'mapping.yaml'}, **kwargs)


def _state(**axes):
    return {'version': 1, 'axes': {
        key.lstrip('a'): {'axis': int(key.lstrip('a')), 'cleared_at': cleared_at, 'pending': pending}
        for key, (cleared_at, pending) in axes.items()
    }}


def test_pending_clear_blocks_playback_and_initial_move_with_the_same_reason():
    rows = [_row('1-1', 0), _row('1-2', 1, reference_set_at=5000.0)]
    manager = _manager(rows, _state(a1=(1000.0, True)))
    with pytest.raises(ValueError, match='1번 모터 다회전 클리어 뒤 기준점 다시 지정 필요'):
        _build(manager)
    with pytest.raises(ValueError, match='1번 모터 다회전 클리어 뒤 기준점 다시 지정 필요'):
        _build(manager, initialization_only=True)


def test_pending_clear_blocks_even_when_the_axis_is_not_in_this_mapping():
    """표시가 PC 단위라 프로젝트를 바꿔도 남는다 · 그 축이 없는 매핑도 · 사용자 결정(어느 프로젝트든)"""
    manager = _manager([_row('1-1', 0)], _state(a5=(1000.0, True)))
    with pytest.raises(ValueError, match='5번 모터 다회전 클리어'):
        _build(manager)


def test_a_reference_set_before_the_clear_still_blocks_after_another_project_fixed_it():
    """다른 프로젝트에서 다시 지정해 표시(pending)는 풀렸지만 이 매핑의 기준점은 클리어 전 것 · 칸 없음도 「전」"""
    state = _state(a1=(1000.0, False))
    with pytest.raises(ValueError, match='1번 모터'):
        _build(_manager([_row('1-1', 0), _row('1-2', 1, reference_set_at=999.0)], state))
    with pytest.raises(ValueError, match='1번 모터'):
        _build(_manager([_row('1-1', 0), _row('1-2', 1)], state))
    assert _build(_manager([_row('1-1', 0), _row('1-2', 1, reference_set_at=1001.0)], state))   # 클리어 뒤 지정 → 됨
    # 「사용」 을 끈 줄은 재생하지 않으니 보지 않는다
    assert _build(_manager([_row('1-1', 0), _row('1-2', 1, enabled=False)], state))


def test_no_marker_means_no_block():
    assert _build(_manager([_row('1-1', 0), _row('1-2', 1)], {}))


def test_plan_builder_reads_the_pc_marker_next_to_motion_projects(tmp_path):
    projects = tmp_path / 'motion_projects'
    projects.mkdir()
    multiturn_clear.record_clear(multiturn_clear.marker_path(tmp_path), [{'axis': 0}], now=10.0)
    manager = _manager([_row('1-1', 0)], {})
    del manager._multiturn_clear_state
    manager.motion_projects_dir = projects
    assert multiturn_clear.pending_axes(manager._plan_builder._multiturn_clear_state()) == [0]


# -- 조인트 매핑 저장 · 기준점 지정 시각 ---------------------------------------------------- #

def _mapping_manager(tmp_path):
    manager = MotionMappingManager.__new__(MotionMappingManager)
    manager.mappings_dir = tmp_path
    return manager


def _save(manager, rows, file_id=None, now=None):
    payload = {'mapping': {'name': 'show', 'mappings': rows}}
    if file_id:
        payload['file_id'] = file_id
    with mock.patch('motion_runtime.motion_mapping_manager.time.time', return_value=now or 2000.0):
        result = manager._save_mapping(payload)
    assert result['success'] is True, result
    return result


def _file_rows(tmp_path, name='show.yaml'):
    return {row['motion_id']: row for row in yaml.safe_load((tmp_path / name).read_text(encoding='utf-8'))['mappings']}


def test_capture_flag_stamps_the_row_even_when_the_value_is_the_same(tmp_path):
    manager = _mapping_manager(tmp_path)
    _save(manager, [_row('1-1', 0), _row('1-2', 1)], now=1000.0)
    file_id = 'show.yaml'
    rows = _file_rows(tmp_path, file_id)
    assert 'reference_set_at' not in rows['1-1']                  # 새 줄 · 지정한 적 없음(= 클리어 전으로 봄)

    _save(manager, [_row('1-1', 0), _row('1-2', 1, reference_captured=True)], file_id=file_id, now=2000.0)
    rows = _file_rows(tmp_path, file_id)
    assert rows['1-2']['reference_set_at'] == 2000.0
    assert 'reference_captured' not in rows['1-2']                # 표시는 파일에 안 남음
    assert 'reference_set_at' not in rows['1-1']


def test_changed_value_stamps_unchanged_keeps_and_motor_change_drops(tmp_path):
    manager = _mapping_manager(tmp_path)
    _save(manager, [_row('1-1', 0, reference_captured=True), _row('1-2', 1, reference_captured=True)], now=1000.0)
    file_id = 'show.yaml'
    assert _file_rows(tmp_path)['1-1']['reference_set_at'] == 1000.0

    _save(manager, [
        _row('1-1', 0, reference_set_at=1.0),                    # 화면이 옛 값을 들고 와도 파일 값이 이긴다
        _row('1-2', 1, reference_position_deg=12.5),             # 숫자를 고침 → 지금
    ], file_id=file_id, now=3000.0)
    rows = _file_rows(tmp_path)
    assert rows['1-1']['reference_set_at'] == 1000.0
    assert rows['1-2']['reference_set_at'] == 3000.0

    _save(manager, [_row('1-1', 2), _row('1-2', 1, reference_position_deg=12.5)], file_id=file_id, now=4000.0)
    rows = _file_rows(tmp_path)
    assert 'reference_set_at' not in rows['1-1']                  # 다른 모터로 옮김 · 그 모터 기준점은 지정 안 함
    assert rows['1-2']['reference_set_at'] == 3000.0


def test_saving_under_a_new_name_carries_the_times_from_the_screen(tmp_path):
    manager = _mapping_manager(tmp_path)
    _save(manager, [_row('1-1', 0, reference_set_at=1500.0)], now=5000.0)
    assert _file_rows(tmp_path)['1-1']['reference_set_at'] == 1500.0


def test_the_saved_rows_release_the_pending_axis(tmp_path):
    marker = multiturn_clear.marker_path(tmp_path / 'ws')
    multiturn_clear.record_clear(marker, [{'axis': 1}], now=1500.0)
    manager = _mapping_manager(tmp_path)
    result = _save(manager, [_row('1-1', 0), _row('1-2', 1, reference_captured=True)], now=2000.0)
    assert multiturn_clear.mark_reference_saved(marker, result['mapping']['mappings']) == [1]
    assert multiturn_clear.pending_axes(multiturn_clear.load(marker)) == []
