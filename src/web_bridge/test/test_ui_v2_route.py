"""새 UI(/v2) 주소 · 설계안 2026-10-09 · 뼈대 + 홈.

기존 화면(/)은 그대로 두고 옆에 새 화면을 연다 · 주소가 끊기거나 정적 파일 규칙
(ETag · 304)을 안 따르면 현장 PC 에서 낡은 새 화면이 남는다.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from motion_web_bridge.routes import system_routes

REPO = Path(__file__).resolve().parents[3]


def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(system_routes, 'get_package_share_directory', lambda _name: str(tmp_path))
    monkeypatch.setenv('MOTION_WORKSPACE', str(REPO))
    app = FastAPI()
    system_routes.register_system_routes(app, bridge=None, project_call=None)
    return TestClient(app)


def test_v2_serves_its_own_page_with_etag(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    for path in ('/v2', '/v2/'):
        response = client.get(path)
        assert response.status_code == 200, path
        assert '/static/v2/js/main.js' in response.text
        assert response.headers['cache-control'] == 'no-cache'
    etag = client.get('/v2').headers['etag']
    assert client.get('/v2', headers={'If-None-Match': etag}).status_code == 304


def test_v2_assets_come_from_the_same_static_route(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    assert client.get('/static/v2/app.css').status_code == 200
    assert client.get('/static/v2/js/main.js').status_code == 200
