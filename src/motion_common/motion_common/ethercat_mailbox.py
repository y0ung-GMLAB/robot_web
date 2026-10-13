"""EtherCAT 메일박스(SDO) · 우리 코드는 한 번에 하나 · 마스터가 버스를 설정하는 동안엔 안 보낸다 · 수정 목록 125

왜 (실물 U-1 · 2026-10-13)
    PC 부팅 때 모터 프로그램(motor_manager)이 PREOP 인 드라이브에 부팅 설정 SDO(param_file · PDO)를 쓰는
    사이 감시 노드의 앱솔루트 확인이 같은 드라이브에 `ethercat upload` 를 보내 메일박스가 엉켰다 ·
    커널 「Received upload response for wrong SDO」 → 마스터 「SDO configuration failed」 → 슬레이브가
    PREOP + E 에 멈추고 시작 스크립트의 오류 플래그 해제로도 안 풀렸다 · PC 만 재부팅 2/2 · 웹을 끄고
    부팅하면 0 · 이미 OP 일 때도 웹이 뜰 때 우리 프로세스 두 곳이 같은 드라이브를 동시에 읽어 1 번.

두 가지를 여기 한 곳에서
    ① 버스 설정 중 표시 · 모터 실행 스크립트(`run_motor_service.sh`)가 motor_manager 를 띄우기 **직전에**
       `begin` 으로 표시 파일을 쓰고, 백그라운드 `watch` 가 슬레이브가 모두 OP 로 자리 잡거나(OP_HOLD_SEC) ·
       설정이 실패해 오류(E)로 굳거나 · CONFIGURE_TIMEOUT_SEC 이 지나거나 · 모터 프로그램이 끝나면 지운다 ·
       표시가 살아 있는 동안 우리 SDO 는 보내지 않고 「버스 설정 중 · 잠시 뒤 다시」 로 돌려준다.
    ② 한 번에 하나 · 우리 프로세스(감시 노드 · 웹 브리지 · 검색) 모두 SDO 를 이 파일의 잠금
       (`fcntl.flock` · 마스터 하나로 묶음 · 단순하게) 안에서만 보낸다 · `begin` 도 같은 잠금을 잡고 표시를
       쓰므로 도는 SDO 가 끝난 뒤에 표시가 서고, 그 뒤 SDO 는 모두 표시를 본다(빈틈 없음).

표시가 낡지 않게
    표시 파일에 모터 프로그램 pid(`$$` · exec 해도 같다)와 마감(monotonic · 프로세스끼리 같은 시계)을 적는다 ·
    pid 가 죽었거나 마감이 지났으면 없는 것으로 본다 · 모터 서비스를 멈추면 같은 cgroup 의 `watch` 도 죽고
    표시가 남지만 pid 가 죽어 무시된다 · 자리는 `$XDG_RUNTIME_DIR/robot-web`(재부팅하면 비워짐 · start_limit 과 같음).

메일박스를 쓰는 명령만 · `upload` · `download` · `foe_*` · `soe_*` · EEPROM 쓰기(`alias` · `sii_write`) ·
`slaves` · `master` · `sii_read` · `reg_*` 는 메일박스가 아니라 그대로 보낸다.

실행 스크립트가 ROS 를 켜기 전에 부르므로 표준 라이브러리만 쓴다 · `net_ready.py` 와 같은 규칙.

    python3 .../ethercat_mailbox.py begin --owner <pid>
    python3 .../ethercat_mailbox.py watch --owner <pid>
    python3 .../ethercat_mailbox.py status
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows · 시험용 · 프로세스 안 잠금만
    fcntl = None

#: 메일박스를 쓰는 `ethercat` 하위 명령
MAILBOX_COMMANDS = frozenset({
    'upload', 'download', 'foe_read', 'foe_write', 'soe_read', 'soe_write', 'alias', 'sii_write',
})

#: 잠금을 기다리는 최대 시간 · SDO 하나가 길어야 제한 시간(2~10 s)이라 그 몇 개
LOCK_WAIT_SEC = 15.0
#: 보내지 않고 돌려준 결과의 종료 코드 · EX_TEMPFAIL · 부른 쪽이 「나중에 다시」 로 구분
REFUSED_EXIT = 75
CONFIGURING_MESSAGE = '버스 설정 중 · 모터 프로그램이 드라이브를 설정하고 있습니다 · 잠시 뒤 다시'
BUSY_MESSAGE = '다른 SDO 요청이 끝나지 않았습니다 · 잠시 뒤 다시'

#: `watch` · 표시를 이만큼 넘게 두지 않는다 · 부팅 때 ROS 기동 + 설정이 보통 10~20 s
CONFIGURE_TIMEOUT_SEC = 90.0
#: 모든 슬레이브가 OP 로 이만큼 그대로면 설정 끝
OP_HOLD_SEC = 2.0
#: 오류(E) 슬레이브가 있고 상태가 이만큼 그대로면 설정 실패로 끝 · 마스터는 E 인 슬레이브를 다시 설정하지 않는다
ERROR_HOLD_SEC = 10.0
POLL_SEC = 0.5
SLAVES_TIMEOUT_SEC = 3.0

MARKER_NAME = 'ethercat-configuring.json'
LOCK_NAME = 'ethercat-mailbox.lock'

#: `ethercat slaves` 한 줄 · `0  0:0  OP  +  MADLN15BE`
_SLAVE_LINE = re.compile(r'^\s*(\d+)\s+\d+:\d+\s+([A-Za-z]+)\s+([+E])', re.MULTILINE)

_THREAD_LOCK = threading.Lock()


# -- 자리 ------------------------------------------------------------------ #

def run_dir() -> str:
    """`$ROBOT_WEB_RUN_DIR`(시험) → `$XDG_RUNTIME_DIR/robot-web` → `/tmp/robot-web`"""
    explicit = os.environ.get('ROBOT_WEB_RUN_DIR')
    if explicit:
        return explicit
    base = os.environ.get('XDG_RUNTIME_DIR') or ('/tmp' if os.name == 'posix' else tempfile.gettempdir())
    return os.path.join(base, 'robot-web')


def marker_path() -> str:
    return os.path.join(run_dir(), MARKER_NAME)


def lock_path() -> str:
    return os.path.join(run_dir(), LOCK_NAME)


# -- 버스 설정 중 표시 ------------------------------------------------------ #

def pid_alive(pid: int) -> bool:
    """POSIX 만 확인 · Windows 의 `os.kill(pid, 0)` 은 Ctrl+C 를 보내므로 부르지 않는다(살아 있다고 본다)"""
    if os.name != 'posix':
        return True
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False
    return True


def read_marker() -> Optional[Dict[str, Any]]:
    try:
        with open(marker_path(), encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def configuring(
    *, now: Optional[float] = None, alive: Callable[[int], bool] = pid_alive,
) -> bool:
    """모터 프로그램이 버스를 설정하는 중인가 · 표시가 있고 · 마감 전이고 · 그 프로그램이 살아 있으면"""
    marker = read_marker()
    if not marker:
        return False
    try:
        owner = int(marker.get('owner_pid'))
        deadline = float(marker.get('deadline_monotonic'))
    except (TypeError, ValueError):
        return False
    if (time.monotonic() if now is None else now) >= deadline:
        return False
    return bool(alive(owner))


def _write_marker(payload: Dict[str, Any]) -> None:
    directory = run_dir()
    os.makedirs(directory, exist_ok=True)
    temporary = os.path.join(directory, f'.{MARKER_NAME}.{os.getpid()}')
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle)
    os.replace(temporary, marker_path())


def begin(owner: int, *, timeout_sec: float = CONFIGURE_TIMEOUT_SEC, lock_wait_sec: float = LOCK_WAIT_SEC) -> bool:
    """표시를 세운다 · 도는 SDO 가 끝나길 기다린 뒤(같은 잠금) · 못 기다려도 표시는 세운다(설정이 먼저)"""
    with mailbox_lock(lock_wait_sec) as held:
        _write_marker({
            'owner_pid': int(owner),
            'started_at': time.time(),
            'deadline_monotonic': time.monotonic() + float(timeout_sec),
        })
    return held


def finish(owner: int) -> bool:
    """내 표시면 지운다 · 그새 다시 시작한 모터 프로그램의 표시는 건드리지 않는다"""
    marker = read_marker()
    if not marker or marker.get('owner_pid') != int(owner):
        return False
    try:
        os.remove(marker_path())
    except OSError:
        return False
    return True


# -- 한 번에 하나 ----------------------------------------------------------- #

@contextmanager
def mailbox_lock(wait_sec: float = LOCK_WAIT_SEC) -> Iterator[bool]:
    """프로세스 안(스레드) + 프로세스 사이(flock) · 못 잡으면 False · 잠금 파일을 못 만들면 프로세스 안 잠금만"""
    deadline = time.monotonic() + max(0.0, float(wait_sec))
    if not _THREAD_LOCK.acquire(timeout=max(0.0, float(wait_sec))):
        yield False
        return
    try:
        handle = None
        if fcntl is not None:
            try:
                os.makedirs(run_dir(), exist_ok=True)
                handle = open(lock_path(), 'a+', encoding='utf-8')
            except OSError:
                handle = None
        if handle is None:
            yield True
            return
        try:
            held, busy = False, False
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held = True
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        busy = True
                        break
                    time.sleep(0.02)
                except OSError:
                    break           # 잠금이 안 되는 파일 시스템 · 프로세스 안 잠금만
            try:
                yield not busy
            finally:
                if held:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
    finally:
        _THREAD_LOCK.release()


def is_mailbox_command(command: Sequence[Any]) -> bool:
    items = [str(item) for item in command or ()]
    return len(items) >= 2 and os.path.basename(items[0]) == 'ethercat' and items[1] in MAILBOX_COMMANDS


def refused(command: Sequence[Any], message: str, kwargs: Dict[str, Any]) -> subprocess.CompletedProcess:
    """보내지 않은 결과 · `subprocess.run` 과 같은 모양 · text 가 아니면 bytes"""
    as_text = bool(kwargs.get('text') or kwargs.get('universal_newlines') or kwargs.get('encoding'))
    empty: Any = '' if as_text else b''
    return subprocess.CompletedProcess(
        list(command), REFUSED_EXIT, stdout=empty, stderr=message if as_text else message.encode('utf-8'),
    )


def is_refused(result: Any) -> bool:
    return getattr(result, 'returncode', None) == REFUSED_EXIT


def run(
    command: Sequence[Any],
    *,
    runner: Optional[Callable[..., Any]] = None,
    lock_wait_sec: float = LOCK_WAIT_SEC,
    **kwargs: Any,
) -> Any:
    """`subprocess.run` 대신 · 메일박스 명령이면 잠금 안에서 · 버스 설정 중이면 보내지 않는다"""
    call = runner or (lambda *args, **kw: subprocess.run(*args, **kw))   # 부를 때 찾는다 · 시험 patch 가 먹게
    if not is_mailbox_command(command):
        return call(command, **kwargs)
    with mailbox_lock(lock_wait_sec) as held:
        if not held:
            return refused(command, BUSY_MESSAGE, kwargs)
        if configuring():
            return refused(command, CONFIGURING_MESSAGE, kwargs)
        return call(command, **kwargs)


def guarded(runner: Optional[Callable[..., Any]] = None) -> Callable[..., Any]:
    """`runner(command, **kwargs)` 를 `run` 으로 감싼다 · 두 번 감싸지 않는다"""
    if getattr(runner, '_ethercat_mailbox_guarded', False):
        return runner

    def call(command: Sequence[Any], **kwargs: Any) -> Any:
        return run(command, runner=runner, **kwargs)

    call._ethercat_mailbox_guarded = True   # type: ignore[attr-defined]
    return call


# -- 설정이 끝났나 보기 (`watch`) -------------------------------------------- #

def parse_slaves(text: str) -> List[Tuple[int, str, bool]]:
    """`ethercat slaves` → (링 위치, 상태, 오류 E)"""
    return [
        (int(position), state.upper(), flag == 'E')
        for position, state, flag in _SLAVE_LINE.findall(text or '')
    ]


def watch(
    owner: int,
    *,
    timeout_sec: float = CONFIGURE_TIMEOUT_SEC,
    runner: Optional[Callable[..., Any]] = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    alive: Callable[[int], bool] = pid_alive,
    log: Callable[[str], None] = lambda message: print(message, flush=True),
) -> str:
    """설정이 끝날 때까지 보고 표시를 지운다 · 끝난 까닭을 돌려준다"""
    call = runner or (lambda *args, **kw: subprocess.run(*args, **kw))
    started = clock()
    deadline = started + float(timeout_sec)
    last: Optional[Tuple[Tuple[int, str, bool], ...]] = None
    since = started
    reason = ''
    while True:
        marker = read_marker()
        if not marker or marker.get('owner_pid') != int(owner):
            return 'replaced'                  # 다시 시작한 모터 프로그램이 새 표시를 세웠다
        now = clock()
        if not alive(int(owner)):
            reason = 'owner_exited'
            break
        if now >= deadline:
            reason = 'timeout'
            break
        try:
            done = call(['ethercat', 'slaves'], check=False, capture_output=True, text=True,
                        timeout=SLAVES_TIMEOUT_SEC)
            slaves = tuple(parse_slaves(done.stdout or '')) if done.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            slaves = None
        if slaves is not None:
            if slaves != last:
                last, since = slaves, now
            held = now - since
            if slaves and all(state == 'OP' for _p, state, _e in slaves) and held >= OP_HOLD_SEC:
                reason = 'all_op'
                break
            if any(error for _p, _s, error in slaves) and held >= ERROR_HOLD_SEC:
                reason = 'error'
                break
        sleep(POLL_SEC)
    finish(owner)
    elapsed = clock() - started
    if reason == 'all_op':
        log(f'EtherCAT 버스 설정 끝 · 슬레이브 {len(last or ())}대 OP ({elapsed:.1f} s)')
    elif reason == 'error':
        stuck = ', '.join(f'{p}:{s}+E' for p, s, e in last or () if e)
        log(f'EtherCAT 버스 설정 실패로 봄 · {stuck} · 그 드라이브 제어 전원을 껐다 켜세요 ({elapsed:.1f} s)')
    elif reason == 'timeout':
        log(f'EtherCAT 버스 설정 표시 시간 초과 ({timeout_sec:.0f} s) · 지금 상태 '
            + (', '.join(f'{p}:{s}{"+E" if e else ""}' for p, s, e in last or ()) or '슬레이브 없음'))
    return reason


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description='EtherCAT 메일박스 · 버스 설정 중 표시 · 수정 목록 125')
    parser.add_argument('action', choices=('begin', 'watch', 'finish', 'status'))
    parser.add_argument('--owner', type=int, default=0)
    parser.add_argument('--timeout', type=float, default=CONFIGURE_TIMEOUT_SEC)
    args = parser.parse_args(argv)
    if args.action == 'status':
        marker = read_marker()
        print(json.dumps({'configuring': configuring(), 'marker': marker, 'path': marker_path()}, ensure_ascii=False))
        return 0
    if args.owner <= 0:
        parser.error('--owner 가 필요합니다')
    try:
        if args.action == 'begin':
            if not begin(args.owner, timeout_sec=args.timeout):
                print('EtherCAT 메일박스 잠금을 못 잡았지만 버스 설정 표시는 세웠습니다', flush=True)
        elif args.action == 'watch':
            watch(args.owner, timeout_sec=args.timeout)
        else:
            finish(args.owner)
    except OSError as exc:
        # 표시를 못 세워도 모터는 떠야 한다
        print(f'EtherCAT 버스 설정 표시 실패(모터는 그대로 시작): {exc}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
