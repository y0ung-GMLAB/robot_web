"""수동 페이더 WebSocket 세션 · 길목(`stream_routes`)에서 떼어낸 업무.

규약 · JSON 한 덩이씩:

    ← {type:'hello', mapping_file_id?, base_mapping_revision?}
    → {type:'hello_ok'}  |  {type:'error', message}  (보내고 닫는다)
    ← {type:'target', axis, target_deg, motion_id?, motion_deg?}   # 모터 deg
    ← {type:'release', axes:[..]}        # 놓음 → 현재 위치에 hold
    → {type:'result', ...}               # supervisor 의 축별 마지막 승인·거부

모션축 deg → 모터 deg 변환은 화면이 자기 매핑 행으로 한다 · 그래서 인사에
`base_mapping_revision` 을 받아 **낡은 변환표**(다른 화면이 매핑을 고친 뒤)
는 그 자리에서 거절한다.

수동 모드에서만 받는다(스케줄·오프는 거절) · `run_mode_gate.manual_control_block_reason` ·
흐르는 중에도 0.5초마다 다시 확인해서, 상단에서 모드를 바꾸면 소켓이 끊긴다.

끊기면(놓지 않고 창을 닫아도) 만졌던 축을 현재 위치에 세운다 · 임대는
어차피 0.15초에 끝나지만, 마지막으로 날아가던 목표가 아니라 **지금 서 있는
곳**이 목표가 되게 한다.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import WebSocketDisconnect

from .run_mode_gate import manual_control_block_reason

#: 오프 전환 재확인 주기 · 매 프레임 파일을 읽지 않는다
BLOCK_RECHECK_SEC = 0.5

HELLO_REQUIRED_MESSAGE = "hello 가 필요합니다 · {type:'hello'}"
STALE_MAPPING_MESSAGE = (
    '모션축 설정이 이 화면을 연 뒤에 바뀌었습니다 · '
    '화면을 새로 고친 뒤 다시 잡으세요'
)


async def run_manual_stream_socket(bridge: Any, websocket: Any) -> None:
    await websocket.accept()

    async def refuse(message: str) -> None:
        await send({'type': 'error', 'message': message})
        await websocket.close()

    async def send(payload: dict) -> None:
        await websocket.send_text(json.dumps(payload, ensure_ascii=False))

    block = await asyncio.to_thread(manual_control_block_reason, bridge)
    if block:
        await refuse(block)
        return

    if not await _handshake(bridge, websocket, refuse):
        return
    await send({'type': 'hello_ok'})

    service = bridge.manual_stream
    touched_axes: list[int] = []
    last_block_check = time.monotonic()
    try:
        while True:
            try:
                raw = await websocket.receive_text()
            except (WebSocketDisconnect, ConnectionError, RuntimeError):
                return
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue

            now = time.monotonic()
            if now - last_block_check > BLOCK_RECHECK_SEC:
                last_block_check = now
                block = await asyncio.to_thread(
                    manual_control_block_reason, bridge
                )
                if block:
                    await refuse(block)
                    return

            kind = message.get('type')
            if kind == 'target':
                result = service.send_target(
                    message.get('axis'),
                    message.get('target_deg'),
                    motion_id=message.get('motion_id'),
                    motion_deg=message.get('motion_deg'),
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


async def _handshake(bridge: Any, websocket: Any, refuse) -> bool:
    """인사를 받고 낡은 변환표를 거절한다 · 통과하면 True."""
    try:
        hello = json.loads(await asyncio.wait_for(
            websocket.receive_text(), timeout=5.0
        ))
    except (asyncio.TimeoutError, json.JSONDecodeError):
        await refuse(HELLO_REQUIRED_MESSAGE)
        return False
    except (WebSocketDisconnect, ConnectionError, RuntimeError):
        return False
    if not isinstance(hello, dict) or hello.get('type') != 'hello':
        await refuse(HELLO_REQUIRED_MESSAGE)
        return False
    mapping_file_id = str(hello.get('mapping_file_id') or '')
    base_revision = str(hello.get('base_mapping_revision') or '')
    if mapping_file_id and base_revision:
        payload = await asyncio.to_thread(
            bridge.load_motion_mapping, mapping_file_id
        )
        current = str((payload or {}).get('revision') or '')
        if current and current != base_revision:
            await refuse(STALE_MAPPING_MESSAGE)
            return False
    return True
