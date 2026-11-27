"""로컬 연결(`local_link.LocalLink`) 시험용 · ROS 없이 · 수정 목록 209

보낸 요청은 `sent` · 감독 안전 정지는 `safety_sent` · 살아 있음은 `alive_sent` · 답은 `answer(command, payload)` ·
None 을 돌려주면 답이 없다(시간 초과).
"""

import json
import time

from motion_coordination.local_link import LocalLink

CONTEXT = {'project_id': 'project-a', 'project_generation': 7, 'context_id': 'ctx-7', 'ready': True}


def fake_link(*, runtime=None, runtime_ago=0.1, safety=None, answer=None, started_ago=60.0):
    """ROS 없이 · 보낸 요청은 `sent` · 감독 안전 정지는 `safety_sent` · 답은 `answer(command, payload)`"""
    link = LocalLink()
    link.sent = []
    link.safety_sent = []
    link.alive_sent = []

    def send(text):
        request = json.loads(text)
        link.sent.append(request)
        reply = (answer or (lambda _command, _payload: {'success': True, 'message': 'ok'}))(
            request['command'], request['payload'],
        )
        if reply is not None:
            link.on_response(json.dumps({**reply, 'request_id': request['request_id']}))

    link._send_request = send
    link._send_safety = lambda text: link.safety_sent.append(json.loads(text))
    link._send_alive = lambda text: link.alive_sent.append(json.loads(text))
    link.started_at = time.monotonic() - started_ago
    link.domain_id = 22
    link.localhost_only = True
    status = {'execution_context': dict(CONTEXT), **(runtime or {})}
    link.on_runtime_status(json.dumps(status))
    with link._lock:
        link._runtime_at = time.monotonic() - runtime_ago
    if safety is not None:
        link.on_safety_status(json.dumps(safety))
    return link


