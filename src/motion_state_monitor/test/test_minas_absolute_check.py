"""연결된 MINAS 드라이브 앱솔루트 값 늘 알기 · 수정 목록 62 ①"""

from types import SimpleNamespace

from motion_common import minas_absolute as ma
from motion_state_monitor.absolute_check import SETTLE_SEC, MinasAbsoluteCheck, visible_slaves
from motion_state_monitor.ethercat_scanner import EthercatScanner

SLAVES_V = """=== Master 0, Slave 0 ===
Alias: 0
State: OP
Vendor Id:       0x0000066f
=== Master 0, Slave 1 ===
Alias: 0
State: OP
Vendor Id:       0x0000066f
=== Master 0, Slave 2 ===
Alias: 0
State: OP
Vendor Id:       0x00000002
"""


def _masters(*positions, master=0, available=True):
    return {str(master): {
        'available': available,
        'master_index': master,
        'states_by_position': {str(position): 'OP' for position in positions},
    }}


class FakeEthercat:
    def __init__(self, *, modes=None, codes=None, slaves=SLAVES_V, fail=()):
        self.modes = modes or {}
        self.codes = codes or {}
        self.slaves = slaves
        self.fail = set(fail)
        self.calls = []

    def __call__(self, command, **_kwargs):
        self.calls.append(' '.join(command))
        if command[1] == 'slaves':
            if 'slaves' in self.fail:
                return SimpleNamespace(returncode=1, stdout='', stderr='master busy')
            return SimpleNamespace(returncode=0, stdout=self.slaves, stderr='')
        position = int(command[command.index('-p') + 1])
        index = command[-2]
        if (position, index) in self.fail:
            return SimpleNamespace(returncode=1, stdout='', stderr='SDO upload aborted')
        table = self.modes if index == '0x3015' else self.codes
        value = table.get(position, 0)
        return SimpleNamespace(returncode=0, stdout=f'0x{value & 0xFFFF:04x} {value}\n', stderr='')


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


def _check(runner, *, axes=None, run_now=True, clock=None, configuring=lambda: False):
    pending = []
    scanner = EthercatScanner(SimpleNamespace(_motor_metadata={}))
    check = MinasAbsoluteCheck(
        parse_slaves=scanner._parse_ethercat_slaves,
        axis_for_slave=lambda master, position: (axes or {}).get((master, position)),
        runner=runner,
        clock=clock or Clock(),
        spawn=(lambda target: target()) if run_now else pending.append,
        bus_configuring=configuring,
    )
    return check, pending


def _see(check, masters):
    """폴링 두 번 · 처음 보면 상태가 자리 잡기를 기다리고(110) · SETTLE_SEC 뒤에 읽는다"""
    check.observe(masters)
    check._clock.now += SETTLE_SEC + 0.5
    check.observe(masters)


def test_starts_as_checking_so_nothing_moves_before_the_first_read():
    check, _ = _check(FakeEthercat())
    assert ma.block_reason(check.snapshot()) == ma.CHECKING_MESSAGE


def test_all_minas_absolute_is_ok_and_other_vendors_are_ignored():
    runner = FakeEthercat()
    check, _ = _check(runner, axes={(0, 0): 0, (0, 1): 1})

    _see(check, _masters(0, 1, 2))

    snapshot = check.snapshot()
    assert snapshot['state'] == ma.STATE_OK
    assert [drive['slave_position'] for drive in snapshot['drives']] == [0, 1]   # 2 는 MINAS 아님
    assert [drive['axis'] for drive in snapshot['drives']] == [0, 1]
    assert not any('-p 2' in call for call in runner.calls if 'upload' in call)


def test_incremental_unregistered_and_err40_drives_block():
    runner = FakeEthercat(modes={1: 1}, codes={0: 0xFF28})
    check, _ = _check(runner, axes={(0, 0): 0})

    _see(check, _masters(0, 1))

    snapshot = check.snapshot()
    assert snapshot['state'] == ma.STATE_BLOCKED
    reason = ma.block_reason(snapshot)
    assert '0번 모터 Err40' in reason
    assert '슬레이브 1(미등록) Pr0.15=1(인크리멘털)' in reason


