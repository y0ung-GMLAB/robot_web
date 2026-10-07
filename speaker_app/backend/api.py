"""REST API + 프론트엔드 서빙. 프론트와의 유일한 접점."""
import os
import urllib.parse

import sysinfo

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(APP_DIR, "frontend")

MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}


def _serve(name):
    path = os.path.join(FRONTEND_DIR, name)
    if not os.path.isfile(path):
        return Response("not found", status_code=404)
    with open(path, "rb") as f:
        body = f.read()
    ext = os.path.splitext(name)[1].lower()
    return Response(body, media_type=MEDIA_TYPES.get(ext, "application/octet-stream"))


MAX_UPLOAD_BYTES = 500 * 1024 * 1024


def _result(ok, message=""):
    return JSONResponse({"ok": bool(ok), "message": message},
                        status_code=200 if ok else 400)


def _as_float(value, fallback=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_int(value, fallback=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def create_app(state):
    app = FastAPI(title="스피커 트리거", docs_url=None, redoc_url=None)

    # ---- 프론트엔드 ---------------------------------------------------
    @app.get("/")
    def index():
        # 새로고침할 때마다 커밋 해시를 다시 읽는다 (폴링에서는 읽지 않는다)
        sysinfo.invalidate_head()
        return _serve("index.html")

    @app.get("/app.js")
    def app_js():
        return _serve("app.js")

    @app.get("/style.css")
    def style_css():
        return _serve("style.css")

    # ---- 상태 ---------------------------------------------------------
    @app.get("/api/state")
    def get_state():
        return JSONResponse(state.snapshot())

    # ---- 모드 ---------------------------------------------------------
    @app.post("/api/mode")
    def set_mode(payload: dict = Body(...)):
        ok, message = state.set_mode(str(payload.get("mode", "")))
        return _result(ok, message)

    # ---- 설정 ---------------------------------------------------------
    @app.get("/api/config")
    def get_config():
        return JSONResponse(state.snapshot()["config"])

    @app.post("/api/config")
    def post_config(payload: dict = Body(...)):
        patch = {}
        if "domain_id" in payload:
            patch["domain_id"] = _as_int(payload["domain_id"], 21)
        if "group_id" in payload:
            patch["group_id"] = str(payload["group_id"])
        if "offset_sec" in payload:
            patch["offset_sec"] = _as_float(payload["offset_sec"], 0.0)
        if "stop_on_motion_stop" in payload:
            patch["stop_on_motion_stop"] = bool(payload["stop_on_motion_stop"])
        if "device" in payload:
            patch["device"] = str(payload["device"])
        if "file_name" in payload:
            # 경로 조작 방지 — 파일명만 허용한다
            patch["file_name"] = os.path.basename(str(payload["file_name"]))
        if "repeat" in payload:
            patch["repeat"] = _as_int(payload["repeat"], 0)
        if "dwell_sec" in payload:
            patch["dwell_sec"] = _as_float(payload["dwell_sec"], 2.0)
        ok, message = state.update_config(patch)
        return _result(ok, message)

    # ---- 볼륨 ---------------------------------------------------------
    @app.post("/api/volume")
    def set_volume(payload: dict = Body(...)):
        ok, message = state.set_volume(_as_int(payload.get("percent"), 50))
        return _result(ok, message)

    # ---- 음원 파일 -----------------------------------------------------
    @app.post("/api/sound/upload")
    async def upload_sound(request: Request):
        """multipart 없이 원시 바디로 받는다(추가 의존성 회피). 이름은 쿼리로 전달."""
        name = os.path.basename(request.query_params.get("name", "").strip())
        if not name.lower().endswith(".wav"):
            return _result(False, "wav 파일만 업로드할 수 있습니다")
        sounds_dir = state.cfg["audio"]["sounds_dir"]
        os.makedirs(sounds_dir, exist_ok=True)
        tmp = os.path.join(sounds_dir, ".upload.tmp")
        written = 0
        try:
            with open(tmp, "wb") as f:
                async for chunk in request.stream():
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES:
                        raise ValueError("파일이 너무 큽니다 (최대 500MB)")
                    f.write(chunk)
        except Exception as exc:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return _result(False, str(exc))
        if written == 0:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return _result(False, "빈 파일입니다")
        ok, message = state.replace_sound(name, tmp)
        return _result(ok, message)

    @app.post("/api/sound/delete")
    def delete_sound():
        ok, message = state.delete_sound()
        return _result(ok, message)

    @app.get("/api/sound/download")
    def download_sound():
        path = state.sound_path()
        if not path or not os.path.isfile(path):
            return Response("음원이 없습니다", status_code=404)
        name = os.path.basename(path)
        quoted = urllib.parse.quote(name)
        return FileResponse(
            path,
            media_type="audio/wav",
            headers={"Content-Disposition": "attachment; filename*=UTF-8\'\'%s" % quoted},
        )

    # ---- 재생 제어 -----------------------------------------------------
    @app.post("/api/play")
    def play():
        ok, message = state.play_standalone()
        return _result(ok, message)

    @app.post("/api/pause")
    def pause():
        ok, message = state.pause()
        return _result(ok, message)

    @app.post("/api/resume")
    def resume():
        ok, message = state.resume()
        return _result(ok, message)

    @app.post("/api/stop")
    def stop():
        ok, message = state.stop_playback()
        return _result(ok, message)

    @app.post("/api/dds/restart")
    def dds_restart():
        ok, message = state.restart_dds()
        return _result(ok, message)

    @app.post("/api/test")
    def test():
        ok, message = state.test_play()
        return _result(ok, message)

    return app
