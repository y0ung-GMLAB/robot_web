"""수동 페이더 WebSocket 세션 · 길목(`stream_routes`)에서 떼어낸 업무.

규약 · JSON 한 덩이씩:

    ← {type:'hello', mapping_file_id?, base_mapping_revision?}
    → {type:'hello_ok'}  |  {type:'error', message}  (보내고 닫는다)
    ← {type:'target', axis, target_rad, motion_id?, motion_rad?, source?}   # 모터 rad (수정 목록 6) · source fader|dial
    ← {type:'release', axes:[..]}        # 놓음 → 마지막 목표까지 천천히 간 뒤 끝 (수정 목록 126)
    ← {type:'stop', axes:[..]}           # 세움 → 현재 위치에 hold (페이지를 떠남 등)
    → {type:'result', ...}               # supervisor 의 축별 마지막 승인·거부

조인트 → 모터 변환은 화면이 자기 매핑 행으로 한다 · 그래서 인사에
`base_mapping_revision` 을 받아 **낡은 변환표**(다른 화면이 매핑을 고친 뒤)
는 그 자리에서 거절한다.

수동 모드에서만 받는다(스케줄·오프는 거절) · `run_mode_gate.manual_control_block_reason` ·
흐르는 중에도 0.5초마다 다시 확인해서, 상단에서 모드를 바꾸면 소켓이 끊긴다.

끊기면(놓지 않고 창을 닫아도) 만졌던 축을 현재 위치에 세운다 · 놓은 뒤 천천히
가던 축도 · 끊긴 화면이 모르는 움직임을 남기지 않는다(수정 목록 126).

X-Touch 화면(수정 목록 156) · 인사에 `watchdog_sec` 를 주면 그 시간 동안 아무것도 안 오면
끊긴 것으로 본다(무선이 멈추기만 하고 연결은 살아 있는 경우) · 화면은 `ping` 을 흘린다 ·
녹화 요청도 이 소켓으로 · 끊기면 녹화는 마지막으로 받은 순간까지 자동 저장:

    ← {type:'ping'}                              → {type:'pong', record:{state, …}}
    ← {type:'record_start', axes:[..], name?}    → {type:'record', success, state, …}
    ← {type:'record_add', axes:[..]}             → {type:'record', …}   # 녹화 중 SELECT 로 더한 축
    ← {type:'record_stop'}                       → {type:'record', success, state:'saved', file, …}
    ← {type:'record_cancel'}                     → {type:'record', state:'idle'}
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Any

from fastapi import WebSocketDisconnect

from .run_mode_gate import manual_motion_block_reason

#: 오프 전환 재확인 주기 · 매 프레임 파일을 읽지 않는다
BLOCK_RECHECK_SEC = 0.5
#: 수신 감시 · 화면이 주는 값의 범위 · 수정 목록 156
WATCHDOG_MIN_SEC = 0.5
WATCHDOG_MAX_SEC = 10.0
DISCONNECT_REASON = '화면 연결 끊김 · 끊긴 순간까지 자동 저장'

HELLO_REQUIRED_MESSAGE = "hello 가 필요합니다 · {type:'hello'}"
STALE_MAPPING_MESSAGE = (
    '화면을 연 뒤에 조인트 매핑이 바뀌었습니다. '
    '화면을 새로 고친 뒤 페이더를 다시 잡으세요.'
)


def _stream_block_reason(bridge: Any) -> str:
    """페이더 연결·0.5초마다 · 운전 모드 + 조인트 범위 확인(수정 목록 97)"""
    reason = manual_motion_block_reason(bridge)
    if reason:
        return reason
    range_blocker = getattr(bridge, 'manual_range_blocker', None)
    return range_blocker() if callable(range_blocker) else ''


async def run_manual_stream_socket(bridge: Any, websocket: Any) -> None:
    await websocket.accept()

    async def refuse(message: str) -> None:
        await send({'type': 'error', 'message': message})
        await websocket.close()

    async def send(payload: dict) -> None:
        await websocket.send_text(json.dumps(payload, ensure_ascii=False))

    block = await asyncio.to_thread(_stream_block_reason, bridge)
    if block:
        await refuse(block)
        return

    hello = await _handshake(bridge, websocket, refuse)
    if hello is None:
        return
    await send({'type': 'hello_ok'})

    service = bridge.manual_stream
    recording = getattr(bridge, 'xtouch_recording', None)
    owner = object()     # 이 화면 · 녹화 주인
    watchdog = _watchdog_sec(hello.get('watchdog_sec'))
    touched_axes: list[int] = []
    last_block_check = time.monotonic()
    last_heard = time.time()
    try:
        while True:
            try:
                if watchdog:
                    raw = await asyncio.wait_for(websocket.receive_text(), timeout=watchdog)
                else:
                    raw = await websocket.receive_text()
            except asyncio.TimeoutError:
                # 연결은 살아 있는데 안 온다(무선 멈춤 등) · 끊긴 것으로 · 수정 목록 156
                with contextlib.suppress(Exception):   # 이미 끊겼으면 그만
                    await websocket.close()
                return
            except (WebSocketDisconnect, ConnectionError, RuntimeError):
                return
            last_heard = time.time()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue

            now = time.monotonic()
            if now - last_block_check > BLOCK_RECHECK_SEC:
                last_block_check = now
                block = await asyncio.to_thread(_stream_block_reason, bridge)
                if block:
                    await refuse(block)
                    return

            kind = message.get('type')
            if kind == 'ping':
                await send({'type': 'pong', 'record': recording.status() if recording else {'state': 'idle'}})
                continue
            if kind in RECORD_MESSAGES:
                await send({'type': 'record', **await asyncio.to_thread(
                    _record_request, recording, owner, kind, message
                )})
                continue
            if kind == 'target':
                # 축 하나 · 「사용」 매핑 줄에 없는 모터는 안 보낸다 · 수정 목록 97
                axis_blocker = getattr(bridge, 'manual_range_axis_blocker', None)
                axis_block = axis_blocker(message.get('axis')) if callable(axis_blocker) else ''
                if axis_block:
                    await send({'type': 'result', 'success': False, 'message': axis_block})
                    continue
                result = service.send_target(
                    message.get('axis'),
                    message.get('target_rad'),
                    motion_id=message.get('motion_id'),
                    motion_rad=message.get('motion_rad'),
                    source=message.get('source'),
                )
                if not result.get('success'):
                    await send({'type': 'result', **result})
                    continue
                axis = result['axis']
                if axis not in touched_axes:
                    touched_axes.append(axis)
                pending = service.pop_result(axis)
                if pending:
                    await send({'type': 'result', **pending})
            elif kind == 'release':
                # 놓음 · 멈추지 않고 마지막 목표까지 · 끊기면 그 자리에 세우도록 만진 축은 그대로 둔다
                axes = message.get('axes')
                if not isinstance(axes, list):
                    axes = [message.get('axis')]
                result = service.release(axes)
                await send({'type': 'result', **result})
            elif kind == 'stop':
                axes = message.get('axes')
                if not isinstance(axes, list):
                    axes = [message.get('axis')]
                result = service.hold(axes)
                for axis in result.get('axes', []):
                    if axis in touched_axes:
                        touched_axes.remove(axis)
                await send({'type': 'result', **result})
    finally:
        # 놓지 않고 끊긴 축은 현재 위치에 세운다
        if touched_axes:
            await asyncio.to_thread(service.hold, list(touched_axes))
        # 녹화 중에 끊기면 마지막으로 받은 순간까지 저장 · 결과는 모터 기록(운영 로그)에 · 수정 목록 156
        if recording is not None and recording.active_for(owner):
            await asyncio.to_thread(recording.stop, owner, last_heard, reason=DISCONNECT_REASON)


RECORD_MESSAGES = ('record_start', 'record_add', 'record_stop', 'record_cancel')


def _record_request(recording: Any, owner: Any, kind: str, message: dict) -> dict:
    if recording is None:
        return {'success': False, 'message': '이 서버는 녹화를 지원하지 않습니다'}
    if kind == 'record_start':
        return recording.start(owner, message.get('axes'), message.get('name'))
    if kind == 'record_add':
        return recording.add_axes(owner, message.get('axes'))
    if kind == 'record_stop':
        return recording.stop(owner)
    return recording.cancel(owner)


def _watchdog_sec(value: Any) -> float:
    """화면이 준 수신 감시 시간 · 없거나 틀리면 0(감시 안 함 · 웹 페이더·다이얼은 그대로)"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not number > 0.0:
        return 0.0
    return min(max(number, WATCHDOG_MIN_SEC), WATCHDOG_MAX_SEC)


async def _handshake(bridge: Any, websocket: Any, refuse) -> dict | None:
    """인사를 받고 낡은 변환표를 거절한다 · 통과하면 인사, 아니면 None."""
    try:
        hello = json.loads(await asyncio.wait_for(
            websocket.receive_text(), timeout=5.0
        ))
    except (asyncio.TimeoutError, json.JSONDecodeError):
        await refuse(HELLO_REQUIRED_MESSAGE)
        return None
    except (WebSocketDisconnect, ConnectionError, RuntimeError):
        return None
    if not isinstance(hello, dict) or hello.get('type') != 'hello':
        await refuse(HELLO_REQUIRED_MESSAGE)
        return None
    mapping_file_id = str(hello.get('mapping_file_id') or '')
    base_revision = str(hello.get('base_mapping_revision') or '')
    if mapping_file_id and base_revision:
        payload = await asyncio.to_thread(
            bridge.load_motion_mapping, mapping_file_id
        )
        current = str((payload or {}).get('revision') or '')
        if current and current != base_revision:
            await refuse(STALE_MAPPING_MESSAGE)
            return None
    return hello
