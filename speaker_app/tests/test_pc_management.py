"""스피커 PC 관리 · 로봇 PC 와 같은 것 · 수정 목록 89 (2026-10-09)

웹 터미널 · Wi-Fi · 시간대 · 앱 다시 시작 · 이 PC 업데이트 · PC 성능 · 사용법.
스피커 PC 도 화면·키보드를 꽂기 어려운 곳에 있어 전부 웹으로 한다.
"""
import os
import sys

import pytest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(APP)
BACKEND = os.path.join(APP, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

pytest.importorskip("fastapi")
pytest.importorskip("yaml")

import api  # noqa: E402


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def test_every_management_route_exists():
    app = api.create_app(state=None)
    paths = {getattr(route, "path", "") for route in app.routes}
    for path in ("/api/system/wifi", "/api/system/wifi/scan", "/api/system/wifi/connect",
                 "/api/system/wifi/confirm", "/api/system/wifi/rollback", "/api/system/time",
                 "/api/system/timezone", "/api/system/restart", "/api/system/update", "/api/docs"):
        assert path in paths, path


def test_wifi_and_timezone_are_the_robot_modules():
    wifi = api._wifi()
    assert type(wifi).__module__ == "motion_web_bridge.wifi_settings"
    assert str(wifi.workspace_root) == WORKSPACE
    tz = api._timezone()
    assert tz._restart_unit == "", "스피커는 바꾼 뒤 로봇 서비스를 다시 띄우지 않는다"


def test_restart_runs_after_the_answer_and_targets_the_speaker_unit():
    cmd = api.restart_command()
    assert cmd[:3] == ["systemd-run", "--user", "--on-active=1"]
    assert cmd[-3:] == ["--user", "restart", "speaker-app.service"]


def test_docs_are_the_speaker_readme():
    assert api.read_docs() == _read(APP, "README.md")


def test_installer_adds_terminal_btop_timezone_and_permissions():
    text = _read(WORKSPACE, "scripts", "install_speaker.sh")
    assert "site_timezone" in text and 'site_web_admin_permissions "$(id -un)"' in text
    assert "apt-get install -y ttyd btop" in text
    assert "motion-terminal.service.in" in text and "motion-btop.service" in text
    # 터미널은 이 설치를 돌리는 창일 수 있다 · 켜져 있으면 건드리지 않는다
    assert 'systemctl --user is-active --quiet "${extra}" || systemctl --user start "${extra}"' in text


def test_screen_has_the_management_card():
    html = _read(APP, "frontend", "index.html")
    for element in ("link-terminal", "link-btop", "btn-docs", "btn-restart-app", "btn-update",
                    "tz-pick", "btn-tz", "wifi-ssid", "btn-wifi-connect", "btn-wifi-keep", "btn-wifi-back"):
        assert f'id="{element}"' in html, element
    js = _read(APP, "frontend", "app.js")
    assert '":8081"' in js and '":8080"' in js
    for path in ("/api/system/wifi/connect", "/api/system/timezone", "/api/system/restart", "/api/docs"):
        assert path in js, path
