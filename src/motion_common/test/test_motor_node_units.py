"""motor_manager 토픽 단위 = 파이썬 경계 상수 · 수정 목록 6-1 (2026-10-06)

토픽 위치·속도의 rad ↔ deg 변환은 C++ 노드(`motor_manager_node.cpp`) 한 곳에만 있다 ·
파이썬 쪽 `wire_units.MOTOR_NODE_UNIT` 과 어긋나면 모터가 57배 크거나 작게 움직인다 ·
둘을 이 시험으로 묶어 둔다(C++ 는 이 PC 에서 빌드하지 못해 글자로 본다).
"""

from pathlib import Path

from motion_common import units, wire_units

NODE = (
    Path(__file__).resolve().parents[2]
    / 'motion_system' / 'ros2' / 'motion_system_ros2' / 'motion_control_bridge'
    / 'src' / 'motor_manager_node.cpp'
)


def test_node_converts_topic_rad_to_driver_deg_and_back():
    source = NODE.read_text(encoding='utf-8')
    assert wire_units.MOTOR_NODE_UNIT == units.RAD
    assert 'motor_frame[i].position = msg->position[i] * kDegPerRad;' in source
    assert 'motor_frame[i].velocity = msg->velocity[i] * kDegPerRad;' in source
    assert 'msg.position[i] = status[i].position * kRadPerDeg;' in source
    assert 'msg.velocity[i] = status[i].velocity * kRadPerDeg;' in source


def test_motor_config_file_stays_in_degrees():
    # 드라이버와 모터 설정 파일은 원본 그대로 deg (사용자 결정 「노드 경계만」)
    assert wire_units.MOTOR_CONFIG_UNIT == units.DEG
