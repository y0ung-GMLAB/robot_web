"""연동 노드 ↔ 이 PC 재생 관리자 · 감독 · 로컬 DDS 로 바로 · 수정 목록 209 · 207

전에는 연동 노드가 이 PC 상태를 웹(HTTP `/api/coordination/local-status` · 50 ms · 시도마다 0.3 s 제한)에서 읽고,
명령도 웹(`/api/coordination/local-control`)을 거쳐 재생 관리자에 보냈다 · 웹이 바쁘면(화면 탭 · 디스크 · 큰 JSON)
상태를 0.3~1.5 s 못 받아 **이 PC 가 그룹에서 빠졌다** · 그것을 시간 여유로 덮어 왔다(172 · 184 B · 188 ①④) ·
마스터 자신의 그룹 예약도 같은 길이라 늦어 여유 바닥 · 다시 시도를 덧댔다(130 · 153 · 171 · 179).

이제 연동 노드 안에 **두 번째 ROS 컨텍스트** 를 연다 · 로컬 도메인(그룹 + 1 · 이 PC 안 루프백만 ·
`group_env.local_target` · 모터 · 웹 서비스와 같은 값 · 수정 목록 176) · 재생 관리자 · 감독과 같은 도메인이다.

- 상태 · `/motion_run/status`(바뀔 때 바로 · 아니어도 0.5 s 마다) · `/safety/status` 를 직접 받는다
- 명령 · `/motion_run/request` → `/motion_run/response` · 웹이 쓰던 것과 같은 JSON 약속(세대 · 실행 컨텍스트)
- 정지 · 감독에 안전 정지(`/safety/request` · `safety_motion_stop`) 먼저 · 웹 `coordination_stop_now` 와 같은 순서
- 살아 있음 · `/motion_coordination/alive` · 웹 역감시가 듣는다(전에는 「웹을 물었나」)

웹은 화면 · 웹만 아는 칸(운전 모드 · 시간표 칸 · 준비 검사 · 운영 로그)만 맡는다 · 웹이 느리거나 죽어도 그룹은 돈다.

rclpy Humble 은 한 프로세스에 컨텍스트 여럿을 쓸 수 있다(`rclpy.init(context=…, domain_id=…)` · 실행기도 컨텍스트마다) ·
루프백만(`ROS_LOCALHOST_ONLY`)은 rclpy 에 칸이 없고 rcl 이 `rcl_init` 때 환경 변수를 읽는다 · 그래서 이 컨텍스트를 여는
그 순간만 환경 변수를 바꿨다 되돌린다(그룹 컨텍스트는 이미 열려 그 값을 다시 읽지 않는다) · Ctrl-C(SIGINT)는 rclpy 가
모든 컨텍스트를 내린다 · 그 뒤 이 연결로 못 보내면 부르는 쪽이 웹 길로 되돌린다.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from motion_common import generation as generation_mod

#: 노드 이름 · `ros2 node list`(로컬 env)에서 연동 노드의 로컬 쪽으로 보인다
LINK_NODE_NAME = 'motion_group_local_link'
#: 요청 번호 앞 글자 · 웹(`run`)과 갈린다 · 재생 관리자 · 웹 로그에서 누가 보냈는지 보인다
REQUEST_PREFIX = 'coord'
#: 재생 관리자 응답을 못 받았을 때 · 웹 길과 같은 글 · 받는 쪽 판정(`is_not_accepted_rejection` 등)이 그대로 쓴다
RESPONSE_TIMEOUT_TEXT = 'motion_run_manager response timeout'

#: 환경 변수를 바꿨다 되돌리는 동안 다른 컨텍스트가 열리지 않게
_ENV_LOCK = threading.Lock()


class LinkUnavailable(RuntimeError):
    """로컬 연결로 보낼 수 없다 · 부르는 쪽은 웹 길(HTTP)로 되돌린다"""


def _parse(data: Any) -> Dict[str, Any]:
    try:
        value = json.loads(data)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


class LocalLink:
    """로컬 도메인 컨텍스트 하나 · 상태 받기 · 요청 · 안전 정지 · 살아 있음

    받는 일(`on_*`)과 보내는 일(`_send_*`)은 ROS 없이도 돈다 · 시험은 `_send_*` 를 갈아 끼우고 `on_*` 를 부른다 ·
    `start()` 가 실제 ROS 를 잇는다.
    """

    def __init__(self, *, logger: Optional[Callable[[str], None]] = None) -> None:
        self._lock = threading.Lock()
        self._log = logger
        self._runtime: Dict[str, Any] = {}
        self._runtime_at = 0.0
        self._safety: Dict[str, Any] = {}
        self._safety_at = 0.0
        #: 요청 번호 → [깨울 것, 답]
        self._pending: Dict[str, list] = {}
        self._send_request: Optional[Callable[[str], None]] = None
        self._send_safety: Optional[Callable[[str], None]] = None
        self._send_alive: Optional[Callable[[str], None]] = None
        self._ok: Callable[[], bool] = lambda: True
        self.started_at = 0.0
        self.domain_id: Optional[int] = None
        self.localhost_only: Optional[bool] = None
        self.error = ''
        self._context = None
        self._node = None
        self._executor = None
        self._thread: Optional[threading.Thread] = None
        self._closed = False

    # ------------------------------------------------------------------ #
    # 잇기 · 끊기
    # ------------------------------------------------------------------ #

    def start(self, *, domain_id: int, localhost_only: bool) -> bool:
        """로컬 도메인에 컨텍스트 · 노드 · 실행기 스레드 · 못 하면 거짓(사유 `error`) · 그때는 웹 길"""
        try:
            import rclpy
            from rclpy.context import Context
            from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
            from rclpy.node import Node
            from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
            from rclpy.signals import SignalHandlerOptions
            from std_msgs.msg import String

            from motion_common import topics

            context = Context()
            with _ENV_LOCK:
                previous = os.environ.get('ROS_LOCALHOST_ONLY')
                os.environ['ROS_LOCALHOST_ONLY'] = '1' if localhost_only else '0'
                try:
                    # 신호 처리는 그룹 컨텍스트가 이미 걸었다 · 여기서 다시 걸지 않는다
                    rclpy.init(
                        context=context, domain_id=int(domain_id),
                        signal_handler_options=SignalHandlerOptions.NO,
                    )
                finally:
                    if previous is None:
                        os.environ.pop('ROS_LOCALHOST_ONLY', None)
                    else:
                        os.environ['ROS_LOCALHOST_ONLY'] = previous
            self._context = context
            # 이름표(PC) 아래에 · 시험처럼 한 기계에 PC 여럿이어도 노드 이름이 안 겹친다 · 토픽은 절대 이름이라 상관없다
            namespace = topics.pc_namespace()
            node = Node(LINK_NODE_NAME, namespace=f'/{namespace}' if namespace else None, context=context)
            self._node = node
            # 감독 안전 상태 · 재생 관리자가 받는 것과 같은 QoS(마지막 한 장을 늦게 붙어도 받는다)
            safety_qos = QoSProfile(
                depth=1, reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
            )
            node.create_subscription(
                String, topics.MOTION_RUN_STATUS, lambda message: self.on_runtime_status(message.data), 10,
            )
            node.create_subscription(
                String, topics.SAFETY_STATUS, lambda message: self.on_safety_status(message.data), safety_qos,
            )
            node.create_subscription(
                String, topics.MOTION_RUN_RESPONSE, lambda message: self.on_response(message.data), 10,
            )
            request_pub = node.create_publisher(String, topics.MOTION_RUN_REQUEST, 10)
            safety_pub = node.create_publisher(String, topics.SAFETY_REQUEST, 10)
            alive_pub = node.create_publisher(String, topics.COORDINATION_ALIVE, 10)
            self._send_request = lambda text: request_pub.publish(String(data=text))
            self._send_safety = lambda text: safety_pub.publish(String(data=text))
            self._send_alive = lambda text: alive_pub.publish(String(data=text))
            self._ok = context.ok
            executor = SingleThreadedExecutor(context=context)
            executor.add_node(node)
            self._executor = executor

            def spin() -> None:
                try:
                    executor.spin()
                except ExternalShutdownException:
                    pass
                except Exception as exc:  # noqa: BLE001 · 연결이 죽어도 연동 노드는 산다 · 웹 길로
                    self.error = f'로컬 연결 실행기 정지: {exc}'
                    self._note(self.error)

            self._thread = threading.Thread(target=spin, name='motion-coordination-local-link', daemon=True)
            self._thread.start()
            self.domain_id = int(domain_id)
            self.localhost_only = bool(localhost_only)
            self.started_at = time.monotonic()
            self.error = ''
            return True
        except Exception as exc:  # noqa: BLE001 · rclpy 가 없거나 컨텍스트를 못 열면 웹 길 그대로
            self.error = f'로컬 연결을 열지 못함: {exc}'
            self._send_request = self._send_safety = self._send_alive = None
            self._shutdown_ros()
            return False

    @property
    def up(self) -> bool:
        if self._closed or self._send_request is None:
            return False
        try:
            return bool(self._ok())
        except Exception:  # noqa: BLE001
            return False

    def close(self) -> None:
        self._closed = True
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for waiter in pending:
            waiter[0].set()
        self._shutdown_ros()

    def _shutdown_ros(self) -> None:
        executor, node, context, thread = self._executor, self._node, self._context, self._thread
        self._executor = self._node = self._context = self._thread = None
        try:
            if executor is not None:
                executor.shutdown(timeout_sec=1.0)
        except Exception:  # noqa: BLE001, S110 · 이미 내려간 컨텍스트(SIGINT)
            pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)
        try:
            if node is not None:
                node.destroy_node()
        except Exception:  # noqa: BLE001, S110 · 종료 중 · 남은 것을 계속 정리
            pass
        try:
            if context is not None:
                context.try_shutdown()
        except Exception:  # noqa: BLE001, S110 · 종료 중
            pass

    def _note(self, text: str) -> None:
        if self._log is not None:
            try:
                self._log(text)
            except Exception:  # noqa: BLE001, S110 · 로그 실패로 연결을 멈추지 않는다
                pass

    # ------------------------------------------------------------------ #
    # 받기 · 실행기 스레드에서
    # ------------------------------------------------------------------ #

    def on_runtime_status(self, data: Any) -> None:
        value = _parse(data)
        if not value:
            return
        with self._lock:
            self._runtime = value
            self._runtime_at = time.monotonic()

    def on_safety_status(self, data: Any) -> None:
        value = _parse(data)
        if not value:
            return
        with self._lock:
            self._safety = value
            self._safety_at = time.monotonic()

    def on_response(self, data: Any) -> None:
        value = _parse(data)
        request_id = str(value.get('request_id') or '')
        if not request_id:
            return
        with self._lock:
            waiter = self._pending.get(request_id)
            if waiter is None:
                return   # 웹이 보낸 요청의 답 · 웹이 받는다
            waiter[1] = value
        waiter[0].set()

    # ------------------------------------------------------------------ #
    # 보기
    # ------------------------------------------------------------------ #

    def runtime(self) -> Tuple[Dict[str, Any], float]:
        """마지막 재생 관리자 상태 · 받은 때(monotonic · 0 = 아직)"""
        with self._lock:
            return dict(self._runtime), self._runtime_at

    def safety(self) -> Tuple[Dict[str, Any], float]:
        with self._lock:
            return dict(self._safety), self._safety_at

    def stamp(self) -> Dict[str, Any]:
        """재생 관리자가 지금 쥔 실행 설정 · 요청에 싣는다 · 모르면 `LinkUnavailable`

        재생 관리자는 세대(`project_generation`) · 실행 컨텍스트가 제 것과 같은 요청만 받는다 · 그 값은 재생 관리자 상태의
        `execution_context` 에 늘 실린다 · 그룹 세션이 도는 동안은 컨텍스트를 바꿀 수 없어(재생 관리자가 거절) 이 값이 그
        세션의 것이다 · 세션을 새로 여는 `group_prepare` 만은 준비 검사 때 웹이 준 값(`run_request`)을 쓴다.
        """
        runtime, received = self.runtime()
        context = runtime.get('execution_context') if received else None
        context = context if isinstance(context, Mapping) else {}
        try:
            generation = int(context.get('project_generation') or 0)
        except (TypeError, ValueError):
            generation = 0
        if generation < 1:
            raise LinkUnavailable('재생 관리자 실행 설정(세대)을 아직 모름')
        return {
            'project_id': str(context.get('project_id') or ''),
            'project_generation': generation,
            'context_id': str(context.get('context_id') or ''),
        }

    # ------------------------------------------------------------------ #
    # 보내기
    # ------------------------------------------------------------------ #

    def request(
        self, command: str, payload: Mapping[str, Any], *,
        timeout_sec: float, stamp: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """재생 관리자 요청 하나 · 답을 기다린다 · 답이 없으면 웹 길과 같은 「response timeout」 실패

        보내지 못하면(연결 없음 · 세대 모름) `LinkUnavailable` · 보낸 뒤 시간이 지나면 실패 답(이미 받았을 수 있어
        웹 길로 다시 보내지 않는다).
        """
        if not self.up:
            raise LinkUnavailable(self.error or '로컬 연결 없음')
        stamp = dict(stamp) if stamp else self.stamp()
        generation = int(stamp.get('project_generation') or 0)
        if generation < 1:
            raise LinkUnavailable('요청에 포함할 세대 정보 없음')
        body = dict(payload or {})
        body['project_id'] = str(stamp.get('project_id') or '')
        body['project_generation'] = generation
        if stamp.get('context_id'):
            body['context_id'] = str(stamp['context_id'])
        request_id = generation_mod.new_request_id(REQUEST_PREFIX, generation)
        waiter = [threading.Event(), None]
        with self._lock:
            self._pending[request_id] = waiter
        try:
            try:
                self._send_request(json.dumps({
                    'request_id': request_id,
                    'project_generation': generation,
                    'command': str(command),
                    'payload': body,
                }, ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001 · 컨텍스트가 내려감(SIGINT) · 웹 길로
                raise LinkUnavailable(f'로컬 연결 전송 실패: {exc}') from exc
            waiter[0].wait(max(float(timeout_sec), 0.0))
            answer = waiter[1]
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
        if not isinstance(answer, dict):
            return {'success': False, 'message': RESPONSE_TIMEOUT_TEXT, 'status': {}}
        answer = dict(answer)
        answer.pop('request_id', None)
        return answer

    def safety_stop(self) -> str:
        """감독에 안전 정지 · 답을 기다리지 않는다 · 웹 `publish_safety_stop` 과 같은 글 · 세대를 보지 않는 명령"""
        if not self.up or self._send_safety is None:
            raise LinkUnavailable(self.error or '로컬 연결 없음')
        request_id = f'{REQUEST_PREFIX}-safety-stop-{time.time_ns()}'
        try:
            self._send_safety(json.dumps({
                'request_id': request_id,
                'command': 'safety_motion_stop',
            }, separators=(',', ':')))
        except Exception as exc:  # noqa: BLE001
            raise LinkUnavailable(f'안전 정지 전송 실패: {exc}') from exc
        return request_id

    def alive(self, info: Mapping[str, Any]) -> bool:
        """연동 노드 살아 있음 · 웹 역감시가 받는다 · 못 보내도 조용히(웹 역감시가 PID 로 가른다)"""
        if not self.up or self._send_alive is None:
            return False
        try:
            self._send_alive(json.dumps(dict(info), ensure_ascii=False, separators=(',', ':')))
        except Exception:  # noqa: BLE001
            return False
        return True
