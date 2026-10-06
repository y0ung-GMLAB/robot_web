"""다이나믹셀 토크 켜기·끄기 명령 · 수정 목록 36 (2026-10-06)

전에는 토크를 끄는 길이 긴급 정지뿐이었다 · 스케줄 끝 주차 뒤 끄는 데 쓴다.
"""

from motion_supervisor import supervisor_node
from motion_supervisor.supervisor_node import MotionSupervisor


def _supervisor(motors):
    supervisor = MotionSupervisor.__new__(MotionSupervisor)
    supervisor._current_motors = lambda: motors
    published = []
    supervisor._publish_controlword = lambda _motors, axes, controlword: published.append(
        (tuple(axes), controlword)
    )
    return supervisor, published


MOTORS = [
    {'controller_index': 0, 'motor_type': 'ac_servo', 'state': 'detected'},
    {'controller_index': 2, 'motor_type': 'dynamixel', 'transport': 'serial', 'state': 'detected'},
    {'controller_index': 3, 'motor_type': 'dynamixel', 'transport': 'serial', 'state': 'detected'},
    {'controller_index': 4, 'motor_type': 'dynamixel', 'transport': 'serial', 'state': 'missing'},
]


def test_torque_off_goes_to_every_detected_dynamixel_only():
    supervisor, published = _supervisor(MOTORS)

    success, message = supervisor._handle_dynamixel_torque_control({'action': 'torque_off'})

    assert success is True
    assert published == [((2, 3), supervisor_node.DYNAMIXEL_TORQUE_DISABLE)]
    assert 'OFF' in message


def test_torque_on_can_target_listed_axes():
    supervisor, published = _supervisor(MOTORS)

    success, _message = supervisor._handle_dynamixel_torque_control(
        {'action': 'torque-on', 'axes': [3]}
    )

    assert success is True
    assert published == [((3,), supervisor_node.DYNAMIXEL_TORQUE_ENABLE)]


def test_unknown_action_and_no_axes_are_refused():
    supervisor, published = _supervisor(MOTORS[:1])
    assert supervisor._handle_dynamixel_torque_control({'action': 'explode'})[0] is False
    assert supervisor._handle_dynamixel_torque_control({'action': 'reboot'})[0] is False
    assert supervisor._handle_dynamixel_torque_control({'action': 'torque_off'})[0] is False
    assert published == []


def test_torque_command_shares_the_servo_power_rules():
    assert 'dynamixel_torque_control' in supervisor_node.SERVO_POWER_COMMANDS
    assert 'ac_servo_control' in supervisor_node.SERVO_POWER_COMMANDS


def test_reboot_sends_the_fault_reset_bit_which_the_serial_controller_turns_into_reboot():
    """수정 목록 24 · 0x80 은 알람 중에도 지나가는 리셋 값 · Torque Enable 에는 쓰이지 않는다"""
    supervisor, published = _supervisor(MOTORS)

    success, message = supervisor._handle_dynamixel_torque_control({'action': 'reboot', 'axes': [2]})

    assert success is True
    assert published == [((2,), supervisor_node.DYNAMIXEL_REBOOT)]
    assert supervisor_node.DYNAMIXEL_REBOOT == supervisor_node.CW_FAULT_RESET_MINAS == 0x80
    assert '토크가 꺼진' in message


def test_torque_on_is_refused_while_the_motor_reports_a_hardware_error():
    motors = [dict(MOTORS[1], fault=True), MOTORS[2]]
    supervisor, published = _supervisor(motors)

    success, message = supervisor._handle_dynamixel_torque_control({'action': 'torque_on'})

    assert success is False
    assert '재부팅' in message
    assert published == []
    # 끄기와 재부팅은 오류 중에도 된다
    assert supervisor._handle_dynamixel_torque_control({'action': 'torque_off'})[0] is True
    assert supervisor._handle_dynamixel_torque_control({'action': 'reboot'})[0] is True
