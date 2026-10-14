"""MINAS 「앱솔루트 설정」 · 단계 진행 · 실패 중단 · 재투입 감지 · 되읽기 판정 · 수정 목록 62 ③④ ·
재투입 뒤 조용한 시간 · 읽기 다시 · 이어서 하기 · 수정 목록 134"""

import json
import threading
from types import SimpleNamespace

import pytest

from motion_web_bridge.absolute_setup import (
    NO_RESUME_MESSAGE,
    ONE_TURN_COUNTS,
    READ_RETRY_WINDOW_SEC,
    RECONFIGURE_WAIT_SEC,
    RESUME_EXPIRE_SEC,
    SETTLE_AFTER_RETURN_SEC,
    AbsoluteSetup,
    plan_targets,
)


class FakeDrive:
    def __init__(self, mode=1, eeprom=1, code=0, position=50_000_000, err40=True):
        #: 처음 앱솔루트로 바꾸면 Err40 이 뜨는 드라이브인가 · 실물 floating4(배터리 정상)는 안 뜸 · 140
        self.err40 = err40
        self.ram = mode
        self.eeprom = eeprom
        self.code = code
        self.position = position
        self.clear_flag = 0
        self.clear_pending = False
        self.cycles = 0

    def power_cycle(self):
        self.cycles += 1
        changed_to_absolute = self.ram != self.eeprom or (self.eeprom == 0 and self.code == 0 and self.position >= ONE_TURN_COUNTS)
        self.ram = self.eeprom
        if self.clear_pending:
            self.code = 0
            self.position = 12_345
            self.clear_pending = False
        elif self.eeprom == 0 and changed_to_absolute and self.err40:
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
    """`visible_slaves` · 작업이 재투입 단계(3/7 · 6/7)에 들어서면 한 번 빠졌다(빈 목록) 돌아오며 드라이브에 재투입을 먹인다

    다른 때(시리얼 기억 · 조용한 시간 보기)는 늘 보인다 · 시리얼 = 1000 + 위치(`serials` 로 바꿈)
    """

    def __init__(self, ethercat, positions):
        self.ethercat = ethercat
        self.positions = positions
        self.cycles = 0
        self.setup = None
        self.serials = {position: 1000 + position for position in positions}
        self._handled = set()
        self._job_started = None

    def __call__(self):
        status = self.setup.status() if self.setup else {}
        if status.get('state') == 'running':
            if status.get('started_at') != self._job_started:
                self._job_started, self._handled = status.get('started_at'), set()
            step = status.get('step')
            if step in ('power_cycle_1', 'power_cycle_2') and step not in self._handled:
                self._handled.add(step)
                for position in self.positions:
                    self.ethercat.drives[position].power_cycle()
                self.cycles += 1
                return []
        return [
            {'master_index': 0, 'slave_position': position, 'device_state': 'OP', 'serial_number': self.serials[position]}
            for position in self.positions
        ]


class ClearMarker:
    """PC 단위 다회전 클리어 표시(가짜) · 적은 드라이브 · 기준점 다시 지정을 기다리는 축 · 140 ③"""

    def __init__(self):
        self.records = []
        self.pending = set()

    def record(self, drives):
        for drive in drives:
            self.records.append(dict(drive))
            if drive.get('axis') is not None:
                self.pending.add(int(drive['axis']))

    def axes(self):
        return sorted(self.pending)


class Bus:
    """버스 「혼자 씀」 표시(가짜) · 세움 · 늘림 · 내림 · 139 E-1"""

    def __init__(self):
        self.calls = []

    def hold(self, purpose, **kwargs):
        self.calls.append(('hold', purpose, kwargs.get('wait_for_running', True)))

    def release(self):
        self.calls.append(('release',))

    @property
    def held(self):
        state = False
        for call in self.calls:
            state = call[0] == 'hold'
        return state


