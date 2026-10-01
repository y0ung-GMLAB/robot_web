from fastapi import FastAPI
from fastapi.responses import FileResponse


def register_motion_trace_routes(app: FastAPI, bridge, project_call) -> None:
    """회차별 모션 기록 · 목록·그래프·CSV 내려받기 · 디스크 일은 모두 스레드에서."""

    @app.get('/api/motion-trace/days')
    async def motion_trace_days():
        return await project_call(bridge.motion_trace.days)

    @app.get('/api/motion-trace/runs')
    async def motion_trace_runs(date: str):
        return await project_call(bridge.motion_trace.runs, date)

    @app.get('/api/motion-trace/trace')
    async def motion_trace(date: str, file: str):
        return await project_call(bridge.motion_trace.trace, date, file)

    @app.get('/api/motion-trace/download')
    async def motion_trace_download(date: str, file: str):
        # 이름 검사 실패·없는 파일은 project_call 이 400 으로 돌려준다
        path = await project_call(bridge.motion_trace.file_path, date, file)
        return FileResponse(path, media_type='text/csv; charset=utf-8', filename=path.name)

    @app.delete('/api/motion-trace/days/{date}')
    async def delete_motion_trace_day(date: str):
        return await project_call(bridge.motion_trace.delete_day, date)
