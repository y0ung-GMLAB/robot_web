"""시간표 재생 · 연동 노드 쪽 · 설정 묶음 주고받기 · 이 PC 시간표 구동 · 사람 명령 · 상태 · 수정 목록 186 (2026-11-09)

`MotionCoordinationNode` 가 이 클래스를 함께 물려받는다 · 신호 재생(lockstep) 코드는 그대로 두고 옆에 붙인다.

- 마스터 · 1 s 마다 제 운전 모드 · 스케줄 · 재생 목록 · PC 들이 알려 준 필요 시간(자동 회차 간격)을 보고 바뀌면
  새 버전 · 바뀔 때 바로 + 2 s 마다 보낸다(늦게 붙은 PC · 다시 붙은 PC 가 받는다)
- 모든 PC · 높은 버전을 받으면 디스크에 저장 · 시간표 재생이면 `ClockDriver` 로 제 시간표를 돈다
- 시간표는 스케줄에만 · 사람이 누른 그룹 재생은 신호 재생(사용자 2026-11-09 · Q9 변경) · 시간표 회차가 아직
  도는 PC 가 있으면 사람 시작을 거절(즉시 정지 뒤 시작)
- 정지 = 묶음의 정지 칸 · 슬레이브의 정지는 마스터에 요청(+ 즉시 정지면 제 재생도 바로)
- 끊긴 PC 는 옛 버전으로 계속 · 다시 붙으면 새 버전을 받는 순간 따른다(즉시 정지 포함 · Q8)

옛 시험 노드(`__new__` 로 만든 것)에는 이 칸들이 없다 · 모두 `getattr` 기본값으로 · 그때는 신호 재생과 같다.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Dict, Mapping

from motion_coordination_interfaces.msg import GroupCommand, GroupTimetable
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

from motion_common import topics

from . import clock_grid, timetable
from .clock_driver import _FINISHED_STATES, PLAN_PREFIX, ClockDriver
from .group_execution import GROUP_PROTOCOL_VERSION
from .participant_rules import SCHEDULE_END_REASON, STARTED_BY_SCHEDULE
from .timetable import TimetableConfig

#: 묶음을 다시 보내는 간격 · 늦게 붙은 PC 가 받는다(TRANSIENT_LOCAL 과 같이)
TIMETABLE_REPUBLISH_SEC = 2.0
#: 마스터가 제 설정을 다시 보는 간격
TIMETABLE_UPKEEP_SEC = 1.0
#: PC 사이 시계 차이 경고 · 사용자 2026-11-09 Q5 「표시만 · 다음 회차에서 맞춤」
CLOCK_WARN_MS = 100.0
#: 시계 차이 추정에 쓰는 하트비트 수 · 가장 작은 지연이 실제 차이에 가장 가깝다
CLOCK_SAMPLES = 40
#: 슬레이브가 마스터에 정지를 요청하는 그룹 명령 · 마스터만 처리
TIMETABLE_STOP_COMMAND = 'timetable_stop'

TIMETABLE_QOS = QoSProfile(
    depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL,
)


class TimetableMixin:
    """연동 노드에 붙는 시간표 재생 부분"""

    # ------------------------------------------------------------------ #
    # 준비
    # ------------------------------------------------------------------ #

    def _init_timetable(self, workspace: Path) -> None:
        self._timetable_path = Path(
            os.environ.get('MOTION_TIMETABLE_FILE') or timetable.default_path(workspace)
        ).expanduser()
        self._timetable = timetable.load(self._timetable_path)
        self._timetable_published_at = 0.0
        self._timetable_upkeep_at = 0.0
        self._timetable_peers: Dict[str, Dict[str, Any]] = {}
        self._clock_driver = ClockDriver(
            self._call_local_control,
            info=lambda text: self.get_logger().info(text),
            warn=self._warn,
            finish=self._timetable_finish,
        )
        self._timetable_pub = self.create_publisher(GroupTimetable, topics.GROUP_TIMETABLE, TIMETABLE_QOS)
        self._timetable_sub = self.create_subscription(
            GroupTimetable, topics.GROUP_TIMETABLE, self._timetable_callback, TIMETABLE_QOS,
        )
        if self._timetable.version:
            self.get_logger().info(
                f'시간표 설정 읽음 · 버전 {self._timetable.version} · '
                f'{"시간표 재생" if self._timetable.clock else "신호 재생"}'
            )

    def _tt(self) -> TimetableConfig:
        config = getattr(self, '_timetable', None)
        return config if isinstance(config, TimetableConfig) else TimetableConfig()

    def _timetable_clock(self) -> bool:
        return self._tt().clock

    # ------------------------------------------------------------------ #
    # 주고받기
    # ------------------------------------------------------------------ #

    def _store_timetable(self, config: TimetableConfig, source: str) -> None:
        previous = self._tt()
        with self._lock:
            self._timetable = config
        try:
            timetable.save(getattr(self, '_timetable_path', Path('config') / timetable.FILE_NAME), config)
        except OSError as exc:
            self._warn(f'시간표 설정 저장 실패 · {exc}')
        if previous.mode != config.mode:
            self.get_logger().info(
                f'재생 방식 · {"시간표 재생" if config.clock else "신호 재생"} · 버전 {config.version} · {source}'
            )
        else:
            self.get_logger().info(f'시간표 설정 버전 {config.version} · {source}')

    def _publish_timetable(self, *, force: bool = False) -> None:
        publisher = getattr(self, '_timetable_pub', None)
        config = self._tt()
        if publisher is None or not config.version:
            return
        now = time.monotonic()
        if not force and now - float(getattr(self, '_timetable_published_at', 0.0)) < TIMETABLE_REPUBLISH_SEC:
            return
        self._timetable_published_at = now
        message = GroupTimetable()
        message.group_id = self._config.group_id
        message.pc_id = self._config.pc_id
        message.boot_id = getattr(self, '_boot_id', '')
        message.version = int(config.version)
        message.body = timetable.body_text(config)
        message.protocol_version = GROUP_PROTOCOL_VERSION
        publisher.publish(message)

    def _timetable_callback(self, message: GroupTimetable) -> None:
        if message.group_id != self._config.group_id or message.pc_id == self._config.pc_id:
            return
        try:
            incoming = timetable.from_body(message.body)
        except ValueError as exc:
            self._warn(f'시간표 설정을 읽지 못함 · {message.pc_id} · {exc}')
            return
        if timetable.accept(self._tt(), incoming):
            self._store_timetable(incoming, f'{message.pc_id} 에서 받음')

    # ------------------------------------------------------------------ #
    # 하트비트
    # ------------------------------------------------------------------ #

    def _timetable_heartbeat(self) -> tuple:
        """(버전, 상태 JSON) · 하트비트에 싣는다"""
        driver = getattr(self, '_clock_driver', None)
        report = {
            'need': round(self._own_cycle_need(), 3),
            'mode': str((self._local_status or {}).get('operation_mode') or ''),
            'run': driver.report() if driver is not None else {},
            # 시간대 · 운영시간을 이 PC 시간대로 읽는다 · 마스터와 다르면 화면 노랑 · 재생은 그대로
            'tz': self._own_timezone(),
        }
        return int(self._tt().version), json.dumps(report, ensure_ascii=False, separators=(',', ':'))

    def _note_timetable_heartbeat(self, message: Any) -> None:
        """다른 PC 의 시간표 상태 · 시계 차이(받은 시각 − 보낸 시각 중 가장 작은 값)"""
        received = time.time()
        try:
            sent = float(message.sent_at.sec) + float(message.sent_at.nanosec) / 1e9
        except (AttributeError, TypeError, ValueError):
            sent = 0.0
        try:
            report = json.loads(str(getattr(message, 'timetable_report', '') or '') or '{}')
        except ValueError:
            report = {}
        peers = getattr(self, '_timetable_peers', None)
        if peers is None:
            peers = self._timetable_peers = {}
        entry = peers.setdefault(message.pc_id, {'delays': deque(maxlen=CLOCK_SAMPLES)})
        entry['version'] = int(getattr(message, 'timetable_version', 0) or 0)
        entry['report'] = report if isinstance(report, Mapping) else {}
        entry['boot_id'] = str(getattr(message, 'boot_id', '') or '')
        if sent > 0.0:
            entry['delays'].append(received - sent)

    def _own_timezone(self) -> str:
        return str((self._local_status or {}).get('timezone') or '')

    def _timezone_differs(self, timezone_name: str) -> bool:
        """마스터 시간대(묶음)와 다른가 · 둘 중 하나라도 모르면 다르지 않은 것으로"""
        master = str(self._tt().timezone or '')
        return bool(master and timezone_name and timezone_name != master)

    def _own_cycle_need(self) -> float:
        try:
            return max(float((self._local_status or {}).get('cycle_need_sec') or 0.0), 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _peer_clock_offsets_ms(self) -> Dict[str, float]:
        """PC 별 시계 차이(ms) · + = 그 PC 시계가 이 PC 보다 빠름 · 망 지연이 섞여 몇 ms 작게 나온다"""
        offsets = {}
        for pc_id, entry in (getattr(self, '_timetable_peers', None) or {}).items():
            delays = entry.get('delays') or ()
            if delays:
                offsets[pc_id] = round(-min(delays) * 1000.0, 1)
        return offsets

    # ------------------------------------------------------------------ #
    # 마스터 · 설정 유지
    # ------------------------------------------------------------------ #

    def _timetable_upkeep(self) -> None:
        if not (self._config.configured and self._joined and self._config.is_master):
            return
        now = time.monotonic()
        if now - float(getattr(self, '_timetable_upkeep_at', 0.0)) < TIMETABLE_UPKEEP_SEC:
            self._publish_timetable()
            return
        self._timetable_upkeep_at = now
        local = dict(self._local_status or {})
        current = self._tt()
        changes: Dict[str, Any] = {}
        mode = str(local.get('operation_mode') or '')
        if mode:
            changes['schedule_enabled'] = mode == timetable.SCHEDULE_MODE
        if isinstance(local.get('schedule_items'), list):
            changes['schedules'] = tuple(dict(item) for item in local['schedule_items'] if isinstance(item, Mapping))
            # 스피커용 · 운영시간을 미리 계산해 싣는다(날짜가 바뀌면 하루 한 번 버전이 오른다)
            changes['windows'] = tuple(timetable.schedule_windows(changes['schedules'], time.time()))
        if isinstance(local.get('motion_playlist'), list):
            changes['playlist'] = tuple(str(name) for name in local['motion_playlist'])
        if local.get('timezone'):
            changes['timezone'] = str(local['timezone'])
        needs = [self._own_cycle_need()]
        for pc_id in self._registry.joined():
            if self._registry.status(pc_id) == 'offline':
                continue
            entry = (getattr(self, '_timetable_peers', None) or {}).get(pc_id) or {}
            try:
                needs.append(float((entry.get('report') or {}).get('need') or 0.0))
            except (TypeError, ValueError):
                pass
        auto = clock_grid.auto_period(needs)
        if auto > 0.0:
            # 자동 간격은 늘리기만 · 다시 붙은 PC 하나 빠졌다고 줄이면 회차 시각이 흔들린다 · 줄이려면 사람이 입력
            changes['auto_period_sec'] = max(auto, current.auto_period_sec) if current.version else auto
        updated = timetable.issue(current, issuer=self._config.pc_id, **changes)
        if updated is not current:
            self._store_timetable(updated, '마스터 설정 바뀜')
            self._publish_timetable(force=True)
        else:
            self._publish_timetable()

    # ------------------------------------------------------------------ #
    # 이 PC 시간표 구동
    # ------------------------------------------------------------------ #

    def _timetable_run_live(self) -> bool:
        """이 PC 가 시간표 실행을 쥐고 도는 중인가 · 그동안 로컬 상태를 50 ms 로 읽는다 · 수정 목록 188"""
        driver = getattr(self, '_clock_driver', None)
        if driver is not None and driver.holding:
            return True
        status = (getattr(self, '_local_status', None) or {}).get('motion_run_status')
        if not isinstance(status, Mapping) or not status.get('group_execution'):
            return False
        return (
            str(status.get('execution_id') or '').startswith(PLAN_PREFIX)
            and str(status.get('state') or '') not in _FINISHED_STATES
        )

    def _drive_timetable(self) -> None:
        driver = getattr(self, '_clock_driver', None)
        if driver is None:
            return
        self._timetable_upkeep()
        config = self._tt()
        local = dict(self._local_status or {})
        status = local.get('motion_run_status') if isinstance(local.get('motion_run_status'), Mapping) else {}
        holding = driver.holding or str(status.get('execution_id') or '').startswith(PLAN_PREFIX)
        if not config.clock and not holding:
            return
        with self._lock:
            if self._execution.execution_id:
                # 신호 재생 실행(초기 위치 이동 등)이 도는 중 · 손대지 않는다
                return
        if not (self._config.configured and self._joined):
            choice = timetable.Choice(reason='그룹 미참가')
        else:
            choice = timetable.choose(config, time.time(), operation_mode=str(local.get('operation_mode') or ''))
        summary = status.get('summary') if isinstance(status.get('summary'), Mapping) else {}
        driver.tick(choice, {
            'status': status,
            'init_sec': float(summary.get('initialization_duration_sec') or local.get('initial_move_sec') or 0.0),
            'initial_move_time_sec': float(config.initial_move_time_sec or 0.0),
            'start_blocker': str(local.get('start_blocker') or ''),
        })

    def _timetable_finish(self, plan_id: str, park: bool, why: str) -> None:
        if park:
            self._stop_own_motion_quietly(plan_id, why, park_after=True)
            return
        self._call_local_control({
            'command': 'group_cancel', 'execution_id': plan_id,
            'network_operation_id': f'tt-end-{uuid.uuid4().hex}',
        })

    # ------------------------------------------------------------------ #
    # 사람 명령 · 웹(로컬 API)에서
    # ------------------------------------------------------------------ #

    def _timetable_set(self, request: Mapping[str, Any]) -> Dict[str, Any]:
        """마스터 그룹 화면 · 재생 방식 · 회차 간격 · 입력은 마스터 한 곳(Q3)"""
        if not self._config.is_master:
            raise ValueError('재생 방식과 회차 간격은 마스터 PC 에서만 바꿀 수 있습니다')
        current = self._tt()
        changes: Dict[str, Any] = {}
        if 'mode' in request:
            mode = str(request.get('mode') or '')
            if mode not in timetable.MODES:
                raise ValueError('재생 방식이 올바르지 않습니다')
            changes['mode'] = mode
        if 'period_sec' in request:
            try:
                period = float(request.get('period_sec') or 0.0)
            except (TypeError, ValueError) as exc:
                raise ValueError('회차 간격이 숫자가 아닙니다') from exc
            error = clock_grid.period_error(period, current.auto_period_sec)
            if error:
                raise ValueError(error)
            changes['period_sec'] = period
        if 'initial_move_time_sec' in request:
            changes['initial_move_time_sec'] = max(float(request.get('initial_move_time_sec') or 0.0), 0.0)
        with self._lock:
            lockstep_active = bool(self._execution.execution_id)
        if changes.get('mode') == timetable.MODE_CLOCK and lockstep_active:
            raise ValueError('신호 재생 그룹 실행이 도는 중입니다 · 정지한 뒤 바꾸세요')
        updated = timetable.issue(current, issuer=self._config.pc_id, **changes)
        if updated is not current:
            self._store_timetable(updated, '마스터 화면')
            self._publish_timetable(force=True)
        return {'success': True, 'message': '저장했습니다', 'timetable': self._timetable_snapshot()}

    def _timetable_start(self, request: Mapping[str, Any]) -> Dict[str, Any]:
        """스케줄이 시작을 원한다 · 각 PC 가 스케줄 시간표로 · 사람 시작은 여기 오지 않는다(신호 재생)"""
        if not self._joined:
            raise ValueError('먼저 DDS 그룹에 참가하세요')
        if not self._config.is_master:
            raise ValueError('이 PC 는 연동 슬레이브라 그룹 실행을 시작할 수 없습니다 · 마스터 PC 에서 시작하세요')
        current = self._tt()
        updated = timetable.resume_schedule(current, issuer=self._config.pc_id)
        if updated is not current:
            self._store_timetable(updated, '스케줄 시작')
            self._publish_timetable(force=True)
        return {'success': True, 'message': '시간표 재생 · 각 PC 가 스케줄 시간표로 재생', 'sync_mode': timetable.MODE_CLOCK}

    def _timetable_held(self) -> Dict[str, str]:
        """시간표 회차를 아직 쥔 PC · {PC: 시간표 이름} · 이 PC(로컬 재생 상태 포함) + 연결된 PC 의 하트비트"""
        held: Dict[str, str] = {}
        driver = getattr(self, '_clock_driver', None)
        status = (self._local_status or {}).get('motion_run_status')
        status = status if isinstance(status, Mapping) else {}
        own = (driver.holding if driver is not None else '') or (
            str(status.get('execution_id') or '') if status.get('group_execution') else ''
        )
        if own.startswith(PLAN_PREFIX):
            held[self._config.pc_id] = own
        registry = getattr(self, '_registry', None)
        for pc_id, entry in (getattr(self, '_timetable_peers', None) or {}).items():
            if registry is not None and registry.status(pc_id) == 'offline':
                continue
            plan_id = str(((entry.get('report') or {}).get('run') or {}).get('plan_id') or '')
            if plan_id.startswith(PLAN_PREFIX):
                held[pc_id] = plan_id
        return held

    def _timetable_human_start_blocker(self) -> str:
        """사람이 누른 그룹 재생(신호 재생)을 막을 이유 · 시간표 회차가 아직 도는 중 · 섞이면 축을 둘이 쥔다"""
        held = self._timetable_held()
        if held:
            return '시간표 재생 회차가 아직 도는 중 · {} · 그룹 「즉시 정지」 뒤 시작하세요'.format(' · '.join(sorted(held)))
        if self._timetable_execution_view():
            return '스케줄 시간표 재생 중 · 마스터를 수동 모드로 바꾼 뒤 시작하세요'
        return ''

    def _timetable_stop(self, *, after_cycle: bool, reason: str = '') -> Dict[str, Any]:
        """시간표 재생에서 정지 · 마스터 = 묶음에 정지 · 슬레이브 = 마스터에 요청 + 즉시 정지면 제 재생도"""
        if after_cycle and reason == SCHEDULE_END_REASON:
            # 운영시간 끝은 각 PC 가 시간표로 안다(회차 끝까지 → 주차) · 따로 할 일 없음
            return {'success': True, 'message': '운영시간 끝 · 각 PC 가 회차를 마치고 주차'}
        if self._config.is_master:
            updated, plan_id = timetable.stop_plan(
                self._tt(), issuer=self._config.pc_id, after_cycle=after_cycle,
                held_plan_id=self._held_plan_id(),
            )
            if not plan_id:
                return {'success': True, 'message': '도는 시간표가 없습니다'}
            self._store_timetable(updated, '정지')
            self._publish_timetable(force=True)
        else:
            message = GroupCommand()
            message.group_id = self._config.group_id
            message.command_id = f'tt-stop-{uuid.uuid4().hex}'
            message.coordinator_id = self._config.pc_id
            message.command = TIMETABLE_STOP_COMMAND
            message.stop_reason = 'after_cycle' if after_cycle else 'now'
            message.participant_ids = [self._config.pc_id]
            self._command_pub.publish(message)
        driver = getattr(self, '_clock_driver', None)
        if not after_cycle and driver is not None and driver.holding:
            plan_id = driver.holding
            self._call_local_control({
                'command': 'stop_now', 'execution_id': plan_id,
                'network_operation_id': f'tt-stop-local-{uuid.uuid4().hex}',
            }, timeout_sec=3.0)
        return {
            'success': True,
            'message': '회차 후 정지' if after_cycle else '즉시 정지',
            'sync_mode': timetable.MODE_CLOCK,
        }

    def _timetable_remote_stop(self, message: GroupCommand) -> None:
        """슬레이브가 보낸 정지 요청 · 마스터만 처리 · 묶음에 정지를 적어 모두에게"""
        if not self._config.is_master or message.coordinator_id == self._config.pc_id:
            return
        after_cycle = str(getattr(message, 'stop_reason', '') or '') == 'after_cycle'
        updated, plan_id = timetable.stop_plan(
            self._tt(), issuer=self._config.pc_id, after_cycle=after_cycle, held_plan_id=self._held_plan_id(),
        )
        if plan_id:
            self._store_timetable(updated, f'{message.coordinator_id} 의 정지 요청')
            self._publish_timetable(force=True)

    def _held_plan_id(self) -> str:
        """따를 시간표가 없어도 아직 회차를 도는 PC 의 시간표 이름 · 즉시 정지를 그 이름으로 적는다"""
        names = sorted(set(self._timetable_held().values()))
        return names[-1] if names else ''

    # ------------------------------------------------------------------ #
    # 상태
    # ------------------------------------------------------------------ #

    def _timetable_execution_view(self) -> Dict[str, Any]:
        """스케줄 노드 · 화면용 · 시간표 실행이 「도는 중」 인가 · 운영시간 안 · 또는 아직 회차를 도는 PC 가 있음

        마스터를 수동으로 바꾸면 따를 시간표는 없어지지만 PC 들은 도는 회차를 마친다 · 그동안도 「도는 중」 으로
        보여야 화면에 정지 버튼이 남는다.
        """
        config = self._tt()
        if not config.clock:
            return {}
        now = time.time()
        local = dict(self._local_status or {})
        choice = timetable.choose(config, now, operation_mode=str(local.get('operation_mode') or ''))
        timeline = choice.timeline
        if timeline is None:
            plan_id = self._held_plan_id()
            if not plan_id or choice.stopped_plan_id == plan_id:
                return {}
            return {
                'execution_id': plan_id,
                'state': 'running',
                'cycle_number': 0,
                'started_by': STARTED_BY_SCHEDULE,
                'sync_mode': timetable.MODE_CLOCK,
                'coordinator_id': config.issued_by,
            }
        running = clock_grid.running_cycle(timeline, now)
        active = bool(running) or timeline.anchor_unix - now <= config.start_lead_sec + 1.0
        if timeline.end_unix and now >= timeline.end_unix:
            active = False
        if not active:
            return {}
        return {
            'execution_id': timeline.plan_id,
            'state': 'running' if running else 'waiting',
            'cycle_number': running,
            'started_by': STARTED_BY_SCHEDULE,
            'sync_mode': timetable.MODE_CLOCK,
            'coordinator_id': config.issued_by,
        }

    def _timetable_snapshot(self) -> Dict[str, Any]:
        config = self._tt()
        now = time.time()
        local = dict(self._local_status or {})
        choice = timetable.choose(config, now, operation_mode=str(local.get('operation_mode') or ''))
        timeline = choice.timeline
        upcoming = clock_grid.next_slot(timeline, now, prep_sec=0.0) if timeline is not None else None
        driver = getattr(self, '_clock_driver', None)
        offsets = self._peer_clock_offsets_ms()
        peers = {}
        for pc_id, entry in (getattr(self, '_timetable_peers', None) or {}).items():
            report = entry.get('report') or {}
            timezone_name = str(report.get('tz') or '')
            peers[pc_id] = {
                'version': int(entry.get('version') or 0),
                'need_sec': float(report.get('need') or 0.0),
                'run': dict(report.get('run') or {}),
                'clock_offset_ms': offsets.get(pc_id),
                'clock_warning': offsets.get(pc_id) is not None and abs(offsets[pc_id]) > CLOCK_WARN_MS,
                'timezone': timezone_name,
                'timezone_mismatch': self._timezone_differs(timezone_name),
            }
        return {
            'mode': config.mode,
            'version': int(config.version),
            'issued_by': config.issued_by,
            'period_sec': float(config.period_sec),
            'auto_period_sec': float(config.auto_period_sec),
            'effective_period_sec': float(config.period()),
            'schedule_enabled': bool(config.schedule_enabled),
            # 시간표 회차를 아직 쥔 PC · 사람 시작(신호 재생)은 이게 빌 때까지 막힌다
            'held': self._timetable_held(),
            'stop': dict(config.stop or {}),
            'plan_id': timeline.plan_id if timeline is not None else '',
            'plan_kind': timeline.kind if timeline is not None else '',
            'reason': choice.reason,
            'running_cycle': clock_grid.running_cycle(timeline, now),
            'next_cycle': upcoming.cycle if upcoming is not None else 0,
            'next_start_unix': upcoming.start_unix if upcoming is not None else 0.0,
            'own_need_sec': self._own_cycle_need(),
            'local': driver.report() if driver is not None else {},
            'peers': peers,
            'clock_warn_ms': CLOCK_WARN_MS,
            'clock_warnings': sorted(pc for pc, item in peers.items() if item['clock_warning']),
            # 시간대 · 마스터(묶음) · 이 PC · 다른 PC 목록 · 표시만(한 PC 문제는 그 PC 만)
            'master_timezone': str(config.timezone or ''),
            'local_timezone': self._own_timezone(),
            'local_timezone_mismatch': self._timezone_differs(self._own_timezone()),
            'timezone_mismatches': sorted(pc for pc, item in peers.items() if item['timezone_mismatch']),
        }