def test_read_failure_is_unknown_and_blocks():
    check, _ = _check(FakeEthercat(fail={(1, '0x3015')}))
    _see(check, _masters(0, 1))
    drives = check.snapshot()['drives']
    assert drives[1]['status'] == ma.DRIVE_UNKNOWN and 'SDO upload aborted' in drives[1]['error']
    assert '확인 불가' in ma.block_reason(check.snapshot())


def test_unknown_vendor_list_is_not_treated_as_not_minas():
    check, _ = _check(FakeEthercat(fail={'slaves'}))
    _see(check, _masters(0))
    assert check.snapshot()['drives'][0]['status'] == ma.DRIVE_UNKNOWN
    assert check.snapshot()['state'] == ma.STATE_BLOCKED


def test_reads_only_when_the_visible_set_changes():
    runner = FakeEthercat()
    check, _ = _check(runner)
    _see(check, _masters(0, 1))
    first = len(runner.calls)

    _see(check, _masters(0, 1))                 # 그대로 · 다시 안 읽음 (속성 C · RAM 값 오판 방지)
    assert len(runner.calls) == first

    _see(check, _masters())                     # 전원 차단 · 안 보임
    assert check.snapshot()['state'] == ma.STATE_NONE
    runner.modes = {0: 1}
    _see(check, _masters(0, 1))                 # 재투입 · 다시 읽음
    assert len(runner.calls) > first
    assert check.snapshot()['state'] == ma.STATE_BLOCKED


def test_no_ethercat_master_means_nothing_to_check():
    check, _ = _check(FakeEthercat())
    _see(check, _masters(0, available=False))
    assert check.snapshot()['state'] == ma.STATE_NONE
    assert ma.block_reason(check.snapshot()) == ''


def test_set_change_while_reading_reads_again_and_shows_checking_meanwhile():
    runner = FakeEthercat()
    check, pending = _check(runner, run_now=False)

    _see(check, _masters(0))
    assert len(pending) == 1
    _see(check, _masters(0, 1))                 # 읽는 중에 구성 바뀜 · 새 스레드는 안 띄움
    assert len(pending) == 1
    assert check.snapshot()['state'] == ma.STATE_CHECKING

    pending[0]()                                  # 도는 읽기가 바뀐 구성으로 다시 읽고 끝남
    snapshot = check.snapshot()
    assert snapshot['state'] == ma.STATE_OK
    assert [drive['slave_position'] for drive in snapshot['drives']] == [0, 1]


def test_visible_slaves_skips_masters_never_seen():
    masters = {**_masters(0, 1), **_masters(5, master=1, available=False)}
    assert visible_slaves(masters) == frozenset({(0, 0), (0, 1)})


def test_a_failed_master_poll_keeps_the_last_set_so_the_block_does_not_blink_open():
    runner = FakeEthercat(modes={1: 1})
    check, _ = _check(runner)
    _see(check, _masters(0, 1))
    assert check.snapshot()['state'] == ma.STATE_BLOCKED
    calls = len(runner.calls)

    _see(check, _masters(0, 1, available=False))     # `ethercat slaves` 한 번 실패

    assert check.snapshot()['state'] == ma.STATE_BLOCKED
    assert len(runner.calls) == calls                  # 구성 그대로 · 다시 안 읽음


def test_scanner_finds_the_registered_axis_by_ring_position():
    scanner = EthercatScanner(SimpleNamespace(_motor_metadata={
        3: {'transport': 'ethercat', 'ethercat_master_index': 0, 'slave_position': 2},
        4: {'transport': 'serial', 'slave_position': 1},
    }))
    assert scanner._axis_for_slave(0, 2) == 3
    assert scanner._axis_for_slave(0, 1) is None
    assert scanner._axis_for_slave(1, 2) is None


def test_scanner_check_is_off_until_the_node_enables_it():
    scanner = EthercatScanner(SimpleNamespace(_motor_metadata={}))
    assert scanner.absolute is None
    scanner.enable_absolute_check()
    assert isinstance(scanner.absolute, MinasAbsoluteCheck)
    assert ma.block_reason(scanner.absolute.snapshot()) == ma.CHECKING_MESSAGE


# -- 수정 목록 110 · 부팅 직후 OP 전환 중엔 안 읽고 · 읽기 실패는 다시 읽는다 -------------- #

