"""수동 조작도 조인트 범위 확인 뒤에만 · 수정 목록 97 (사용자 결정 2026-10-12)

「수동 전부 막기」 · 「가급적이면 최대한 안전하고 보수적으로」 ·
자동 생성 범위(−180 ~ 180)로는 페이더가 조인트 ±180° 를 그대로 끈다 ·
모터 설정 기본 한계(±36000 모터 deg)도 막는 것이 없다.

    PC 전체   저장·적용 매핑 어느 쪽이든 「사용」 줄 미확인 → 전부 거절
    축 하나   「사용」 매핑 줄에 없는 모터 → 거절
    모름      프로젝트·매핑 없음 · 못 읽음 → 거절
"""

from pathlib import Path

import pytest
from types import SimpleNamespace

import yaml

from motion_web_bridge import manual_range_gate
from motion_web_bridge.manual_range_gate import ManualRangeGate

BRIDGE_DIR = Path(__file__).resolve().parents[1] / 'motion_web_bridge'

MOTORS = [
    {'controller_index': 0, 'motor_type': 'ac_servo', 'ethercat_master_index': 0, 'alias': 0, 'slave_position': 0},
    {'controller_index': 1, 'motor_type': 'ac_servo', 'ethercat_master_index': 0, 'alias': 0, 'slave_position': 1},
]


