"""웹 터미널 길 · `/api/terminal/programs` · `/ws/terminal` · §6-311

받아서 넘기기만 한다 · PTY·프로세스·소켓 규약은 전부 `terminal_service`
에 있다 (§6-190) · `/ws/manual-stream` 과 같은 모양.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, WebSocket

from motion_web_bridge.terminal_service import run_terminal_socket, terminal_programs


def register_terminal_routes(app: FastAPI, bridge) -> None:

    @app.get('/api/terminal/programs')
    async def list_terminal_programs():
        return await asyncio.to_thread(terminal_programs)

    @app.websocket('/ws/terminal')
    async def websocket_terminal(
        websocket: WebSocket,
        program: str = 'shell',
        cols: int = 0,
        rows: int = 0,
    ):
        await run_terminal_socket(bridge, websocket, program, cols, rows)