def _states(states, master=0, phase='', active=False):
    return {str(master): {'available': True, 'master_index': master, 'phase': phase, 'master_active': active,
                          'states_by_position': {str(p): s for p, s in states.items()}}}


def test_does_not_read_while_the_master_is_bringing_drives_up():
    runner = FakeEthercat()
    clock = Clock()
    check, _ = _check(runner, clock=clock)

    check.observe(_states({0: 'PREOP', 1: 'PREOP'}))
    clock.now += 1.0
    check.observe(_states({0: 'SAFEOP', 1: 'PREOP'}))      # 설정 중 · 상태가 바뀐다
    clock.now += 1.0
    check.observe(_states({0: 'OP', 1: 'OP'}))
    assert not [c for c in runner.calls if 'upload' in c]
    assert check.snapshot()['state'] == ma.STATE_CHECKING

    clock.now += SETTLE_SEC + 0.1                          # OP 로 자리 잡음
    check.observe(_states({0: 'OP', 1: 'OP'}))
    assert check.snapshot()['state'] == ma.STATE_OK


def test_steady_preop_is_read_too():
    """모터 프로그램이 멈춘 PC(검색 중 등 · 마스터 Idle) · PREOP 그대로여도 자리 잡았으면 읽는다"""
    clock = Clock()
    check, _ = _check(FakeEthercat(), clock=clock)
    check.observe(_states({0: 'PREOP'}, phase='Idle'))
    clock.now += SETTLE_SEC + 0.1
    check.observe(_states({0: 'PREOP'}, phase='Idle'))
    assert check.snapshot()['state'] == ma.STATE_OK


def test_read_failure_is_read_again_and_the_block_clears():
    """2026-10-12 floating4 · 0x3015 「wrong SDO」 한 번으로 「확인 불가」 가 굳었다"""
    runner = FakeEthercat(fail={(0, '0x3015')})
    clock = Clock()
    check, _ = _check(runner, clock=clock)
    _see(check, _masters(0, 1))
    assert check.snapshot()['drives'][0]['status'] == ma.DRIVE_UNKNOWN
    assert '다시 읽는 중' in ma.block_reason(check.snapshot())

    runner.fail.clear()
    clock.now += 1.0
    check.observe(_masters(0, 1))                          # 아직 2 초 전 · 다시 안 읽음
    assert check.snapshot()['state'] == ma.STATE_BLOCKED
    clock.now += 1.5
    check.observe(_masters(0, 1))                          # 2 초 지남 · 다시 읽어 풀림
    assert check.snapshot()['state'] == ma.STATE_OK


def test_not_absolute_is_not_read_again():
    """Pr0.15 ≠ 0 은 다시 읽어도 같다 · 속성 C 라 RAM 값을 되읽어 오판하지 않게 다시 안 읽는다"""
    runner = FakeEthercat(modes={0: 1})
    clock = Clock()
    check, _ = _check(runner, clock=clock)
    _see(check, _masters(0))
    calls = len(runner.calls)
    clock.now += 30
    check.observe(_masters(0))
    assert len(runner.calls) == calls
    assert check.snapshot()['state'] == ma.STATE_BLOCKED


def test_retries_slow_down_after_a_minute():
    runner = FakeEthercat(fail={(0, '0x3015')})
    clock = Clock()
    check, _ = _check(runner, clock=clock)
    _see(check, _masters(0))
    for _ in range(40):                                   # 1 분 넘게 계속 실패
        clock.now += 2.0
        check.observe(_masters(0))
    reads = sum('0x3015' in c for c in runner.calls)
    clock.now += 3.0
    check.observe(_masters(0))
    assert sum('0x3015' in c for c in runner.calls) == reads   # 이제 10 초 간격
    clock.now += 8.0
    check.observe(_masters(0))
    assert sum('0x3015' in c for c in runner.calls) == reads + 1


# -- 수정 목록 108 (가) · 게인도 같이 읽어 화면에 · 막지 않는다 · 5 분마다 게인만 다시 ------------------- #

