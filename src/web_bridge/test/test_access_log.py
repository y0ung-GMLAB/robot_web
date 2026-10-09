"""웹 접속 기록 줄이기 · 수정 목록 77 (2026-10-08)

밤샘 13 h 에 접속 기록 한 파일이 110 MB(101만 줄이 화면 폴링 GET) · 성공한 GET 은 버리고
명령(POST·PUT·DELETE)과 실패(400 이상)는 남긴다.
"""

import logging

from motion_web_bridge.access_log import QuietPollingFilter, install_access_log_filter


def _record(method, path, status):
    return logging.LogRecord(
        'uvicorn.access', logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d', ('127.0.0.1:5000', method, path, '1.1', status), None,
    )


def test_successful_polling_gets_are_dropped():
    quiet = QuietPollingFilter()
    assert quiet.filter(_record('GET', '/api/coordination', 200)) is False
    assert quiet.filter(_record('GET', '/api/schedule/status', 304)) is False
    assert quiet.filter(_record('HEAD', '/', 200)) is False


def test_commands_and_failures_are_kept():
    quiet = QuietPollingFilter()
    assert quiet.filter(_record('POST', '/api/motion-run/start', 200)) is True
    assert quiet.filter(_record('PUT', '/api/schedule/mode', 200)) is True
    assert quiet.filter(_record('GET', '/api/coordination', 500)) is True
    assert quiet.filter(_record('GET', '/missing', 404)) is True


def test_unknown_record_shapes_are_kept():
    quiet = QuietPollingFilter()
    odd = logging.LogRecord('uvicorn.access', logging.INFO, __file__, 1, 'free text', None, None)
    assert quiet.filter(odd) is True


def test_installing_twice_adds_one_filter():
    name = 'test.access.install'
    first = install_access_log_filter(name)
    second = install_access_log_filter(name)
    assert first is second
    assert sum(isinstance(f, QuietPollingFilter) for f in logging.getLogger(name).filters) == 1


def test_the_bridge_installs_it_after_uvicorn_configures_logging():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / 'motion_web_bridge/bridge_node.py').read_text(encoding='utf-8')
    config_at = source.index('config = uvicorn.Config(')
    assert config_at < source.index('install_access_log_filter()') < source.index('uvicorn.Server(config).run()')