def _setup(ethercat, minas, *, servo=None, records=None, switch=None, resume_file=None, wall=None, configuring=None,
           marker=None, bus=None):
    motors = servo if servo is not None else {}
    service_calls = []
    clock = [0.0]
    marker = marker if marker is not None else ClearMarker()
    bus = bus if bus is not None else Bus()

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
        bus_configuring=configuring or (lambda: False),
        resume_file=resume_file,
        wall_clock=wall or (lambda: 1_000_000.0),
        record_clear=marker.record,
        pending_axes=marker.axes,
        hold_bus=bus.hold,
        release_bus=bus.release,
    )
    if isinstance(switch, PowerSwitch):
        switch.setup = setup
    setup.test_clock = clock
    setup.test_marker = marker
    setup.test_bus = bus
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
    # 처음 앱솔루트로 바꾼 드라이브가 Err40 → 클리어 → 「기준점 다시 지정 대기」 · 140
    assert status['state'] == 'reference_pending', status['message']
    assert status['message'] == '다회전 클리어한 0번 모터 · 몸을 정면·수평에 맞추고 기준점을 다시 지정해 저장하세요'
    assert status['reference_pending_axes'] == [0] and status['cleared_axes'] == [0]
    assert [r['slave_position'] for r in setup.test_marker.records] == [0, 1]      # 미등록(축 없음)도 넘긴다
    assert setup.test_marker.records[0]['serial'] == 1000
    assert switch.cycles == 2
    assert servo[0] is False                                     # 등록 축 서보 끄기
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


def test_returned_drives_are_read_only_after_the_master_brings_them_to_op():
    """수정 목록 125 · 재투입으로 돌아온 드라이브를 모터 프로그램이 다시 설정하는 동안(PREOP · SAFEOP)은 SDO 를 안 보낸다"""
    states = iter(['PREOP', 'SAFEOP', 'OP'])
    seen = []

    def slaves():
        state = next(states, 'OP')
        seen.append(state)
        return [{'master_index': 0, 'slave_position': 1, 'device_state': state}]

    setup, _calls, _records = _setup(FakeEthercat({1: FakeDrive()}), _minas(_drive(1, 'not_absolute', 1)))
    setup._visible_slaves = slaves
    setup._wait_reconfigured({(0, 1)}, slaves())
    assert seen == ['PREOP', 'SAFEOP', 'OP']

    # 모터 프로그램이 없으면 기다리지 않는다(PREOP 그대로가 정상)
    setup._service_active = lambda _service: False
    seen.clear()
    setup._wait_reconfigured({(0, 1)}, [{'master_index': 0, 'slave_position': 1, 'device_state': 'PREOP'}])
    assert seen == []


# -- 수정 목록 134 · 재투입 뒤 조용한 시간 · 읽기 다시 · 이어서 하기 ---------------------- #

class Flaky(FakeEthercat):
    """첫 재투입 뒤 0x3015 읽기가 `failures` 번 Input/output error · 마스터가 SDO 사전을 읽는 동안(실물 S-4)"""

    def __init__(self, drives, failures):
        super().__init__(drives)
        self.failures = failures
        self.reads_after_cycle = 0

    def __call__(self, command, **kwargs):
        position = int(command[command.index('-p') + 1])
        if command[1] == 'upload' and '0x3015' in command and self.drives[position].cycles == 1:
            self.reads_after_cycle += 1
            if self.failures > 0:
                self.failures -= 1
                self.calls.append(' '.join(command[1:]))
                return SimpleNamespace(returncode=1, stdout='', stderr='Failed to upload SDO: Input/output error')
        return super().__call__(command, **kwargs)


def _absolute(minas, *positions):
    """재투입 뒤 상태 모니터가 다시 읽은 모습 · 그 드라이브는 이제 「정상」"""
    for drive in minas['drives']:
        if drive['slave_position'] in positions:
            drive.update(status='ok', absolute_mode=0)


def test_check_mode_retries_a_read_failure_then_goes_on():
    drives = {0: FakeDrive()}
    ethercat = Flaky(drives, failures=3)
    switch = PowerSwitch(ethercat, [0])
    setup, _calls, _records = _setup(ethercat, _minas(_drive(0, 'not_absolute', 0)), servo={0: True}, switch=switch)

    setup.start({'scope': 'all', 'confirmed': True})

    status = setup.status()
    assert status['state'] == 'reference_pending', status['message']      # Err40 → 클리어함 · 140
    assert ethercat.reads_after_cycle >= 4                      # 3 번 실패 뒤 4 번째에 읽음
    assert switch.cycles == 2
    assert status['resume'] is None