def _row(motion_id, axis, **overrides):
    row = {
        'motion_id': motion_id, 'enabled': True, 'motor_axis': axis,
        'motion_lower_deg': -15.0, 'motion_upper_deg': 15.0, 'range_confirmed': True,
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------- 순수 규칙 --


def test_all_confirmed_and_mapped_passes():
    rows = [_row('Neck_Yaw', 0), _row('Neck_Pitch', 1)]

    assert manual_range_gate.block_reason(rows, rows, MOTORS) == ''
    assert manual_range_gate.block_reason(rows, rows, MOTORS, 1) == ''


def test_one_unconfirmed_row_blocks_every_axis():
    """축별이 아니라 PC 전체 · 확인된 축도 막힌다"""
    rows = [_row('Neck_Yaw', 0), _row('Neck_Pitch', 1, range_confirmed=False)]

    reason = manual_range_gate.block_reason(rows, [], MOTORS, 0)

    assert reason.startswith('수동 조작 불가 · 조인트 범위 미확인 · Neck_Pitch')


def test_the_applied_mapping_counts_too():
    """저장은 확인됐어도 장비에 적용된 쪽이 아직 미확인이면 막는다"""
    saved = [_row('Neck_Yaw', 0)]
    applied = [_row('Neck_Yaw', 0, range_confirmed=False)]

    assert '조인트 범위 미확인 · Neck_Yaw' in manual_range_gate.block_reason(saved, applied, MOTORS)


def test_a_motor_without_an_enabled_row_does_not_move():
    rows = [_row('Neck_Yaw', 0), _row('Spare', 1, enabled=False, range_confirmed=False)]

    assert manual_range_gate.block_reason(rows, [], MOTORS, 0) == ''
    reason = manual_range_gate.block_reason(rows, [], MOTORS, 1)
    assert reason.startswith('수동 조작 불가 · 1번 모터는 조인트 매핑의 「사용」 줄에 없습니다')


def test_rows_are_matched_by_motor_ref_like_playback():
    """저장된 `motor_axis` 가 옛 번호여도 `motor_ref` 로 지금 번호를 찾는다"""
    rows = [_row('Neck_Yaw', 7, motor_ref='ac_servo:master:0:slave:1')]

    assert manual_range_gate.block_reason(rows, [], MOTORS, 1) == ''
    assert manual_range_gate.block_reason(rows, [], MOTORS, 7) != ''


# ---------------------------------------------------------------- 파일 읽기 --


def _bridge(tmp_path, rows, *, project_id='p1', mapping_id='mapping.yaml', applied=()):
    mapping_dir = tmp_path / project_id / 'motion_axis_matching'
    mapping_dir.mkdir(parents=True, exist_ok=True)
    path = mapping_dir / mapping_id
    if rows is not None and mapping_id:
        path.write_text(yaml.safe_dump({'mappings': rows}, allow_unicode=True), encoding='utf-8')
    def require_selected_project_id():
        if not project_id:
            raise ValueError('선택한 프로젝트가 없습니다')
        return project_id

    repository = SimpleNamespace(
        require_selected_project_id=require_selected_project_id,
        get_project=lambda _id: {'project': {'active_files': {'motion_axis_matching': mapping_id}}},
        export_path=lambda _id, _category, name: mapping_dir / name,
    )
    return SimpleNamespace(
        project_repository=repository,
        _execution_context=SimpleNamespace(status=lambda validate_files=False: {}),
        _monitoring_mapping_rows_for_context=lambda _context, _id: [dict(row) for row in applied],
        motion_state=lambda: {'motors': MOTORS},
        _path=path,
    )


def test_gate_reads_the_saved_mapping(tmp_path):
    bridge = _bridge(tmp_path, [_row('Neck_Yaw', 0), _row('Neck_Pitch', 1)])

    assert ManualRangeGate(bridge).block_reason(0) == ''


def test_gate_sees_a_save_right_away(tmp_path):
    """체크를 끄고 저장하면 다음 조그부터 막힌다 · 장비에 적용을 기다리지 않는다"""
    bridge = _bridge(tmp_path, [_row('Neck_Yaw', 0)])
    gate = ManualRangeGate(bridge)
    assert gate.block_reason(0) == ''

    bridge._path.write_text(
        yaml.safe_dump({'mappings': [_row('Neck_Yaw', 0, range_confirmed=False, motion_upper_deg=14.0)]}),
        encoding='utf-8',
    )

    assert '조인트 범위 미확인 · Neck_Yaw' in gate.block_reason(0)


def test_auto_generated_mapping_blocks(tmp_path):
    rows = [{'motion_id': 'Neck_Yaw', 'enabled': True, 'motor_axis': 0,
             'motion_lower_rad': -3.141592653589793, 'motion_upper_rad': 3.141592653589793}]

    assert '조인트 범위 미확인' in ManualRangeGate(_bridge(tmp_path, rows)).block_reason(0)


def test_unknown_means_blocked(tmp_path):
    no_project = _bridge(tmp_path, [_row('Neck_Yaw', 0)], project_id='')
    no_file = _bridge(tmp_path, None, project_id='p2')
    no_mapping = _bridge(tmp_path, [_row('Neck_Yaw', 0)], project_id='p3', mapping_id='')

    for bridge in (no_project, no_file, no_mapping):
        reason = ManualRangeGate(bridge).block_reason(0)
        assert reason.startswith('수동 조작 불가 · 조인트 범위를 확인할 수 없습니다'), reason


def test_fader_targets_use_the_last_full_check(tmp_path):
    gate = ManualRangeGate(_bridge(tmp_path, [_row('Neck_Yaw', 0)]))
    # 전체 판정 전에는 막는다
    assert gate.cached_axis_reason(0) != ''

    assert gate.block_reason() == ''
    assert gate.cached_axis_reason(0) == ''
    assert gate.cached_axis_reason(1) != ''


# ---------------------------------------------------------------- 연결 --


def test_every_manual_motion_command_passes_the_gate():
    source = (BRIDGE_DIR / 'manual_motor_commands.py').read_text(encoding='utf-8')

    # 조그 2 · 동작(절대 이동·범위 복구) 2 · 모두 축을 넘긴다
    assert source.count('off = self._off_mode_block(axis)') == 4
    assert "getattr(self.bridge, 'manual_range_blocker', None)" in source


def test_the_fader_stream_passes_the_gate():
    source = (BRIDGE_DIR / 'manual_stream_socket.py').read_text(encoding='utf-8')

    assert source.count('asyncio.to_thread(_stream_block_reason, bridge)') == 2
    assert "getattr(bridge, 'manual_range_axis_blocker', None)" in source


# ------------------------------------------------- 수동 조작 상한 · 수정 목록 126 --


def test_speed_limits_use_the_mapping_gain_so_every_joint_moves_alike(tmp_path):
    """조인트 2 °/s · 4 °/s² · 모터로는 |scale × 감속·기어비| 배 · 방향(invert)은 상관없음"""
    import math
    from motion_common import manual_speed
    bridge = _bridge(tmp_path, [
        _row('Neck_Pitch', 0, gear_ratio=150, invert=True),
        _row('Eye_Yaw', 1, gear_ratio=35, scale=1.047),
    ])
    gate = ManualRangeGate(bridge)
    assert gate.block_reason(0) == ''      # 판정 때 읽은 저장 매핑을 쓴다

    pitch = gate.speed_limits(0)
    eye = gate.speed_limits(1)
    assert math.degrees(pitch[manual_speed.VELOCITY_FIELD]) == pytest.approx(300.0)
    assert math.degrees(pitch[manual_speed.ACCELERATION_FIELD]) == pytest.approx(600.0)
    assert math.degrees(eye[manual_speed.VELOCITY_FIELD]) == pytest.approx(2.0 * 35 * 1.047)


def test_speed_limits_fall_back_to_gain_one_for_an_unmapped_motor(tmp_path):
    import math
    from motion_common import manual_speed
    gate = ManualRangeGate(_bridge(tmp_path, [_row('Neck_Pitch', 0, gear_ratio=150)]))
    gate.block_reason(0)
    assert math.degrees(gate.speed_limits(7)[manual_speed.VELOCITY_FIELD]) == pytest.approx(2.0)
    assert math.degrees(gate.speed_limits(None)[manual_speed.VELOCITY_FIELD]) == pytest.approx(2.0)


def test_jog_and_action_requests_carry_the_speed_limits():
    source = (BRIDGE_DIR / 'manual_motor_commands.py').read_text(encoding='utf-8')
    assert source.count('**self._speed_limits(axis_value),') == 4   # 조그 2 · 절대 이동(범위 복구 포함) 2
