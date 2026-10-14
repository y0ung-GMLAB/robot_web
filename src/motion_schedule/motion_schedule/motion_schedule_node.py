import os
import json
import time
import urllib.request
import urllib.error
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from datetime import datetime
from typing import Dict, Any

from pathlib import Path

from motion_common.coordination import (
    coordination_settings_path,
    load_coordination_settings,
    resolve_master_role,
)
from motion_common.paths import motion_projects_dir, workspace_root
from motion_common import topics

from motion_common.repeat_policy import (
    DEFAULT_GROUP_SYNC_MODE,
    DEFAULT_REPEAT_MODE,
    normalize_group_sync_mode,
    normalize_repeat_mode,
)
from motion_common.run_state import group_is_active, is_running
from motion_common.schedule_models import ScheduleItem
from motion_common.schedule_store import (
    DEFAULT_RUN_MODE,
    OFF_MODE,
    SCHEDULE_MODE,
    ScheduleStore,
    normalize_run_mode,
)

try:
    from motion_schedule.schedule_engine import ScheduleEngine, unreadable_schedules
    from motion_schedule import schedule_rules
except ImportError:
    from .schedule_engine import ScheduleEngine, unreadable_schedules
    from . import schedule_rules

PACKAGE_HINT = 'motion_schedule'

#: 몇 초마다 「스케줄이 말하는 상태」와 실제를 맞출 것인가 · §6-137
#:
#: 짧게 하면 시작이 정확해지는 대신 브리지를 자주 두드린다 · 1분이면 전시·
#: 무대에서 충분하고, 개장 시각을 정확히 맞춰야 하면 시작 시각을 1분 당겨
#: 적으면 된다.
#:
#: 한 번 10초로 줄였다가 되돌렸다 · §6-149 · "공연 중에 멈추면 최대 1분을
#: 죽어 있는다" 가 줄인 이유였는데, **이 값은 현장 운영이 정하는 값이지
#: 코드가 정할 값이 아니다** · 바꾸려면 현장에서 어느 쪽이 나은지 보고 정한다.
RECONCILE_INTERVAL_SEC = 60.0


