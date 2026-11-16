"""Validate and execute motion plans independently from the web API process."""

import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import rclpy
import yaml
from motion_common import paths as common_paths
from motion_common.execution_context import confirm_context_id
from motion_common.paths import project_dir_for
from motion_common import check_timing, command_router, generation as generation_mod, latest_tap, motion_tracks, smoothing, topics, wire_units
from motion_common import run_state
from motion_common import stop_fence
from motion_common.values import finite_float, optional_int
from motion_control_msgs.msg import MotorStatus
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.serialization import deserialize_message
from std_msgs.msg import String

from .motion_run_constants import (
    DEFAULT_PERIOD_SEC,
    STATE_TIMEOUT_SEC,
    SAFETY_STATUS_TIMEOUT_SEC,
    AC_TARGET_TOLERANCE_DEG,
    AC_TARGET_TOLERANCE_JOINT_DEG,
    DYNAMIXEL_TARGET_TOLERANCE_DEG,
    TARGET_SETTLE_TIMEOUT_SEC,
)
from . import motion_run_rules
from .group_session import GroupSession
from .motion_file_reader import parse_motion_tracks
from .motion_player import MotionPlayer
from .plan_builder import PlanBuilder
from .plan_cache import SingleFlightCache
from .registered_motion_file import playlist_from_mapping
from .motion_automation_store import (
    MotionAutomationStore,
    default_automation_state,
    normalize_automation_state,
)
from .motion_group_display import apply_group_display
from .motion_trace import DEFAULT_MAX_BYTES, DEFAULT_RETENTION_DAYS, MotionTraceRecorder


#: 캐시를 처음 쓸 때 만드는 곳이 두 스레드에서 겹치지 않게 · 수정 목록 164
_LAZY_CACHE_LOCK = threading.Lock()


# 프로젝트 폴더는 `motion_common.paths` 하나가 정한다 · 파라미터로 받지 않는다 · 수정 목록 32
DEFAULT_MOTION_PROJECTS_DIR = common_paths.motion_projects_dir()


def check_timing_text(timing: Dict[str, Any]) -> str:
    """단계별 시간 한 줄 · 「대기 0 · 파일 3200 · 재샘플 1800(새로) · 계획 5050 ms」 · 수정 목록 174"""
    text = check_timing.stage_text(timing)
    return f'{text} ms' if text else '단계 기록 없음'


def _decode_motor_positions(raw: bytes) -> Dict[int, float]:
    """모터 노드 상태 바이트 → {controller_index: 모터 rad} · 기록 쓰기 스레드가 부른다."""
    msg = deserialize_message(raw, MotorStatus)
    return {
        int(index): wire_units.from_motor_node(position)
        for index, position in zip(msg.controller_index, msg.position)
    }


#: 재생이 **비켜 주지 않아도 되는** 주인 · §6-290
#:
#: 중재기는 재생이 MIDI 를 뺏도록 돼 있다(`_PREEMPTS`) · 그런데 시작 판정은
#: 그보다 엄격해서, 어느 PC 에서 페이더 하나만 잡고 있어도 그 PC 가 「준비 안
#: 됨」으로 답했고 **그룹 전체가 취소**됐다 · 실측으로 pc-a 의 MIDI 때문에
#: 세 대짜리 그룹이 못 떴다.
#:
#: 모션 실행은 MIDI 와 상관없이 시작한다 · 축은 중재기가 넘겨준다.
#:
#: 수동 조그는 그대로 막는다 · 재생이 그것은 못 뺏는다 · 사람이 손으로 움직이는
#: 중에 모션이 끼어들면 안 된다.
#:
#: 'stream' = 수동 스트림(페이더) · 옛 MIDI 경로를 개명한 것(P4-1) · supervisor 가
#: 2026-10-01 부터 이 이름으로 보낸다 · 'midi' 는 개명 전 supervisor 와 섞여
#: 도는 배포 과도기용으로 남긴다 (원자 배포가 끝나면 지워도 된다).
PLAYBACK_MAY_TAKE_FROM = ('none', 'playback', 'stream', 'midi')


