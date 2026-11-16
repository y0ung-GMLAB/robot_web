"""응답을 다 보낸 **뒤에** 할 일 · 수정 목록 204

「장비에 적용」 · 「프로그램 다시 시작」 은 이 웹 서버가 든 서비스(motion-control)를 다시 띄운다 ·
전에는 재시작을 `sleep 0.5`(132 뒤 2 s) 뒤에 걸어 「그 사이 응답이 나가겠지」 했다 · 0.5 s 일 때는
재시작 요청 뒤의 작업 기록 갱신이 더 오래 걸려 응답 전에 서버가 내려갔고, 적용은 성공했는데 화면은
HTTP 500 이었다(132 · 실물 2026-10-13) · 2 s 로 늘려도 같은 경쟁이다 · 더 느린 날에는 또 진다.

이제는 순서로 한다 · 요청을 처리하는 동안 `defer()` 로 넘긴 일은 응답 본문을 다 보낸 뒤에 돈다 ·
기다리는 시간이 없다 · 재시작 신호(SIGTERM)를 받은 웹 서버는 이미 보낸 응답을 그대로 두고 내린다.

요청 밖(ROS 스레드 · 감시 타이머 등 · 보낼 응답이 없다)에서 부르면 그 자리에서 바로 한다.

노드 없는 순수 모듈이다 · 표준 라이브러리만 쓴다(`motor_config_rules` 가 기댄다 · test_pure_modules).
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from typing import Callable, List, Optional

logger = logging.getLogger('bridge.after_response')

#: 지금 처리 중인 HTTP 요청의 「응답 뒤 할 일」 목록 · 요청 밖이면 None ·
#: `asyncio.to_thread` · 스레드 풀이 문맥을 복사하므로 작업 스레드에서 넣어도 같은 목록에 들어간다
_PENDING: contextvars.ContextVar[Optional[List[Callable[[], None]]]] = contextvars.ContextVar(
    'after_response_pending', default=None,
)


def defer(action: Callable[[], None]) -> bool:
    """응답 뒤로 미룬다 · 요청 안이면 참 · 요청 밖이면 바로 하고 거짓"""
    pending = _PENDING.get()
    if pending is None:
        action()
        return False
    pending.append(action)
    return True


def middleware(app):
    """ASGI 한 겹 · 요청마다 목록을 열고 · 앱이 응답을 다 보내고 끝나면 목록을 돈다"""

    async def call(scope, receive, send) -> None:
        if scope.get('type') != 'http':
            await app(scope, receive, send)
            return
        pending: List[Callable[[], None]] = []
        token = _PENDING.set(pending)
        try:
            await app(scope, receive, send)
        finally:
            _PENDING.reset(token)
            # 응답을 다 보냈다(앱이 끝났다) · 오류로 끝나도 미룬 일은 한다(재시작 요청을 잃지 않게)
            for action in pending:
                try:
                    await asyncio.to_thread(action)
                except Exception:  # noqa: BLE001 · 하나가 실패해도 나머지는 한다
                    logger.exception('응답 뒤 할 일 실패')

    return call


def wrap(app):
    """FastAPI 앱의 미들웨어 묶음 **바깥**에 씌운다 · 오류 응답(500)을 만드는 층보다도 바깥

    Starlette 는 미들웨어 묶음을 `build_middleware_stack` 으로 짓는다 · 그 결과를 감싸면 어떤 응답이든
    다 나간 뒤에 미룬 일이 돈다 · 이미 지어 둔 묶음이 있으면(옛 Starlette) 바로 다시 짓는다.
    """
    build = app.build_middleware_stack

    def build_wrapped():
        return middleware(build())

    app.build_middleware_stack = build_wrapped
    if getattr(app, 'middleware_stack', None) is not None:
        app.middleware_stack = app.build_middleware_stack()
    return app
