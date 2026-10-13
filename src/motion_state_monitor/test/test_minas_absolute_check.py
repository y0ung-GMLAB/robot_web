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


def _check(runner, *, axes=None, run_now=True, clock=None):
    pending = []
    scanner = EthercatScanner(SimpleNamespace(_motor_metadata={}))
    check = MinasAbsoluteCheck(
        parse_slaves=scanner._parse_ethercat_slaves,
        axis_for_slave=lambda master, position: (axes or {}).get((master, position)),
        runner=runner,
        clock=clock or Clock(),
        spawn=(lambda target: target()) if run_now else pending.append,
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

def _states(states, master=0):
    return {str(master): {'available': True, 'master_index': master,
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
    """모터 프로그램이 멈춘 PC(검색 중 등) · PREOP 그대로여도 자리 잡았으면 읽는다"""
    clock = Clock()
    check, _ = _check(FakeEthercat(), clock=clock)
    check.observe(_states({0: 'PREOP'}))
    clock.now += SETTLE_SEC + 0.1
    check.observe(_states({0: 'PREOP'}))
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
    assert gains['error'] == ''
    assert any('0x3004' in call for call in runner.calls)


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
