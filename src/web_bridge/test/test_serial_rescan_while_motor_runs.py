"""직렬 서보만 쓰는 PC · 모터 프로그램이 도는 중에 재검색이 거절되던 것 · 수정 목록 160

chicken2(라즈베리파이 5 · 다이나믹셀 3 + Feetech 1 · EtherCAT 없음) 실물 2026-10-29

    POST /api/motors/scan/dynamixel   (motion-motor.service 실행 중)
    → AC 서보 검색을 하지 않았습니다: 모터 상태에서 AC 서보 모터를 찾을 수 없습니다

매니저를 먼저 멈추면 됐다 · 원인 · 매니저가 도는 중이면 안전 검사가 「상태에 **EtherCAT**
축이 보여야 한다」 를 직렬 검색에도 걸었다 · 이제 직렬 검색은 **모든 축**을 본다
(매니저를 멈추면 직렬 축도 멈추므로 움직이는 축이 있으면 그대로 거절).
"""

import threading
import time

import pytest

from motion_web_bridge import motor_config_rules
from motion_web_bridge.motor_runtime_service import MotorRuntimeService
from motion_web_bridge.scan_orchestrator import ScanOrchestrator


def _serial_motor(axis, velocity_deg_s=0.0, transport='serial'):
    return {
        'controller_index': axis,
        'transport': transport,
        'connection_state': 'online',
        'connection_connected': True,
        'fault': False,
        'velocity_deg_s': velocity_deg_s,
    }


class _Bridge:
    def __init__(self, motors, *, received_at=None):
        self.motors = motors
        self.received_at = time.time() if received_at is None else received_at
        self.absolute_setup = None

    def motion_state_with_time(self):
        return {'motors': self.motors}, self.received_at

    def current_project_generation(self):
        return 3

    def snapshot(self):
        return {}


class _Project:
    @staticmethod
    def change_blocker(**_kwargs):
        return ''


def _runtime(motors):
    service = MotorRuntimeService.__new__(MotorRuntimeService)
    service.bridge = _Bridge(motors)
    service.project = _Project()
    service._recovery_lock = threading.Lock()
    return service


CHICKEN2 = [_serial_motor(0), _serial_motor(1), _serial_motor(2), _serial_motor(3)]


# --------------------------------------------------------------------------- #
# 안전 검사 · 기본값은 전과 같고 · 직렬 검색만 모든 축을 본다
# --------------------------------------------------------------------------- #

def test_the_default_still_wants_an_ethercat_axis():
    """AC 서보 검색 · 정비 · 앱솔루트 설정 쪽은 전과 같다."""
    blocker = _runtime(CHICKEN2).ethercat_scan_safety_blocker(require_fresh_motor_state=True)

    assert blocker == '모터 상태에서 AC 서보 모터를 찾을 수 없습니다'


def test_a_serial_scan_is_fine_with_serial_axes_only():
    """**이것이 그 버그다** · 직렬 축만 있어도 살아 있는 상태면 된다."""
    blocker = _runtime(CHICKEN2).ethercat_scan_safety_blocker(
        require_fresh_motor_state=True, all_transports=True,
    )

    assert blocker == ''


def test_a_moving_serial_axis_still_blocks_the_serial_scan():
    motors = [_serial_motor(0), _serial_motor(2, velocity_deg_s=40.0)]

    blocker = _runtime(motors).ethercat_scan_safety_blocker(
        require_fresh_motor_state=True, all_transports=True,
    )

    assert '2번 모터가 움직이는 중' in blocker
    assert 'AC 서보' not in blocker


def test_a_moving_ac_axis_also_blocks_the_serial_scan():
    """매니저 하나가 둘 다 몬다 · 직렬 검색으로 멈춰도 AC 축이 같이 멈춘다."""
    motors = [_serial_motor(0), _serial_motor(5, velocity_deg_s=-30.0, transport='ethercat')]

    blocker = _runtime(motors).ethercat_scan_safety_blocker(
        require_fresh_motor_state=True, all_transports=True,
    )

    assert '5번 모터가 움직이는 중' in blocker


def test_an_empty_motor_state_is_still_refused_for_the_serial_scan():
    blocker = _runtime([]).ethercat_scan_safety_blocker(
        require_fresh_motor_state=True, all_transports=True,
    )

    assert blocker == '모터 상태에서 모터를 찾을 수 없습니다'


def test_a_stale_motor_state_is_still_refused_for_the_serial_scan():
    service = _runtime(CHICKEN2)
    service.bridge.received_at = time.time() - 5.0

    blocker = service.ethercat_scan_safety_blocker(
        require_fresh_motor_state=True, all_transports=True,
    )

    assert '정지 여부를 확인할 수 없습니다' in blocker


def test_the_ac_default_ignores_serial_motion():
    """기본값은 EtherCAT 축만 · AC 쪽 판정은 바뀌지 않는다."""
    motors = [_serial_motor(0, velocity_deg_s=90.0), _serial_motor(1, transport='ethercat')]

    assert _runtime(motors).ethercat_scan_safety_blocker() == ''