def test_read_failure_for_longer_than_the_window_fails_at_check_mode_and_leaves_resume():
    drives = {0: FakeDrive(), 1: FakeDrive()}
    ethercat = Flaky(drives, failures=10_000)
    setup, _calls, records = _setup(
        ethercat, _minas(_drive(0, 'not_absolute', 0), _drive(1, 'not_absolute', 1)),
        switch=PowerSwitch(ethercat, [0, 1]),
    )

    setup.start({'scope': 'all', 'confirmed': True})

    status = setup.status()
    assert status['state'] == 'failed' and status['step'] == 'check_mode'
    assert 'Input/output error' in status['error'] and '번 시도' in status['error']
    # 1 s 간격 · 10 s 까지 · 그 드라이브에서 멈춤
    assert ethercat.reads_after_cycle == pytest.approx(READ_RETRY_WINDOW_SEC + 1, abs=1)
    assert status['resume']['from_step'] == 'check_mode' and status['resume']['from_index'] == 4
    assert [t['slave_position'] for t in status['resume']['targets']] == [0, 1]
    assert records[-1]['resume_from'] == 'check_mode'


def test_a_wrong_value_is_not_retried_and_leaves_no_resume():
    """EEPROM 에 0 이 없다(값이 틀림) · 다시 읽어도 같다 · 이어서 하기도 안 남김(상태 모니터가 앱솔루트 아님으로 봄)"""
    drives = {0: FakeDrive()}

    class NoSave(FakeEthercat):
        def __call__(self, command, **kwargs):
            if '0x1010' in command:
                self.calls.append(' '.join(command[1:]))
                return SimpleNamespace(returncode=0, stdout='', stderr='')
            return super().__call__(command, **kwargs)

    ethercat = NoSave(drives)
    setup, _calls, _records = _setup(ethercat, _minas(_drive(0, 'not_absolute', None)), switch=PowerSwitch(ethercat, [0]))
    setup.start({'scope': 'all', 'confirmed': True})

    status = setup.status()
    assert status['state'] == 'failed' and status['step'] == 'check_mode'
    after_save = ethercat.calls[ethercat.calls.index('download -m 0 -p 0 -t uint32 0x1010 1 0x65766173') + 1:]
    assert after_save == ['upload -m 0 -p 0 -t int16 0x3015 0']   # 한 번만
    assert status['resume'] is None


def test_a_write_is_not_retried_unless_it_was_refused_unsent():
    drives = {0: FakeDrive()}
    ethercat = FakeEthercat(drives, fail={('download', '0x1010')})
    setup, _calls, _records = _setup(ethercat, _minas(_drive(0, 'not_absolute', None)))
    setup.start({'scope': 'all', 'confirmed': True})
    assert sum('0x1010' in call for call in ethercat.calls) == 1

    class RefusedOnce(FakeEthercat):
        refused = 1

        def __call__(self, command, **kwargs):
            if '0x1010' in command and self.refused:
                self.refused -= 1
                return SimpleNamespace(returncode=75, stdout='', stderr='버스 설정 중')   # 보내지 않음
            return super().__call__(command, **kwargs)

    ethercat = RefusedOnce({0: FakeDrive()})
    setup, _calls, _records = _setup(ethercat, _minas(_drive(0, 'not_absolute', None)), switch=PowerSwitch(ethercat, [0]))
    setup.start({'scope': 'all', 'confirmed': True})
    assert setup.status()['state'] == 'done', setup.status()['message']