def test_gains_are_read_with_the_absolute_values():
    runner = FakeEthercat(modes={}, codes={})
    clock = Clock()
    check, _ = _check(runner, clock=clock)
    _see(check, _masters(0))
    gains = check.snapshot()['drives'][0]['gains']
    assert set(gains) >= {'auto_tuning', 'stiffness', 'inertia_ratio', 'estimation_speed', 'error'}
    assert set(gains) >= {'command_smoothing', 'command_fir'}     # 지령 필터 · 2026-10-16
    assert gains['error'] == ''
    assert any('0x3004' in call for call in runner.calls)
    assert any('0x3222' in call for call in runner.calls) and any('0x3223' in call for call in runner.calls)


def test_a_gain_read_failure_does_not_block():
    runner = FakeEthercat(fail={(0, '0x3003')})
    check, _ = _check(runner, clock=Clock())
    _see(check, _masters(0))
    drive = check.snapshot()['drives'][0]
    assert drive['status'] == ma.DRIVE_OK
    assert '0x3003' in drive['gains']['error']
    assert check.snapshot()['state'] == ma.STATE_OK


def test_gains_alone_are_read_again_later_without_rereading_pr015():
    from motion_state_monitor.absolute_check import GAIN_REFRESH_SEC
    runner = FakeEthercat(modes={}, codes={})
    clock = Clock()
    check, _ = _check(runner, clock=clock)
    _see(check, _masters(0))
    mode_reads = sum('0x3015' in c for c in runner.calls)
    inertia_reads = sum('0x3004' in c for c in runner.calls)
    clock.now += GAIN_REFRESH_SEC + 1
    check.observe(_masters(0))
    assert sum('0x3015' in c for c in runner.calls) == mode_reads          # 속성 C · 다시 안 읽음
    assert sum('0x3004' in c for c in runner.calls) == inertia_reads + 1
    assert check.snapshot()['state'] == ma.STATE_OK


def test_a_failed_read_sends_nothing_more_to_that_drive_in_the_same_pass():
    """실물 U-1b(10-13) · 막 켜진 드라이브에 SDO 를 줄줄이 보내면 늦은 응답이 다음 요청 답으로 섞인다(「wrong SDO」)
    · 0x3015 가 안 되면 그 드라이브엔 0x603F · 게인을 이번엔 안 묻고 다음 다시 읽기로"""
    runner = FakeEthercat(fail={(1, '0x3015')})
    check, _ = _check(runner)
    _see(check, _masters(0, 1))
    to_slave_1 = [c for c in runner.calls if ' -p 1 ' in c]
    assert len(to_slave_1) == 1 and '0x3015' in to_slave_1[0]
    drive = check.snapshot()['drives'][1]
    assert drive['status'] == ma.DRIVE_UNKNOWN
    assert drive['gains']['error'] and drive['gains']['inertia_ratio'] is None
    # 다른 드라이브는 그대로 다 읽음
    assert any(' -p 0 ' in c and '0x3004' in c for c in runner.calls)


def test_a_failed_gain_read_stops_the_other_gain_reads_on_that_drive():
    runner = FakeEthercat(fail={(0, '0x3002')})
    check, _ = _check(runner)
    _see(check, _masters(0))
    assert not any('0x3003' in c or '0x3004' in c for c in runner.calls)
    assert '0x3002' in check.snapshot()['drives'][0]['gains']['error']


# -- 수정 목록 125 · 모터 프로그램이 버스를 설정하는 동안엔 안 읽는다 (실물 U-1 · PC 만 재부팅 2/2 PREOP + E) ------ #

def test_no_reads_while_the_motor_program_configures_the_bus():
    """**이것이 그 버그다** · 부팅 때 PREOP 가 한참 그대로여도 모터 프로그램이 설정 중이면 안 읽는다"""
    runner = FakeEthercat()
    clock = Clock()
    busy = {'on': True}
    check, _ = _check(runner, clock=clock, configuring=lambda: busy['on'])
    for _ in range(10):                                    # 설정 중 · 상태는 그대로(PREOP)
        check.observe(_states({0: 'PREOP', 1: 'PREOP'}))
        clock.now += SETTLE_SEC
    assert not [c for c in runner.calls if 'upload' in c]
    assert check.snapshot()['state'] == ma.STATE_CHECKING

    busy['on'] = False                                     # 설정 끝 · 모두 OP
    check.observe(_states({0: 'OP', 1: 'OP'}, phase='Operation', active=True))
    clock.now += SETTLE_SEC + 0.1
    check.observe(_states({0: 'OP', 1: 'OP'}, phase='Operation', active=True))
    assert check.snapshot()['state'] == ma.STATE_OK


