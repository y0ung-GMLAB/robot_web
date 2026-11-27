"""로봇 팩 · PC 전역 · 받아서 넘기기만 한다 (업무는 robot_pack_service)

zip 은 multipart 가 아니라 **본문 그대로**(application/zip) 받는다 ·
python-multipart 의존을 늘리지 않는다.
"""

import asyncio

from fastapi import FastAPI, Request

from motion_web_bridge import robot_pack_service


def register_robot_pack_routes(app: FastAPI, bridge) -> None:
    @app.get('/api/robot-pack')
    async def robot_pack_status():
        return await asyncio.to_thread(robot_pack_service.pack_status, bridge.workspace_root)

    @app.put('/api/robot-pack')
    async def upload_robot_pack(request: Request):
        data = await request.body()
        return await asyncio.to_thread(robot_pack_service.install_pack, bridge.workspace_root, data)

    @app.post('/api/robot-pack/rollback')
    async def rollback_robot_pack():
        return await asyncio.to_thread(robot_pack_service.rollback_pack, bridge.workspace_root)

    @app.get('/api/robot-pack/mapping-diff')
    async def robot_pack_mapping_diff():
        return await asyncio.to_thread(
            robot_pack_service.active_mapping_diff,
            bridge.workspace_root,
            bridge.project_repository,
        )