def test_settle_waits_for_the_marker_to_clear_and_states_to_hold():
    """돌아온 뒤 · 「버스 설정 중」 표시가 꺼지고 대상 상태가 그대로 SETTLE_AFTER_RETURN_SEC 이어야 읽는다"""
    setup, _calls, _records = _setup(FakeEthercat({}), _minas())
    clock = setup.test_clock

    def slaves():
        state = 'SAFEOP' if clock[0] < 8.0 else 'OP'            # 8 s 에 OP
        return [{'master_index': 0, 'slave_position': 1, 'device_state': state}]

    setup._bus_configuring = lambda: clock[0] < 5.0             # 5 s 동안 표시
    setup._visible_slaves = slaves
    setup._settle({(0, 1)})
    assert 8.0 + SETTLE_AFTER_RETURN_SEC <= clock[0] < 8.0 + SETTLE_AFTER_RETURN_SEC + 2.0   # 마지막 바뀐 때부터 다시 셈

    # 표시가 안 꺼지면 길어도 RECONFIGURE_WAIT_SEC 뒤 넘어간다(읽기는 다시 읽기로 버틴다)
    clock[0] = 0.0
    setup._bus_configuring = lambda: True
    setup._settle({(0, 1)})
    assert RECONFIGURE_WAIT_SEC <= clock[0] < RECONFIGURE_WAIT_SEC + 2.0


def test_first_read_after_a_power_cycle_waits_for_the_marker_and_the_quiet_time():
    """재투입 뒤 첫 SDO 는 표시 꺼짐 + 조용한 시간 뒤 · 125 · 134"""
    drives = {0: FakeDrive()}
    first_read_at = []
    marker_until = [None]
    holder = {}

    class Clocked(FakeEthercat):
        def __call__(self, command, **kwargs):
            if command[1] == 'upload' and drives[0].cycles == 1 and not first_read_at:
                first_read_at.append(holder['setup'].test_clock[0])
            return super().__call__(command, **kwargs)

    def configuring():
        now = holder['setup'].test_clock[0]
        if drives[0].cycles == 1 and marker_until[0] is None:
            marker_until[0] = now + 4.0                          # 재투입 뒤 4 s 동안 모터 프로그램이 설정
        return marker_until[0] is not None and now < marker_until[0]

    ethercat = Clocked(drives)
    setup, _calls, _records = _setup(
        ethercat, _minas(_drive(0, 'not_absolute', None)), switch=PowerSwitch(ethercat, [0]), configuring=configuring,
    )
    holder['setup'] = setup
    setup.start({'scope': 'all', 'confirmed': True})
    assert setup.status()['state'] == 'done', setup.status()['message']
    assert first_read_at[0] >= marker_until[0] + SETTLE_AFTER_RETURN_SEC


def _failed_at_check_mode(tmp_path=None, wall=None):
    drives = {0: FakeDrive(), 1: FakeDrive()}
    ethercat = Flaky(drives, failures=10_000)
    switch = PowerSwitch(ethercat, [0, 1])
    minas = _minas(_drive(0, 'not_absolute', 0), _drive(1, 'not_absolute', 1))
    servo = {0: True, 1: True}
    setup, _service_calls, records = _setup(
        ethercat, minas, servo=servo, switch=switch,
        resume_file=(tmp_path / 'runtime' / 'absolute_setup_resume.json') if tmp_path else None, wall=wall,
    )
    setup.start({'scope': 'all', 'confirmed': True})
    assert setup.status()['step'] == 'check_mode'
    _absolute(minas, 0, 1)            # 실물 · Pr0.15 = 0 · 오류 없음 → 「정상」 으로 보임
    ethercat.failures = 0
    return setup, ethercat, switch, minas, servo, records


def test_resume_continues_from_check_mode_for_the_same_drives():
    setup, ethercat, switch, _minas_state, servo, records = _failed_at_check_mode()
    assert '이미 앱솔루트' in setup.start({'scope': 'all', 'confirmed': True})['message']   # 예전 · 막힘

    preview = setup.preview({'resume': True})
    assert preview['success'] is True and preview['from_index'] == 4 and preview['failed_index'] == 4
    assert preview['steps'] == ['앱솔루트 방식 확인', '다회전 클리어', '드라이브 전원 껐다 켜기 2', '최종 확인']
    assert [t['label'] for t in preview['targets']] == ['0번 모터', '1번 모터']
    assert preview['clear_done'] is False
    assert setup.start({'resume': True})['success'] is False                               # 확인 필요

    servo.update({0: True, 1: True})
    calls_before = len(ethercat.calls)
    started = setup.start({'resume': True, 'confirmed': True})

    status = setup.status()
    assert started['success'] is True and '4/7' in started['message']
    assert status['state'] == 'reference_pending', status['message']     # 4/7 에서 Err40 다시 판정 → 클리어 · 140 ⑤
    assert status['reference_pending_axes'] == [0, 1]
    resumed_calls = ethercat.calls[calls_before:]
    assert not any(call.startswith('download') and '0x3015' in call for call in resumed_calls)   # 1/7 · 2/7 안 함
    assert any(call.startswith('download') and '0x4D00' in call for call in resumed_calls)       # 클리어 함
    assert switch.cycles == 2                                    # 재투입 2 만 더
    for drive in ethercat.drives.values():
        assert drive.code == 0 and drive.position < ONE_TURN_COUNTS
    assert servo == {0: False, 1: False}
    assert status['resume'] is None and records[-1]['resumed'] is True
    assert setup.preview({'resume': True})['message'] == NO_RESUME_MESSAGE