# --------------------------------------------------------------------------- #
# 검색 순서 · 직렬 서보만 쓰는 PC 에서 매니저를 멈췄다 다시 켠다
# --------------------------------------------------------------------------- #

class _Operations:
    def update_motor_operation(self, *_args, **_kwargs):
        return {}


class _Repository:
    runtime = _Operations()

    @staticmethod
    def selected_project_id():
        return 'chicken'


def _orchestrator(monkeypatch, motors, *, ethercat_axes=()):
    runtime = _runtime(motors)
    calls = []
    runtime.managed_service_active = lambda _service: True
    runtime.run_managed_service = lambda action, service: calls.append((action, service))
    runtime.wait_for_runtime_recovery = lambda axes, **_kwargs: {
        'required': True, 'expected_axes': list(axes), 'online_axes': list(axes),
        'missing_axes': [], 'recovered': True, 'service_active': True,
    }

    orchestrator = ScanOrchestrator.__new__(ScanOrchestrator)
    orchestrator.bridge = runtime.bridge
    orchestrator.runtime = runtime
    orchestrator.repository = _Repository()
    orchestrator._runtime_handoff = lambda: {'required': False}
    orchestrator._expected_runtime_axes = lambda: [0, 1, 2, 3]
    orchestrator._expected_runtime_ethercat_axes = lambda: list(ethercat_axes)
    orchestrator._call_service_locked = lambda *_args: (
        calls.append(('scan',)) or {'success': True, 'message': '직렬 서보 검색 완료', 'scan': {}}
    )

    def no_ethercat(timeout_sec):
        calls.append(('released', timeout_sec))
        raise RuntimeError('Motor Manager 정지 후에도 EtherCAT Master 또는 Slave 운전 상태가 해제되지 않았습니다')

    monkeypatch.setattr(motor_config_rules, 'wait_for_ethercat_release', no_ethercat)
    monkeypatch.setenv('MOTION_MOTOR_SERVICE_UNIT', 'motion-motor.service')
    return orchestrator, calls


def test_serial_scan_runs_while_the_motor_service_is_up(monkeypatch):
    orchestrator, calls = _orchestrator(monkeypatch, CHICKEN2)

    result = orchestrator._call_ethercat_service_locked(
        object(), '/motor/scan_dynamixel', 10.0, operation_type='dynamixel_scan',
    )

    assert result['success'] is True, result.get('message')
    assert result['motor_service_restored'] is True
    # EtherCAT 이 없는 PC · `ethercat master` 를 기다리지 않는다
    assert calls == [
        ('stop', 'motion-motor.service'),
        ('scan',),
        ('start', 'motion-motor.service'),
    ]


def test_serial_scan_on_a_mixed_pc_still_waits_for_ethercat(monkeypatch):
    """AC 와 섞어 쓰는 PC 는 전처럼 EtherCAT 을 놓았는지 본다."""
    orchestrator, calls = _orchestrator(
        monkeypatch, CHICKEN2 + [_serial_motor(4, transport='ethercat')], ethercat_axes=[4],
    )
    monkeypatch.setattr(
        motor_config_rules, 'wait_for_ethercat_release',
        lambda timeout_sec: calls.append(('released', timeout_sec)),
    )

    result = orchestrator._call_ethercat_service_locked(
        object(), '/motor/scan_dynamixel', 10.0, operation_type='dynamixel_scan',
    )

    assert result['success'] is True
    assert calls[:3] == [('stop', 'motion-motor.service'), ('released', 5.0), ('scan',)]


def test_serial_scan_is_refused_in_serial_words_while_an_axis_moves(monkeypatch):
    orchestrator, calls = _orchestrator(
        monkeypatch, [_serial_motor(0), _serial_motor(1, velocity_deg_s=25.0)],
    )

    result = orchestrator._call_ethercat_service_locked(
        object(), '/motor/scan_dynamixel', 10.0, operation_type='dynamixel_scan',
    )

    assert result['success'] is False
    assert result['scan_blocked'] is True
    assert result['message'].startswith('직렬 서보 검색을 하지 않았습니다: ')
    assert '1번 모터가 움직이는 중' in result['message']
    assert calls == [], '움직이는 중에는 매니저를 멈추지 않는다'


@pytest.mark.parametrize('operation_type', ['ac_servo_scan', 'full_scan'])
def test_ac_scans_on_a_serial_only_pc_are_refused_as_before(monkeypatch, operation_type):
    """AC 서보 검색 · 전체 검색의 판정과 문구는 그대로."""
    orchestrator, calls = _orchestrator(monkeypatch, CHICKEN2)

    result = orchestrator._call_ethercat_service_locked(
        object(), '/motor/scan_ac_servo', 10.0, operation_type=operation_type,
    )

    assert result['success'] is False
    assert result['message'] == (
        'AC 서보 검색을 하지 않았습니다: 모터 상태에서 AC 서보 모터를 찾을 수 없습니다'
    )
    assert calls == []