def test_steady_preop_waits_longer_while_the_motor_program_holds_the_master():
    """모터 프로그램이 마스터를 잡고 있는데 PREOP · 설정 중일 수 있다 · `STUCK_SEC` 그대로일 때만(설정 실패 · 미등록)"""
    from motion_state_monitor.absolute_check import STUCK_SEC
    runner = FakeEthercat()
    clock = Clock()
    check, _ = _check(runner, clock=clock)
    claimed = _states({0: 'OP', 1: 'PREOP'}, phase='Operation', active=True)
    check.observe(claimed)
    clock.now += SETTLE_SEC + 0.1
    check.observe(claimed)
    assert not [c for c in runner.calls if 'upload' in c]
    clock.now += STUCK_SEC
    check.observe(claimed)
    assert check.snapshot()['state'] == ma.STATE_OK


def test_marker_raised_mid_read_drops_that_pass_and_reads_again_later():
    """읽는 중에 표시가 서면 남은 SDO 는 안 나간다 · 「확인 불가」 로 굳히지 않고 「확인 중」 그대로 · 다시 읽는다"""
    from motion_common import ethercat_mailbox
    clock = Clock()
    refuse = {'on': True}
    base = FakeEthercat()

    def runner(command, **kwargs):
        if refuse['on'] and command[1] == 'upload':
            return ethercat_mailbox.refused(command, ethercat_mailbox.CONFIGURING_MESSAGE, kwargs)
        return base(command, **kwargs)

    check, _ = _check(runner, clock=clock)
    _see(check, _masters(0, 1))
    assert check.snapshot()['state'] == ma.STATE_CHECKING
    assert not any(drive.get('status') == ma.DRIVE_UNKNOWN for drive in check.snapshot()['drives'])

    refuse['on'] = False
    clock.now += 1.0
    check.observe(_masters(0, 1))
    assert check.snapshot()['state'] == ma.STATE_OK


def test_gain_refresh_respects_the_marker():
    from motion_state_monitor.absolute_check import GAIN_REFRESH_SEC
    runner = FakeEthercat()
    clock = Clock()
    busy = {'on': False}
    check, _ = _check(runner, clock=clock, configuring=lambda: busy['on'])
    _see(check, _masters(0))
    reads = sum('0x3004' in c for c in runner.calls)

    busy['on'] = True                                      # 「적용」 · 모터 재시작 · 설정 중
    clock.now += GAIN_REFRESH_SEC + 1
    check.observe(_masters(0))
    assert sum('0x3004' in c for c in runner.calls) == reads

    busy['on'] = False
    clock.now += 1
    check.observe(_masters(0))
    assert sum('0x3004' in c for c in runner.calls) == reads + 1


def test_gain_refresh_refused_mid_way_keeps_the_old_gains():
    from motion_common import ethercat_mailbox
    from motion_state_monitor.absolute_check import GAIN_REFRESH_SEC, GAIN_RETRY_SEC
    clock = Clock()
    refuse = {'on': False}
    base = FakeEthercat()

    def runner(command, **kwargs):
        if refuse['on'] and command[1] == 'upload':
            return ethercat_mailbox.refused(command, ethercat_mailbox.BUSY_MESSAGE, kwargs)
        return base(command, **kwargs)

    check, _ = _check(runner, clock=clock)
    _see(check, _masters(0))
    before = check.snapshot()['drives'][0]['gains']
    refuse['on'] = True
    clock.now += GAIN_REFRESH_SEC + 1
    check.observe(_masters(0))
    assert check.snapshot()['drives'][0]['gains'] == before
    refuse['on'] = False
    clock.now += GAIN_RETRY_SEC + 1
    check.observe(_masters(0))
    assert check.snapshot()['drives'][0]['gains']['read_at'] > before['read_at']