def test_resume_is_refused_without_a_record_for_other_drives_and_for_swapped_drives():
    setup, _calls, _records = _setup(FakeEthercat({}), _minas(_drive(0, 'ok', 0, 0)), switch=lambda: [])
    refused = setup.start({'resume': True, 'confirmed': True})
    assert refused['success'] is False and NO_RESUME_MESSAGE in refused['message']

    setup, _ethercat, switch, _minas_state, _servo, _records = _failed_at_check_mode()
    other = setup.preview({'resume': True, 'scope': 'one', 'master_index': 0, 'slave_position': 5})
    assert other['success'] is False and '이어서 할 작업의 드라이브가 아닙니다' in other['message']
    # 한 대만 고르면 · 그 작업이 두 대라 거절(함께 진행)
    assert setup.preview({'resume': True, 'scope': 'one', 'master_index': 0, 'slave_position': 0})['success'] is False

    switch.serials[1] = 4242                                     # 드라이브를 바꿔 끼움
    swapped = setup.start({'resume': True, 'confirmed': True})
    assert swapped['success'] is False and '시리얼' in swapped['message']
    assert setup.status()['resume'] is None                      # 지움


def test_resume_after_the_clear_starts_at_power_cycle_2_without_clearing_again():
    drives = {0: FakeDrive()}
    ethercat = FakeEthercat(drives)
    switch = PowerSwitch(ethercat, [0])
    minas = _minas(_drive(0, 'not_absolute', 0))
    setup, _calls, _records = _setup(ethercat, minas, switch=switch)
    original_sleep = setup._sleep

    def no_second_cycle():
        # 재투입 2 를 기다리는 동안 아무도 전원을 안 끈다 → 취소
        if setup.status().get('step') == 'power_cycle_2':
            return [{'master_index': 0, 'slave_position': 0, 'device_state': 'OP', 'serial_number': 1000}]
        return switch()

    def sleep_and_cancel(seconds):
        original_sleep(seconds)
        if setup.status().get('step') == 'power_cycle_2':
            setup._cancel.set()

    setup._visible_slaves = no_second_cycle
    setup._sleep = sleep_and_cancel
    setup.start({'scope': 'all', 'confirmed': True})
    status = setup.status()
    assert status['state'] == 'failed' and status['step'] == 'power_cycle_2'
    assert status['resume']['from_index'] == 6

    setup._visible_slaves = switch
    setup._sleep = original_sleep
    _absolute(minas, 0)
    calls_before = len(ethercat.calls)
    preview = setup.preview({'resume': True})
    assert preview['clear_done'] is True and preview['steps'] == ['드라이브 전원 껐다 켜기 2', '최종 확인']
    assert setup.start({'resume': True, 'confirmed': True})['success'] is True
    assert setup.status()['state'] == 'reference_pending', setup.status()['message']
    assert not any(call.startswith('download') and '0x4D00' in call for call in ethercat.calls[calls_before:])
    assert any('0x6064' in call for call in ethercat.calls[calls_before:])     # 클리어한 드라이브라 위치도 봄