class MotionRunManager(Node):
    """Runs a saved motion file through a saved motion-axis mapping.

    This node owns the motion-file lifecycle but never publishes to the final
    hardware command topic. Combined setpoints are submitted to the supervisor
    through /motion_run/command.
    """

    def __init__(self) -> None:
        super().__init__('motion_run_manager')

        self.motion_state_topic = str(
            self.declare_parameter('motion_state_topic', topics.MOTION_STATE).value
        )
        # 이 노드의 출력은 최종 하드웨어 명령이 아니라 supervisor로 보내는 합산 요청이다.
        # motion_supervisor의 동명 파라미터(motor_command_topic)는 최종 출력 토픽이므로
        # 이름을 분리해 launch 재정의 시 오배선을 막는다.
        self.motion_run_command_topic = str(
            self.declare_parameter(
                'motion_run_command_topic',
                topics.MOTION_RUN_COMMAND,
            ).value
        )
        self.request_topic = str(
            self.declare_parameter(
                'request_topic',
                topics.MOTION_RUN_REQUEST,
            ).value
        )
        self.response_topic = str(
            self.declare_parameter(
                'response_topic',
                topics.MOTION_RUN_RESPONSE,
            ).value
        )
        self.status_topic = str(
            self.declare_parameter(
                'status_topic',
                topics.MOTION_RUN_STATUS,
            ).value
        )
        self.motion_value_topic = str(
            self.declare_parameter(
                'motion_value_topic',
                topics.MOTION_VALUE_STATE,
            ).value
        )
        self.safety_status_topic = str(
            self.declare_parameter(
                'safety_status_topic',
                topics.SAFETY_STATUS,
            ).value
        )
        self.action_request_topic = str(
            self.declare_parameter(
                'action_request_topic',
                topics.MANUAL_ACTION_REQUEST,
            ).value
        )
        self.action_result_topic = str(
            self.declare_parameter(
                'action_result_topic',
                topics.MANUAL_ACTION_RESULT,
            ).value
        )
        self.motion_projects_dir = Path(DEFAULT_MOTION_PROJECTS_DIR).expanduser().resolve()
        self.period_sec = self._load_period_sec()
        self.motion_files_dir = self.motion_projects_dir
        self.mappings_dir = self.motion_projects_dir

        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        self._state_lock = threading.Lock()
        self._latest_state: Optional[Dict[str, Any]] = None
        self._latest_state_at: Optional[float] = None
        self._safety_status_lock = threading.Lock()
        self._latest_safety_status: Optional[Dict[str, Any]] = None
        self._latest_safety_status_at: Optional[float] = None
        self._run_lock = threading.RLock()
        #: 재생 라이브 오버라이드 · 조인트 뮤트·좁힌 리밋 · P7
        #:
        #: 재생 **중에도** 바꿀 수 있다 · 발행 직전에 읽어서 적용하므로
        #: 다음 20ms 틱부터 듣는다 · 계획(plan)은 건드리지 않는다.
        self._live_overrides: Dict[str, Dict[str, Any]] = {}
        self._live_override_lock = threading.Lock()
        self._run_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._graceful_stop_event = threading.Event()
        # 정지 표지 · 재생 세션 · 수정 목록 200 · 203 (`motion_common.stop_fence`)
        #: 감독 safety 상태에서 마지막으로 본 표지 · 상태에 실어 「봤다」 를 알린다
        self._seen_stop_marker: Optional[stop_fence.Marker] = None
        #: 지금 실행을 잡을 때의 표지 · 이것과 다르면 그 뒤에 감독 정지가 있었다
        self._run_stop_marker: Optional[stop_fence.Marker] = None
        #: 실행 스레드가 할 일을 다 했다(곧 끝난다) · 세션을 닫는 표시 · 단독 실행만 적는다
        self._run_task_done = True
        #: 이 표지의 정지로 이미 세운 실행 · 같은 정지로 두 번 세우지 않게
        self._supervisor_stopped_marker: Optional[stop_fence.Marker] = None
        # 그룹 세션은 별도 객체가 갖는다 · 조건변수는 실행 락 위에 선다 (§6-29)
        self._plan_builder = PlanBuilder(self)
        self._player = MotionPlayer(self)
        self._group = GroupSession(self, run_lock=self._run_lock)
        self._automation_store = MotionAutomationStore(self.motion_projects_dir)
        self._automation_state = default_automation_state()
        self._automation_runtime: Dict[str, Any] = {
            'state': 'off',
            'message': '',
            'stop_after_cycle': False,
        }
        self._automation_project_id = ''
        self._automation_last_attempt_at = 0.0
        self.ac_target_tolerance_deg = max(
            float(self.declare_parameter('ac_target_tolerance_deg', AC_TARGET_TOLERANCE_DEG).value),
            0.0,
        )
        self.ac_target_tolerance_joint_deg = max(
            float(self.declare_parameter(
                'ac_target_tolerance_joint_deg', AC_TARGET_TOLERANCE_JOINT_DEG,
            ).value),
            0.0,
        )
        self.dynamixel_target_tolerance_deg = max(
            float(
                self.declare_parameter(
                    'dynamixel_target_tolerance_deg',
                    DYNAMIXEL_TARGET_TOLERANCE_DEG,
                ).value
            ),
            0.0,
        )
        self.target_settle_timeout_sec = max(
            float(self.declare_parameter('target_settle_timeout_sec', TARGET_SETTLE_TIMEOUT_SEC).value),
            0.0,
        )
        self._status: Dict[str, Any] = motion_run_rules._empty_status()
        self._execution_context: Dict[str, Any] = {}
        self._execution_context_ready = False
        self._project_generation = 0
        self._action_result_lock = threading.Lock()
        self._action_results: Dict[str, List[Dict[str, Any]]] = {}

        self._state_sub = self.create_subscription(
            String,
            self.motion_state_topic,
            self._motion_state_callback,
            10,
        )
        safety_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._safety_status_sub = self.create_subscription(
            String,
            self.safety_status_topic,
            self._safety_status_callback,
            safety_qos,
        )
        self._request_sub = self.create_subscription(
            String,
            self.request_topic,
            self._request_callback,
            10,
        )
        self._action_result_sub = self.create_subscription(
            String,
            self.action_result_topic,
            self._action_result_callback,
            10,
        )
        self._response_pub = self.create_publisher(String, self.response_topic, 10)
        self._status_pub = self.create_publisher(String, self.status_topic, 10)
        self._command_pub = self.create_publisher(MotorStatus, self.motion_run_command_topic, qos)
        motion_value_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._motion_value_pub = self.create_publisher(
            String, self.motion_value_topic, motion_value_qos
        )
        self._action_request_pub = self.create_publisher(String, self.action_request_topic, 10)
        # X-Touch 녹화 재생 · 구간 덮어쓰기 입력 · 프레임 알림 · 수정 목록 156 ⑨
        self._punch_lock = threading.Lock()
        self._punch_controller = None
        self._punch_input_sub = self.create_subscription(
            String, topics.MOTION_RUN_PUNCH_INPUT, self._punch_input_callback, 50,
        )
        self._take_frame_pub = self.create_publisher(String, topics.MOTION_RUN_TAKE_FRAMES, 50)
        self._status_timer = self.create_timer(0.5, self._publish_status)
        self._automation_timer = None

        # 회차별 목표·실제 기록 · 실제 위치는 모터 노드 1kHz 상태에서 바이트로만 받는다
        self._motion_trace = MotionTraceRecorder(
            decode=_decode_motor_positions,
            logger=self.get_logger(),
            enabled=bool(self.declare_parameter('motion_trace_enabled', True).value),
            retention_days=int(self.declare_parameter(
                'motion_trace_retention_days', DEFAULT_RETENTION_DAYS).value),
            max_bytes=int(self.declare_parameter(
                'motion_trace_max_mb', DEFAULT_MAX_BYTES // (1024 * 1024)).value) * 1024 * 1024,
        )
        self._motor_status_raw_sub = None
        self._motor_status_tap = None
        if self._motion_trace.enabled:
            motor_status_topic = str(
                self.declare_parameter('motor_status_topic', topics.MOTOR_STATUS).value
            )
            # 실행기 밖 구독 · 재생 틱에 마지막 한 장만 꺼낸다 · 서 있을 때 1 kHz 로 깨지 않게 · 수정 목록 130
            self._motor_status_tap = latest_tap.open_tap(
                self, MotorStatus, motor_status_topic,
                node_class=Node, qos=qos, raw=True,
                suffix='motor_status_tap', logger=self.get_logger(),
            )
            if self._motor_status_tap is not None:
                self._motion_trace.set_poll(self._motor_status_tap.take_latest)
            else:
                self._motor_status_raw_sub = self.create_subscription(
                    MotorStatus,
                    motor_status_topic,
                    self._motion_trace.on_motor_status,
                    qos,
                    raw=True,
                )

        self.get_logger().info(
            f'motion_run_manager started: state={self.motion_state_topic}, '
            f'command={self.motion_run_command_topic}, request={self.request_topic}, '
            f'action_request={self.action_request_topic}, '
            f'safety_status={self.safety_status_topic}, '
            f'period={self.period_sec * 1000.0:.3f} ms, '
            f'motion_projects_dir={self.motion_projects_dir}'
        )

    def _motion_trace_begin(self, plan: Dict[str, Any], cycle_number: int):
        """회차 기록을 연다 · 무슨 일이 있어도 재생을 막지 않는다."""
        try:
            project_dir = project_dir_for(self.motion_projects_dir, str(plan.get('project_id') or ''))
            return self._motion_trace.begin(plan, cycle_number, project_dir)
        except Exception as exc:  # noqa: BLE001 · 기록을 못 열어도 재생은 계속한다
            self.get_logger().warning(f'motion trace disabled for this cycle: {exc}')
            return None

    def destroy_node(self):
        executor = getattr(self, '_check_executor', None)
        if executor is not None:
            executor.shutdown(wait=False)
        # 쓰다 만 회차 기록을 마저 쓴다
        self._motion_trace.close()
        tap = getattr(self, '_motor_status_tap', None)
        if tap is not None:
            self._motion_trace.set_poll(None)
            tap.close()
        return super().destroy_node()

    def _motion_state_callback(self, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warn('Invalid motion_state JSON received.')
            return
        with self._state_lock:
            self._latest_state = payload if isinstance(payload, dict) else None
            self._latest_state_at = time.time()
        self._warm_on_motor_limits_change(payload)

    @staticmethod
    def _motor_limits_signature(motors: Any) -> Optional[tuple]:
        """재샘플 변환본 키에 드는 모터 값(번호 · 하한 · 상한) · 모터가 없으면 None · 수정 목록 208"""
        if not isinstance(motors, list):
            return None
        signature = tuple(
            (
                optional_int(motor.get('controller_index')),
                wire_units.motor_limit(motor, 'lower'),
                wire_units.motor_limit(motor, 'upper'),
            )
            for motor in motors
            if isinstance(motor, dict)
        )
        return signature or None

    def _warm_on_motor_limits_change(self, state: Any) -> None:
        """모터 한계가 바뀌면(장비에 적용 · 모터 재시작) 재생 등록 애니를 다시 변환해 둔다 · 수정 목록 208

        한계는 재샘플 키에 든다 · 매핑 저장(새 실행 컨텍스트)은 모터 재시작보다 먼저 와서 그때 변환본은 옛
        한계로 지어진다 · 여기서 새 한계를 보면 다시 · 실행 중이면 끝난 뒤 다음 상태에서.
        """
        signature = self._motor_limits_signature(state.get('motors') if isinstance(state, dict) else None)
        if signature is None or signature == getattr(self, '_warm_limits_signature', None):
            return
        if getattr(self, '_run_lock', None) is None or self._warm_should_yield():
            return
        # 실행 락 없이 읽는다 · 상태 콜백(10 Hz)이 계획 짓는 쪽을 기다리지 않게 · 컨텍스트는 통째로 바꿔 끼운다
        context = getattr(self, '_execution_context', None) or {}
        if not getattr(self, '_execution_context_ready', False) or not context:
            return
        context = dict(context)
        self._warm_limits_signature = signature
        self._warm_motion_cache(context)

    def _safety_status_callback(self, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warn('Invalid safety_status JSON received.')
            return
        if not isinstance(payload, dict):
            return
        with self._safety_status_lock:
            self._latest_safety_status = payload
            self._latest_safety_status_at = time.monotonic()
        self._on_stop_marker(payload)

    # ------------------------------------------------------------------ #
    # 정지 표지 · 재생 세션 · 수정 목록 200 · 203
    #
    # 감독 정지 = 이 PC 재생 정지 · 전에는 재생기가 safety 상태의 「정지 처리 중」(0.5 s)을 프레임
    # 틱에서 보고서야 섰고, 그 0.5 s 안에 정지 요청이 안 오면 오류로 끝났다(112 다 · 1 s 기다림) ·
    # 이제는 표지가 바뀌는 그 순간 「정지」 와 같은 길로 세우고, 표지를 봤다고 상태로 알린다.
    # ------------------------------------------------------------------ #

    def _on_stop_marker(self, safety: Dict[str, Any]) -> None:
        marker = stop_fence.marker(safety)
        if marker is None:
            return
        with self._run_lock:
            if marker == getattr(self, '_seen_stop_marker', None):
                return
            self._seen_stop_marker = marker
        if not stop_fence.hard_block_reason(safety):
            # 알람 · 긴급 · 앱솔루트와 함께 온 정지는 재생기가 오류로 끝낸다(이유가 남아야 한다)
            self.stop_for_supervisor(marker)
        # 표지를 봤다 · 감독이 「정지 정리 끝」 을 판단한다 · 세운 실행은 끝날 때 다시 알린다
        self._announce_playback_session()

    def stop_for_supervisor(self, marker: stop_fence.Marker) -> bool:
        """이 표지 **앞에** 잡은 실행이 돌면 「정지」 버튼과 같은 길로 세운다 · 세웠으면 참"""
        with self._run_lock:
            if not self._run_session_alive():
                return False
            if getattr(self, '_run_stop_marker', None) == marker:
                return False   # 이 정지 뒤에 잡은 실행
            if getattr(self, '_supervisor_stopped_marker', None) == marker:
                return True
            self._supervisor_stopped_marker = marker
        try:
            self.get_logger().info('[정지 표지] 감독 정지 · 이 PC 재생을 「정지」 와 같은 길로 세웁니다')
        except Exception:  # noqa: BLE001 · 로그 실패로 정지를 막지 않는다
            pass
        self._handle_stop()
        return True

    def _run_session_alive(self) -> bool:
        """실행 스레드가 아직 할 일이 남았나 · `_run_lock` 안에서 부른다"""
        thread = getattr(self, '_run_thread', None)
        return bool(
            thread is not None and thread.is_alive()
            and not getattr(self, '_run_task_done', False)
        )

    def _playback_session(self) -> Dict[str, Any]:
        """상태에 싣는 재생 세션 · 감독은 지금 표지로 열린 세션의 프레임만 받는다 · `_run_lock` 안에서"""
        stop_event = getattr(self, '_stop_event', None)
        state = str((getattr(self, '_status', None) or {}).get('state') or '').strip().lower()
        active = (
            self._run_session_alive()
            and not (stop_event is not None and stop_event.is_set())
            and state not in stop_fence.SESSION_ENDED_STATES
        )
        return stop_fence.session_payload(
            active=active,
            streaming=state in stop_fence.STREAMING_STATES,
            run_marker=getattr(self, '_run_stop_marker', None),
            seen_marker=getattr(self, '_seen_stop_marker', None),
        )

    def _run_task(self, mode: str, payload: Dict[str, Any], motors_snapshot: List[Dict[str, Any]]) -> None:
        """단독 실행 스레드 · 끝나면 세션을 닫았다고 바로 알린다 · 수정 목록 203

        감독은 이 알림에서 재생이 쥔 축을 놓는다 · 전에는 마지막 프레임 뒤 0.15 s 임대가 끝나야 놓였다.
        """
        try:
            self._player._prepare_and_run(mode, payload, motors_snapshot)
        finally:
            self._close_run_session()

    def _close_run_session(self) -> None:
        """실행 스레드가 할 일을 다 했다 · 세션을 닫고 바로 알린다 · 단독(`_run_task`) · 그룹(`GroupSession._run`)
        실행 스레드가 끝에서 부른다 · 수정 목록 203

        부른 스레드가 지금 실행 스레드일 때만 닫는다(늦게 끝난 옛 스레드가 새 실행의 세션을 닫지 않게) ·
        전에는 그룹 실행 스레드가 정상으로 끝나면(`completed`) 다음 0.5 s 상태 틱에야 세션이 닫혀 감독이 축을 늦게 놓았다.
        """
        lock = getattr(self, '_run_lock', None)
        if lock is not None:
            with lock:
                if getattr(self, '_run_thread', None) is threading.current_thread():
                    self._run_task_done = True
        self._announce_playback_session()

    def _announce_playback_session(self) -> None:
        """재생 세션이 바뀌었다(표지를 봤다 · 실행이 끝났다) · 상태를 바로 낸다 · 노드 없는 시험 관리자는 건너뛴다"""
        if getattr(self, '_status_pub', None) is None:
            return
        self._publish_status()

    def _action_result_callback(self, msg: String) -> None:
        """Action 결과를 60초 창으로 모아둔다.

        **지금은 읽는 곳이 없다** · 결과를 기다리던 초기 이동 대기 코드가
        §6-49에서 죽은 코드로 판명되어 함께 사라졌다. 구독을 떼는 것은 이 노드가
        토픽에서 빠지는 일이라 별도 판단으로 남긴다 · 모으는 양은 60초로 제한된다.
        """
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warn('Invalid action result JSON received.')
            return
        if not isinstance(payload, dict):
            return
        request_id = str(payload.get('request_id') or '')
        if not request_id:
            return
        generation = int(self._execution_context.get('project_generation') or 0)
        try:
            if int(payload.get('project_generation')) != generation:
                return
        except (TypeError, ValueError):
            return
        now = time.time()
        with self._action_result_lock:
            self._action_results.setdefault(request_id, []).append(payload)
            for key, values in list(self._action_results.items()):
                last_stamp = now
                if values:
                    last_stamp = finite_float(values[-1].get('stamp')) or now
                if now - last_stamp > 60.0:
                    self._action_results.pop(key, None)

    #: 실행 컨텍스트가 서 있어야 처리하는 명령
    #: **모터를 움직이는 명령만** 여기 넣는다 · §6-269
    #:
    #: `automation_configure` 가 여기 있었다 · 그것은 반복 방식을 파일에 적는
    #: 일이고 모터를 건드리지 않는다 · 처리기도 실행 컨텍스트를 읽기만 하고
    #: 쓰지 않는다 · 그런데 모터가 준비되지 않으면 저장이 「현재 프로젝트 실행
    #: 컨텍스트 적용 대기 중입니다」로 거절됐다 (실측 3회 전부 실패).
    #:
    #: 화면은 드롭다운을 회색으로 만들지도 않는다 · 고를 수는 있는데 저장만
    #: 실패했다 · 같은 성격인 스튜디오 레이어 저장·조인트 매핑 읽기·MIDI 뱅크
    #: 편집은 모두 열려 있다.
    COMMANDS_REQUIRING_CONTEXT = frozenset({
        'check',
        'initialize',
        'start',
        'group_prepare',
        'group_start_at',
        'group_initialize_at',
        # 시간표 재생 회차 명령 · 초기 이동 → 시작을 이 PC 가 한다 · 수정 목록 206
        'group_cycle_at',
    })

    def _command_router(self) -> command_router.CommandRouter:
        """처리기 표 · 처음 쓸 때 만든다.

        노드를 띄우지 않고 (`__new__`) 콜백만 검증하는 테스트에서도 동작하도록
        `__init__`에 의존하지 않는다.
        """
        router = getattr(self, '_router', None)
        if router is None:
            router = self._build_router()
            self._router = router
        return router

    def _build_router(self) -> command_router.CommandRouter:
        """명령 → 처리기 표 · 처리기는 payload를 받아 응답 dict를 돌려준다."""
        router = command_router.CommandRouter(context_commands=self.CONTEXT_COMMANDS)
        router.register('apply_context', self._apply_execution_context)
        router.register('confirm_context', self._confirm_execution_context)
        router.register('invalidate_context', self._invalidate_execution_context)
        router.register('status', lambda payload: {
            'success': True, 'message': 'motion run status', 'status': self.status(),
        })
        router.register('automation_configure', self._configure_automation)
        router.register('check', self._handle_check)
        router.register('initialize', lambda payload: self._start_thread('initialize', payload))
        router.register('start', lambda payload: self._start_thread('run', payload))
        router.register('group_prepare', self._group.prepare)
        router.register('group_start_at', self._group.schedule_cycle)
        router.register('group_initialize_at', self._group.schedule_initialization)
        # 시간표 재생 · 회차 하나 = 시작 시각이 박힌 명령 하나 · 수정 목록 206
        router.register('group_cycle_at', self._group.schedule_timed_cycle)
        router.register('group_cancel', self._group.cancel)
        # 도는 그룹에 복귀 · 합류 확정 · 수정 목록 30-3
        router.register('group_join_commit', self._group.commit_join)
        router.register('set_live_override', self._set_live_override)
        router.register('stop', lambda payload: self._handle_stop())
        router.register('stop_after_cycle', self._handle_stop_after_cycle)
        return router

    def _invalidate_execution_context(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """**실행 허용만 거둔다 · 사람이 저장한 설정은 그대로 둔다** · §6-267

        브릿지는 실행 컨텍스트가 준비되지 않으면 **1초마다** 이것을 보낸다 ·
        전에는 그때마다 자동 반복 설정과 그것이 어느 프로젝트 것인지까지
        지웠다.

        `_automation_project_id` 가 비면 저장이 **「자동 반복을 저장할 현재
        프로젝트가 없습니다」**로 거절된다 · 사람이 설정을 고치는 동안 1초마다
        그 상태가 되었다.

        자동 반복 설정은 파일에 저장되고 `select_project` 가 다시 읽는다 ·
        여기서 지울 이유가 없다 · 스튜디오 §6-257 · MIDI §6-265 와 같은 원칙.

        동작 중에는 여전히 거부한다.
        """
        with self._run_lock:
            if self._run_thread is not None and self._run_thread.is_alive():
                raise ValueError('모션 동작 중에는 프로젝트 메모리를 폐기할 수 없습니다')
            self._execution_context = {}
            self._execution_context_ready = False
            self._automation_runtime = {
                'state': 'off',
                'message': '',
                'stop_after_cycle': False,
            }
            project_id = self._automation_project_id
        return {
            'success': True,
            'message': '모션 실행 대기 · 저장된 자동 반복 설정은 유지',
            'project_id': project_id,
            'context_id': '',
            'status': self.status(),
        }

    def _request_callback(self, msg: String) -> None:
        request = command_router.parse_request(msg.data)
        if request is None:
            self.get_logger().warn('invalid motion run request JSON')
            return

        command = request.command
        payload = request.payload

        try:
            self._validate_request_generation(command, request.generation, payload)
            handler = self._command_router().resolve(command)
            if handler is None:
                response = command_router.error_response(
                    f'unknown motion run command: {command}'
                )
            else:
                if command in self.COMMANDS_REQUIRING_CONTEXT:
                    self._require_execution_context(payload)
                if command in self.BACKGROUND_COMMANDS:
                    # 답은 작업 스레드가 다 지은 뒤에 보낸다 · 실행기는 바로 다음 요청으로 · 수정 목록 164
                    self._submit_background(command, request, payload)
                    return
                response = handler(payload)
        except Exception as exc:  # Defensive boundary for the web bridge.
            command_router.log_command_failure(
                self.get_logger(), f'motion run command failed: {command}', exc,
            )
            response = command_router.error_response(
                f'motion run command failed: {exc}'
            )

        self._publish_response(command_router.finalize(response, request))
        self._publish_status()

    #: 실행기(단일 스레드) 밖에서 처리하고 끝나면 답하는 명령 · 수정 목록 164
    #:
    #: 실행 준비 검사(`check`)는 계획을 통째로 짓는다(파일 읽기 · 20 ms 재샘플 · 속도 검사) ·
    #: 920 s × 20 조인트 파일이면 데스크톱에서도 2 s 를 넘었다 · 그동안 실행기가 막혀 뒤따른
    #: `group_prepare` · `status` · `stop` 이 줄을 섰고 브리지가 2 s 만에 「response timeout」 으로
    #: 끝냈다(NY 실물 2026-11-03 · 「준비 거절 · motion_run_manager response timeout」).
    #:
    #: 이제 검사는 작업 스레드 하나가 차례로 처리한다 · 실행기는 정지 · 상태 · 그룹 명령에 바로 답한다.
    #: 실행 슬롯은 잡지 않는다 · 검사는 아무것도 움직이지 않는다.
    #:
    #: 수정 목록 208 · 검사는 디스크 변환본을 읽는다(ms) · 변환본이 없으면 자식 프로세스가 변환하는 동안
    #: 이 스레드는 기다리기만 한다(GIL 을 안 쥔다) · 그래서 쉬어 가기(171 `background_pacing`)는 뺐다.
    BACKGROUND_COMMANDS = frozenset({'check'})

    def _background_executor(self) -> ThreadPoolExecutor:
        executor = getattr(self, '_check_executor', None)
        if executor is None:
            with _LAZY_CACHE_LOCK:
                executor = getattr(self, '_check_executor', None)
                if executor is None:
                    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='motion-check')
                    self._check_executor = executor
        return executor

    def _submit_background(self, command: str, request: Any, payload: Dict[str, Any]) -> None:
        # 상태 표 차례를 받을 때 본다 · 검사 도중 실행이 시작됐거나 상태가 바뀌었으면 검사 결과로 덮지 않는다
        status_epoch = self._status_epoch_now()
        self._background_executor().submit(
            self._run_background, command, request, payload, status_epoch, time.monotonic(),
        )

    def _run_background(
        self, command: str, request: Any, payload: Dict[str, Any], status_epoch: int,
        submitted_at: Optional[float] = None,
    ) -> None:
        # 작업 스레드 줄에서 기다린 시간 · 앞 검사가 길었으면 여기서 보인다 · 수정 목록 174
        queued_ms = (
            None if submitted_at is None
            else round((time.monotonic() - submitted_at) * 1000.0, 1)
        )
        try:
            if command == 'check':
                response = self._handle_check(
                    payload, status_epoch=status_epoch, queued_ms=queued_ms,
                )
            else:
                response = self._command_router().resolve(command)(payload)
        except Exception as exc:  # noqa: BLE001 · 답은 꼭 보낸다 · 안 보내면 브리지가 시간 초과로만 안다
            command_router.log_command_failure(
                self.get_logger(), f'motion run command failed: {command}', exc,
            )
            response = command_router.error_response(f'motion run command failed: {exc}')
        try:
            self._publish_response(command_router.finalize(response, request))
            self._publish_status()
        except Exception as exc:  # noqa: BLE001 · 노드가 내려가는 중
            self.get_logger().warning(f'motion run background response not sent: {exc}')

    def _status_epoch_now(self) -> int:
        with self._run_lock:
            return int(getattr(self, '_status_epoch', 0))

    #: 실행 컨텍스트를 새로 세우는 명령 · 이때만 세대가 오를 수 있다
    #:
    #: 목록의 주인은 `generation` 이다 · §6-166 · 세 노드가 똑같이 적어 두고
    #: 있었다 · 새 명령이 생기면 세 곳을 고쳐야 하고, 빠뜨린 노드만 세대를
    #: 안 올려 그 노드의 응답이 「이전 프로젝트의 늦은 응답」으로 버려진다.
    #:
    #: MIDI 노드는 `select_project` 를 쓰므로 **진짜로 다르다** · 거기는
    #: 제 목록을 갖는다.
    CONTEXT_COMMANDS = generation_mod.CONTEXT_COMMANDS

    def _validate_request_generation(
        self, command: str, request_generation: Any, payload: Dict[str, Any]
    ) -> int:
        advancing = command in self.CONTEXT_COMMANDS
        value = generation_mod.validate_request_generation(
            request_generation,
            payload,
            current_generation=getattr(self, '_project_generation', 0),
            advances_context=advancing,
        )
        if advancing:
            self._project_generation = value
        return value

    def _apply_execution_context(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._clear_live_overrides()
        project_id, _, mappings_dir = self._project_asset_dirs(payload)
        context_id = str(payload.get('context_id') or '').strip()
        mapping_file_id = str(payload.get('mapping_file_id') or '').strip()
        mapping_sha256 = ''
        if not context_id or not mapping_file_id:
            raise ValueError('실행 컨텍스트 ID와 조인트 매핑 버전이 필요합니다')
        mapping_path = self._mapping_file_path(mapping_file_id, mappings_dir)
        actual_sha = ''
        with self._run_lock:
            if self._run_thread is not None and self._run_thread.is_alive():
                raise ValueError('모션 동작 중에는 실행 컨텍스트를 변경할 수 없습니다')
            next_context = {
                'context_id': context_id,
                'project_id': project_id,
                'project_generation': int(payload.get('project_generation') or 0),
                'mapping_file_id': mapping_path.name,
                'mapping_sha256': actual_sha,
            }
            same_context = self._execution_context == next_context
            self._execution_context = next_context
            if not same_context:
                self._execution_context_ready = False
        if not same_context:
            self._load_automation_project(project_id)
        return {
            'success': True,
            'message': '모션 실행 컨텍스트 적용 확인 완료',
            **self._execution_context,
        }

    def _confirm_execution_context(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._run_lock:
            context_id = confirm_context_id(self._execution_context, payload)
            # 부팅 때 스스로 시작하는 기능은 없앴다 · §6-134
            #
            # 켜는 곳이 둘이었고(이 PC · 그룹) 서로 배타적이었다 · 연동을 켜면
            # 로컬이 스스로 꺼지고, 그룹은 필수 PC 가 2대 미만이면 안 떴다 ·
            # 그래서 혼자 쓰는 PC 가 연동을 켜 두면 아무것도 안 됐다.
            #
            # 시작은 사람이 누르거나 스케줄이 시킨다 · 판단 주체가 하나다.
            self._execution_context_ready = True
            context = dict(self._execution_context)
        self._warm_motion_cache(context)
        return {
            'success': True,
            'message': '모션 실행 허용',
            **self._execution_context,
        }

    #: 미리 짓기가 모터 상태(번호 · 한계)를 기다리는 최대 시간 · 실행 허용은 모터 상태가 선 뒤라 보통 바로 · 수정 목록 174
    #: 수정 목록 208 · 아직 필요하다 · 재샘플 변환본 키에 모터 번호 · 한계가 든다(파일 변환은 기다리지 않고 먼저)
    WARM_MOTOR_WAIT_SEC = 30.0
    WARM_MOTOR_POLL_SEC = 0.5

    def _warm_motion_cache(self, context: Dict[str, Any]) -> None:
        """재생 등록 애니를 변환본(디스크)으로 만들어 둔다 · 뒤에서 · 실행 중이면 안 한다 · 수정 목록 164 · 174 · 208

        등록(매핑 · 재생 목록 저장 = 새 context_id → 실행 허용) · 부팅 · 모터 한계 바뀜 때 부른다.
        변환본이 이미 맞으면 읽기만 하고 끝난다(ms) · 없거나 키가 다르면 자식 프로세스가 변환한다 ·
        재생 목록 **전부**(디스크라 칸 제한 없음) · 키는 준비 검사와 똑같이 짓는다(`PlanBuilder.build(warm_only=True)`).

        174 까지는 메모리 캐시에 지어 두어 서비스가 다시 뜰 때마다(재부팅) 다시 지었다 · 이제는 등록 때 한 번.
        도는 중에 새 요청이 오면 끝나고 마지막 요청 하나만 이어서 한다.
        """
        project_id = str(context.get('project_id') or '').strip()
        mapping_file_id = str(context.get('mapping_file_id') or '').strip()
        # 노드 없이 만든 시험 객체(폴더 모름)는 건너뛴다
        if not project_id or not mapping_file_id or getattr(self, 'motion_files_dir', None) is None:
            return
        with self._run_lock:
            if self._warm_should_yield():
                return
            self._warm_request = (project_id, mapping_file_id)
            warm = getattr(self, '_warm_thread', None)
            if warm is not None and warm.is_alive():
                return
            self._warm_thread = threading.Thread(
                target=self._warm_worker,
                name='motion-cache-warm',
                daemon=True,
            )
            self._warm_thread.start()

    def _warm_worker(self) -> None:
        # 무거운 변환은 자식 프로세스 · 이 스레드는 기다리고 읽기만 한다 · 쉬어 가기(171)는 뺐다 · 수정 목록 208
        try:
            while True:
                with self._run_lock:
                    request = getattr(self, '_warm_request', None)
                    self._warm_request = None
                    if request is None:
                        self._warm_thread = None
                        return
                self._warm_motion_cache_now(*request)
        finally:
            with self._run_lock:
                if getattr(self, '_warm_thread', None) is threading.current_thread():
                    self._warm_thread = None

    def _warm_should_yield(self) -> bool:
        """미리 짓기를 시작하지 않을 때 · 애니 사이에서 그만둘 때 · 실행 스레드가 돌면 · 174

        수정 목록 208 · 변환 도중에는 그만두지 않는다(자식 프로세스라 재생과 GIL 을 안 나눈다 · 그 결과를
        준비 검사 · 재생 목록이 곧 쓴다) · 애니와 애니 사이에서만 본다.
        """
        run_thread = getattr(self, '_run_thread', None)
        return run_thread is not None and run_thread.is_alive()

    def _warm_motion_cache_now(self, project_id: str, mapping_file_id: str) -> None:
        try:
            _, motion_files_dir, mappings_dir = self._project_asset_dirs({'project_id': project_id})
            mapping = self._load_mapping(self._mapping_file_path(mapping_file_id, mappings_dir))
            names = []
            for name in playlist_from_mapping(mapping):
                if name and name not in names:
                    names.append(name)
            self._warm_plan_samples(project_id, mapping_file_id, mapping, names, motion_files_dir)
        except Exception as exc:  # noqa: BLE001 · 미리 변환은 실패해도 그만이다 · 검사가 다시 한다
            self.get_logger().info(f'motion cache warm-up skipped: {exc}')

    def _warm_motors(self) -> List[Dict[str, Any]]:
        """미리 짓기에 쓸 모터 상태 · 아직 없으면 잠깐 기다린다 · 실행이 시작되면 빈 목록 · 174"""
        deadline = time.monotonic() + self.WARM_MOTOR_WAIT_SEC
        while True:
            if self._warm_should_yield():
                return []
            motors = self._current_motors()
            if motors or time.monotonic() >= deadline:
                return motors
            time.sleep(self.WARM_MOTOR_POLL_SEC)

    def _warm_plan_samples(
        self, project_id: str, mapping_file_id: str, mapping: Dict[str, Any], names: List[str],
        motion_files_dir: Optional[Path] = None,
    ) -> None:
        """재생 목록 전부를 준비 검사와 같은 요청으로 변환해 둔다 · 수정 목록 174 · 208

        ① 파일 → 조인트별 배열(tracks 변환본) · 모터 상태 없이 · 가장 무거운 몫(파일 읽기)
        ② 20 ms 재샘플 · 속도 검사(samples 변환본) · 모터 번호 · 한계가 키에 들어 모터 상태를 기다린다
        1번을 **마지막에** 지어 메모리 칸(2)에도 남게 · 곧 올 준비 검사가 디스크도 안 읽는다.
        """
        first = str(mapping.get('motion_file_id') or '').strip() or (names[0] if names else '')
        if not first:
            return
        order = [first] + [name for name in names if name != first]
        if motion_files_dir is not None:
            for name in order:
                if self._warm_should_yield():
                    self.get_logger().info(f'[계획 미리 짓기] {name} · 실행 시작으로 그만둠')
                    return
                started = time.perf_counter()
                try:
                    source = self._plan_builder.warm_records(
                        self._motion_file_path(name, motion_files_dir), mapping,
                    )
                except (OSError, ValueError) as exc:
                    self.get_logger().info(f'[계획 미리 짓기] {name} · 파일 건너뜀: {str(exc)[:200]}')
                    continue
                if source not in ('memory', 'artifact'):
                    self.get_logger().info(
                        f'[계획 미리 짓기] {name} · 파일 변환 {(time.perf_counter() - started) * 1000.0:.0f} ms '
                        f'({source})'
                    )
        motors = self._warm_motors()
        if motors:
            self._warm_limits_signature = self._motor_limits_signature(motors)
        else:
            if not self._warm_should_yield():
                self.get_logger().info('[계획 미리 짓기] 재샘플 건너뜀 · 모터 상태 없음')
            return
        for name in reversed(order):
            if self._warm_should_yield():
                self.get_logger().info(f'[계획 미리 짓기] {name} · 실행 시작으로 그만둠')
                return
            timing: Dict[str, Any] = {}
            started = time.perf_counter()
            try:
                result = self._plan_builder.build(
                    {
                        'project_id': project_id,
                        'motion_file_id': name,
                        'mapping_file_id': mapping_file_id,
                        # 준비 검사(`local_motion_readiness`)와 같은 칸 · 구간 없음(0/0) = 통째로
                        'run_mode': 'once',
                        'request_source': 'cache_warm',
                        'initial_move_time_sec': None,
                    },
                    warm_only=True,
                    motors_snapshot=list(motors),
                    timing=timing,
                )
            except (OSError, ValueError) as exc:
                # 검사에서도 같은 이유로 거절된다 · 미리 지을 것이 없다
                self.get_logger().info(f'[계획 미리 짓기] {name} · 건너뜀: {str(exc)[:200]}')
                continue
            total_ms = (time.perf_counter() - started) * 1000.0
            self.get_logger().info(
                f'[계획 미리 짓기] {name} · {total_ms:.0f} ms · {check_timing_text(timing)} · '
                f'샘플 {int(result.get("sample_count") or 0)}'
            )

    def _require_execution_context(self, payload: Dict[str, Any]) -> None:
        context_id = str(payload.get('context_id') or '').strip()
        project_id = str(payload.get('project_id') or '').strip()
        with self._run_lock:
            applied = dict(self._execution_context)
            ready = self._execution_context_ready
        if (
            not ready
            or not context_id
            or context_id != applied.get('context_id')
            or project_id != applied.get('project_id')
            or int(payload.get('project_generation') or 0)
            != int(applied.get('project_generation') or 0)
        ):
            raise ValueError('현재 프로젝트 실행 컨텍스트 적용 대기 중입니다')
        _, _, mappings_dir = self._project_asset_dirs(payload)
        mapping_path = self._mapping_file_path(applied.get('mapping_file_id'), mappings_dir)
        actual_sha = ''
        if False:
            raise ValueError('조인트 매핑 파일이 변경되어 실행 컨텍스트 재적용이 필요합니다')

    def _load_automation_project(self, project_id: str) -> None:
        try:
            state = self._automation_store.load(project_id)
            error = ''
        except ValueError as exc:
            state = default_automation_state()
            error = str(exc)
        with self._run_lock:
            self._automation_project_id = project_id
            self._automation_state = state
            self._automation_runtime = {
                'state': 'blocked' if error else 'ready',
                'message': error,
                'stop_after_cycle': False,
            }
        self._graceful_stop_event.clear()

    def _save_automation(
        self,
        values: Dict[str, Any],
        *,
        runtime_state: Optional[str] = None,
        runtime_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._run_lock:
            project_id = self._automation_project_id
            candidate = {**self._automation_state, **values}
        if not project_id:
            raise ValueError('자동 반복을 저장할 현재 프로젝트가 없습니다')
        saved = self._automation_store.save(project_id, candidate)
        with self._run_lock:
            self._automation_state = saved
            if runtime_state is not None:
                self._automation_runtime['state'] = runtime_state
            if runtime_message is not None:
                self._automation_runtime['message'] = runtime_message
        return dict(saved)

    def _configure_automation(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._run_lock:
            current = dict(self._automation_state)
            context = dict(self._execution_context)

        repeat_mode = str(
            payload.get('repeat_mode') or current.get('repeat_mode') or 'reinitialize'
        ).strip()
        try:
            dwell_sec = float(payload.get('dwell_sec', current.get('dwell_sec', 0.0)))
        except (TypeError, ValueError):
            dwell_sec = 0.0

        motion_file_id = str(
            payload.get('motion_file_id')
            or current.get('motion_file_id')
            or ''
        ).strip()
        mapping_file_id = str(
            payload.get('mapping_file_id')
            or current.get('mapping_file_id')
            or ''
        ).strip()

        # 반복 방식만 저장한다 · 부팅 자동 재생은 없앴다 · §6-134
        files_ready = bool(motion_file_id and mapping_file_id)

        candidate = normalize_automation_state({
            **current,
            'repeat_mode': repeat_mode,
            'dwell_sec': dwell_sec,
            'group_sync_mode': (
                payload.get('group_sync_mode') or current.get('group_sync_mode')
            ),
            'schedule_end_action': (
                payload.get('schedule_end_action') or current.get('schedule_end_action')
            ),
            'motion_file_id': motion_file_id if files_ready else '',
            'mapping_file_id': mapping_file_id if files_ready else '',
            'motion_sha256': '',
            'mapping_sha256': '',
            'last_error': '',
        })

        saved = self._save_automation(
            candidate,
            runtime_state='ready' if files_ready else 'blocked',
            runtime_message=(
                '자동 반복 설정 저장 완료'
                if files_ready
                else '재생 등록 모션 및 매핑 파일이 필요합니다'
            ),
        )
        return {
            'success': True,
            'message': '자동 반복 설정 저장 완료',
            'automation': self._automation_snapshot(),
            'settings': saved,
            'status': self.status(),
        }

    def _automation_failure(self, message: str) -> None:
        text = str(message or '자동 반복 실행 실패')
        try:
            self._save_automation(
                {
                    'last_error': text,
                },
                runtime_state='blocked',
                runtime_message=text,
            )
        except ValueError:
            with self._run_lock:
                self._automation_runtime.update({
                    'state': 'blocked',
                    'message': text,
                })

    def _automation_snapshot(self) -> Dict[str, Any]:
        with self._run_lock:
            return {
                **getattr(self, '_automation_state', {}),
                **getattr(self, '_automation_runtime', {}),
                'project_id': getattr(self, '_automation_project_id', ''),
            }



    def _handle_check(
        self, payload: Dict[str, Any], *, status_epoch: Optional[int] = None,
        queued_ms: Optional[float] = None,
    ) -> Dict[str, Any]:
        """실행 준비 검사 · 계획을 지어 보고 버린다 · 지은 재료는 계획 캐시에 남아 그룹 준비가 다시 쓴다(164)

        `status_epoch` · 작업 스레드에서 돌 때 요청을 받은 때의 상태 차례 · 그 사이 상태가 바뀌었으면
        (실행 시작 · 정지 등) 검사 결과로 상태 표를 덮지 않는다 · 답은 그대로 보낸다.

        단계별 시간 · 답의 `timing_ms`(브리지 준비 확인이 제 줄에 싣는다) · 1 s 넘거나 실패면 로그 한 줄 · 수정 목록 174
        """
        timing: Dict[str, Any] = {}
        if queued_ms is not None:
            timing['queued_ms'] = queued_ms
        started = time.perf_counter()
        try:
            plan = self._plan_builder.build(payload, timing=timing)
        except Exception as exc:
            timing['build_ms'] = round((time.perf_counter() - started) * 1000.0, 1)
            self._log_check_timing(payload, timing, failure=str(exc) or type(exc).__name__)
            reason = str(exc) or '실행 준비 검사 실패'
            status = motion_run_rules._empty_status()
            status.update({
                'state': 'error',
                'phase': 'error',
                'message': f'실행 준비 검사 실패: {reason}',
                'project_id': str(payload.get('project_id') or ''),
                'motion_file_id': str(payload.get('motion_file_id') or ''),
                'mapping_file_id': str(payload.get('mapping_file_id') or ''),
                'capabilities': motion_run_rules._unavailable_capabilities(reason),
                'updated_at': time.time(),
            })
            self._set_check_status(status, status_epoch)
            return {
                'success': False,
                'message': reason,
                'status': self.status(),
                'summary': {},
                'timing_ms': timing,
            }
        timing['build_ms'] = round((time.perf_counter() - started) * 1000.0, 1)
        self._log_check_timing(payload, timing)
        status = motion_run_rules._status_from_plan('ready', '실행 준비 검사 완료', plan)
        status['phase'] = 'ready'
        status['lifecycle'] = {
            **status.get('lifecycle', {}),
            'checked_at': time.time(),
            'initial_started_at': None,
            'initial_finished_at': None,
            'motion_started_at': None,
            'motion_finished_at': None,
        }
        self._set_check_status(status, status_epoch)
        return {
            'success': True,
            'message': 'motion run check complete',
            'status': self.status(),
            'summary': plan['summary'],
            'timing_ms': timing,
        }

    #: 준비 검사가 이보다 길면(작업 줄 대기 포함) 단계별 시간을 로그에 · 실패는 늘 · 수정 목록 174
    CHECK_SLOW_LOG_MS = 1000.0

    def _log_check_timing(
        self, payload: Dict[str, Any], timing: Dict[str, Any], failure: str = '',
    ) -> None:
        """준비 검사 단계별 시간 한 줄 · 느리거나(1 s 이상) 실패일 때만 · 수정 목록 174

        NY 실물 2026-11-05 · 재부팅 뒤 첫 그룹 시작 · 「준비 거절 · 로컬 Web Bridge 응답 없음: timed out」 ·
        단계 기록이 없어 어디가 느렸는지 미확인 · 다음에는 이 줄로 본다.
        """
        total = float(timing.get('build_ms') or 0.0) + float(timing.get('queued_ms') or 0.0)
        if not failure and total < self.CHECK_SLOW_LOG_MS:
            return
        line = check_timing_text(timing)
        name = str(payload.get('motion_file_id') or '')
        source = str(payload.get('request_source') or '')
        try:
            logger = self.get_logger()
        except Exception:  # noqa: BLE001 · 노드 없이 만든 시험 객체 · 로그 때문에 검사 답이 안 가면 안 된다
            return
        if failure:
            logger.warning(f'[준비 검사 시간] {name} · {source} · {line} · 실패: {failure[:200]}')
        else:
            logger.info(f'[준비 검사 시간] {name} · {source} · {line}')

    def _claim_run_slot(self) -> List[Dict[str, Any]]:
        """실행 슬롯을 잡고 모터 스냅샷을 돌려준다 · `_run_lock`을 잡은 채 부른다.

        단일 실행(`_start_thread`)과 그룹 실행(`GroupSession.prepare`)이 각자
        같은 세 관문을 통과시키고 있었다 · 앞선 실행 · 재생 소유권 · 모터 상태.
        관문이 하나 늘 때 한쪽만 고치면 그쪽으로만 빠져나간다.

        막혀 있으면 :class:`RunSlotUnavailable`, 모터 상태가 없으면
        ``ValueError``를 올린다 · 후자는 호출부 위의 명령 라우터가 오류 응답으로
        바꾸므로 통합 전 계약 그대로다.
        """
        if self._run_thread is not None and self._run_thread.is_alive():
            raise motion_run_rules.RunSlotUnavailable(
                'previous motion run task is still running'
            )
        ownership_error = self._playback_ownership_error()
        if ownership_error:
            raise motion_run_rules.RunSlotUnavailable(ownership_error)
        motors_snapshot = self._current_motors()
        if not motors_snapshot:
            raise ValueError('current motion_state is unavailable')
        # 도는 중인 준비 검사의 결과가 이 실행의 상태 표를 덮지 않게 · 164
        self._status_epoch = int(getattr(self, '_status_epoch', 0)) + 1
        self._stop_event.clear()
        self._graceful_stop_event.clear()
        # 이 실행의 정지 표지 · 감독은 이 표지로 연 세션의 프레임만 받고, 이 뒤 감독 정지가 오면
        # 표지가 달라져 이 실행은 선다 · 정지 직후의 주차 · 초기 이동도 거절 없이 여기서 바로 잡힌다 · 200
        lock = getattr(self, '_safety_status_lock', None)
        if lock is not None:
            with lock:
                self._run_stop_marker = stop_fence.marker(getattr(self, '_latest_safety_status', None))
        self._run_task_done = False
        # 실행 번호 · 상태에 실려 「**이번** 실행의 상태인가」 를 시각 비교 없이 가린다 ·
        # 구간 끝 주차가 옛 상태(1 s 안의 멈춤)를 이번 이동의 끝으로 읽던 것 · 수정 목록 36 · 200
        self._run_seq = int(getattr(self, '_run_seq', 0) or 0) + 1
        return motors_snapshot

    def _start_thread(self, mode: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._run_lock:
            try:
                motors_snapshot = self._claim_run_slot()
            except motion_run_rules.RunSlotUnavailable as exc:
                return {
                    'success': False,
                    'message': str(exc),
                    'status': self.status(),
                }
            # 초기 위치 이동은 **받을 때 먼저 계획을 세워 본다** · 2026-10-02
            #
            # 전에는 곧바로 「시작됨」으로 답하고 계획은 스레드에서 세웠다 · 거기서
            # 실패하면 상태 표에만 남아 화면이 팝업을 못 띄웠다 (애니메이션이
            # 없을 때는 그 줄마저 다른 안내로 덮여 실패가 안 보였다).
            # 자동 실행은 준비를 기다린 뒤 세우므로 여기서 미리 보지 않는다.
            if mode == 'initialize' and not bool(payload.get('automation_run')):
                try:
                    self._plan_builder.build(
                        payload,
                        initialization_only=True,
                        motors_snapshot=list(motors_snapshot),
                    )
                except Exception as exc:  # noqa: BLE001 · 사유를 그대로 사람에게 돌려준다
                    return {
                        'success': False,
                        'message': f'초기 위치 이동 불가: {exc}',
                        'status': self.status(),
                    }
            preparing_status = motion_run_rules._empty_status()
            preparing_status.update({
                'state': 'preparing',
                'phase': 'preparing',
                'message': (
                    '초기 위치 이동 계획 생성 중'
                    if mode == 'initialize'
                    else '모션 실행 계획 생성 중'
                ),
                'project_id': str(payload.get('project_id') or ''),
                'motion_file_id': str(payload.get('motion_file_id') or ''),
                'mapping_file_id': str(payload.get('mapping_file_id') or ''),
                'run_mode': str(payload.get('run_mode') or 'once'),
                'automation_run': bool(payload.get('automation_run')),
                'operation_generation': int(
                    payload.get('operation_generation') or 0
                ),
                'request_source': str(
                    payload.get('request_source') or 'motion_run'
                ),
                # **누가 켰는지 기억한다** · §6-270
                #
                # 전에는 스케줄이 보낸 `schedule_id` 를 받고도 버렸다 · 그래서
                # 스케줄은 돌고 있는 모션이 자기가 켠 것인지 알 수 없었고,
                # 구간이 끝나도 멈출 근거가 없었다 · 실측으로 16~18시 스케줄이
                # 17:58 에 켠 모션이 18:16 까지 돌았다.
                'schedule_id': str(payload.get('schedule_id') or ''),
                'phase_started_at': time.time(),
            })
            self._set_status(preparing_status)
            self._run_thread = threading.Thread(
                target=self._run_task,
                args=(mode, dict(payload), list(motors_snapshot)),
                daemon=True,
            )
            self._run_thread.start()

        return {
            'success': True,
            'message': (
                '초기 위치 이동을 시작합니다'
                if mode == 'initialize'
                else '모션 실행을 준비합니다'
            ),
            'status': self.status(),
            'summary': {},
        }

    def _wait_group_deadline(
        self,
        scheduled_monotonic: float,
        *,
        phase: str,
        message: str,
        execution_id: str,
        cycle_number: int = 0,
        refresh: Optional[Callable[[], Optional[float]]] = None,
        late_ok: bool = False,
    ) -> None:
        """그룹 예약 시각까지 기다린다 · 지났으면 「놓쳤습니다」 오류(신호 재생 · 진행 PC 가 정한 시각)

        수정 목록 206 · 시간표 재생 회차 명령(`group_cycle_at`)은 이 PC 가 시각을 정한다 ·
        `late_ok` · 지났으면 기다리지 않고 바로(늦음은 부르는 쪽이 정함 · 사용자 2026-11-16 「늦어도 끝나는 대로 시작」) ·
        `refresh` · 기다리는 동안 시각이 바뀔 수 있다(1회차 준비 뒤 회차 명령이 오면 그 시작에서 거꾸로 센 초기 이동 시각) ·
        새 시각 또는 None(그대로)
        """
        remaining = float(scheduled_monotonic) - time.monotonic()
        if remaining < -self.period_sec and not late_ok:
            raise RuntimeError('그룹 예약 시작시각을 놓쳤습니다')
        deadline = float(scheduled_monotonic)
        self._update_status({
            'state': 'waiting',
            'phase': phase,
            'message': message,
            'group_execution': True,
            'execution_id': execution_id,
            'current_cycle': cycle_number,
            'group_cycle_number': cycle_number,
            'scheduled_start_monotonic': float(scheduled_monotonic),
        })
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                raise InterruptedError()
            updated = refresh() if refresh is not None else None
            if updated is not None and float(updated) != deadline:
                deadline = float(updated)
                self._update_status({'scheduled_start_monotonic': deadline})
                continue
            # 시계를 두 번 본다 · 위의 `while` 에서 한 번, 여기서 또 한 번.
            # 그 사이에 마감이 지나가면 남은 시간이 음수가 되고
            # `time.sleep()` 이 터진다 · 기다림의 **마지막 한 바퀴**는 늘
            # 남은 시간이 0 에 가까우므로 매 회차가 이 외줄을 한 번씩 탄다.
            #
            # 실제로 터졌다 · 2026-09-18 15:04 · 그룹 11회차의 「회차 후
            # 초기화 대기」에서 `sleep length must be non-negative` 가 나고
            # 세 대 연동이 통째로 정지했다 · 그전에는 6회차였다 · 확률이
            # 낮아 재현이 안 됐다.
            #
            # 이미 지났으면 안 자고 넘어가면 된다 · 바로 다음 `while` 이
            # 거짓이 되어 빠져나간다.
            time.sleep(max(min(0.02, deadline - time.monotonic()), 0.0))

    def _wait_for_automation_ready(self, payload: Dict[str, Any], timeout_sec: float = 60.0) -> None:
        deadline = time.monotonic() + timeout_sec
        last_error = ''
        while True:
            if self._stop_event.is_set():
                raise InterruptedError()
            error = self._playback_ownership_error()
            if not error:
                motors = self._current_motors()
                if not motors:
                    error = '모터 통신 대기 중'
                else:
                    try:
                        plan = self._plan_builder.build(payload, motors_snapshot=motors)
                        init_plan = self._plan_builder.build(
                            payload,
                            initialization_only=True,
                            motors_snapshot=motors,
                        )
                        axes_to_check = {int(axis['motor_axis']) for axis in plan.get('axes', [])}
                        axes_to_check.update(int(axis['motor_axis']) for axis in init_plan.get('axes', []))
                        
                        for motor_axis in sorted(axes_to_check):
                            motor = self._motor_for_axis(motor_axis, motors)
                            motor_error = motion_run_rules._motor_ready_error(
                                motor or {'controller_index': motor_axis}
                            )
                            if motor_error:
                                error = motor_error
                                break
                            if motion_run_rules._motor_position(motor) is None:
                                error = f'{motor_axis}번 모터의 현재 위치를 읽을 수 없습니다'
                                break
                    except ValueError as exc:
                        error = str(exc)
            if not error:
                return
            if time.monotonic() > deadline:
                raise ValueError(f"자동 반복 준비 대기 시간 초과: {error}")
            if error != last_error:
                last_error = error
                with self._run_lock:
                    self._automation_runtime['message'] = f"자동 반복 준비 대기 중: {error}"
                self._publish_status()
            time.sleep(0.5)

    def _handle_stop(self) -> Dict[str, Any]:
        current = self.status()
        if current.get('automation_run'):
            try:
                self._save_automation(
                    {
                        'last_error': '사용자가 모션을 즉시 정지했습니다',
                    },
                    runtime_state='stopped',
                    runtime_message='사용자가 모션을 즉시 정지했습니다',
                )
            except ValueError:
                pass
        self._stop_event.set()
        self._graceful_stop_event.clear()
        self._group.mark_stopping()
        if current.get('state') == 'preparing':
            self._update_status({
                'state': 'stopped',
                'phase': 'stopped',
                'phase_finished_at': time.time(),
                'message': '계획 준비 중 정지 요청',
            })
        elif current.get('state') in (
            'initializing',
            'countdown',
            'running',
            'verifying',
        ):
            self._update_status({
                'state': 'stopping',
                'phase': 'stopping',
                'message': '정지 요청',
            })
        else:
            self._update_status({
                'state': 'stopped',
                'phase': 'stopped',
                'phase_finished_at': time.time(),
                'message': '정지 요청',
            })
        return {
            'success': True,
            'message': '정지합니다. 서보 토크 유지.',
            'status': self.status(),
        }

    def _handle_stop_after_cycle(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        current = self.status()
        # 스케줄 구간 끝이면 `schedule_end` · 그룹 끝 문구를 가른다 · 수정 목록 141
        reason = str(payload.get('reason') or '') if isinstance(payload, dict) else ''
        # 진행 PC 가 아는 그룹 전체 정지 · 회차 맞춤은 장벽에서 풀기를 기다린다 · 수정 목록 154
        group_wide = bool(payload.get('group_wide')) if isinstance(payload, dict) else False
        if current.get('group_execution'):
            if not self._group.request_stop_after_cycle(current, reason, group_wide=group_wide):
                # 그룹 세션도 실행 번호도 없으면 단독이다 · 아래 단독 길로 · 전에는 표시용
                # `group_execution` 만 보고 거절해 단독 연속을 회차 후 정지로 못 멈췄다 · 수정 목록 111
                if not str(current.get('execution_id') or '').strip():
                    current = {**current, 'group_execution': False}
                    return self._handle_stop_after_cycle_local(current)
                return {
                    'success': False,
                    'message': '활성 그룹 실행이 없습니다',
                    'status': current,
                }
            return {
                'success': True,
                'message': '현재 그룹 모션 회차 완료 후 정지 요청',
                'status': self.status(),
            }
        return self._handle_stop_after_cycle_local(current)

    def _handle_stop_after_cycle_local(self, current: Dict[str, Any]) -> Dict[str, Any]:
        is_sync_repeat = bool(int(current.get('synchronized_repeat_count') or 0))
        is_continuous = current.get('run_mode') == 'continuous'
        is_automation = bool(current.get('automation_run'))

        if not (is_sync_repeat or is_continuous or is_automation):
            return {
                'success': False,
                'message': '반복 모션 실행 중일 때만 현재 회차 후 정지를 사용할 수 있습니다',
                'status': current,
            }
        self._graceful_stop_event.set()
        # 단독 연속 재생에 「동기」 라고 답했다(실물 R-41 · 2026-10-13) · 동기 반복일 때만 그 말 · 화면 글자와 같게
        return {
            'success': True,
            'message': (
                '이번 동기 반복 회차가 끝나면 정지합니다'
                if is_sync_repeat else '이번 회차가 끝나면 정지합니다'
            ),
            'status': self.status(),
        }

    def _axes_held_by_others(self, axes) -> Dict[int, str]:
        """이 축들 중 **남이 쥔 것**과 그 주인 · §6-276

        재생이 그 축만 놓고 나머지는 계속 몰 수 있도록, 이유가 아니라 **축
        목록**을 돌려준다 · 판정 자체는 감독자가 축별로 들고 있는 표를 본다.
        """
        lock = getattr(self, '_safety_status_lock', None)
        if lock is None:
            return {}
        with lock:
            payload = getattr(self, '_latest_safety_status', None)
            status = dict(payload) if isinstance(payload, dict) else None
        axis_owners = status.get('command_axis_owners') if status else None
        if not isinstance(axis_owners, dict) or axes is None:
            return {}
        held: Dict[int, str] = {}
        for axis in axes:
            holder = str(axis_owners.get(str(int(axis))) or 'none').strip().lower()
            if holder not in PLAYBACK_MAY_TAKE_FROM:
                held[int(axis)] = holder
        return held

    def _playback_ownership_error(self, axes=None) -> str:
        """재생이 지금 모터를 몰 수 없는 이유 · 없으면 빈 문자열.

        `axes` 를 주면 **그 축들만** 본다 · 안 주면 지금까지대로 대표 주인을
        본다(옛 호출부).
        """
        lock = getattr(self, '_safety_status_lock', None)
        if lock is None:
            # Lightweight unit-test instances created with __new__ predate this
            # runtime subscription. Normal ROS nodes always initialize the lock.
            return ''
        with lock:
            payload = getattr(self, '_latest_safety_status', None)
            received_at = getattr(self, '_latest_safety_status_at', None)
            status = dict(payload) if isinstance(payload, dict) else None
        if status is None or received_at is None:
            return '모션 Supervisor 상태를 아직 받지 못했습니다'
        if time.monotonic() - float(received_at) > SAFETY_STATUS_TIMEOUT_SEC:
            return '모션 Supervisor 상태가 갱신되지 않았습니다'
        if bool(status.get('emergency_latched')):
            return '긴급정지 잠김 상태입니다. 상위 프로그램 재시작이 필요합니다'
        if bool(status.get('commands_blocked')):
            return str(status.get('message') or '모터 명령이 일시 차단된 상태입니다')
        owner_names = {
            'stream': '수동 페이더',
            'midi': 'MIDI 제어',
            'manual': '수동 제어',
        }
        # 내가 쓰는 축의 주인만 본다 · §6-106
        #
        # `command_owner` 는 **대표 하나로 줄인 축약형**이다 · 추가 녹화에서
        # MIDI 가 축 하나를 잡으면 대표가 `midi` 로 바뀐다 · 그러면 다른 축을
        # 몰던 재생이 매 프레임 이 검사에 걸려 **스스로 멈췄다** · 레이어에
        # 있는 축의 재생이 끊기고, 그 위에 얹어 녹화하는 것이 불가능했다.
        #
        # 소유는 `CommandArbiter` 가 **축별**로 갖고 있다 · 축약형은 화면에
        # 쓰고, 계속할지 말지는 축별로 묻는다.
        axis_owners = status.get('command_axis_owners')
        if isinstance(axis_owners, dict) and axes is not None:
            blanket = str(axis_owners.get('all') or 'none').strip().lower()
            if blanket not in PLAYBACK_MAY_TAKE_FROM:
                return f"{owner_names.get(blanket, blanket)}가 사용 중이어서 모션을 시작할 수 없습니다"
            taken = self._axes_held_by_others(axes)
            # **한 축이라도 남았으면 계속한다** · §6-276
            #
            # 전에는 축 하나만 남이 쥐어도 곧바로 실행 전체를 오류로 끝냈다 ·
            # 추가 녹화에서 사람이 1-4 를 잡는 순간 1-1·1-2·1-3 의 재생까지
            # 같이 죽었다 · 축 하나의 다툼이 전부를 세울 이유가 없다.
            #
            # 몰 축이 하나도 안 남았을 때만 멈춘다 · 그때는 정말로 남이
            # 이 모션을 대신 몰고 있는 것이다.
            if taken and len(taken) >= len(set(int(axis) for axis in axes)):
                axis, holder = sorted(taken.items())[0]
                return (
                    f"{owner_names.get(holder, holder)}가 축 {axis}를 "
                    '사용 중이어서 모션을 시작할 수 없습니다'
                )
            return ''
        # 축을 모르는 옛 호출 · 표를 못 받은 상태 · 지금까지대로 축약형을 본다
        owner = str(status.get('command_owner') or 'none').strip().lower()
        if owner not in PLAYBACK_MAY_TAKE_FROM:
            return f"{owner_names.get(owner, owner)}가 사용 중이어서 모션을 시작할 수 없습니다"
        return ''

    def _runtime_float_parameter(self, name: str, fallback: float) -> float:
        try:
            value = float(self.get_parameter(name).value)
        except Exception:
            value = float(fallback)
        if not math.isfinite(value):
            return float(fallback)
        return max(value, 0.0)

    def _current_motors(self) -> List[Dict[str, Any]]:
        with self._state_lock:
            state = self._latest_state
            received_at = self._latest_state_at
        if state is None or received_at is None:
            return []
        if time.time() - received_at > STATE_TIMEOUT_SEC:
            return []
        motors = state.get('motors', [])
        return [motor for motor in motors if isinstance(motor, dict)] if isinstance(motors, list) else []

    def _motor_for_axis(
        self,
        axis: int,
        motors: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        for motor in motors if motors is not None else self._current_motors():
            if optional_int(motor.get('controller_index')) == axis:
                return motor
        return None

    #: 읽어 둔 모션 파일을 몇 개나 들고 있을 것인가 · §6-173
    #:
    #: 한 번 시작할 때 계획을 여러 번 만든다 · 단독 재생은 둘(재생 + 초기
    #: 이동), 연동은 셋(검증 + 재생 + 초기 이동) · 그때마다 같은 파일을 다시
    #: 읽고 파싱했다 · 183KB 짜리로 재 보니 **한 번에 45ms**, 세 번이면 135ms 다.
    #:
    #: 그 135ms 가 하필 **그룹 동기 시작 직전**에 놓인다.
    #:
    #: 파일이 바뀌면 자동으로 버린다 (`mtime` 과 크기를 같이 본다) · 그래서
    #: 스튜디오가 새로 내보낸 파일을 옛것으로 돌릴 일이 없다.
    #:
    #: 이 PC 매핑의 조인트만 담는다 · 키에 조인트 묶음이 들어간다 · 수정 목록 164 ·
    #: 920 s × 20 조인트 파일이 레코드 92만 개(수백 MB)였다 · 5 조인트면 그 1/4.
    #:
    #: 수정 목록 170 · 레코드를 사전으로 들지 않고 조인트별 배열(`motion_tracks`)로 든다 · 레코드 하나
    #: 약 380 B → 32 B · 920 s × 5 조인트 파일 하나 88 MB → 7 MB.
    #:
    #: 수정 목록 208 · 프로젝트 애니의 재생 계획은 이 캐시를 안 거친다 · 디스크 변환본(`plan_artifact`)에서
    #: 읽는다 · 여기는 변환본 자리가 없는 파일(스튜디오 임시 · 시험)만 · 그래서 칸 2 · 바이트 예산(170)은 뺐다.
    MOTION_CACHE_SIZE = 2

    def _records_cache(self) -> SingleFlightCache:
        """모션 파일 레코드 캐시 · `__new__` 로 만든 시험 객체도 처음 쓸 때 만든다"""
        cache = getattr(self, '_motion_record_cache', None)
        if cache is None:
            with _LAZY_CACHE_LOCK:
                cache = getattr(self, '_motion_record_cache', None)
                if cache is None:
                    cache = SingleFlightCache(self.MOTION_CACHE_SIZE)
                    self._motion_record_cache = cache
        return cache

    def _motion_records_token(self, path: Any, motion_ids: Any = None) -> Optional[tuple]:
        """이 파일 · 이 조인트 묶음의 레코드를 가리키는 키 · 파일이 바뀌면 키도 바뀐다 · 수정 목록 164

        계획 캐시(`PlanBuilder`)가 이 키로 「같은 레코드」 를 알아본다 · 파일을 못 보거나
        읽는 함수를 갈아 끼운 객체(시험 대역)면 None · 그때는 계획 캐시를 안 쓴다.
        """
        if path is None or '_load_motion_records' in vars(self):
            return None
        try:
            stat = Path(path).stat()
        except (OSError, TypeError, ValueError):
            return None
        ids = None if motion_ids is None else frozenset(str(item) for item in motion_ids)
        return (str(path), stat.st_mtime_ns, stat.st_size, ids)

    def _load_motion_tracks(self, path: Path, motion_ids: Any = None) -> motion_tracks.MotionTracks:
        """모션 파일을 조인트별 배열로 · 같은 파일이면 다시 안 읽는다 · §6-173 · 수정 목록 170

        **돌려준 것은 캐시 것 그대로다 · 고치지 않는다** · 계획은 조인트 사전(`tracks`)을 얕게
        복사해서 덧붙인다(초기 이동 대체값).

        `motion_ids` · 이 조인트만 남긴다(읽으면서 뺀다) · None 이면 전부 · 수정 목록 164 ·
        여러 스레드가 같은 파일을 같이 찾으면 한 번만 읽는다.
        """
        key = self._motion_records_token(path, motion_ids)

        def parse():
            if motion_ids is None:
                return self._parse_motion_records(path)
            return self._parse_motion_records(path, motion_ids)

        return self._records_cache().get_or_compute(key, parse)

    def _load_motion_records(self, path: Path, motion_ids: Any = None) -> List[Dict[str, Any]]:
        """옛 모양 · 레코드 사전 목록(시각 · 조인트 이름 · 줄 번호 순) · 캐시는 `_load_motion_tracks`

        **돌려주는 목록과 사전은 매번 새로 만든다** · 부르는 쪽이 덧붙여도 캐시에 번지지 않는다.
        재생 계획은 이것을 쓰지 않는다(배열을 바로 본다) · 시험 · 다른 도구용.
        """
        tracks = self._load_motion_tracks(path, motion_ids)
        return tracks.records() if isinstance(tracks, motion_tracks.MotionTracks) else list(tracks)

    def _parse_motion_records(self, path: Path, motion_ids: Any = None) -> motion_tracks.MotionTracks:
        """파일 → 조인트별 배열 · 옛 레코드 사전과 같은 값 · 같은 순서 · 수정 목록 170

        본문은 `motion_file_reader.parse_motion_tracks` · 애니 변환 자식 프로세스가 같은 함수를 쓴다 · 수정 목록 208
        """
        return parse_motion_tracks(path, motion_ids)

    def _load_mapping(self, path: Path) -> Dict[str, Any]:
        data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        if not isinstance(data, dict):
            raise ValueError('motion mapping root must be an object')
        return data

    def _project_asset_dirs(self, payload: Dict[str, Any]) -> tuple[str, Path, Path]:
        project_id = str(payload.get('project_id') or '').strip()
        project_dir = project_dir_for(self.motion_projects_dir, project_id)
        return project_id, project_dir / 'motions', project_dir / 'motion_axis_matching'

    def _mapping_file_path(self, file_id: Any, directory: Optional[Path] = None) -> Path:
        name = str(file_id or '').strip()
        if not name:
            raise ValueError('mapping file_id is required')
        if name != Path(name).name or '/' in name or '\\' in name:
            raise ValueError('invalid mapping file id')
        if not name.lower().endswith(('.yaml', '.yml')):
            name = f'{name}.yaml'
        path = (directory or self.mappings_dir) / name
        if not path.is_file():
            raise ValueError(f'motion mapping not found: {name}')
        return path

    def _motion_file_path(self, file_id: Any, directory: Optional[Path] = None) -> Path:
        name = str(file_id or '').strip()
        if not name:
            raise ValueError('motion file_id is required')
        if name != Path(name).name or '/' in name or '\\' in name:
            raise ValueError('invalid motion file id')
        path = (directory or self.motion_files_dir) / name
        if not path.is_file():
            raise ValueError(f'motion file not found: {name}')
        return path

    def _set_status(self, status: Dict[str, Any]) -> None:
        with self._run_lock:
            # 상태 표시 · `_update_status` 참고 · 수정 목록 199
            status[run_state.STATUS_STAMP_KEY] = time.monotonic()
            self._status = status
            self._status_epoch = int(getattr(self, '_status_epoch', 0)) + 1
        self._publish_status()

    def _set_check_status(self, status: Dict[str, Any], status_epoch: Optional[int]) -> bool:
        """검사 결과를 상태 표에 · 검사하는 사이 상태가 바뀌었거나 실행이 돌면 쓰지 않는다 · 164

        검사가 실행기에서 돌 때는 그 사이에 다른 명령이 끼어들 수 없었다 · 이제 작업 스레드라
        `group_prepare` · `start` 가 먼저 끝날 수 있다 · 늦게 끝난 검사가 「준비 완료」 로 덮으면
        실행 중 표시가 지워진다.
        """
        if status_epoch is None:
            self._set_status(status)
            return True
        with self._run_lock:
            if int(getattr(self, '_status_epoch', 0)) != int(status_epoch):
                return False
            run_thread = getattr(self, '_run_thread', None)
            if run_thread is not None and run_thread.is_alive():
                return False
            status[run_state.STATUS_STAMP_KEY] = time.monotonic()
            self._status = status
            self._status_epoch = int(status_epoch) + 1
        self._publish_status()
        return True

    def _update_status(self, values: Dict[str, Any]) -> None:
        with self._run_lock:
            self._status_epoch = int(getattr(self, '_status_epoch', 0)) + 1
            self._status = {
                **self._status,
                **values,
                'updated_at': time.time(),
                # 상태 표시 · 상태가 바뀔 때마다 · 명령 응답에도 실린다 · 연동 노드(시간표 구동부)가 「내 명령 뒤의
                # 상태인가」 를 시간으로 짐작하지 않고 이것으로 가린다(옛 3 s 기다림) · 진행만 바뀌는 것은 안 올림 · 수정 목록 199
                run_state.STATUS_STAMP_KEY: time.monotonic(),
            }
        self._publish_status()

    def _current_lifecycle(self) -> Dict[str, Any]:
        with self._run_lock:
            lifecycle = self._status.get('lifecycle', {})
        return dict(lifecycle) if isinstance(lifecycle, dict) else {}

    def _update_progress(
        self,
        state: str,
        elapsed_sec: float,
        duration_sec: float,
        sample_index: int,
        active_axis_count: int,
        run_mode: Optional[str] = None,
        cycle_count: Optional[int] = None,
        current_cycle: Optional[int] = None,
    ) -> None:
        duration = max(float(duration_sec), 1e-9)
        with self._run_lock:
            self._status = {
                **self._status,
                'state': state,
                'progress': {
                    'elapsed_sec': float(elapsed_sec),
                    'duration_sec': float(duration_sec),
                    'ratio': min(max(float(elapsed_sec) / duration, 0.0), 1.0),
                    'sample_index': int(sample_index),
                    'active_axis_count': int(active_axis_count),
                },
                'updated_at': time.time(),
            }
            if run_mode is not None:
                self._status['run_mode'] = run_mode
            if cycle_count is not None:
                self._status['cycle_count'] = int(cycle_count)
            if current_cycle is not None:
                self._status['current_cycle'] = int(current_cycle)

    def status(self) -> Dict[str, Any]:
        with self._run_lock:
            result = json.loads(json.dumps(self._status, ensure_ascii=False))
            result['execution_context'] = {
                **self._execution_context,
                'ready': self._execution_context_ready,
            }
            result['automation'] = self._automation_snapshot()
            # 재생 세션 · 감독이 이것으로 프레임을 받고 축을 놓는다 · 수정 목록 200 · 203
            result['playback_session'] = self._playback_session()
            # 실행 스레드가 아직 있나 · 상태가 「끝」 이어도 스레드가 살아 있으면 새 실행은
            # 「previous motion run task is still running」 으로 거절된다 · 기다리는 쪽(구간 끝 주차)이 본다 · 155
            thread = getattr(self, '_run_thread', None)
            result['run_task_active'] = bool(thread is not None and thread.is_alive())
            result['run_id'] = int(getattr(self, '_run_seq', 0) or 0)
        result['live_overrides'] = self.live_override_snapshot()
        # 다시 체크했지만 다음 회차를 기다리는 조인트 · 95
        player = getattr(self, '_player', None)
        result['held_motion_ids'] = player.held_motion_ids() if player is not None else []
        return result

    # ------------------------------------------------------------------ #
    # 재생 라이브 오버라이드 · P7
    # ------------------------------------------------------------------ #

    def live_override_snapshot(self) -> Dict[str, Dict[str, Any]]:
        # 재생 시작이 이어 가기 기억을 비울 때도 부른다(40) · 노드 없이 만든
        # 가벼운 관리자(시험)에는 오버라이드 칸이 없다 · 없으면 「오버라이드 없음」
        if not hasattr(self, '_live_override_lock'):
            return {}
        with self._live_override_lock:
            return {key: dict(value) for key, value in self._live_overrides.items()}

    def _set_live_override(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """조인트 이름 하나의 뮤트·라이브 리밋을 바꾼다 · 재생 중에도 듣는다.

        뮤트 = 그 조인트의 명령 송출 제외 · PP 드라이브는 마지막 목표에
        머무르므로 모터는 그 자리에 선다(서보는 켠 채) · 리밋 = 모션값을
        [lo, hi] 로 산 채로 자르고 그 축만 모터 목표를 다시 계산한다.
        매핑 파일은 건드리지 않는다 · 영구 반영은 조인트 매핑에서 한다.
        """
        motion_id = str(payload.get('motion_id') or '').strip()
        if not motion_id:
            raise ValueError('조인트 이름(motion_id)가 필요합니다')
        with self._live_override_lock:
            entry = dict(self._live_overrides.get(motion_id) or {})
            if 'muted' in payload:
                entry['muted'] = bool(payload.get('muted'))
            if 'clamp' in payload:
                clamp = payload.get('clamp')
                if clamp is None:
                    entry.pop('clamp', None)
                else:
                    if not isinstance(clamp, (list, tuple)) or len(clamp) != 2:
                        raise ValueError('clamp 는 [최소, 최대] 두 수여야 합니다')
                    low = finite_float(clamp[0])
                    high = finite_float(clamp[1])
                    if low is None or high is None or low > high:
                        raise ValueError('라이브 리밋은 최소 <= 최대 인 두 수여야 합니다')
                    entry['clamp'] = [low, high]
            if entry.get('muted') or entry.get('clamp'):
                self._live_overrides[motion_id] = entry
            else:
                self._live_overrides.pop(motion_id, None)
        snapshot = self.live_override_snapshot()
        # 재생 중이 아니어도 화면이 상태로 읽을 수 있게 바로 싣는다
        self._update_status({'live_overrides': snapshot})
        return {'success': True, 'live_overrides': snapshot}

    def _clear_live_overrides(self) -> None:
        """프로젝트·매핑이 바뀌면 지운다 · 옛 조인트 이름에 걸어 둔
        오버라이드가 새 연결에 몰래 따라붙으면 안 된다."""
        with self._live_override_lock:
            if not self._live_overrides:
                return
            self._live_overrides.clear()
        self._update_status({'live_overrides': {}})

    def _publish_response(self, payload: Dict[str, Any]) -> None:
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self._response_pub.publish(msg)

    def _punch_input_callback(self, msg: String) -> None:
        """화면 페이더 → 덮어쓸 조인트 목표 · 놓음 · 녹화 재생 중일 때만 · 수정 목록 156 ⑨-2"""
        try:
            payload = json.loads(msg.data)
        except (AttributeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        motion_id = str(payload.get('motion_id') or '')
        with self._punch_lock:
            controller = self._punch_controller
            if controller is None or not motion_id:
                return
            if payload.get('release'):
                controller.release(motion_id)
                return
            try:
                target = float(payload.get('target_rad'))
            except (TypeError, ValueError):
                return
            # 화면은 날 값 · 거르는 것은 펀치 쪽(화면에서 고른 시간) · 사용자 결정 2026-10-19
            controller.input(
                motion_id, target, time.monotonic(), smooth_sec=smoothing.smooth_sec_from(payload.get('smooth_sec')),
            )

    def _publish_status(self) -> None:
        with self._run_lock:
            self._status = apply_group_display(dict(self._status))
        msg = String()
        msg.data = json.dumps(self.status(), ensure_ascii=False)
        self._status_pub.publish(msg)

    def _load_period_sec(self) -> float:
        period = finite_float(
            self.declare_parameter('command_period_sec', DEFAULT_PERIOD_SEC).value
        )
        if period is None or period <= 0:
            return DEFAULT_PERIOD_SEC
        return max(period, 0.001)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MotionRunManager()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
