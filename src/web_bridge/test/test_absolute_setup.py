"""MINAS 「앱솔루트 설정」 · 단계 진행 · 실패 중단 · 재투입 감지 · 되읽기 판정 · 수정 목록 62 ③④"""

import threading
from types import SimpleNamespace

import pytest

from motion_web_bridge.absolute_setup import AbsoluteSetup, ONE_TURN_COUNTS, plan_targets


class FakeDrive:
    def __init__(self, mode=1, eeprom=1, code=0, position=50_000_000):
        self.ram = mode
        self.eeprom = eeprom
        self.code = code
        self.position = position
        self.clear_flag = 0
        self.clear_pending = False

    def power_cycle(self):
        changed_to_absolute = self.ram != self.eeprom or (self.eeprom == 0 and self.code == 0 and self.position >= ONE_TURN_COUNTS)
        self.ram = self.eeprom
        if self.clear_pending:
            self.code = 0
            self.position = 12_345
            self.clear_pending = False
        elif self.eeprom == 0 and changed_to_absolute:
            self.code = 0xFF28          # 처음 앱솔루트로 바꾸면 Err40
        self.clear_flag = 0


class FakeEthercat:
    def __init__(self, drives, fail=None):
        self.drives = drives
        self.fail = fail or set()
        self.calls = []

    def __call__(self, command, **_kwargs):
        self.calls.append(' '.join(command[1:]))
        position = int(command[command.index('-p') + 1])
        drive = self.drives[position]
        kind, index = command[1], command[-3] if command[1] == 'download' else command[-2]
        if (kind, index) in self.fail:
            return SimpleNamespace(returncode=1, stdout='', stderr='SDO aborted')
        if kind == 'download':
            value = int(command[-1], 0)
            if index == '0x3015':
                drive.ram = value
            elif index == '0x1010':
                drive.eeprom = drive.ram
            elif index == '0x4D00':
                drive.clear_flag = value
                if value & 0x200:
                    drive.clear_pending = True
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        value = {
            '0x3015': drive.ram, '0x603F': drive.code, '0x6064': drive.position, '0x4D00': drive.clear_flag,
        }[index]
        return SimpleNamespace(returncode=0, stdout=f'0x{value & 0xFFFFFFFF:08x} {value}\n', stderr='')


def _minas(*drives):
    return {'state': 'blocked', 'drives': list(drives), 'message': 'x'}


def _drive(position, status, axis=None, mode=1):
    return {'master_index': 0, 'slave_position': position, 'axis': axis, 'absolute_mode': mode, 'status': status}


class PowerSwitch:
    """`visible_slaves` · 재투입 요청이 오면 빠졌다(빈 목록) 돌아오며 드라이브에 재투입을 먹인다"""

    def __init__(self, ethercat, positions):
        self.ethercat = ethercat
        self.positions = positions
        self.off_next = False
        self.cycles = 0

    def __call__(self):
        if self.off_next:
            self.off_next = False
            for position in self.positions:
                self.ethercat.drives[position].power_cycle()
            self.cycles += 1
            return []
        self.off_next = True
        return [{'master_index': 0, 'slave_position': position} for position in self.positions]


def _setup(ethercat, minas, *, servo=None, records=None, switch=None):
    motors = servo if servo is not None else {}
    service_calls = []
    clock = [0.0]

    def sleep(seconds):
        clock[0] += seconds

    def servo_off(axis):
        motors[axis] = False
        return {'success': True}

    records = records if records is not None else []
    setup = AbsoluteSetup(
        runner=ethercat,
        minas_absolute_state=lambda: minas,
        visible_slaves=switch or (lambda: []),
        current_motor=lambda axis: {'servo_on': motors.get(axis, False)},
        servo_off=servo_off,
        safety_blocker=lambda: '',
        lifecycle_lock=threading.Lock(),
        motor_service=lambda: 'motion-motor.service',
        service_active=lambda _service: True,
        run_service=lambda action, _service: service_calls.append(action),
        wait_release=lambda: None,
        wait_recovery=lambda _service, _axes: {'service_active': True},
        expected_axes=lambda: [0],
        record=records.append,
        clock=lambda: clock[0],
        sleep=sleep,
        spawn=lambda target: target(),
    )
    return setup, service_calls, records


def test_plan_skips_normal_drives_and_refuses_when_all_are_normal():
    minas = _minas(_drive(0, 'ok', 0, 0), _drive(1, 'not_absolute', 1), _drive(3, 'unknown', None, None))
    targets, skipped, reason = plan_targets(minas, scope='all')
    assert reason == '' and [d['slave_position'] for d in targets] == [1, 3]
    assert [d['slave_position'] for d in skipped] == [0]

    targets, skipped, reason = plan_targets(minas, scope='one', master=0, position=0)
    assert targets == [] and '정상' in reason          # 다시 클리어하면 기준점이 사라진다
    assert '확인 중' in plan_targets({'state': 'checking'}, scope='all')[2]


def test_full_run_goes_through_every_step_with_two_power_cycles():
    drives = {0: FakeDrive(), 1: FakeDrive()}
    ethercat = FakeEthercat(drives)
    switch = PowerSwitch(ethercat, [0, 1])
    servo = {0: True}
    setup, service_calls, records = _setup(
        ethercat, _minas(_drive(0, 'not_absolute', 0), _drive(1, 'not_absolute', None)),
        servo=servo, switch=switch,
    )

    started = setup.start({'scope': 'all', 'confirmed': True})

    status = setup.status()
    assert started['success'] is True
    assert status['state'] == 'done', status['message']
    assert '기준점을 다시 캡처' in status['message']
    assert switch.cycles == 2
    assert servo[0] is False                                     # 등록 축 서보 OFF
    assert service_calls == ['stop', 'start', 'stop', 'start']   # 쓰기 두 번 · 늘 다시 띄움
    for drive in drives.values():
        assert drive.ram == 0 and drive.eeprom == 0 and drive.code == 0 and drive.position < ONE_TURN_COUNTS
    assert any('upload -m 0 -p 1 -t uint32 0x4D00 1' in call for call in ethercat.calls)
    assert records[-1]['event_type'] == 'minas_absolute_setup_done'