def test_clear_failure_resumes_from_check_mode():
    drives = {0: FakeDrive()}
    ethercat = FakeEthercat(drives, fail={('download', '0x4D01')})
    setup, _calls, _records = _setup(ethercat, _minas(_drive(0, 'not_absolute', 0)), switch=PowerSwitch(ethercat, [0]))
    setup.start({'scope': 'all', 'confirmed': True})
    status = setup.status()
    assert status['step'] == 'clear' and status['resume']['from_step'] == 'check_mode'
    assert status['resume']['failed_index'] == 5


def test_resume_record_survives_a_bridge_restart_and_expires(tmp_path):
    now = [1_000_000.0]
    setup, ethercat, switch, minas, _servo, _records = _failed_at_check_mode(tmp_path, wall=lambda: now[0])
    path = tmp_path / 'runtime' / 'absolute_setup_resume.json'
    saved = json.loads(path.read_text(encoding='utf-8'))
    assert saved['resume_from'] == 'check_mode' and saved['targets'][0]['identity']['serial_number'] == 1000

    again, _calls, _records = _setup(ethercat, minas, switch=switch, resume_file=path, wall=lambda: now[0])
    assert again.status()['state'] == 'idle'
    assert again.status()['resume']['from_index'] == 4
    assert again.preview({'resume': True})['success'] is True

    now[0] += RESUME_EXPIRE_SEC + 1
    assert again.status()['resume'] is None
    assert not path.exists()

    path.write_text('{"version": 1, "failed_step": "write_mode"}', encoding='utf-8')   # 엉뚱한 기록은 버린다
    third, _calls, _records = _setup(ethercat, minas, switch=switch, resume_file=path)
    assert third.status()['resume'] is None and not path.exists()


# -- 수정 목록 140 · 다회전 클리어는 Err40 일 때만 · 클리어한 경우만 기준점 보호 ------------------ #

def test_without_err40_there_is_no_clear_no_second_power_cycle_and_references_stay():
    """실물 10-14 · 인크리멘털 → 앱솔루트 뒤 Err40 없음 · 회전 수를 버리지 않는다 · 한 바퀴 넘는 위치도 정상"""
    drives = {0: FakeDrive(err40=False), 1: FakeDrive(err40=False, position=-30_000_000)}
    ethercat = FakeEthercat(drives)
    switch = PowerSwitch(ethercat, [0, 1])
    setup, service_calls, records = _setup(
        ethercat, _minas(_drive(0, 'not_absolute', 0), _drive(1, 'not_absolute', 1)), switch=switch,
    )

    setup.start({'scope': 'all', 'confirmed': True})

    status = setup.status()
    assert status['state'] == 'done', status['message']
    assert status['message'] == '앱솔루트 설정을 마쳤습니다 · 다회전 정상 · 클리어 안 함 · 기준점 그대로'
    assert switch.cycles == 1                                    # 재투입 2 건너뜀
    assert service_calls == ['stop', 'start']                    # 클리어용 정지 없음
    assert not any('0x4D0' in call for call in ethercat.calls)   # 클리어 명령 없음
    assert not any('0x6064' in call for call in ethercat.calls)  # 1 바퀴 검사 없음(감속 축은 원래 넘나든다)
    assert drives[0].position == 50_000_000 and drives[1].position == -30_000_000   # 회전 수 그대로
    assert setup.test_marker.records == [] and status['cleared_axes'] == []
    assert [t['needs_clear'] for t in status['targets']] == [False, False]
    assert records[-1]['event_type'] == 'minas_absolute_setup_done'


def test_only_the_err40_drive_is_cleared_and_marked():
    drives = {0: FakeDrive(err40=False), 1: FakeDrive(err40=True)}
    ethercat = FakeEthercat(drives)
    switch = PowerSwitch(ethercat, [0, 1])
    setup, service_calls, _records = _setup(
        ethercat, _minas(_drive(0, 'not_absolute', 0), _drive(1, 'not_absolute', 3)), switch=switch,
    )

    setup.start({'scope': 'all', 'confirmed': True})

    status = setup.status()
    assert status['state'] == 'reference_pending', status['message']
    assert status['state_label'] == '기준점 다시 지정 대기'
    assert status['message'] == '다회전 클리어한 3번 모터 · 몸을 정면·수평에 맞추고 기준점을 다시 지정해 저장하세요'
    assert not any('-p 0' in call and '0x4D0' in call for call in ethercat.calls)
    assert any('-p 1' in call and '0x4D00' in call for call in ethercat.calls)
    assert any('-p 1' in call and '0x6064' in call for call in ethercat.calls)
    assert not any('-p 0' in call and '0x6064' in call for call in ethercat.calls)
    assert [(r['axis'], r['serial'], r['source']) for r in setup.test_marker.records] == [(3, 1001, 'absolute_setup')]
    assert switch.cycles == 2 and service_calls == ['stop', 'start', 'stop', 'start']
    assert drives[0].position == 50_000_000                      # 정상 드라이브는 그대로