def test_sdo_goes_through_the_shared_mailbox_guard(tmp_path, monkeypatch):
    """감시 노드의 SDO 도 웹 브리지와 같은 문지기 · 주입한 runner 도 감싼다 · 판단을 지나쳐도 마지막에 막는다"""
    from motion_common import ethercat_mailbox
    monkeypatch.setenv('ROBOT_WEB_RUN_DIR', str(tmp_path))
    monkeypatch.setattr(ethercat_mailbox, 'configuring', lambda **_kw: True)
    runner = FakeEthercat()
    check, _ = _check(runner, configuring=lambda: False)
    _see(check, _masters(0))
    assert not [c for c in runner.calls if 'upload' in c]
    assert check.snapshot()['state'] == ma.STATE_CHECKING


# -- 수정 목록 125 · PREOP 등에 멈춘 드라이브를 화면에 ------------------------------------------ #

def _bus(states, errors=(), phase='Operation', active=True):
    masters = _states(states, phase=phase, active=active)
    masters['0']['error_positions'] = [str(p) for p in errors]
    return masters


def test_a_slave_stuck_in_preop_is_reported_after_a_while(monkeypatch):
    from motion_common import ethercat_mailbox
    from motion_state_monitor.ethercat_scanner import STUCK_NOTICE_SEC
    monkeypatch.setattr(ethercat_mailbox, 'configuring', lambda **_kw: False)
    scanner = EthercatScanner(SimpleNamespace(_motor_metadata={
        1: {'transport': 'ethercat', 'ethercat_master_index': 0, 'slave_position': 1},
    }))
    bus = _bus({0: 'OP', 1: 'PREOP'}, errors=[1])
    assert scanner._stuck_slaves(bus, 100.0) == []
    stuck = scanner._stuck_slaves(bus, 100.0 + STUCK_NOTICE_SEC)
    assert [(s['slave_position'], s['axis'], s['state'], s['error_flag']) for s in stuck] == [(1, 1, 'PREOP', True)]
    assert stuck[0]['message'] == '1번 드라이브가 PREOP 에 멈춤 · 그 드라이브 제어 전원을 껐다 켜세요'
    # OP 로 올라가면 사라지고 시간도 다시 잰다
    assert scanner._stuck_slaves(_bus({0: 'OP', 1: 'OP'}), 200.0) == []
    assert scanner._stuck_slaves(bus, 201.0) == []


def test_preop_is_not_stuck_while_configuring_or_without_motor_program(monkeypatch):
    from motion_common import ethercat_mailbox
    monkeypatch.setattr(ethercat_mailbox, 'configuring', lambda **_kw: True)
    scanner = EthercatScanner(SimpleNamespace(_motor_metadata={}))
    bus = _bus({0: 'PREOP'})
    scanner._stuck_slaves(bus, 0.0)
    assert scanner._stuck_slaves(bus, 100.0) == []         # 모터 프로그램이 설정 중
    monkeypatch.setattr(ethercat_mailbox, 'configuring', lambda **_kw: False)
    idle = _bus({0: 'PREOP'}, phase='Idle', active=False)
    scanner._stuck_slaves(idle, 0.0)
    assert scanner._stuck_slaves(idle, 100.0) == []        # 모터 프로그램 없음(검색 뒤) · PREOP 가 정상
    # 모터 프로그램이 없어도 오류(E)가 붙어 그대로면 알린다(시작 스크립트가 못 풀어 모터가 못 뜸)
    errored = _bus({0: 'PREOP'}, errors=[0], phase='Idle', active=False)
    scanner._stuck_slaves(errored, 200.0)
    assert scanner._stuck_slaves(errored, 300.0)[0]['message'].startswith('슬레이브 0 드라이브가 PREOP')


# -- 수정 목록 139 ③ · 멈춘 메일박스 · 한 대만 응답 없음이 이어지면 알리고 그 드라이브엔 덜 보낸다 ------------- #

EIO = 'Failed to upload SDO: Input/output error'