def test_a_failed_write_stops_there_and_still_restarts_motor_manager():
    drives = {0: FakeDrive()}
    ethercat = FakeEthercat(drives, fail={('download', '0x1010')})
    setup, service_calls, records = _setup(ethercat, _minas(_drive(0, 'not_absolute', None)))

    setup.start({'scope': 'all', 'confirmed': True})

    status = setup.status()
    assert status['state'] == 'failed' and status['step'] == 'write_mode'
    assert 'SDO aborted' in status['error']
    assert service_calls == ['stop', 'start']
    assert records[-1]['event_type'] == 'minas_absolute_setup_failed'


def test_eeprom_value_wrong_after_power_cycle_fails_at_check_mode():
    drives = {0: FakeDrive()}
    ethercat = FakeEthercat(drives)

    class NoSave(FakeEthercat):
        def __call__(self, command, **kwargs):
            if '0x1010' in command:
                self.calls.append(' '.join(command[1:]))
                return SimpleNamespace(returncode=0, stdout='', stderr='')   # 저장한 척만
            return super().__call__(command, **kwargs)

    ethercat = NoSave(drives)
    setup, _calls, _records = _setup(
        ethercat, _minas(_drive(0, 'not_absolute', None)), switch=PowerSwitch(ethercat, [0]),
    )
    setup.start({'scope': 'all', 'confirmed': True})
    status = setup.status()
    assert status['state'] == 'failed' and status['step'] == 'check_mode'
    assert 'EEPROM' in status['error']


def test_verify_fails_when_position_is_still_beyond_one_turn():
    drives = {0: FakeDrive()}
    ethercat = FakeEthercat(drives, fail=set())

    class ClearIgnored(FakeEthercat):
        def __call__(self, command, **kwargs):
            result = super().__call__(command, **kwargs)
            self.drives[0].clear_pending = False            # 클리어가 먹지 않은 드라이브
            return result

    ethercat = ClearIgnored(drives)
    setup, _calls, _records = _setup(
        ethercat, _minas(_drive(0, 'not_absolute', None)), switch=PowerSwitch(ethercat, [0]),
    )
    setup.start({'scope': 'all', 'confirmed': True})
    status = setup.status()
    assert status['state'] == 'failed' and status['step'] == 'verify'
    assert '오류 0xFF28' in status['error'] or '한 바퀴' in status['error']


def test_needs_confirmation_and_only_one_at_a_time():
    ethercat = FakeEthercat({0: FakeDrive()})
    setup, _calls, _records = _setup(ethercat, _minas(_drive(0, 'not_absolute', None)))
    assert setup.start({'scope': 'all'})['success'] is False
    setup._job = {'state': 'running'}
    refused = setup.start({'scope': 'all', 'confirmed': True})
    assert refused['success'] is False and '이미 진행 중' in refused['message']
    assert '진행 중' in setup.blocker()


def test_waiting_for_power_cycle_can_be_cancelled():
    ethercat = FakeEthercat({0: FakeDrive()})
    setup, service_calls, _records = _setup(
        ethercat, _minas(_drive(0, 'not_absolute', None)),
        switch=lambda: [{'master_index': 0, 'slave_position': 0}],   # 아무도 전원을 안 끈다
    )
    original_sleep = setup._sleep

    def sleep_and_cancel(seconds):
        original_sleep(seconds)
        if setup.status().get('step') == 'power_cycle_1':
            setup._cancel.set()

    setup._sleep = sleep_and_cancel
    setup.start({'scope': 'all', 'confirmed': True})
    status = setup.status()
    assert status['state'] == 'failed' and '취소' in status['error']
    assert service_calls == ['stop', 'start']


def test_preview_lists_targets_and_skipped():
    setup, _calls, _records = _setup(
        FakeEthercat({}), _minas(_drive(0, 'ok', 0, 0), _drive(1, 'multiturn_invalid', 1, 0)),
    )
    preview = setup.preview({'scope': 'all'})
    assert preview['success'] is True
    assert [item['label'] for item in preview['targets']] == ['1번 모터']
    assert [item['label'] for item in preview['skipped']] == ['0번 모터']
    assert len(preview['steps']) == 7


def test_while_running_the_bridge_blocks_motion_and_other_drive_work():
    import time as _time

    from motion_web_bridge.bridge_node import MotionWebBridge
    from motion_web_bridge.motor_runtime_service import MotorRuntimeService

    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge._lock = threading.Lock()
    bridge._motion_state_received_at = _time.time()
    bridge._motion_state = {
        'motors': [{'controller_index': 0, 'connection_state': 'online', 'connection_connected': True, 'fault': False}],
        'minas_absolute': {'state': 'ok'},
    }
    setup, _calls, _records = _setup(FakeEthercat({}), _minas())
    bridge.absolute_setup = setup
    assert bridge.motor_runtime_control_blocker() == ''

    setup._job = {'state': 'running'}
    assert '앱솔루트 설정 진행 중' in bridge.motor_runtime_control_blocker()

    runtime = MotorRuntimeService.__new__(MotorRuntimeService)
    runtime.bridge = bridge
    runtime.project = SimpleNamespace(change_blocker=lambda **_kwargs: '')
    assert '앱솔루트 설정 진행 중' in runtime.ethercat_scan_safety_blocker()