def test_reference_pending_turns_done_when_every_cleared_axis_is_saved():
    """「기준점 다시 지정 대기」 → 클리어한 축의 기준점을 모두 다시 저장하면(표시 풀림) 완료 · 웹을 다시 켜면 일은 사라짐"""
    drives = {0: FakeDrive(), 1: FakeDrive()}
    ethercat = FakeEthercat(drives)
    setup, _calls, _records = _setup(
        ethercat, _minas(_drive(0, 'not_absolute', 0), _drive(1, 'not_absolute', 1)), switch=PowerSwitch(ethercat, [0, 1]),
    )
    setup.start({'scope': 'all', 'confirmed': True})
    assert setup.status()['reference_pending_axes'] == [0, 1]
    assert setup.blocker() == ''                                  # 진행 중 차단은 아님 · 막는 것은 PC 단위 표시

    setup.test_marker.pending.discard(0)                          # 0번 기준점 저장
    status = setup.status()
    assert status['state'] == 'reference_pending' and status['reference_pending_axes'] == [1]
    assert '1번 모터' in status['message'] and '0번' not in status['message']

    setup.test_marker.pending.discard(1)
    status = setup.status()
    assert status['state'] == 'done'
    assert status['message'] == '앱솔루트 설정을 마쳤습니다 · 다회전 클리어한 축의 기준점을 다시 지정했습니다'

    # 표시를 못 읽으면 대기로 둔다(안전한 쪽)
    setup._pending_axes = lambda: (_ for _ in ()).throw(OSError('x'))
    assert setup.status()['state'] == 'reference_pending'


def test_resume_from_check_mode_rejudges_err40_and_skips_the_clear_when_it_is_gone():
    setup, ethercat, switch, _minas_state, servo, _records = _failed_at_check_mode()
    for drive in ethercat.drives.values():
        drive.code = 0                                            # 다시 보니 Err40 없음
    setup.start({'resume': True, 'confirmed': True})
    status = setup.status()
    assert status['state'] == 'done', status['message']
    assert status['message'].endswith('클리어 안 함 · 기준점 그대로')
    assert switch.cycles == 1                                     # 재투입 2 없음
    assert setup.test_marker.records == []


def test_a_failed_clear_still_leaves_the_marker_because_it_is_written_first():
    """클리어 명령 전에 표시를 남긴다 · 중간에 끊겨도(되읽기 실패 · 웹 재시작) 막는 쪽으로"""
    drives = {0: FakeDrive()}
    ethercat = FakeEthercat(drives, fail={('download', '0x4D00')})
    setup, _calls, _records = _setup(ethercat, _minas(_drive(0, 'not_absolute', 2)), switch=PowerSwitch(ethercat, [0]))
    setup.start({'scope': 'all', 'confirmed': True})
    status = setup.status()
    assert status['state'] == 'failed' and status['step'] == 'clear'
    assert [r['axis'] for r in setup.test_marker.records] == [2]
    assert status['resume']['from_step'] == 'check_mode'
    assert [t.get('cleared') for t in status['targets']] == [None]   # 클리어 못 함 · 이어서 하면 다시 판정


