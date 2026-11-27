"""수동 페이더 WebSocket · `/ws/manual-stream`.

왜 WebSocket 인가 · 페이더는 20Hz 안팎으로 목표를 흘린다 · POST 로 치면
요청마다 접속·직렬화가 쌓이고, supervisor 임대(0.15s · 7Hz 이상 유지)가
체감에 바로 닿는 경로라 소켓 하나에 싣는다 (`/ws/status` 와 같은 모양).

규약·게이트·끊김 처리는 전부 `manual_stream_socket` 에 있다 · 길목은
받아서 넘기기만 한다 · §6-190.
"""

from __future__ import annotations

from fastapi import WebSocket

from ..manual_stream_socket import run_manual_stream_socket


def register_stream_routes(app, bridge) -> None:

    @app.websocket('/ws/manual-stream')
    async def websocket_manual_stream(websocket: WebSocket):
        await run_manual_stream_socket(bridge, websocket)
