from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response


def register_project_routes(app: FastAPI, bridge, project_call) -> None:
    @app.get('/api/projects')
    async def motion_projects():
        return await project_call(bridge.project.list_projects)

    @app.post('/api/projects')
    async def create_motion_project(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail='request body must be an object')
        return await project_call(bridge.project.create_project, body)

    # 백업·복원·휴지통 · 수정 목록 33 · `/api/projects/{project_id}` 와 겹치지 않게 앞에 둔다
    @app.get('/api/projects/{project_id}/export')
    async def export_motion_project(project_id: str):
        result = await project_call(bridge.project.export_project_zip, project_id)
        return Response(
            content=result['data'],
            media_type='application/zip',
            headers={'Content-Disposition': f'attachment; filename="{result["filename"]}"'},
        )

    @app.post('/api/project-import')
    async def import_motion_project(request: Request, overwrite: bool = False):
        data = await request.body()
        if not data:
            raise HTTPException(status_code=400, detail='zip 파일이 비어 있습니다')
        return await project_call(bridge.project.import_project_zip, data, overwrite)

    @app.get('/api/project-trash')
    async def motion_project_trash():
        return await project_call(bridge.project.list_trash)

    @app.post('/api/project-trash/{entry}/restore')
    async def restore_motion_project(entry: str):
        return await project_call(bridge.project.restore_trash, entry)

    @app.get('/api/projects/{project_id}')
    async def motion_project(project_id: str):
        return await project_call(bridge.project.load_project, project_id)

    @app.patch('/api/projects/{project_id}')
    async def update_motion_project(project_id: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail='request body must be an object')
        return await project_call(bridge.project.update_project, project_id, body)

    @app.post('/api/projects/{project_id}/select')
    async def select_motion_project(project_id: str):
        return await project_call(bridge.project.select_project, project_id)

    @app.delete('/api/projects/{project_id}')
    async def delete_motion_project(project_id: str):
        return await project_call(bridge.project.delete_project, project_id)

    @app.post('/api/projects/{project_id}/files')
    async def import_motion_project_file(project_id: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail='request body must be an object')
        return await project_call(bridge.project.import_file, project_id, body)

    @app.get('/api/projects/{project_id}/tree-file')
    async def read_only_motion_project_file(project_id: str, relative_path: str):
        return await project_call(
            bridge.project.load_read_only_file, project_id, relative_path
        )

    @app.get('/api/projects/{project_id}/files/{category}/{file_name}/download')
    async def download_motion_project_file(
        project_id: str, category: str, file_name: str
    ):
        path = await project_call(
            bridge.project.download_file, project_id, category, file_name
        )
        return FileResponse(str(path), filename=path.name)

    @app.get('/api/projects/{project_id}/files/{category}/{file_name}')
    async def motion_project_file(project_id: str, category: str, file_name: str):
        return await project_call(
            bridge.project.load_file, project_id, category, file_name
        )

    @app.put('/api/projects/{project_id}/files/{category}/{file_name}')
    async def save_motion_project_file(
        project_id: str, category: str, file_name: str, request: Request
    ):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail='request body must be an object')
        return await project_call(
            bridge.project.save_file,
            project_id,
            category,
            file_name,
            body,
        )

    @app.post('/api/projects/{project_id}/files/{category}/{file_name}/rename')
    async def rename_motion_project_file(
        project_id: str, category: str, file_name: str, request: Request
    ):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail='request body must be an object')
        return await project_call(
            bridge.project.rename_file,
            project_id,
            category,
            file_name,
            body,
        )

    @app.post('/api/projects/{project_id}/files/{category}/{file_name}/active')
    async def activate_motion_project_file(
        project_id: str, category: str, file_name: str
    ):
        return await project_call(
            bridge.project.activate_file,
            project_id,
            category,
            file_name,
        )

    @app.post('/api/projects/{project_id}/files/{category}/{file_name}/open-editor')
    async def open_motion_project_file_for_editing(
        project_id: str, category: str, file_name: str
    ):
        return await project_call(
            bridge.project.open_file_for_editing,
            project_id,
            category,
            file_name,
        )

    @app.delete('/api/projects/{project_id}/files/{category}/{file_name}')
    async def delete_motion_project_file(
        project_id: str, category: str, file_name: str
    ):
        return await project_call(
            bridge.project.delete_file, project_id, category, file_name
        )
