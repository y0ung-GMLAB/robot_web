"""응답을 다 보낸 뒤에 서비스 재시작 · 「정지 정리 끝」 기다리기 · 수정 목록 204 · 200

204 · 실물 2026-10-13 20:32(floating4 · 132) · 「장비에 적용」 이 성공했는데 HTTP 500 · 재시작을
`sleep 0.5`(뒤에 2 s) 뒤에 걸어 「그 사이 응답이 나가겠지」 했는데 재시작 요청 뒤의 작업이 더 걸렸다 ·
이제는 시간이 아니라 순서 · 응답 본문의 마지막 조각이 나간 뒤에 systemctl 을 부른다.

rclpy 없이 돈다.
"""

import asyncio
import json
import threading
import time

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from std_msgs.msg import String

from motion_web_bridge import after_response, motor_config_rules
from motion_web_bridge.bridge_node import MotionWebBridge


def _run_asgi(app):
    """ASGI 앱 한 번 · 보낸 조각을 순서대로 적는다"""
    events = []

    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}

    async def send(message):
        events.append(message['type'])

    asyncio.run(app({'type': 'http', 'method': 'POST', 'path': '/', 'headers': []}, receive, send))
    return events


def test_a_deferred_action_runs_only_after_the_whole_response_went_out():
    order = []

    async def endpoint(scope, receive, send):
        after_response.defer(lambda: order.append('restart'))
        order.append('handler-done')
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        order.append('start-sent')
        await send({'type': 'http.response.body', 'body': b'{}', 'more_body': False})
        order.append('body-sent')

    _run_asgi(after_response.middleware(endpoint))

    assert order == ['handler-done', 'start-sent', 'body-sent', 'restart']


def test_outside_a_request_the_action_runs_at_once():
    """감시 타이머 등 · 보낼 응답이 없다 · 그 자리에서"""
    done = []
    assert after_response.defer(lambda: done.append(True)) is False
    assert done == [True]


def test_the_restart_is_requested_after_the_apply_response(monkeypatch):
    """FastAPI 길목 · 작업 스레드(`asyncio.to_thread`)에서 건 재시작도 응답 뒤로 · 미들웨어(`@app.middleware`)가 있어도"""
    popen_calls = []
    monkeypatch.setattr(
        motor_config_rules.subprocess, 'Popen',
        lambda command, **kwargs: popen_calls.append(command),
    )
    seen_in_handler = []
    app = FastAPI()

    @app.middleware('http')
    async def passthrough(request: Request, call_next):
        return await call_next(request)

    def apply_like():
        motor_config_rules.schedule_managed_service_restart('motion-motor.service', 'motion-control.service')
        time.sleep(0.05)                       # 재시작 요청 뒤에도 작업이 남아 있다(132 · 작업 기록 갱신)
        seen_in_handler.append(list(popen_calls))
        return {'success': True}

    @app.post('/apply')
    async def apply_route():
        return await asyncio.to_thread(apply_like)

    after_response.wrap(app)
    response = TestClient(app).post('/apply')

    assert response.status_code == 200 and response.json() == {'success': True}
    assert seen_in_handler == [[]], '응답을 만드는 동안 재시작이 걸렸다(웹 서버가 응답 전에 내려간다)'
    assert popen_calls == [[
        '/usr/bin/systemctl', '--user', 'restart', '--no-block',
        'motion-motor.service', 'motion-control.service',
    ]]


# --------------------------------------------------------------------------- #
# 200 · 「정지 정리 끝」 은 safety 상태가 올 때 깬다 · 시계로 다시 보지 않는다
# --------------------------------------------------------------------------- #

def _bridge():
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge._safety_status_lock = threading.Lock()
    bridge._safety_status_changed = threading.Condition(bridge._safety_status_lock)
    bridge._safety_status = {'stop_boot': 'b', 'stop_epoch': 3, 'stop_settled': False}
    bridge.supervisor_watchdog = None
    return bridge


def test_waiting_for_stop_settled_wakes_on_the_safety_status():
    bridge = _bridge()

    def settle_later():
        time.sleep(0.05)
        bridge._safety_status_callback(String(data=json.dumps(
            {'stop_boot': 'b', 'stop_epoch': 3, 'stop_settled': True},
        )))

    threading.Thread(target=settle_later, daemon=True).start()
    started = time.monotonic()

    assert bridge.wait_for_stop_settled(('b', 3), 5.0) is True
    assert time.monotonic() - started < 1.0


def test_waiting_for_stop_settled_gives_up_only_at_the_failure_bound():
    bridge = _bridge()
    assert bridge.wait_for_stop_settled(('b', 3), 0.05) is False


def test_a_restarted_supervisor_means_the_old_stop_is_over():
    bridge = _bridge()
    bridge._safety_status = {'stop_boot': 'new', 'stop_epoch': 0, 'stop_settled': True}
    assert bridge.wait_for_stop_settled(('b', 3), 0.05) is True
