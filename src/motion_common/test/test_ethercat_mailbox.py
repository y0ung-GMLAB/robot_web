"""EtherCAT 메일박스 · 한 번에 하나 · 버스 설정 중엔 안 보냄 · 수정 목록 125 (실물 U-1 · 2026-10-13)

PC 부팅 때 모터 프로그램이 드라이브에 부팅 설정 SDO 를 쓰는 사이 우리 앱솔루트 확인이 같은 드라이브에
SDO 를 보내 「SDO configuration failed」 → PREOP + E 로 굳었다 · 웹이 뜰 때 우리 두 곳이 동시에 읽어
「wrong SDO」 도 났다.
"""

import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from motion_common import ethercat_mailbox as em

UPLOAD = ['ethercat', 'upload', '-m', '0', '-p', '1', '-t', 'int16', '0x3015', '0']


@pytest.fixture(autouse=True)
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('ROBOT_WEB_RUN_DIR', str(tmp_path))
    return tmp_path


class Runner:
    def __init__(self, delay=0.0):
        self.calls = []
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.guard = threading.Lock()

    def __call__(self, command, **kwargs):
        with self.guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append((list(command), time.monotonic()))
        time.sleep(self.delay)
        with self.guard:
            self.active -= 1
        return subprocess.CompletedProcess(command, 0, stdout='0x0000 0\n', stderr='')


def _mark(owner=None, *, ttl=60.0):
    em._write_marker({
        'owner_pid': os.getpid() if owner is None else owner,
        'started_at': time.time(),
        'deadline_monotonic': time.monotonic() + ttl,
    })


def test_without_marker_the_sdo_goes_out():
    runner = Runner()
    done = em.run(UPLOAD, runner=runner, check=False, capture_output=True, text=True)
    assert done.returncode == 0 and len(runner.calls) == 1


def test_no_sdo_while_the_motor_program_configures_the_bus():
    """**이것이 그 버그다** · 표시가 있으면 우리 SDO 는 드라이브에 가지 않는다"""
    _mark()
    runner = Runner()
    done = em.run(UPLOAD, runner=runner, check=False, capture_output=True, text=True)
    assert runner.calls == []
    assert em.is_refused(done) and '버스 설정 중' in done.stderr
    # text 가 아니면 bytes 로 · 부른 쪽이 decode 한다
    raw = em.run(['ethercat', 'download', '-p', '0', '0x3015', '0', '0'], runner=runner, capture_output=True)
    assert isinstance(raw.stderr, bytes) and raw.returncode == em.REFUSED_EXIT


def test_non_mailbox_commands_are_not_held_back():
    """목록 · 상태 · SII 읽기는 메일박스가 아니다 · 설정 중에도 그대로(감시·검색이 멈추지 않게)"""
    _mark()
    runner = Runner()
    for command in (['ethercat', 'slaves', '-v'], ['ethercat', 'master'], ['ethercat', 'sii_read', '-p', '0']):
        assert em.run(command, runner=runner).returncode == 0
    assert len(runner.calls) == 3


def test_a_stale_marker_does_not_block():
    """마감이 지났거나 · 표시를 세운 모터 프로그램이 끝났으면 없는 것"""
    _mark(ttl=-1.0)
    assert not em.configuring()
    _mark(owner=999_999)
    assert not em.configuring(alive=lambda _pid: False)
    assert em.configuring(alive=lambda _pid: True)


def test_two_callers_never_overlap():
    runner = Runner(delay=0.05)
    threads = [threading.Thread(target=em.run, args=(UPLOAD,), kwargs={'runner': runner}) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(runner.calls) == 4
    assert runner.max_active == 1


def test_a_held_lock_refuses_after_the_wait():
    started, release = threading.Event(), threading.Event()

    def hold():
        with em.mailbox_lock() as held:
            assert held
            started.set()
            release.wait(5)

    holder = threading.Thread(target=hold)
    holder.start()
    started.wait(5)
    try:
        runner = Runner()
        done = em.run(UPLOAD, runner=runner, lock_wait_sec=0.05, text=True)
        assert em.is_refused(done) and runner.calls == [] and 'SDO' in done.stderr
    finally:
        release.set()
        holder.join()


def test_begin_waits_for_the_sdo_in_flight_then_later_sdos_see_the_marker():
    """표시는 도는 SDO 가 끝난 뒤에 선다 · 그 뒤 SDO 는 모두 표시를 본다(빈틈 없음)"""
    runner = Runner(delay=0.2)
    worker = threading.Thread(target=em.run, args=(UPLOAD,), kwargs={'runner': runner})
    worker.start()
    while not runner.calls:
        time.sleep(0.005)
    assert em.begin(os.getpid()) is True
    finished_first = runner.active == 0
    worker.join()
    assert finished_first
    assert em.configuring()
    assert em.is_refused(em.run(UPLOAD, runner=runner, text=True))
    assert em.finish(os.getpid()) and not em.configuring()


def test_guarded_wraps_once():
    runner = Runner()
    wrapped = em.guarded(runner)
    assert em.guarded(wrapped) is wrapped
    _mark()
    assert em.is_refused(wrapped(UPLOAD, text=True)) and runner.calls == []


def test_parse_slaves_reads_state_and_error_flag():
    text = '0  0:0  OP  +  MADLN15BE\n1  0:1  PREOP  E  MADLN15BE\n2  101:0  SAFEOP  +  x\n'
    assert em.parse_slaves(text) == [(0, 'OP', False), (1, 'PREOP', True), (2, 'SAFEOP', False)]


# -- watch · 설정이 끝나면 표시를 지운다 ------------------------------------- #

class Bus:
    def __init__(self, frames):
        self.frames = list(frames)

    def __call__(self, command, **_kwargs):
        text = self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]
        return subprocess.CompletedProcess(command, 0, stdout=text, stderr='')


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


