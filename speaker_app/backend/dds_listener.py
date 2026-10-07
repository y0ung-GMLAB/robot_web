"""DDS 구독 전용 리스너.

이 파일이 rclpy를 import하는 유일한 곳이다. 나머지 모듈은 ROS를 모른다.
따라서 ROS가 없거나 DDS가 붙지 않아도 재생과 웹 UI는 정상 동작한다.

원칙: 발행(publish) 0건. 어떤 토픽에도 쓰지 않는다.
"""
import os
import threading
import time
from collections import deque

import sysinfo

TOPIC = "/motion_group/command"
EVENT_TOPIC = "/motion_group/event"

# 이 상태가 오면 재생을 멈춘다. motion_completed(정상 사이클 종료)는 제외한다.
STOP_STATES = ("stopped", "error")
NODE_NAME = "speaker_trigger_listener"

OFF = "off"
CONNECTING = "connecting"
CONNECTED = "connected"
ERROR = "error"

# 부팅 직후에는 Wi-Fi DHCP보다 이 앱이 먼저 뜬다. 네트워크가 없는 상태로
# rclpy를 초기화하면 참가자가 loopback에만 묶이고, FastDDS는 참가자 생성 시점에
# 인터페이스를 한 번만 열거하므로 나중에 랜이 올라와도 상대를 영구히 못 찾는다.
# 그래서 초기화 전에 기본 경로가 잡힐 때까지 기다린다.
NET_WAIT_SEC = 30


