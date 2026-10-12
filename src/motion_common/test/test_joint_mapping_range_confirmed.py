"""조인트 범위 확인 · 판정 하나 · 수정 목록 97

「자동 생성」 줄은 범위가 −180 ~ 180°다 · 기계 범위가 아니라 아무것도 막지
않는다 · 사람이 범위를 넣거나 「범위 확인」 을 체크하기 전에는 재생을 막는다.
"""

import math

from motion_common import joint_mapping


def test_explicit_flag_wins():
    assert joint_mapping.range_confirmed({'range_confirmed': True}) is True
    # 범위를 넣었어도 사람이 체크를 끄면 미확인
    assert joint_mapping.range_confirmed({
        'range_confirmed': False, 'motion_lower_deg': -10.0, 'motion_upper_deg': 13.0,
    }) is False


def test_old_file_with_default_range_is_unconfirmed():
    assert joint_mapping.range_confirmed({'motion_lower_deg': -180.0, 'motion_upper_deg': 180.0}) is False
    assert joint_mapping.range_confirmed({
        'motion_lower_rad': -math.pi, 'motion_upper_rad': math.pi,
    }) is False
    # 칸이 아예 없으면 기본값 −180 ~ 180 과 같다
    assert joint_mapping.range_confirmed({}) is False


def test_old_file_with_a_real_range_counts_as_confirmed():
    """이미 범위를 넣어 둔 PC 가 업데이트하자마자 멈추면 안 된다"""
    assert joint_mapping.range_confirmed({'motion_lower_deg': -10.0, 'motion_upper_deg': 13.0}) is True
    assert joint_mapping.range_confirmed({
        'motion_lower_rad': math.radians(-15.0), 'motion_upper_rad': math.radians(15.0),
    }) is True
    # 한쪽만 바꿔도 누가 넣은 값이다
    assert joint_mapping.range_confirmed({'motion_lower_deg': -180.0, 'motion_upper_deg': 90.0}) is True


def test_only_enabled_rows_with_a_name_count():
    rows = [
        {'motion_id': 'Neck_Yaw', 'enabled': True},                       # 미확인
        {'motion_id': 'Neck_Pitch', 'enabled': False},                    # 꺼짐 · 안 봄
        {'motion_id': 'Eye_Pitch', 'range_confirmed': True},              # 확인
        {'motion_id': '', 'enabled': True},                               # 이름 없음 · 안 봄
        {'motion_id': 'Eye_Yaw_L', 'motion_lower_deg': -11.3, 'motion_upper_deg': 11.3},
        'not a row',
    ]

    assert joint_mapping.unconfirmed_range_ids(rows) == ['Neck_Yaw']


def test_reason_names_the_joints_and_what_to_do():
    reason = joint_mapping.range_block_reason([
        {'motion_id': 'Neck_Yaw'}, {'motion_id': 'Neck_Pitch'},
    ])

    assert reason.startswith('조인트 범위 미확인 · Neck_Yaw, Neck_Pitch')
    assert '범위 확인' in reason
    assert joint_mapping.range_block_reason([{'motion_id': 'a', 'range_confirmed': True}]) == ''
    assert joint_mapping.range_block_reason([]) == ''