class SilentEthercat(FakeEthercat):
    """`silent` 의 슬레이브는 메일박스가 멈춘 것처럼 · CLI 는 EIO(커널 로그엔 「upload request … timeout」)"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.silent = set()

    def __call__(self, command, **kwargs):
        if command[1] == 'upload' and int(command[command.index('-p') + 1]) in self.silent:
            self.calls.append(' '.join(command))
            return SimpleNamespace(returncode=1, stdout='', stderr=EIO)
        return super().__call__(command, **kwargs)


def _uploads_to(runner, position):
    return [c for c in runner.calls if 'upload' in c and f' -p {position} ' in c]


def _all_ok_first(runner, *, axes=None):
    """처음엔 모두 정상으로 읽는다(앱솔루트 정상) · 그 뒤 게인 다시 읽기에서 응답 없음을 만든다"""
    check, _ = _check(runner, clock=Clock(), axes=axes)
    masters = _masters(0, 1)
    _see(check, masters)
    assert check.snapshot()['state'] == ma.STATE_OK and check.snapshot()['stuck_mailboxes'] == []
    return check, masters


def _gain_rounds(check, masters, rounds):
    """게인 다시 읽기 · 첫 번은 `GAIN_REFRESH_SEC` 뒤 · 실패가 남으면 `GAIN_RETRY_SEC` 마다"""
    from motion_state_monitor.absolute_check import GAIN_REFRESH_SEC, GAIN_RETRY_SEC
    check._clock.now += GAIN_REFRESH_SEC + 1
    check.observe(masters)
    for _ in range(rounds - 1):
        check._clock.now += GAIN_RETRY_SEC + 0.5
        check.observe(masters)


def _make_stuck(runner, *, axes=None):
    check, masters = _all_ok_first(runner, axes=axes)
    runner.silent = {1}
    _gain_rounds(check, masters, 3)                        # 응답 없음 3 번 · 30 s 넘게 · 슬레이브 0 은 계속 답함
    assert [s['slave_position'] for s in check.snapshot()['stuck_mailboxes']] == [1]
    return check, masters


def test_one_slave_timing_out_while_others_answer_is_a_stuck_mailbox():
    runner = SilentEthercat()
    check, masters = _all_ok_first(runner, axes={(0, 1): 2})
    runner.silent = {1}
    _gain_rounds(check, masters, 2)
    assert check.snapshot()['stuck_mailboxes'] == []       # 아직 2 번
    _gain_rounds(check, masters, 1)

    snapshot = check.snapshot()
    assert [(s['slave_position'], s['axis']) for s in snapshot['stuck_mailboxes']] == [(1, 2)]
    assert snapshot['stuck_mailboxes'][0]['message'] == '2번 드라이브 메일박스 응답 없음 · 그 드라이브 제어 전원을 껐다 켜세요'
    # 막지 않는다 · 앱솔루트 판정 · PDO · 재생은 그대로
    assert snapshot['state'] == ma.STATE_OK and ma.block_reason(snapshot) == ''


def test_three_quick_timeouts_are_not_enough_without_ten_seconds():
    """연속 3 번이어도 첫 번째부터 10 s 가 안 됐으면 아직 · 재투입 직후 잠깐 겹치는 것과 가른다"""
    runner = SilentEthercat()
    clock = Clock()
    check, _ = _check(runner, clock=clock)
    runner.silent = {1}
    masters = _masters(0, 1)
    _see(check, masters)                                   # 0x3015 응답 없음 1 · 「확인 불가」 · 2 s 뒤 다시
    for _ in range(2):
        clock.now += 2.5
        check.observe(masters)                             # 2 · 3 (첫 번째부터 5 s)
    assert len(_uploads_to(runner, 1)) == 3
    assert check.snapshot()['stuck_mailboxes'] == []
    for _ in range(2):
        clock.now += 2.5
        check.observe(masters)                             # 4 · 5 (10 s)
    assert [s['slave_position'] for s in check.snapshot()['stuck_mailboxes']] == [1]


def test_all_slaves_timing_out_is_a_bus_problem_not_a_stuck_mailbox():
    runner = SilentEthercat()
    check, masters = _all_ok_first(runner)
    runner.silent = {0, 1}
    _gain_rounds(check, masters, 6)
    assert check.snapshot()['stuck_mailboxes'] == []
    # 둘 다 계속 물어본다(어느 쪽도 쉬지 않음)
    assert sum('0x3002' in c for c in _uploads_to(runner, 1)) >= 6


def test_aborts_are_answers_and_never_make_a_stuck_mailbox():
    runner = SilentEthercat(fail={(1, '0x3002')})          # 「SDO upload aborted」 · 드라이브가 답한 것
    check, masters = _all_ok_first(runner)
    _gain_rounds(check, masters, 6)
    assert check.snapshot()['stuck_mailboxes'] == []


def test_reads_to_a_stuck_slave_stop_except_a_sparse_probe():
    from motion_state_monitor.absolute_check import GAIN_RETRY_SEC, MAILBOX_PROBE_SEC
    runner = SilentEthercat()
    check, masters = _make_stuck(runner)
    sent = len(_uploads_to(runner, 1))
    other = len(_uploads_to(runner, 0))

    check._clock.now += GAIN_RETRY_SEC + 0.5               # 다시 읽기 · 멈춘 드라이브엔 안 보냄
    check.observe(masters)
    assert len(_uploads_to(runner, 1)) == sent
    assert len(_uploads_to(runner, 0)) > other             # 다른 드라이브는 그대로 읽음
    assert '읽기 쉼' in check.snapshot()['drives'][1]['gains']['error']

    check._clock.now += MAILBOX_PROBE_SEC - GAIN_RETRY_SEC  # 떠볼 때 · 한 번만
    check.observe(masters)
    assert len(_uploads_to(runner, 1)) == sent + 1
    assert [s['slave_position'] for s in check.snapshot()['stuck_mailboxes']] == [1]   # 여전히 답 없음 · 그대로


def test_an_answer_to_the_probe_clears_the_stuck_mailbox():
    from motion_state_monitor.absolute_check import MAILBOX_PROBE_SEC
    runner = SilentEthercat()
    check, masters = _make_stuck(runner)
    runner.silent = set()                                  # 다시 답함 · 떠보기로 안다
    check._clock.now += MAILBOX_PROBE_SEC + 1
    check.observe(masters)
    assert check.snapshot()['stuck_mailboxes'] == []
    assert check.snapshot()['drives'][1]['gains']['error'] == ''   # 풀리면 그 자리에서 게인을 다 읽음


def test_leaving_op_or_a_rescan_clears_the_stuck_mailbox():
    check, _ = _make_stuck(SilentEthercat())
    check.observe(_states({0: 'OP', 1: 'PREOP'}))          # 그 슬레이브가 OP 를 벗어남(재설정 · 재스캔)
    assert check.snapshot()['stuck_mailboxes'] == []

    check, _ = _make_stuck(SilentEthercat())
    check.observe(_masters(0, 1, 2))                       # 슬레이브 구성 바뀜
    assert check.snapshot()['stuck_mailboxes'] == []


def test_a_failed_master_poll_does_not_clear_the_stuck_mailbox():
    check, _ = _make_stuck(SilentEthercat())
    check.observe(_masters(0, 1, available=False))         # `ethercat slaves` 한 번 실패 · 모름 · 직전 그대로
    assert [s['slave_position'] for s in check.snapshot()['stuck_mailboxes']] == [1]


def test_timeouts_on_a_slave_not_in_op_do_not_count():
    """OP 가 아니면 마스터가 설정 중일 수 있다 · 그때의 응답 없음은 판정에 안 쓴다"""
    runner = SilentEthercat()
    clock = Clock()
    check, _ = _check(runner, clock=clock)
    runner.silent = {1}
    masters = _states({0: 'OP', 1: 'PREOP'})               # 모터 프로그램 없음 · PREOP 그대로면 읽는다
    _see(check, masters)
    for _ in range(20):
        clock.now += 2.5
        check.observe(masters)
    assert len(_uploads_to(runner, 1)) >= 5
    assert check.snapshot()['stuck_mailboxes'] == []


def test_mailbox_answered_reads_the_cli_text():
    from motion_state_monitor.absolute_check import mailbox_answered
    assert mailbox_answered(EIO) is False
    assert mailbox_answered('Reception of CoE upload request for SDO 0x3015:0 failed with timeout after 1000 ms') is False
    assert mailbox_answered('SDO transfer aborted with code 0x06020000: This object does not exist') is True
    assert mailbox_answered('Failed to open master device /dev/EtherCAT0') is None