PRE = '0  0:0  PREOP  +  a\n1  0:1  PREOP  +  b\n'
SAFE = '0  0:0  SAFEOP  +  a\n1  0:1  PREOP  +  b\n'
OP = '0  0:0  OP  +  a\n1  0:1  OP  +  b\n'
STUCK = '0  0:0  OP  +  a\n1  0:1  PREOP  E  b\n'


def _watch(frames, *, alive=lambda _pid: True, timeout=em.CONFIGURE_TIMEOUT_SEC):
    clock = Clock()
    logs = []
    reason = em.watch(
        os.getpid(), timeout_sec=timeout, runner=Bus(frames), clock=clock, sleep=clock.sleep,
        alive=alive, log=logs.append,
    )
    return reason, clock, logs


def test_watch_clears_the_marker_once_all_slaves_are_op():
    em.begin(os.getpid())
    reason, clock, logs = _watch([PRE] * 6 + [SAFE] * 2 + [OP])
    assert reason == 'all_op' and not em.configuring()
    assert '2대 OP' in logs[0]
    assert clock.now - 1000.0 >= 4.0 + em.OP_HOLD_SEC      # PREOP 동안은 계속 표시


def test_watch_gives_up_on_a_slave_stuck_in_error():
    em.begin(os.getpid())
    reason, _clock, logs = _watch([PRE, STUCK])
    assert reason == 'error' and not em.configuring()
    assert '1:PREOP+E' in logs[0] and '제어 전원' in logs[0]


def test_watch_stops_when_the_motor_program_ends_or_time_runs_out():
    em.begin(os.getpid())
    assert _watch([PRE], alive=lambda _pid: False)[0] == 'owner_exited'
    assert em.read_marker() is None
    em.begin(os.getpid())
    assert _watch([PRE], timeout=5.0)[0] == 'timeout'
    assert em.read_marker() is None


def test_watch_leaves_a_newer_marker_alone():
    """다시 시작한 모터 프로그램의 표시는 지우지 않는다"""
    em.begin(424242)
    assert _watch([PRE])[0] == 'replaced'
    assert em.read_marker()['owner_pid'] == 424242


def test_motor_script_raises_the_marker_before_launch_and_watches_after():
    script = (Path(__file__).resolve().parents[2] / 'web_bridge' / 'deploy' / 'run_motor_service.sh').read_text(
        encoding='utf-8')
    begin = script.index('ethercat_mailbox.py')
    assert script.index('begin --owner "$$"') < script.index('if ! recover_ethercat_errors_before_launch')
    assert begin < script.index('watch --owner "$$"') < script.index('exec "${MOTOR_EXECUTABLE}"')


# -- 수정 목록 139 E-1 · 앱솔루트 설정이 버스를 혼자 쓰는 동안 ------------------------------ #

def test_exclusive_hold_blocks_other_processes_but_not_the_holder():
    """세운 프로세스 자신의 SDO 는 나가고 · 다른 프로세스(감시 노드)는 `configuring()` 참 · 돌려받음"""
    runner = Runner()
    assert em.hold('absolute_setup') is True
    assert not em.configuring()                                   # 나(웹 브리지)는 그대로 보낸다
    assert em.run(UPLOAD, runner=runner).returncode == 0
    assert len(runner.calls) == 1

    other = os.getppid()                                          # 살아 있는 다른 프로세스 · `run()` 은 진짜로 살아 있나 본다(pid+1 은 가끔 없음)
    assert em.held_by_other(me=other, alive=lambda _pid: True)    # 감시 노드 쪽에서 보면
    marker = em.read_exclusive()
    marker['owner_pid'] = other                                   # 다른 프로세스가 세운 표시
    em._write_json(em.EXCLUSIVE_NAME, marker)
    assert em.configuring(alive=lambda _pid: True)
    refused = em.run(UPLOAD, runner=runner, text=True)
    assert em.is_refused(refused) and '앱솔루트 설정 중' in refused.stderr
    assert len(runner.calls) == 1
    assert em.release() is False                                  # 남의 표시는 안 내림
    assert em.release(other) is True and not em.configuring(alive=lambda _pid: True)


def test_exclusive_hold_expires_and_ignores_a_dead_owner():
    em.hold('absolute_setup', owner=os.getpid() + 7, timeout_sec=5.0)
    now = time.monotonic()
    assert em.held_by_other(now=now, alive=lambda _pid: True)
    assert not em.held_by_other(now=now + 6.0, alive=lambda _pid: True)   # 마감 지남(못 늘림)
    assert not em.held_by_other(now=now, alive=lambda _pid: False)        # 세운 프로세스가 죽음


def test_exclusive_hold_refresh_keeps_start_time_and_motor_marker_is_separate():
    em.hold('absolute_setup', timeout_sec=5.0)
    started = em.read_exclusive()['started_at']
    em.begin(os.getpid() + 3)                                     # 모터 프로그램 재시작 · 다른 파일
    em.hold('absolute_setup', wait_for_running=False)
    assert em.read_exclusive()['started_at'] == started
    assert em.read_marker()['owner_pid'] == os.getpid() + 3
    assert em.release() is True and em.read_marker() is not None  # 모터 표시는 그대로