class MotionScheduleNode(Node):
    def __init__(self):
        super().__init__('motion_schedule_node')

        self.workspace_dir = str(workspace_root(PACKAGE_HINT))
        self.projects_dir = str(motion_projects_dir(PACKAGE_HINT))

        self.declare_parameter(
            'coordination_file',
            str(coordination_settings_path(PACKAGE_HINT)),
        )
        self.coordination_file = self.get_parameter('coordination_file').value
        self._master_role_cache = None
        self._master_role_stamp = None

        self.store = ScheduleStore(projects_dir=self.projects_dir)
        self.engine = ScheduleEngine()
        self._last_reconcile_monotonic = 0.0
        self._run_mode = DEFAULT_RUN_MODE
        # 마지막으로 거부당한 시도 · §6-147
        #
        # 전에는 아무 데도 안 남았다 · 스케줄이 발화하고 연동이 거부해도
        # 로그에 `success` 라고 찍히고 끝이라, 화면 배지는 초록불이었다 ·
        # 한 시간 내내 매분 거부당하는 동안 아무도 몰랐다.
        self._last_failure = {}
        # 지금 도는 재생을 스케줄이 켰나 · True 켰음 · False 사람이 켬 · None 모름(기동 직후) · 수정 목록 106
        # 그룹은 연동 상태의 `started_by` 를 먼저 믿는다 · 이 값은 그것을 못 읽을 때만 · 수정 목록 143
        self._schedule_started = None
        #: 조회가 연달아 몇 번 실패했나 · 상태가 바뀔 때만 적는다 · §6-271
        self._read_failures: Dict[str, int] = {}
        #: 브리지가 말하는 「지금 시작하면 안 되는 이유」 · 부팅 직후 앱솔루트 확인 등 · 수정 목록 124
        self._start_blocker = ''
        #: 시작을 보냈고 받아들여졌다 · 다음 점검에 안 돌고 있으면 실패로 센다 · 수정 목록 123·124
        self._start_pending = False

        # Status publisher
        self.status_pub = self.create_publisher(String, topics.SCHEDULE_STATUS, 10)

        # Subscribers
        self.active_project_sub = self.create_subscription(
            String,
            topics.ACTIVE_PROJECT,
            self._on_active_project_changed,
            10
        )

        # Load initial active project if exists
        self._load_active_project_from_file()

        # 1-second background timer for schedule checking
        self.timer = self.create_timer(1.0, self._on_timer_tick)

        self.get_logger().info("motion_schedule_node started (Master Only Coordinated Motion Scheduler)")

    def _is_master_pc(self) -> bool:
        """Check if current PC role is master.

        1초 주기 타이머에서 반복 호출되므로 설정 파일 mtime·크기가 그대로면
        직전 판정을 재사용한다. 판정 결과가 바뀔 때만 로그를 남긴다.
        """
        path = Path(self.coordination_file)
        try:
            stat = path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            stamp = None

        if self._master_role_cache is not None and stamp == self._master_role_stamp:
            return self._master_role_cache.is_master

        role = resolve_master_role(path)
        previous = self._master_role_cache
        self._master_role_cache = role
        self._master_role_stamp = stamp

        if previous is None or previous.is_master != role.is_master:
            self.get_logger().info(f"마스터 판정 · {role.is_master} · {role.reason}")
        return role.is_master

    def _coordination_enabled(self) -> bool:
        """연동을 쓰는 PC 인가 · 아니면 단독으로 돈다.

        스케줄은 그룹 전용이었다 · `start_group` 만 보내서, 연동을 쓰지 않는
        PC 에서는 발화는 하는데 "먼저 DDS 그룹에 참가하세요" 로 매번 실패했다.
        `resolve_master_role` 이 연동 미사용을 "단독 동작으로 간주" 하며 마스터
        판정을 통과시키기 때문에 조용히 실패했다 · §6-68
        """
        path = Path(self.coordination_file)
        if not path.is_file():
            return False
        settings = load_coordination_settings(path)
        if settings is None:
            return False
        return bool(settings.get('enabled', False))

    def _load_active_project_from_file(self):
        project_id = None
        
        # 1. Single Source of Truth: .selected_project.json (written by project_repository.py)
        selected_file = os.path.join(self.projects_dir, '.selected_project.json')
        if os.path.exists(selected_file):
            try:
                with open(selected_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    project_id = data.get('selected_project_id') or data.get('project_id')
            except (OSError, ValueError) as exc:
                self.get_logger().warning(f"Failed to load .selected_project.json: {exc}")

        # 2. Legacy fallback
        if not project_id:
            active_file = os.path.join(self.projects_dir, 'active_project.json')
            if os.path.exists(active_file):
                try:
                    with open(active_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        project_id = data.get('active_project_id') or data.get('project_id')
                except (OSError, ValueError) as exc:
                    self.get_logger().warning(
                        f"Failed to load active_project.json: {exc}"
                    )

        if not project_id:
            project_id = "default"

        self.get_logger().info(f"Loading schedule store for project: {project_id}")
        self.store.load_project(project_id)

    def _on_active_project_changed(self, msg: String):
        project_id = msg.data.strip()
        if project_id and project_id != self.store.current_project_id:
            self.get_logger().info(f"Switching schedule store to active project: {project_id}")
            self.store.load_project(project_id)

    def _send_http_request(self, endpoint: str, payload: Dict[str, Any]) -> bool:
        """Send HTTP POST request to local Web Bridge API."""
        url = f"http://127.0.0.1:8000{endpoint}"
        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                url,
                data=data,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                result = json.loads(resp.read().decode('utf-8'))
        except (OSError, ValueError) as exc:
            self._remember_failure(endpoint, str(exc))
            self.get_logger().error(f"HTTP Request [{endpoint}] failed: {exc}")
            return False
        # 200 이 왔다고 받아들여진 것이 아니다 · §6-147
        #
        # 전에는 여기서 바로 `success` 라고 찍고 True 를 돌려줬다 · 그래서
        # 로그에 `success: {'success': False, ...}` 같은 자기모순이 남았고,
        # 거부가 실패로 세어지지 않아 알람도 화면 표시도 생기지 않았다.
        if isinstance(result, dict) and result.get('success') is False:
            message = str(result.get('message') or '이유를 알려주지 않았습니다')
            self._remember_failure(endpoint, message)
            self.get_logger().warning(f"[거부] {endpoint} · {message}")
            return False
        self._forget_failure()
        self.get_logger().info(f"HTTP Request [{endpoint}] success: {result}")
        return True

    def _remember_failure(self, endpoint: str, message: str, *, deferred: bool = False) -> None:
        """연달아 몇 번째인지까지 센다 · 한 번은 경합, 계속이면 고장이다.

        `deferred` · 거부가 아니라 준비를 기다려 미룬 것 · 화면이 「대기」 로 쓴다 · 수정 목록 124
        """
        previous = self._last_failure.get('count') or 0
        self._last_failure = {
            'endpoint': endpoint,
            'message': message,
            'count': int(previous) + 1,
            'at': datetime.now().astimezone().isoformat(),
        }
        if deferred:
            self._last_failure['deferred'] = True

    def _forget_failure(self) -> None:
        if getattr(self, '_last_failure', None):
            self.get_logger().info('스케줄 시도가 다시 받아들여졌습니다')
        self._last_failure = {}

    def _read_json(self, endpoint: str, timeout_sec: float = 0.5):
        """브릿지에 물어본다 · **실패를 조용히 넘기지 않는다** · §6-271

        전에는 `debug` 로만 남겼다 · 디버그 기록은 꺼져 있어 아무 데도 안
        남았다 · 그래서 17:58 에 수동 모드인데 모터가 돌기 시작했을 때, 조회가
        실패했는지조차 확인할 수 없었다.

        1초마다 물어보므로 실패할 때마다 적으면 로그가 넘친다 · **상태가
        바뀔 때만** 적는다 · 처음 실패할 때 한 번, 다시 될 때 한 번.
        """
        url = f"http://127.0.0.1:8000{endpoint}"
        try:
            with urllib.request.urlopen(url, timeout=timeout_sec) as response:
                answer = json.loads(response.read().decode())
        except (OSError, ValueError) as exc:
            # 시험은 노드를 `__init__` 없이 만든다 · 없으면 여기서 만든다
            counts = getattr(self, '_read_failures', None)
            if counts is None:
                counts = {}
                self._read_failures = counts
            failures = counts.get(endpoint, 0) + 1
            counts[endpoint] = failures
            if failures == 1:
                self.get_logger().warn(
                    f"조회 실패 [{endpoint}] · {exc} · 제한 {timeout_sec}초"
                )
            return None
        failures = getattr(self, '_read_failures', {}).pop(endpoint, 0)
        if failures:
            self.get_logger().warn(f"조회 회복 [{endpoint}] · {failures}번 실패한 뒤")
        return answer

    def _coordination_joined(self) -> bool:
        """지금 **실제로** 여러 대로 묶여 있는가 · §6-266

        「쓰겠다」는 설정이고 「지금 묶여 있다」는 상태다 · 둘은 다르다 ·
        설정만 보고 그쪽으로 보내면, 묶이지 않은 PC 에서는 받을 데가 없어
        매번 거절당한다.

        실측으로 16~18시 구간 안에서 1분마다 거절이 쌓였고(15분에 7회),
        그동안 모션은 한 번도 돌지 않았다 · 단독으로 도는 길은 이미 있고
        같은 요청을 넣어 보면 「초기 위치 이동 → 연속 모션 실행 중」까지
        정상으로 간다 · 스케줄만 그 길로 갈 방법이 없었다.
        """
        payload = self._read_json('/api/coordination')
        runtime = (payload or {}).get('runtime') if isinstance(payload, dict) else None
        if not isinstance(runtime, dict):
            return False
        return runtime.get('joined') is True

    def _local_run_status(self) -> dict:
        """이 PC 의 모션 상태 · 못 읽으면 빈 것."""
        payload = self._read_json('/api/motion-run/status')
        if not isinstance(payload, dict):
            return {}
        status = payload.get('status') if isinstance(payload.get('status'), dict) else payload
        return status if isinstance(status, dict) else {}

    def _local_run_state(self) -> str:
        """이 PC 의 모션이 지금 어느 단계인가 · 못 읽으면 빈 문자열."""
        return str(self._local_run_status().get('state') or '')

    def _recovery_exhausted(self) -> bool:
        """자동 복구 한도 초과로 멈춘 상태인가 · `error` 일 때만 상태 전체를 읽는다"""
        if self._local_run_state() != 'error':
            return False
        return bool(self._local_run_status().get('auto_recovery_exhausted'))

    def _auto_recovery_hold(self) -> bool:
        """런타임이 자동 복구를 다 쓰고 멈췄으면 스케줄도 다시 시작하지 않는다 · 수정 목록 73

        사람이 보고 풀어야 한다 · 운전 모드를 「수동」 으로 바꿨다 「스케줄」 로 돌아오면 풀린다
        (모드를 바꾸는 것이 사람의 확인) · 수동 모드에서 재생·초기 이동을 하면 상태가 바뀌어 풀린다.
        """
        exhausted = self._recovery_exhausted()
        acknowledged = getattr(self, '_auto_recovery_ack_mode_seen', False)
        if not exhausted:
            self._auto_recovery_ack_mode_seen = False
            return False
        if acknowledged:
            return False
        if not getattr(self, '_auto_recovery_hold_logged', False):
            self.get_logger().warning(
                "[점검] 자동 복구 한도 초과로 멈춤 · 스케줄 다시 시작 안 함 · 모드를 바꿨다 돌아오면 다시 시작"
            )
            self._auto_recovery_hold_logged = True
        return True

    def _group_execution(self) -> dict:
        """지금 살아 있는 그룹 실행 · 없으면 빈 것."""
        payload = self._read_json('/api/coordination')
        runtime = (payload or {}).get('runtime') if isinstance(payload, dict) else None
        execution = (runtime or {}).get('execution') if isinstance(runtime, dict) else None
        return execution if isinstance(execution, dict) else {}

    def _motion_is_running(self) -> bool:
        """지금 모션이 돌고 있는가 · 로컬과 그룹을 **둘 다** 본다 · §6-145

        그룹 실행은 준비가 길다 · 마스터가 신호를 보내고 각 PC 가 응답하고
        시각을 맞추는 동안, 이 PC 의 로컬 모션은 아직 `stopped` 다.

        전에는 로컬만 봐서 그 틈을 「멈춤」으로 읽고, 이미 시작된 그룹 실행을
        1분마다 또 시작시켰다 · 조정 노드가 `이전 그룹 실행 정리 확인 중입니다`
        로 막아 피해는 없었지만 헛시도가 계속 나갔다.
        """
        if is_running(self._local_run_state()):
            return True
        return group_is_active(self._group_execution())

    def _on_timer_tick(self):
        # 0. 활성 프로젝트를 브리지에 맞춘다
        data = self._read_json('/api/schedule/status')
        if isinstance(data, dict):
            api_proj = data.get("active_project_id")
            if api_proj and api_proj != self.store.current_project_id:
                self.get_logger().info(f"Syncing active project from Web API: {api_proj}")
                self.store.load_project(api_proj)
        # **못 읽었으면 짐작하지 않는다** · 직전 값을 그대로 쓴다 · §6-271
        #
        # 전에는 `normalize_run_mode(None)` 이 기본값인 「스케줄」을 돌려줬다 ·
        # 사람이 걸어 둔 「수동」이 조회 한 번 실패로 풀렸고, 그 순간 구간
        # 안이면 모터가 돌기 시작했다 · 모르면 아무것도 바꾸지 않는 쪽이 맞다.
        if isinstance(data, dict) and data.get('run_mode') is not None:
            self._run_mode = normalize_run_mode(data.get('run_mode'))
        # 지금 시작하면 안 되는 이유 · 못 읽었으면 직전 값 · 수정 목록 124
        blocker = schedule_rules.start_blocker(data)
        if blocker is not None:
            self._start_blocker = blocker

        if not self.store.current_project_id:
            self._load_active_project_from_file()

        self.store.check_and_reload()

        now = datetime.now().astimezone()

        # 슬레이브는 아무것도 하지 않는다 · 마스터가 그룹 전체를 몬다 · §6-137
        if not self._is_master_pc():
            return

        if time.monotonic() - self._last_reconcile_monotonic >= RECONCILE_INTERVAL_SEC:
            self._last_reconcile_monotonic = time.monotonic()
            self._reconcile(now)

        self._publish_status(now)

    def _reconcile(self, now: datetime) -> None:
        """스케줄이 말하는 상태와 실제를 맞춘다 · §6-137

        시각을 지나갔는지 보지 않는다 · **지금 구간 안인가**만 본다 · 그래서
        재부팅해도, 시작을 놓쳐도, 어긋나도 다음 점검에서 스스로 맞춘다.
        """
        schedules = self.store.list_schedules()
        wanted = self.engine.active(now, schedules)
        running = self._motion_is_running()
        self._warn_about_unreadable(schedules)
        if not running and not self._last_read_failed('/api/coordination'):
            # 멈춰 있는 것을 봤다 · 다음에 도는 것은 스케줄이 켰거나(`_execute_start`) 사람이 켠 것이다 ·
            # 그룹 상태를 못 읽은 점검은 「멈춤」 을 본 것이 아니다 · 기억을 바꾸지 않는다 · 수정 목록 143 ③
            self._schedule_started = False
        if running or wanted is None:
            # 지난 시작이 돌기 시작했거나 구간이 끝났다 · 셀 것이 없다 · 수정 목록 124
            self._start_pending = False
            self._deferred_reason = ''

        # 구간 끝에 멈춰 있던 로봇도 기준점 주차 → 서보 OFF · 스케줄 모드 · 구간 끝마다 한 번 · 사용자 2026-10-13
        step = schedule_rules.window_end_step(
            pending=getattr(self, '_window_end_pending', False),
            in_window=wanted is not None, running=running, run_mode=self._run_mode,
        )
        self._window_end_pending = step == schedule_rules.WINDOW_END_WAIT
        if step == schedule_rules.IDLE_PARK:
            self.get_logger().info("[점검] 구간 끝 · 멈춰 있다 · 기준점 주차 → 서보 OFF")
            self._execute_idle_park()
            return

        # **구간이 끝나면 멈춘다 · 모드와 상관없이** · §6-270
        #
        # 전에는 수동 모드면 맨 앞에서 돌아갔다 · 그래서 정지도 검사하지
        # 않았다 · 실측으로 16~18시 스케줄이 17:58 에 켠 모션이, 그 뒤 수동
        # 모드가 되자 18시가 지나도 아무도 멈추지 않아 18분을 더 돌았다.
        #
        # (2026-10-12 바뀜 · 수정 목록 106) 수동 모드에서 사람이 켠 재생은 예외 · 아래.
        if wanted is None and running:
            # **구간이 끝나서 멈추는 것은 스케줄이 켠 재생만** · 수정 목록 106 (사용자 2026-10-12)
            #
            # 수동 모드에서 사람이 켠 재생(단독 · 그룹)은 손대지 않는다 · 시험은 운영 구간이
            # 없는 날에도 돼야 한다 · 스케줄이 켰다가 도중에 수동으로 바꾼 것은 위 17:58 사고라
            # 그대로 멈춘다 · 그룹은 연동 상태의 `started_by` 로 안다(스케줄 노드가 재시작해도) ·
            # 상태를 읽었는데도 누가 켰는지 모르면 멈추는 쪽 · 못 읽었으면 다음 점검 · 수정 목록 143 ·
            # 스케줄 모드 · 오프 모드는 누가 켰든 멈춘다.
            if self._run_mode not in (SCHEDULE_MODE, OFF_MODE):
                started = self._started_by_schedule()
                if started is False:
                    if not getattr(self, '_manual_run_noted', False):
                        self._manual_run_noted = True
                        self.get_logger().info("[점검] 구간 밖 · 수동 모드에서 사람이 켠 재생 · 그대로 둠")
                    return
                if started is None and not self._run_state_readable():
                    # 상태를 못 읽었다 · 도는지도 누가 켰는지도 모른다 · 이번 점검은 정하지 않는다 ·
                    # 다음 점검(1분)에 다시 본다 · 수정 목록 143 ③
                    #
                    # 전에는 못 읽은 상태를 「도는 단독 재생 · 스케줄 칸 없음」 으로 읽어 「사람이 켠 재생」
                    # 으로 지나갔고, 기억(모름)은 그대로 남아 그다음 사람이 켠 그룹을 멈췄다(실물 V-28).
                    return
            self._manual_run_noted = False
            self.get_logger().info("[점검] 구간 밖인데 돌고 있다 · 회차 후 정지")
            # 스케줄 모드에서 운영 시간이 끝났다 · 정지 뒤 PC 마다 제 설정대로
            # 기준점 주차 → 서보 OFF · 수동·오프 모드는 멈추기만 (사람이 만지는 중일 수 있다) ·
            # 수정 목록 36
            self._execute_stop_after_cycle(
                None,
                reason='schedule_end' if self._run_mode == SCHEDULE_MODE else '',
            )
            return

        # **원하는 대로 되어 있으면 지난 거부는 잊는다** · §6-287
        #
        # 전에는 「다음 번 보내기가 성공할 때」만 지웠다 · 그런데 한 번 성공해
        # 돌기 시작하면 더 보낼 일이 없어서, 이미 풀린 거부 문구가 화면에
        # 몇 시간이고 남았다 · 실측으로 모터는 도는데 스케줄 창에는 「MIDI 제어가
        # 사용 중이어서 시작할 수 없습니다」가 그대로 떠 있었다.
        #
        # 사람이 직접 고쳐서 풀린 경우도 마찬가지다 · 스케줄이 다시 보내지
        # 않아도 사실이 아니게 된다.
        if (wanted is not None) == running:
            self._forget_failure()

        # 오프 모드 · 구간 **안**이라도 돌고 있으면 회차 후 정지 · 수동과 다른 점이다
        #
        # 오프 = 「아무것도 움직이지 않는다 · 서보는 홀드」 · 사람이 켠 것이든
        # 스케줄이 켠 것이든 회차를 마치고 멈춘다 · 새 시작은 아래 공통 분기가 막는다.
        if self._run_mode == OFF_MODE and running:
            self.get_logger().info("[점검] 오프 모드인데 돌고 있다 · 회차 후 정지")
            self._execute_stop_after_cycle(None)
            return

        if self._run_mode != SCHEDULE_MODE:
            # 자동 복구 한도 초과로 멈춘 **동안** 사람이 모드를 바꿨다 · 스케줄로 돌아오면 다시 시작한다 · 73
            # (그 전의 모드 변경은 확인으로 치지 않는다 · 나중 한도 초과를 그냥 넘기면 안 된다)
            if self._recovery_exhausted():
                self._auto_recovery_ack_mode_seen = True
            # 수동 모드 · 스케줄은 **새로 시작하지 않는다** · §6-143
            #
            # 전에는 「사람이 멈췄나」를 요청 내용으로 추측했다 · 그룹 정지나
            # 안전 정지까지 사람이 멈춘 것으로 읽어서, 1회 연동 실행만 해도
            # "사람이 모션을 정지했습니다" 가 떴다 · 추측을 없앴다.
            return

        if wanted is not None and not running:
            # 지난 점검에 보낸 시작이 받아들여졌는데 아직 안 돈다 · 거부로 센다 · 수정 목록 123·124
            #
            # 그룹 시작은 받아들여진 뒤 준비 단계에서 실패한다 · 전에는 그 실패가 아무 데도 안
            # 세어져 1분마다 「받아들여졌다」 만 찍히고 화면은 초록이었다(실물 S-11).
            self._note_start_went_nowhere()
            if self._auto_recovery_hold():
                return
            self._auto_recovery_hold_logged = False
            # 부팅 직후 · 앱솔루트 확인 · 모터 상태가 준비될 때까지 미룬다 · 수정 목록 124
            #
            # 전에는 준비 전에 그룹 시작을 보내 「실행 준비 검사 실패: 앱솔루트 미확인」 으로
            # 거절당했고, 그 거절이 그룹 오류 2등급으로 잠겨 준비가 끝난 뒤에도 사람이 풀 때까지
            # 안 돌았다(실물 S-12 · 15:34) · 잠그지 않고 다음 점검(1분)에 다시 본다.
            blocker = getattr(self, '_start_blocker', '')
            if blocker:
                self._defer_start(wanted, blocker)
                return
            self.get_logger().info(
                f"[점검] 구간 안인데 멈춰 있다 · 시작 · {wanted.schedule_name}"
            )
            self._execute_start(wanted)

    def _defer_start(self, item: ScheduleItem, reason: str) -> None:
        """준비가 덜 됐다 · 시작을 미루고 화면에 「대기」 로 남긴다 · 이유가 바뀔 때만 로그"""
        if getattr(self, '_deferred_reason', '') != reason:
            self._deferred_reason = reason
            self.get_logger().warning(
                f"[점검] 구간 안 · 준비 전이라 시작 미룸 · {item.schedule_name} · {reason} · "
                f"{RECONCILE_INTERVAL_SEC:.0f}초 뒤 다시"
            )
        self._remember_failure('준비 대기', reason, deferred=True)

    def _note_start_went_nowhere(self) -> None:
        if not getattr(self, '_start_pending', False):
            return
        self._start_pending = False
        payload = self._read_json('/api/coordination')
        runtime = payload.get('runtime') if isinstance(payload, dict) else None
        message = schedule_rules.start_failure_message(runtime, self._local_run_status())
        self.get_logger().warning(f"[점검] 지난 시작이 재생으로 이어지지 않음 · {message}")
        self._remember_failure('시작 뒤 재생 없음', message)

    def _started_by_schedule(self):
        """지금 도는 재생을 스케줄이 켰나 · True 켰음 · False 사람이 켬 · None 모름 · 수정 목록 106 · 143

        단독 재생은 런타임 상태의 `schedule_id` 가 답이다(스케줄만 그 칸을 채운다 · §6-270) ·
        그룹은 연동 상태의 `started_by` 가 답이다(진행 PC 인 이 PC 의 연동 노드가 시작 요청에서 받아
        둔다 · 이 노드가 재시작해도 남는다) · 그것도 없으면 이 노드가 기억한 값.
        모름(None)은 부르는 쪽이 정한다 · 상태를 읽었는데 모르면 멈추는 쪽(106) · 못 읽었으면 다음 점검.

        전에는 그룹이면 기억만 봤다 · 재시작 직후 기억은 「모름」 이라, 사람이 켠 그룹도 구간 밖이면
        멈췄다(실물 V-28 · 수정 목록 143).
        """
        try:
            status = self._local_run_status()
        except Exception:
            status = {}
        state = str(status.get('state') or '').strip()
        # 빈 상태는 「도는 단독 재생」 이 아니라 「못 읽음」 이다 · 수정 목록 143 ③
        if state and is_running(state) and not status.get('group_execution'):
            return bool(str(status.get('schedule_id') or '').strip())
        starter = self._group_started_by_schedule()
        if starter is not None:
            # 연동 노드가 아는 답 · 기억도 맞춰 둔다(다음에 못 읽을 때를 위해)
            self._schedule_started = starter
            return starter
        return getattr(self, '_schedule_started', None)

    def _group_started_by_schedule(self):
        """살아 있는 그룹 실행을 누가 켰나 · 연동 상태의 `started_by` · 없거나 모르면 None · 수정 목록 143

        값은 연동 노드의 `participant_rules.STARTED_BY_*` 와 같은 글자다(`human` · `schedule`) ·
        진행 PC 가 아니면 연동 노드가 빈 값을 준다 · 옛 연동 노드는 칸이 없다 · 둘 다 None.
        """
        execution = self._group_execution()
        if not group_is_active(execution):
            return None
        started_by = str(execution.get('started_by') or '').strip().lower()
        if started_by == 'schedule':
            return True
        if started_by == 'human':
            return False
        return None

    def _last_read_failed(self, endpoint: str) -> bool:
        """마지막 조회가 실패했나 · `_read_json` 이 세는 연속 실패 · 성공하면 지운다 · 수정 목록 143"""
        return bool((getattr(self, '_read_failures', None) or {}).get(endpoint))

    def _run_state_readable(self) -> bool:
        """이번 점검이 이 PC 의 모션 상태와 그룹 상태를 **둘 다** 읽었나 · 수정 목록 143 ③

        못 읽은 모션 상태는 빈 문자열이고 「도는 중」 으로 친다(`run_state.is_running`) · 시작을 막는 데는
        맞지만, 「누가 켰나」 의 기억을 바꾸거나 정지를 정하는 근거로는 쓰지 않는다.
        """
        state = str(self._local_run_state() or '').strip()
        return bool(state) and not self._last_read_failed('/api/coordination')

    def _warn_about_unreadable(self, schedules) -> None:
        """시각을 못 읽는 스케줄은 **말이라도 한다** · §6-285

        못 읽는 시각(예전의 `24:00`)은 구간이 없는 것과 같아서 조용히 건너뛴다 ·
        켜 뒀는데 안 도는 이유를 알 길이 없었다 · 한 번만 남기고, 고쳐지면
        다시 말할 수 있게 기억해 둔다.
        """
        try:
            broken = unreadable_schedules(schedules)
        except Exception:
            return
        previous = getattr(self, '_unreadable_schedules', None)
        if broken == previous:
            return
        self._unreadable_schedules = broken
        if broken:
            self.get_logger().warning(
                '[점검] 시각을 읽을 수 없어 돌지 않는 스케줄: ' + ' · '.join(broken)
            )
        elif previous:
            self.get_logger().info('[점검] 시각을 못 읽던 스케줄이 정상으로 돌아왔다')

    def _execute_start(self, item: ScheduleItem):
        self.get_logger().info(f"[SCHEDULE TRIGGER] START -> {item.schedule_name} ({item.schedule_id})")
        self._schedule_started = True   # 구간이 끝나면 이 재생은 스케줄이 멈춘다 · 수정 목록 106
        
        # 스케줄러 자체 판단을 제거하고, 연동 설정 파일에 사용자가 저장한 값을 그대로 가져와 웹 UI와 100% 동일하게 쏩니다.
        # 반복 방식의 주인은 `motion_common.repeat_policy` 다 · §6-135
        #
        # 전에는 여기 기본값만 `direct` 였다 · 화면에는 「초기 위치 이동 후
        # 다음」이 골라져 보이는데 스케줄은 `direct` 로 쐈고, 시작값과 끝값이
        # 5° 이상 벌어진 모션은 "연속 동작할 수 없습니다" 로 죽었다.
        req_repeat_mode = DEFAULT_REPEAT_MODE
        req_dwell_sec = 0.0
        req_sync_mode = DEFAULT_GROUP_SYNC_MODE
        automation_file = os.path.join(self.projects_dir, self.store.current_project_id, "runtime", "motion_automation.json")
        try:
            if os.path.exists(automation_file):
                with open(automation_file, "r", encoding="utf-8") as f:
                    auto_config = json.load(f)
                    req_repeat_mode = normalize_repeat_mode(auto_config.get("repeat_mode"))
                    req_dwell_sec = float(auto_config.get("dwell_sec", 0.0))
                    req_sync_mode = normalize_group_sync_mode(auto_config.get("group_sync_mode"))
        except (OSError, ValueError) as exc:
            self.get_logger().warning(f"Failed to read motion_automation.json: {exc}")
            
        if self._coordination_enabled() and self._coordination_joined():
            endpoint = "/api/coordination/control"
            payload = {
                "command": "start_group",
                "run_mode": "continuous",
                "repeat_mode": req_repeat_mode,
                "dwell_sec": req_dwell_sec,
                "sync_mode": req_sync_mode,
                "target_cycle_count": 0,
                "schedule_id": item.schedule_id,
            }
        else:
            # 단독 · 모션·매핑 파일은 브리지가 프로젝트의 활성 파일로 채운다
            endpoint = "/api/motion-run/start"
            payload = {
                "run_mode": "continuous",
                "repeat_mode": req_repeat_mode,
                "dwell_sec": req_dwell_sec,
                "target_cycle_count": 0,
                "schedule_id": item.schedule_id,
            }
        # **받아들여진 것은 아직 성공이 아니다** · 실제로 돌아야 지운다(`_reconcile`) · 수정 목록 124
        #
        # 그룹 시작은 받아들여진 뒤 준비 단계에서 실패할 수 있다 · 받아들여졌다고 지난 실패를
        # 지우면, 1분마다 실패해도 횟수가 1을 넘지 못해 화면이 빨강이 되지 않는다.
        previous = dict(getattr(self, '_last_failure', {}) or {})
        accepted = self._send_http_request(endpoint, payload)
        self._start_pending = bool(accepted)
        if accepted and previous:
            self._last_failure = previous

    def _execute_stop_after_cycle(self, item=None, reason: str = ''):
        name = getattr(item, 'schedule_name', '구간 밖')
        schedule_id = getattr(item, 'schedule_id', '')
        self.get_logger().info(f"[SCHEDULE TRIGGER] STOP-AFTER-CYCLE -> '{name}'")
        # **도는 것이 그룹 실행일 때만** 그룹 길 · 단독 재생은 단독 길 · 수정 목록 115
        #
        # 전에는 연동이 켜져 있고 묶여 있으면 무조건 그룹 길로 보냈다 · 사람이 켠 단독 연속
        # 재생은 「활성 그룹 실행이 없습니다」 로 거절당해 4회차 넘게 안 멈췄다(실물 R-43) ·
        # 단독 길도 `reason` 을 실어 스케줄 끝 동작(기준점 주차 → 서보 OFF)이 같이 돈다.
        joined = self._coordination_enabled() and self._coordination_joined()
        route = schedule_rules.stop_route(
            self._group_execution() if joined else {}, joined=joined,
        )
        if route == schedule_rules.GROUP_ROUTE:
            if self._send_http_request("/api/coordination/control", {
                "command": "stop_after_cycle",
                "schedule_id": schedule_id or 'reconcile',
                "reason": reason,
            }):
                return
            # 그룹 길이 거절했다(그 사이 그룹이 끝났거나 실행이 없다) · 단독 길로 다시
            self.get_logger().info("[점검] 그룹 회차 후 정지 거절 · 단독 길로 다시")
        self._send_http_request("/api/motion-run/stop-after-cycle", {
            "schedule_id": schedule_id or 'reconcile',
            "reason": reason,
        })

    def _execute_idle_park(self):
        """구간 끝 · 멈춰 있던 로봇 · 회차 후 정지와 같은 `reason=schedule_end` 길 · 사용자 2026-10-13

        묶여 있으면 그룹 길 · 도는 그룹이 없어도 연동 노드가 스케줄 모드 PC 마다 전한다 ·
        그룹 길이 거절하면(옛 연동 노드 · 묶임 풀림) 이 PC 만.
        브리지가 PC 마다 다시 본다 · 스케줄 모드 · 알람 없음 · 서보 켜짐 · 끌 모터 있음.
        여기서는 한 번만 보낸다 · 거절·실패 뒤 1분 간격 다시 시도(모두 3번) · 그래도 안 되면 그 자리에서
        서보 OFF 는 PC 마다 브리지(`schedule_end.ScheduleEndService`)가 맡는다 · 결과는 PC 마다 다르고
        마스터는 슬레이브 결과를 모른다 · 수정 목록 131
        """
        payload = {"schedule_id": "window_end", "reason": "schedule_end"}
        if self._coordination_enabled() and self._coordination_joined():
            if self._send_http_request("/api/coordination/control", {"command": "stop_after_cycle", **payload}):
                return
            self.get_logger().info("[점검] 그룹 길 거절 · 이 PC 만 주차")
        self._send_http_request("/api/motion-run/stop-after-cycle", payload)

    def _publish_status(self, now: datetime):
        schedules = self.store.list_schedules()
        status = {
            "is_master": self._is_master_pc(),
            "active_project_id": self.store.current_project_id,
            "current_time": now.isoformat(),
            "schedule_count": len(schedules),
            "active_schedule_id": getattr(
                self.engine.active(now, schedules),
                'schedule_id', None,
            ),
            # 시각을 못 읽어 **영영 안 도는** 스케줄 · 화면이 빨간 줄로 띄운다 ·
            # §6-285 · 전에는 조용히 건너뛰어 「켜 뒀는데 안 돈다」로만 보였다
            "unreadable_schedules": unreadable_schedules(schedules),
            "run_mode": self._run_mode,
            # 단독으로 돌았는지 화면이 알 수 있게 남긴다 · §6-266
            "coordination_enabled": self._coordination_enabled(),
            "coordination_joined": self._coordination_joined(),
            # 마지막으로 거부당한 시도 · 비어 있으면 정상이다
            "last_failure": dict(self._last_failure),
            # 멈춰도 몇 초 뒤에 다시 맞추는가 · 화면이 사람에게 알려준다 · §6-149
            "reconcile_interval_sec": RECONCILE_INTERVAL_SEC,
        }
        msg = String()
        msg.data = json.dumps(status)
        self.status_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = MotionScheduleNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