def test_resume_record_from_before_140_counts_as_cleared_after_the_clear_step():
    """140 전 기록(드라이브마다 `cleared` 없음) · 6/7 부터면 그때 규칙대로 모두 클리어한 것으로"""
    drives = {0: FakeDrive(eeprom=0, mode=0, code=0, position=12_345)}
    ethercat = FakeEthercat(drives)
    switch = PowerSwitch(ethercat, [0])
    setup, _calls, _records = _setup(ethercat, _minas(_drive(0, 'ok', 0, 0)), switch=switch)
    setup._save_resume({
        'version': 1, 'failed_at': 1_000_000.0, 'failed_step': 'power_cycle_2', 'resume_from': 'power_cycle_2',
        'error': 'x', 'scope': 'all',
        'targets': [{'master_index': 0, 'slave_position': 0, 'axis': 0, 'label': '0번 모터',
                     'identity': {'serial_number': 1000}}],
    })
    preview = setup.preview({'resume': True})
    assert preview['clear_done'] is True
    setup.start({'resume': True, 'confirmed': True})
    status = setup.status()
    assert status['cleared_axes'] == [0] and switch.cycles == 1
    assert status['state'] == 'done'                              # 가짜 표시엔 기록이 없다(그때 남기지 않음)


def test_the_bus_is_held_for_the_whole_run_refreshed_and_released_on_every_ending():
    """139 E-1 · 앱솔루트 설정이 도는 동안 감시 노드의 SDO 를 쉬게 하는 표시 · 끝 · 실패 · 취소 모두 내림"""
    from motion_web_bridge.absolute_setup import HOLD_REFRESH_SEC

    drives = {0: FakeDrive(err40=False)}
    ethercat = FakeEthercat(drives)
    held_during = []

    class Watching(FakeEthercat):
        def __call__(self, command, **kwargs):
            held_during.append(holder['setup'].test_bus.held)
            return super().__call__(command, **kwargs)

    holder = {}
    ethercat = Watching(drives)
    setup, _calls, _records = _setup(ethercat, _minas(_drive(0, 'not_absolute', 0)), switch=PowerSwitch(ethercat, [0]))
    holder['setup'] = setup
    setup.start({'scope': 'all', 'confirmed': True})
    assert setup.status()['state'] == 'done'
    assert held_during and all(held_during)                      # 모든 SDO 가 표시 아래에서
    assert setup.test_bus.calls[0] == ('hold', 'absolute_setup', True)
    assert setup.test_bus.calls[-1] == ('release',) and not setup.test_bus.held

    # 실패해도 내림
    ethercat = FakeEthercat({0: FakeDrive()}, fail={('download', '0x1010')})
    setup, _calls, _records = _setup(ethercat, _minas(_drive(0, 'not_absolute', None)))
    setup.start({'scope': 'all', 'confirmed': True})
    assert setup.status()['state'] == 'failed' and not setup.test_bus.held

    # 재투입을 오래 기다리면 마감을 늘리고 · 취소하면 내림
    ethercat = FakeEthercat({0: FakeDrive()})
    setup, _calls, _records = _setup(
        ethercat, _minas(_drive(0, 'not_absolute', None)), switch=lambda: [{'master_index': 0, 'slave_position': 0}],
    )
    original_sleep = setup._sleep

    def sleep_then_cancel(seconds):
        original_sleep(seconds)
        if setup.test_clock[0] > HOLD_REFRESH_SEC * 3:
            setup._cancel.set()

    setup._sleep = sleep_then_cancel
    setup.start({'scope': 'all', 'confirmed': True})
    refreshes = [call for call in setup.test_bus.calls if call[0] == 'hold' and call[2] is False]
    assert len(refreshes) >= 2
    assert setup.status()['state'] == 'failed' and not setup.test_bus.held


def test_absolute_setup_holding_the_bus_makes_the_monitor_skip_its_reads(tmp_path, monkeypatch):
    """실제 표시 파일 · 웹 브리지(세운 쪽)는 보내고 · 다른 프로세스(감시 노드)는 `configuring()` 참 · 139 E-1"""
    import os

    from motion_common import ethercat_mailbox

    monkeypatch.setenv('ROBOT_WEB_RUN_DIR', str(tmp_path))
    ethercat_mailbox.hold('absolute_setup')
    assert not ethercat_mailbox.configuring()
    assert ethercat_mailbox.held_by_other(me=os.getpid() + 1, alive=lambda _pid: True)
    assert ethercat_mailbox.release() is True
    assert not ethercat_mailbox.held_by_other(me=os.getpid() + 1, alive=lambda _pid: True)
