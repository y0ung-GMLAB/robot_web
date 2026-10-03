"""웹 터미널 · 셸과 btop 을 브라우저 안에서 연다 · §6-311

지키는 것 셋 · **목록에 적힌 프로그램만** 띄운다 · 소켓이 끊기면 **프로세스도
끝난다** · 출력은 바이트 그대로 나간다 (여러 바이트 글자가 조각 경계에서
안 깨진다).

실제 PTY 를 띄운다 · `sh` 만 있으면 된다 · btop 은 없어도 통과해야 한다
(현장 PC 에 없을 수 있고, 그때 화면이 「없다」고 말하는 것이 이 기능의 일부다).
"""

import fcntl
import json
import os
import struct
import termios
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from motion_web_bridge import terminal_service
from motion_web_bridge.routes.terminal_routes import register_terminal_routes
from motion_web_bridge.terminal_service import (
    TerminalSession,
    terminal_enabled,
    terminal_programs,
)

#: 어느 PC 에도 없을 이름
MISSING = 'definitely-missing-binary-xyz'

#: 시험용 프로그램 · 준비됐다고 말하고 받은 것을 되돌려 준다
ECHO_PROGRAM = {
    'argv': ['sh', '-c', 'echo READY; cat'],
    'title': '시험 셸',
    'install_hint': '',
}


class _Bridge:
    def __init__(self, root: Path) -> None:
        self.workspace_root = root


def _read_until(session: TerminalSession, needle: bytes, timeout_sec: float = 3.0) -> bytes:
    import select
    collected = b''
    deadline = time.monotonic() + timeout_sec
    while needle not in collected and time.monotonic() < deadline:
        ready, _, _ = select.select([session.fd], [], [], 0.1)
        if not ready:
            continue
        chunk = session.read_available()
        if chunk is None:
            break
        collected += chunk
    assert needle in collected, f'{needle!r} 을 받지 못했습니다 · 받은 것: {collected!r}'
    return collected