class DdsListener:
    def __init__(self, logbuf):
        self._log = logbuf
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._status = OFF
        self._error = ""
        self._on_trigger = None
        self._on_stop = None
        self._watch_stop = False
        self._group_id = ""
        self._domain_id = 0
        self._seen = deque(maxlen=500)
        self._seen_set = set()
        # 첫 시작(및 재시작) 결과 — 웹에서 성공/실패를 그대로 보여주기 위한 값
        self._init_ok = None        # None=시도 전, True=성공, False=실패
        self._init_error = ""
        self._bound_ip = ""
        self._bound_iface = ""
        self._started_at = 0.0

    # ---- 조회 -------------------------------------------------------
    @property
    def status(self):
        with self._lock:
            return self._status

    @property
    def error(self):
        with self._lock:
            return self._error

    @property
    def init(self):
        """첫 연동 시도의 결과 묶음. 웹 표시용."""
        with self._lock:
            elapsed = time.time() - self._started_at if self._started_at else 0.0
            return {
                "ok": self._init_ok,
                "error": self._init_error,
                "ip": self._bound_ip,
                "iface": self._bound_iface,
                "elapsed": int(elapsed),
                "domain_id": self._domain_id,
                "group_id": self._group_id,
            }

    def _set_status(self, status, error=""):
        with self._lock:
            self._status = status
            self._error = error

    def _fail(self, message):
        """시작 실패를 상태와 로그에 함께 남긴다."""
        with self._lock:
            self._status = ERROR
            self._error = message
            self._init_ok = False
            self._init_error = message
        self._log.add("DDS 시작 실패: %s" % message)

    # ---- 제어 -------------------------------------------------------
    def start(self, domain_id, group_id, on_trigger, on_stop=None, watch_stop=False):
        self.stop()
        self._domain_id = int(domain_id)
        self._group_id = str(group_id)
        self._on_trigger = on_trigger
        self._on_stop = on_stop
        self._watch_stop = bool(watch_stop)
        self._stop = threading.Event()
        self._seen.clear()
        self._seen_set.clear()
        self._thread = threading.Thread(target=self._run, args=(self._stop,), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=8)
        self._set_status(OFF)

    def set_group_id(self, group_id):
        """그룹 ID는 단순 필터라 재시작 없이 즉시 반영된다."""
        self._group_id = str(group_id)

    # ---- 내부 -------------------------------------------------------
    def _wait_network(self, stop_event):
        """기본 경로가 잡힐 때까지 최대 NET_WAIT_SEC 기다린다. (ip, iface) 반환."""
        deadline = time.time() + NET_WAIT_SEC
        waited = False
        while True:
            ip, iface = sysinfo.network(force=True)
            if iface != "-" and not ip.startswith("127."):
                if waited:
                    self._log.add("네트워크 확인됨 (%s %s)" % (iface, ip))
                return ip, iface
            if stop_event.is_set() or time.time() >= deadline:
                return ip, iface
            if not waited:
                waited = True
                self._log.add("네트워크 대기 중 (최대 %d초)" % NET_WAIT_SEC)
            stop_event.wait(1.0)

    def _run(self, stop_event):
        self._set_status(CONNECTING)
        with self._lock:
            self._init_ok = None
            self._init_error = ""
            self._bound_ip = ""
            self._bound_iface = ""
            self._started_at = time.time()
        rclpy = None
        context = None
        node = None
        executor = None
        try:
            os.environ["ROS_LOCALHOST_ONLY"] = "0"
            import rclpy as _rclpy
            from rclpy.context import Context
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.qos import (DurabilityPolicy, HistoryPolicy, QoSProfile,
                                   ReliabilityPolicy)
            from motion_coordination_interfaces.msg import GroupCommand, GroupEvent

            rclpy = _rclpy
            ip, iface = self._wait_network(stop_event)
            if stop_event.is_set():
                return
            if iface == "-" or ip.startswith("127."):
                self._fail("네트워크가 없어 DDS를 시작하지 못했습니다 "
                           "(%d초 대기 후 포기, 랜/Wi-Fi 확인 후 재시작 필요)" % NET_WAIT_SEC)
                return
            context = Context()
            rclpy.init(context=context, domain_id=self._domain_id)
            # 발자국 최소화: rosout 로그 발행과 파라미터 서비스를 끈다.
            # 도메인에 남는 것은 command 토픽 구독 하나뿐이 되도록 한다.
            node = rclpy.create_node(
                NODE_NAME,
                context=context,
                enable_rosout=False,
                start_parameter_services=False,
            )

            # BEST_EFFORT + VOLATILE: RELIABLE 발행자와 정상 매칭되면서
            # 발행자에게 ACK/재전송 의무를 지우지 않는다.
            qos = QoSProfile(
                depth=32,
                history=HistoryPolicy.KEEP_LAST,
                reliability=ReliabilityPolicy.BEST_EFFORT,
                durability=DurabilityPolicy.VOLATILE,
            )
            node.create_subscription(GroupCommand, TOPIC, self._on_message, qos)
            if self._watch_stop:
                # event 토픽도 VOLATILE 이라 발행자에게 부담이 없다
                node.create_subscription(GroupEvent, EVENT_TOPIC, self._on_event, qos)

            executor = SingleThreadedExecutor(context=context)
            executor.add_node(node)
            with self._lock:
                self._init_ok = True
                self._init_error = ""
                self._bound_ip = ip
                self._bound_iface = iface
            self._log.add("DDS 시작 성공 — 도메인 %d / 그룹 %s / %s %s%s"
                          % (self._domain_id, self._group_id, iface, ip,
                             " / 정지신호 수신" if self._watch_stop else ""))

            last_check = 0.0
            was_connected = False
            while not stop_event.is_set():
                executor.spin_once(timeout_sec=0.2)
                now = time.time()
                if now - last_check >= 1.0:
                    last_check = now
                    connected = node.count_publishers(TOPIC) > 0
                    self._set_status(CONNECTED if connected else CONNECTING)
                    if connected != was_connected:
                        self._log.add("모션 PC 연결됨" if connected else "모션 PC 연결 끊김")
                        was_connected = connected
        except ImportError as exc:
            self._fail("ROS 환경이 로드되지 않았습니다 (%s)" % exc)
            return
        except Exception as exc:
            self._fail(str(exc))
            return
        finally:
            try:
                if executor is not None:
                    executor.shutdown()
            except Exception:
                pass
            try:
                if node is not None:
                    node.destroy_node()
            except Exception:
                pass
            try:
                if rclpy is not None and context is not None:
                    rclpy.shutdown(context=context)
            except Exception:
                pass
        self._set_status(OFF)
        self._log.add("DDS 리스너 정지")

    def _on_message(self, msg):
        # 1) 우리 그룹인가
        if msg.group_id != self._group_id:
            return
        # 2) 모션 시작 명령인가 (initialize_at / cycle_initialize_at 은 제외)
        if msg.command != "start_at":
            return
        # 3) 초기화 전용 실행이 아닌가
        if msg.initialization_only:
            return
        # 4) 처음 보는 명령인가 (3대가 같은 명령을 받으므로 중복 제거 필수)
        command_id = msg.command_id
        if not command_id or command_id in self._seen_set:
            return
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(command_id)
        self._seen_set.add(command_id)

        callback = self._on_trigger
        if callback is not None:
            try:
                callback(msg)
            except Exception as exc:
                self._log.add("트리거 처리 오류: %s" % exc)

    def _on_event(self, msg):
        """모션 정지/오류 이벤트. 판정을 단순하게 유지한다."""
        if msg.group_id != self._group_id:
            return
        if msg.state not in STOP_STATES:
            return
        callback = self._on_stop
        if callback is not None:
            try:
                callback(msg)
            except Exception as exc:
                self._log.add("정지 처리 오류: %s" % exc)
