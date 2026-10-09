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


WORKSPACE = os.path.dirname(APP_DIR)
#: 이 앱 서비스 이름 · 「다시 시작」 이 쓴다 (install_speaker.sh 의 UNIT)
SPEAKER_UNIT = "speaker-app.service"


def _robot_modules():
    """robot_web 의 같은 모듈을 쓴다 · 이 앱은 robot_web/speaker_app 안에서 돈다"""
    import sys
    for sub in ("web_bridge", "motion_common"):
        path = os.path.join(WORKSPACE, "src", sub)
        if path not in sys.path:
            sys.path.insert(0, path)


def _updater():
    _robot_modules()
    from motion_web_bridge.system_update import SPEAKER_COMMAND, SystemUpdate
    return SystemUpdate(WORKSPACE, command=SPEAKER_COMMAND)


def _wifi():
    """로봇 PC 와 같은 Wi-Fi 설정 · 수정 목록 89 (2026-10-09)"""
    _robot_modules()
    from motion_web_bridge.wifi_settings import WifiSettings
    return WifiSettings(WORKSPACE)


def _timezone():
    """로봇 PC 와 같은 시간대 · 스피커는 스케줄이 없어 바꾼 뒤 다시 띄우지 않는다 (89)"""
    _robot_modules()
    from motion_web_bridge.system_timezone import SystemTimezone
    return SystemTimezone(restart_unit="", workspace_hint=WORKSPACE)


def restart_command(unit=SPEAKER_UNIT):
    """응답이 나간 뒤 1초 있다가 이 앱을 다시 띄운다 · 앱이 제 손으로 죽으면 응답이 안 간다"""
    return ["systemd-run", "--user", "--on-active=1", "--unit", "speaker-app-restart", "--collect",
            "systemctl", "--user", "restart", unit]


def read_docs():
    """스피커 사용법 · 이 앱 README 글자 그대로 (89)"""
    try:
        with open(os.path.join(APP_DIR, "README.md"), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return "사용법 문서(speaker_app/README.md)를 찾지 못했습니다"


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

    # ---- 업데이트 · 로봇 PC 의 「모든 PC 업데이트」 가 부른다 (2026-10-08) ----
    @app.get("/api/system/update")
    def system_update_status():
        return JSONResponse(_updater().status())

    @app.post("/api/system/update")
    def system_update_start():
        return JSONResponse(_updater().start())

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
        if "pc_name" in payload:
            patch["pc_name"] = str(payload["pc_name"])
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
        ok, message = state.add_sound(name, tmp)
        return _result(ok, message)

    @app.post("/api/sound/delete")
    def delete_sound(payload: dict = Body(default={})):
        # 이름이 없으면 기본 음원(옛 화면과 같은 동작)
        ok, message = state.delete_sound(os.path.basename(str((payload or {}).get("name") or "")))
        return _result(ok, message)

    @app.post("/api/sound/default")
    def default_sound(payload: dict = Body(...)):
        ok, message = state.set_default_sound(str(payload.get("name") or ""))
        return _result(ok, message)

    @app.post("/api/motion-sound")
    def motion_sound(payload: dict = Body(...)):
        """애니메이션 → 음원 · 이름이 비면 기본 음원으로 돌린다"""
        ok, message = state.set_motion_sound(
            str(payload.get("motion_file_id") or ""), str(payload.get("file_name") or ""))
        return _result(ok, message)

    @app.get("/api/sound/download")
    def download_sound(name: str = ""):
        path = state.sound_path(name)
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

    # ---- PC 관리 · 로봇 PC 와 같은 것 · 수정 목록 89 (2026-10-09) ----------
    # 스피커 PC 도 화면·키보드를 꽂기 어려운 곳에 있다 · 웹으로 다 한다
    @app.get("/api/system/wifi")
    def wifi_status():
        return JSONResponse(_wifi().status())

    @app.post("/api/system/wifi/scan")
    def wifi_scan():
        return JSONResponse(_wifi().scan())

    @app.post("/api/system/wifi/connect")
    def wifi_connect(payload: dict = Body(default={})):
        payload = payload or {}
        static = payload.get("static") if isinstance(payload.get("static"), dict) else None
        return JSONResponse(_wifi().connect(payload.get("ssid"), payload.get("password"), static,
                                            security=payload.get("security")))

    @app.post("/api/system/wifi/confirm")
    def wifi_confirm():
        return JSONResponse(_wifi().confirm())

    @app.post("/api/system/wifi/rollback")
    def wifi_rollback():
        return JSONResponse(_wifi().rollback())

    @app.get("/api/system/time")
    def system_time():
        return JSONResponse(_timezone().status())

    @app.post("/api/system/timezone")
    def system_timezone(payload: dict = Body(default={})):
        return JSONResponse(_timezone().apply((payload or {}).get("zone")))

    @app.post("/api/system/restart")
    def system_restart():
        import subprocess
        try:
            result = subprocess.run(restart_command(), capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            return _result(False, "다시 시작 예약 실패 · %s" % exc)
        if result.returncode != 0:
            return _result(False, "다시 시작 예약 실패 · %s" % (result.stderr.strip() or result.returncode))
        return _result(True, "1초 뒤 스피커 앱을 다시 띄웁니다 · 몇 초 뒤 화면이 다시 붙습니다")

    @app.get("/api/docs")
    def docs():
        return JSONResponse({"ok": True, "text": read_docs()})

    return app
