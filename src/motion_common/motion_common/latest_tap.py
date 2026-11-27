"""빠른 토픽의 **마지막 한 장만** 필요할 때 꺼낸다 · 실행기 밖 구독 · 수정 목록 130

모터 노드(`motor_manager`)는 `motor_status` 를 1 ms 마다 낸다 · 파이썬 노드가 이것을 보통 구독으로
받으면 실행기가 초당 1,000 번 깨어 메시지를 꺼내고 콜백을 돈다 · 쓰는 쪽은 10~100 Hz 만 보는데도 ·
실물(floating4 · 2026-10-13)에서 서 있을 때 motion_state_monitor 85 % · motion_run_manager 51 %
(1 h 40 m 평균) · 그 바쁜 노드들 사이를 오가는 그룹 예약 확인이 0.4 s 를 넘겨 그룹 시작이 실패했다.

여기서는 구독을 **실행기에 넣지 않은 작은 노드** 에 만든다 · DDS 가 마지막 한 장(KEEP_LAST 1)만
받아 두고 · 쓰는 쪽이 제 박자(타이머 · 재생 틱)에 `take_latest()` 로 꺼낸다 · 파이썬은 쓰는 만큼만 깬다.
만들지 못하면(`open_tap` 이 None) 부르는 쪽이 옛 콜백 구독으로 돌아간다.

rclpy 는 들여오지 않는다 · 노드 클래스와 QoS 는 부르는 노드가 넘긴다 · rclpy 없는 시험에서도 쓴다.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

#: 한 번 꺼낼 때 비우는 최대 장 수 · KEEP_LAST 1 이면 한 장 · 혹시 깊이가 커도 끝이 있게
MAX_DRAIN = 64


class LatestMessageTap:
    """실행기 밖 구독 하나 · `take_latest()` 가 쌓인 것 중 가장 새 것을 돌려준다(없으면 None)"""

    def __init__(
        self, subscription: Any, *, owner: Any = None,
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        self._subscription = subscription
        self._owner = owner
        self._on_close = on_close
        self._lock = threading.Lock()
        self._closed = False

    def take_latest(self) -> Any:
        with self._lock:
            if self._closed or self._subscription is None:
                return None
            subscription = self._subscription
            newest = None
            try:
                with subscription.handle:
                    for _ in range(MAX_DRAIN):
                        taken = subscription.handle.take_message(
                            subscription.msg_type, subscription.raw,
                        )
                        if taken is None:
                            break
                        newest = taken[0] if isinstance(taken, tuple) else taken
            except Exception:  # noqa: BLE001 · 닫히는 중(InvalidHandle) · 이번엔 없는 것으로
                return newest
            return newest

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._subscription = None
        if self._on_close is not None:
            try:
                self._on_close()
            except Exception:  # noqa: BLE001 · 끄는 길 · 이미 내려간 컨텍스트
                pass


def open_tap(
    parent: Any, msg_type: Any, topic: str, *,
    node_class: Any, qos: Any,
    raw: bool = False, suffix: str = 'latest_tap',
    logger: Any = None,
) -> Optional[LatestMessageTap]:
    """`parent` 노드 곁에 실행기 밖 구독을 연다 · 못 열면 None(부르는 쪽이 옛 구독으로)

    `node_class` (rclpy `Node`) · `qos` (깊이 1 · KEEP_LAST) 는 부르는 노드가 넘긴다 ·
    공용 커널은 rclpy 를 들여오지 않는다(`test_package_boundaries`).
    """
    try:
        node = node_class(
            f'{parent.get_name()}_{suffix}',
            namespace=parent.get_namespace(),
            context=parent.context,
            start_parameter_services=False,
            enable_rosout=False,
        )
    except Exception as exc:  # noqa: BLE001 · 옛 rclpy · 시험 대역 · 옛 구독으로
        _warn(logger, f'실행기 밖 구독을 만들지 못해 콜백 구독으로 받습니다 · {topic} · {exc}')
        return None
    try:
        subscription = node.create_subscription(
            msg_type, topic, _never_called, qos, raw=bool(raw),
        )
    except Exception as exc:  # noqa: BLE001
        try:
            node.destroy_node()
        except Exception:  # noqa: BLE001
            pass
        _warn(logger, f'실행기 밖 구독을 만들지 못해 콜백 구독으로 받습니다 · {topic} · {exc}')
        return None
    return LatestMessageTap(subscription, owner=node, on_close=node.destroy_node)


def _never_called(_message: Any) -> None:
    """실행기에 넣지 않은 노드라 불리지 않는다 · rclpy 가 콜백 자리를 요구할 뿐"""


def _warn(logger: Any, text: str) -> None:
    if logger is None:
        return
    warn = getattr(logger, 'warning', None) or getattr(logger, 'warn', None)
    if callable(warn):
        warn(text)