def _process_gone(pid: int, timeout_sec: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        # 좀비면 아직 살아 있는 것으로 보인다 · 거둔 뒤 다시 본다
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return True
        time.sleep(0.05)
    return False


# --------------------------------------------------------------------------- #
# 목록 · 스위치
# --------------------------------------------------------------------------- #

def test_the_listing_says_which_programs_this_pc_has():
    table = {
        'shell': {'argv': ['sh'], 'title': '셸', 'install_hint': ''},
        'btop': {'argv': [MISSING], 'title': 'btop', 'install_hint': 'sudo apt install btop'},
    }
    payload = terminal_programs(table, environ={})
    assert payload['success'] is True
    assert payload['enabled'] is True
    by_id = {item['id']: item for item in payload['programs']}
    assert by_id['shell']['available'] is True
    assert by_id['shell']['install_hint'] == ''
    assert by_id['btop']['available'] is False
    assert by_id['btop']['install_hint'] == 'sudo apt install btop'


def test_the_real_table_offers_a_shell_and_btop():
    assert set(terminal_service.PROGRAMS) == {'shell', 'btop'}
    assert terminal_service.PROGRAMS['btop']['install_hint'], 'btop 설치 안내가 비어 있다'


def test_the_switch_only_turns_it_off_with_a_zero():
    assert terminal_enabled({}) is True
    assert terminal_enabled({'MOTION_WEB_TERMINAL': '1'}) is True
    assert terminal_enabled({'MOTION_WEB_TERMINAL': ''}) is True
    assert terminal_enabled({'MOTION_WEB_TERMINAL': '0'}) is False
    assert terminal_programs({}, environ={'MOTION_WEB_TERMINAL': '0'})['enabled'] is False


# --------------------------------------------------------------------------- #
# PTY 세션
# --------------------------------------------------------------------------- #

def test_a_session_echoes_what_it_is_given_and_dies_when_closed(tmp_path):
    session = TerminalSession(ECHO_PROGRAM['argv'], tmp_path, dict(os.environ, TERM='xterm'))
    session.spawn(cols=100, rows=30)
    try:
        _read_until(session, b'READY')
        session.write(b'hello\n')
        _read_until(session, b'hello')
        assert session.alive() is True
    finally:
        pid = session.pid
        code = session.close()
    assert session.alive() is False
    assert code is not None
    assert _process_gone(pid), '소켓을 닫았는데 셸이 살아 있다'


def test_the_window_size_reaches_the_pty(tmp_path):
    session = TerminalSession(['sh', '-c', 'sleep 5'], tmp_path, dict(os.environ))
    session.spawn(cols=132, rows=43)
    try:
        packed = fcntl.ioctl(session.fd, termios.TIOCGWINSZ, struct.pack('HHHH', 0, 0, 0, 0))
        rows, cols, _, _ = struct.unpack('HHHH', packed)
        assert (rows, cols) == (43, 132)
        session.resize(80, 24)
        packed = fcntl.ioctl(session.fd, termios.TIOCGWINSZ, struct.pack('HHHH', 0, 0, 0, 0))
        rows, cols, _, _ = struct.unpack('HHHH', packed)
        assert (rows, cols) == (24, 80)
    finally:
        session.close()


def test_the_shell_starts_in_the_workspace(tmp_path):
    session = TerminalSession(['sh', '-c', 'pwd'], tmp_path, dict(os.environ))
    session.spawn()
    try:
        output = _read_until(session, str(tmp_path).encode())
        assert str(tmp_path).encode() in output
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# 소켓
# --------------------------------------------------------------------------- #

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv('MOTION_WEB_TERMINAL', raising=False)
    monkeypatch.setitem(terminal_service.PROGRAMS, 'shell', ECHO_PROGRAM)
    app = FastAPI()
    register_terminal_routes(app, _Bridge(tmp_path))
    return TestClient(app)


def _receive_until(websocket, needle: bytes, timeout_sec: float = 3.0) -> bytes:
    collected = b''
    deadline = time.monotonic() + timeout_sec
    while needle not in collected and time.monotonic() < deadline:
        message = websocket.receive()
        if message.get('bytes') is not None:
            collected += message['bytes']
        elif message.get('text'):
            collected += message['text'].encode('utf-8')
    assert needle in collected, f'{needle!r} 을 받지 못했습니다 · 받은 것: {collected!r}'
    return collected


def test_the_socket_streams_bytes_both_ways_and_ends_the_shell(client):
    with client.websocket_connect('/ws/terminal?program=shell&cols=90&rows=25') as websocket:
        ready = json.loads(websocket.receive_text())
        assert ready['type'] == 'ready'
        assert ready['program'] == '시험 셸'
        pid = ready['pid']
        _receive_until(websocket, b'READY')
        websocket.send_text(json.dumps({'type': 'input', 'data': 'ping 한글\n'}))
        _receive_until(websocket, 'ping 한글'.encode('utf-8'))
        websocket.send_text(json.dumps({'type': 'resize', 'cols': 120, 'rows': 40}))
        assert not _process_gone(pid, timeout_sec=0.2), '열려 있는데 셸이 죽었다'
    assert _process_gone(pid), '소켓이 끊겼는데 셸이 살아 있다'


def test_an_unknown_program_is_refused(client):
    with client.websocket_connect('/ws/terminal?program=rm-rf') as websocket:
        message = json.loads(websocket.receive_text())
        assert message['type'] == 'error'
        assert '모르는 프로그램' in message['message']
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_text()


def test_a_missing_binary_is_refused_with_the_install_hint(client, monkeypatch):
    monkeypatch.setitem(terminal_service.PROGRAMS, 'btop', {
        'argv': [MISSING], 'title': 'btop', 'install_hint': 'sudo apt install btop',
    })
    with client.websocket_connect('/ws/terminal?program=btop') as websocket:
        message = json.loads(websocket.receive_text())
        assert message['type'] == 'error'
        assert MISSING in message['message']
        assert 'sudo apt install btop' in message['message']


def test_the_switch_turns_the_socket_away(client, monkeypatch):
    monkeypatch.setenv('MOTION_WEB_TERMINAL', '0')
    with client.websocket_connect('/ws/terminal?program=shell') as websocket:
        message = json.loads(websocket.receive_text())
        assert message['type'] == 'error'
        assert 'MOTION_WEB_TERMINAL=0' in message['message']
    assert client.get('/api/terminal/programs').json()['enabled'] is False


def test_the_listing_route_answers(client):
    payload = client.get('/api/terminal/programs').json()
    assert payload['success'] is True
    assert {item['id'] for item in payload['programs']} == {'shell', 'btop'}
