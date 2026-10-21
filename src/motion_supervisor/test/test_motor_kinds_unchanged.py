"""supervisor 모터 종류 판정 · Feetech 가 아닌 모터는 옛 결과 그대로 · 수정 목록 158

옛 `_is_ac_servo` · `_is_dynamixel`(`serial`+`xm` 규칙) 을 글자 그대로 두고 맞춘다 ·
직렬 서보 공통 경로(`_is_serial_servo` · 토크 · 조그 · 절대 이동 · 정지)도 Feetech 가 없으면 옛 `_is_dynamixel` 과 같다.
"""

import itertools

from motion_supervisor.supervisor_node import MotionSupervisor


def _old_text(motor):
    values = [
        motor.get('motor_type'),
        motor.get('motor_type_label'),
        motor.get('driver_model'),
        motor.get('driver_name'),
        motor.get('transport'),
    ]
    return ' '.join(str(value or '').lower() for value in values)


def old_is_ac_servo(motor):
    text = _old_text(motor)
    return 'minas' in text or 'ac servo' in text or 'ac_servo' in text


def old_is_dynamixel(motor):
    text = _old_text(motor)
    return 'dynamixel' in text or 'serial' in text and 'xm' in text


def _motors():
    for motor_type, label, model, transport in itertools.product(
        [None, '', 'minas', 'ac_servo', 'dynamixel', 'unknown', 'zeroerr', 'cubemars', 'serial'],
        [None, 'AC Servo', 'Dynamixel', 'Unknown', 'Serial'],
        [None, 'MADLN05BE', 'XM540-W150', 'xm430', 'AK80', 'UNVERIFIED_MINAS'],
        [None, 'ethercat', 'serial', 'can'],
    ):
        yield {'motor_type': motor_type, 'motor_type_label': label, 'driver_model': model, 'transport': transport}
        yield {'motor_type': motor_type, 'motor_type_label': label, 'driver_name': model, 'transport': transport}


def test_supervisor_kind_checks_are_unchanged_for_every_non_feetech_motor():
    for motor in _motors():
        assert MotionSupervisor._is_ac_servo(motor) == old_is_ac_servo(motor), motor
        assert MotionSupervisor._is_dynamixel(motor) == old_is_dynamixel(motor), motor
        assert MotionSupervisor._is_serial_servo(motor) == old_is_dynamixel(motor), motor


def test_feetech_takes_the_serial_servo_path_but_is_not_dynamixel():
    feetech = {'motor_type': 'feetech', 'motor_type_label': 'Feetech', 'driver_model': 'STS3215', 'transport': 'serial'}
    assert MotionSupervisor._is_serial_servo(feetech)
    assert not MotionSupervisor._is_dynamixel(feetech)
    assert not MotionSupervisor._is_ac_servo(feetech)


def _supervisor(motors):
    supervisor = MotionSupervisor.__new__(MotionSupervisor)
    supervisor._current_motors = lambda: motors
    published = []
    supervisor._publish_controlword = lambda _motors, axes, controlword: published.append(
        (tuple(axes), controlword)
    )
    return supervisor, published


MIXED = [
    {'controller_index': 0, 'motor_type': 'ac_servo', 'state': 'detected'},
    {'controller_index': 1, 'motor_type': 'dynamixel', 'transport': 'serial', 'state': 'detected'},
    {'controller_index': 2, 'motor_type': 'feetech', 'transport': 'serial', 'state': 'detected'},
]


def test_feetech_torque_uses_the_dynamixel_torque_values_only_0_and_1():
    from motion_supervisor import supervisor_node

    supervisor, published = _supervisor(MIXED)
    assert supervisor._handle_dynamixel_torque_control({'action': 'torque_off'})[0] is True
    assert supervisor._handle_dynamixel_torque_control({'action': 'torque_on', 'axes': [2]})[0] is True
    assert published == [
        ((1, 2), supervisor_node.DYNAMIXEL_TORQUE_DISABLE),
        ((2,), supervisor_node.DYNAMIXEL_TORQUE_ENABLE),
    ]
    assert {value for _axes, value in published} <= {0, 1}


def test_reboot_is_dynamixel_only_and_a_listed_feetech_is_refused():
    from motion_supervisor import supervisor_node

    supervisor, published = _supervisor(MIXED)
    success, message = supervisor._handle_dynamixel_torque_control({'action': 'reboot', 'axes': [2]})
    assert success is False and 'Feetech' in message and published == []
    # 목록 없이 · 다이나믹셀만 재부팅
    assert supervisor._handle_dynamixel_torque_control({'action': 'reboot'})[0] is True
    assert published == [((1,), supervisor_node.DYNAMIXEL_REBOOT)]


def test_torque_on_waits_while_serial_config_is_pending():
    motors = [dict(MIXED[2], config_pending=True, fault=True)]
    supervisor, published = _supervisor(motors)
    success, message = supervisor._handle_dynamixel_torque_control({'action': 'torque_on'})
    assert success is False and '설정 대기' in message and published == []
