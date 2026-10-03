"""웹 터미널 · 이 PC 의 셸과 btop 을 브라우저 안에서 연다 · §6-311

**다른 PC 의 터미널에 URL 로 닿는 길이 없었다.**

현장 PC 는 모니터 없이 돌고, 사람은 다른 PC 의 브라우저 앞에 앉아 있다 ·
깃을 받거나 로그를 보려면 SSH 클라이언트를 따로 열고 주소·계정을 외워야
했다 · 웹 화면은 이미 모든 PC 에 열려 있으니 그 안에 터미널 하나를 둔다.

구조 · 브라우저 xterm.js ↔ WebSocket ↔ 여기 ↔ PTY ↔ `bash -l` 또는 `btop`

- 소켓 하나 = PTY 하나 = 프로세스 하나 · 소켓이 끊기면 프로세스도 끝낸다
- 출력은 **바이트 그대로**(binary frame) 내보낸다 · 글자로 바꾸면 여러
  바이트짜리 글자가 조각 경계에서 깨진다 · 해석은 xterm.js 가 한다
- 입력·크기 변경은 JSON 글자 프레임으로 받는다
- `pty.fork` 를 쓴다 · `subprocess` 로 띄우면 제어 터미널이 없어서 Ctrl+C
  가 셸 안의 명령을 세우지 못한다

**이것은 프로그램을 돌리는 계정의 셸이다.** 웹 화면을 열 수 있는 사람은 누구나
이 PC 에서 명령을 칠 수 있다 · 지금 화면이 이미 모터를 움직이고 프로그램을
재시작할 수 있으므로 같은 울타리 안이지만, 외부망에 노출된 PC 라면
`MOTION_WEB_TERMINAL=0` 으로 끈다.

업무는 여기, HTTP 는 `routes/terminal_routes.py` 가 한다 · §6-190.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import pty
import shutil
import signal
import struct
import termios
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from fastapi import WebSocketDisconnect

#: 소켓이 먼저 끊겼을 때 나는 예외들 · 오류가 아니라 「끝」이다
SOCKET_GONE = (WebSocketDisconnect, ConnectionError, RuntimeError)

#: 끄는 스위치 · 비어 있거나 다른 값이면 켜진 것이다
DISABLE_ENV = 'MOTION_WEB_TERMINAL'

#: 화면이 고를 수 있는 프로그램 · 이름 → (명령, 설명, 설치 안내)
#: **여기 적힌 것만** 띄운다 · 명령을 밖에서 받지 않는다
PROGRAMS: Dict[str, Dict[str, Any]] = {
    'shell': {
        'argv': ['bash', '-l'],
        'title': '터미널',
        'install_hint': '',
    },
    'btop': {
        'argv': ['btop'],
        'title': 'btop',
        'install_hint': 'sudo apt install btop',
    },
}

#: 한 번에 PTY 에서 읽는 크기
READ_SIZE = 65536

#: 소켓이 끊긴 뒤 프로세스가 스스로 끝나기를 기다리는 시간 · 지나면 KILL
EXIT_GRACE_SEC = 0.5

#: 기본 터미널 크기 · 화면이 첫 크기를 못 보냈을 때
DEFAULT_COLS = 80
DEFAULT_ROWS = 24


def terminal_enabled(environ: Optional[Dict[str, str]] = None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get(DISABLE_ENV, '1')).strip() != '0'


def terminal_programs(
    programs: Optional[Dict[str, Dict[str, Any]]] = None,
    environ: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """화면에 보여 줄 목록 · 어느 프로그램이 이 PC 에 깔려 있는가."""
    table = PROGRAMS if programs is None else programs
    listing: List[Dict[str, Any]] = []
    for name, spec in table.items():
        executable = str(spec['argv'][0])
        found = shutil.which(executable) is not None
        listing.append({
            'id': name,
            'title': spec.get('title', name),
            'available': found,
            'executable': executable,
            'install_hint': '' if found else str(spec.get('install_hint') or ''),
        })
    return {
        'success': True,
        'enabled': terminal_enabled(environ),
        'programs': listing,
    }


def _child_environment(base: Dict[str, str]) -> Dict[str, str]:
    env = dict(base)
    env['TERM'] = 'xterm-256color'
    env['COLORTERM'] = 'truecolor'
    env.setdefault('LANG', 'C.UTF-8')
    return env


class TerminalSession:
    """PTY 하나와 그 안의 프로세스 하나.

    소켓과 무관하게 시험할 수 있도록 떼어 놓았다 · `spawn` → `write` /
    `resize` → `read_available` → `close`.
    """

    def __init__(self, argv: Sequence[str], cwd: Optional[Path], environ: Dict[str, str]) -> None:
        self.argv = [str(part) for part in argv]
        self.cwd = cwd
        self.environ = environ
        self.pid: Optional[int] = None
        self.fd: Optional[int] = None
        self.exit_code: Optional[int] = None

    def spawn(self, cols: int = DEFAULT_COLS, rows: int = DEFAULT_ROWS) -> None:
        pid, fd = pty.fork()
        if pid == 0:  # 자식 · 여기서 돌아가면 안 된다
            try:
                if self.cwd is not None:
                    os.chdir(str(self.cwd))
            except OSError:
                pass
            try:
                os.execvpe(self.argv[0], self.argv, self.environ)
            except OSError as exc:
                os.write(2, f'실행 실패: {self.argv[0]} · {exc}\r\n'.encode('utf-8', 'replace'))
            os._exit(127)
        self.pid = pid
        self.fd = fd
        self.resize(cols, rows)

    def resize(self, cols: int, rows: int) -> None:
        if self.fd is None:
            return
        cols = max(2, min(int(cols), 1000))
        rows = max(2, min(int(rows), 500))
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))

    def write(self, data: bytes) -> None:
        if self.fd is None or not data:
            return
        view = memoryview(data)
        while view:
            written = os.write(self.fd, view)
            view = view[written:]

    def read_available(self) -> Optional[bytes]:
        """읽을 수 있는 만큼 · 프로세스가 끝나 PTY 가 닫혔으면 `None`."""
        if self.fd is None:
            return None
        try:
            chunk = os.read(self.fd, READ_SIZE)
        except OSError:
            return None
        return chunk or None

    def alive(self) -> bool:
        if self.pid is None or self.exit_code is not None:
            return False
        try:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            self.exit_code = -1
            return False
        if pid == 0:
            return True
        self.exit_code = os.waitstatus_to_exitcode(status)
        return False

    def close(self) -> Optional[int]:
        """PTY 를 닫고 프로세스를 끝낸다 · 종료 코드."""
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        if self.pid is None:
            return self.exit_code
        if self.alive():
            self._signal(signal.SIGHUP)
            deadline = time.monotonic() + EXIT_GRACE_SEC
            while self.alive() and time.monotonic() < deadline:
                time.sleep(0.02)
        if self.alive():
            self._signal(signal.SIGKILL)
            try:
                _pid, status = os.waitpid(self.pid, 0)
                self.exit_code = os.waitstatus_to_exitcode(status)
            except ChildProcessError:
                self.exit_code = -1
        return self.exit_code

    def _signal(self, signo: int) -> None:
        if self.pid is None:
            return
        try:
            os.killpg(self.pid, signo)
        except ProcessLookupError:
            pass
        except PermissionError:
            os.kill(self.pid, signo)


def _program_spec(program: str, programs: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return programs.get(str(program or 'shell').strip().lower())


def _dimension(value: Any, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback


async def run_terminal_socket(
    bridge: Any,
    websocket: Any,
    program: str = 'shell',
    cols: Any = None,
    rows: Any = None,
    programs: Optional[Dict[str, Dict[str, Any]]] = None,
    environ: Optional[Dict[str, str]] = None,
) -> None:
    """소켓 하나를 끝까지 돌본다 · 열고 · 잇고 · 끊기면 치운다."""
    await websocket.accept()
    table = PROGRAMS if programs is None else programs
    base_env = dict(os.environ if environ is None else environ)

    async def send_json(payload: dict) -> None:
        await websocket.send_text(json.dumps(payload, ensure_ascii=False))

    async def refuse(message: str) -> None:
        await send_json({'type': 'error', 'message': message})
        await websocket.close(code=1008)

    if not terminal_enabled(base_env):
        await refuse(f'웹 터미널이 꺼져 있습니다 · {DISABLE_ENV}=0')
        return
    spec = _program_spec(program, table)
    if spec is None:
        await refuse(f'모르는 프로그램입니다: {program}')
        return
    if shutil.which(str(spec['argv'][0])) is None:
        hint = str(spec.get('install_hint') or '')
        await refuse(f'{spec["argv"][0]} 이(가) 이 PC 에 없습니다' + (f' · {hint}' if hint else ''))
        return

    cwd = getattr(bridge, 'workspace_root', None)
    session = TerminalSession(spec['argv'], Path(cwd) if cwd else None, _child_environment(base_env))
    loop = asyncio.get_running_loop()
    output: asyncio.Queue = asyncio.Queue()

    def on_readable() -> None:
        chunk = session.read_available()
        if chunk is None:
            loop.remove_reader(session.fd)
            output.put_nowait(None)
            return
        output.put_nowait(chunk)

    try:
        await asyncio.to_thread(
            session.spawn, _dimension(cols, DEFAULT_COLS), _dimension(rows, DEFAULT_ROWS)
        )
    except OSError as exc:
        await refuse(f'터미널을 열지 못했습니다: {exc}')
        return
    loop.add_reader(session.fd, on_readable)
    await send_json({'type': 'ready', 'program': spec.get('title', program), 'pid': session.pid})

    async def pump_output() -> None:
        while True:
            chunk = await output.get()
            if chunk is None:
                code = await asyncio.to_thread(session.close)
                await send_json({'type': 'exit', 'code': code})
                return
            await websocket.send_bytes(chunk)

    async def pump_input() -> None:
        while True:
            event = await websocket.receive()
            kind = event.get('type')
            if kind == 'websocket.disconnect':
                return
            try:
                if event.get('bytes') is not None:
                    session.write(event['bytes'])
                    continue
            except OSError:
                return
            text = event.get('text')
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            if message.get('type') == 'input':
                try:
                    session.write(str(message.get('data') or '').encode('utf-8'))
                except OSError:
                    return
            elif message.get('type') == 'resize':
                session.resize(
                    _dimension(message.get('cols'), DEFAULT_COLS),
                    _dimension(message.get('rows'), DEFAULT_ROWS),
                )

    output_task = asyncio.create_task(pump_output())
    input_task = asyncio.create_task(pump_input())
    try:
        done, pending = await asyncio.wait(
            {output_task, input_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, SOCKET_GONE):
                raise exc
    finally:
        if session.fd is not None:
            try:
                loop.remove_reader(session.fd)
            except (ValueError, OSError):
                pass
        await asyncio.to_thread(session.close)
        try:
            await websocket.close()
        except SOCKET_GONE:
            pass
