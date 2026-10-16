"""Local web/ROS adapter for the independent PC coordination service."""

import copy
from dataclasses import replace
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from motion_common import motion_segment, repeat_policy

from motion_web_bridge import run_mode_gate
from motion_common import run_state

import yaml

from motion_common.group_config import (
    load_group_config,
    migrate_legacy_group_config,
    save_group_config,
)


#: 웹 서비스가 내려갈 때 「이 PC 빠짐」 알림을 기다리는 시간 · systemd 종료 제한(8 s) 안 · 수정 목록 145 ①
LEAVE_NOTICE_TIMEOUT_SEC = 1.5


class LeaveNotice:
    """웹 서비스가 내려갈 때 한 번만 · 연동 노드에 「이 PC 빠짐」 · 수정 목록 145 ①

    신호(SIGINT · SIGTERM)를 받은 바로 그때 보낸다 · 웹 서버가 연결을 닫는 동안 연동 노드는 0.5 s
    안에 「상태 수신 중단」 을 본다 · 그보다 먼저 닿아야 이 PC 만 빠진다 · 신호 처리기를 막지 않게
    따로 스레드에서 · 종료 끝에서 잠깐(`wait`) 기다린다 · 여러 번 불려도 한 번만 보낸다.
    """

    def __init__(self, send: Callable[[], Any]) -> None:
        self._send = send
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self.result: Any = None

    def send(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._run, name='coordination-leave-notice', daemon=True,
            )
            self._thread.start()

    def wait(self, timeout_sec: float = LEAVE_NOTICE_TIMEOUT_SEC + 0.5) -> None:
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=max(float(timeout_sec), 0.0))

    def _run(self) -> None:
        try:
            self.result = self._send()
        except Exception as exc:  # noqa: BLE001 · 알림 실패가 종료를 막지 않는다
            self.result = {'success': False, 'message': str(exc)}


class CoordinationWebBridge:
    """Expose global coordination state without mixing it into project data."""

    def __init__(
        self,
        node: Any,
        workspace: Path,
        project_generation: Callable[[], int],
    ) -> None:
        self._node = node
        self._workspace = Path(workspace).resolve()
        self._project_generation = project_generation
        self._config_path = Path(
            os.environ.get('MOTION_COORDINATION_CONFIG')
            or self._workspace / 'config/motion_coordination.yaml'
        ).expanduser()
        self._config, _migrated = migrate_legacy_group_config(self._config_path)
        self._status: Dict[str, Any] = {}
        self._status_received_at = 0.0
        self._local_port = int(
            os.environ.get('MOTION_COORDINATION_LOCAL_PORT') or 8011
        )

    def snapshot(self) -> Dict[str, Any]:
        """Return runtime state plus a non-secret global configuration summary."""
        try:
            runtime = self._local_api('/status')
            self._status = copy.deepcopy(runtime)
            self._status_received_at = time.time()
            runtime_error = ''
        except (OSError, ValueError) as exc:
            runtime = copy.deepcopy(self._status)
            runtime_error = str(exc)
        received_at = self._status_received_at
        try:
            config = load_group_config(self._config_path)
            config_error = ''
            configured = self._config_summary(config)
        except (ImportError, OSError, ValueError) as exc:
            configured = {}
            config_error = str(exc)
        age = max(time.time() - received_at, 0.0) if received_at else None
        return {
            'success': not bool(config_error or runtime_error),
            'node_connected': age is not None and age <= 3.0,
            'status_age_sec': round(age, 3) if age is not None else None,
            'config': configured,
            'config_error': config_error or runtime_error,
            'runtime': runtime,
        }

    def session_summary(self) -> Dict[str, Any]:
        """연동을 쓰는가 · 지금 그룹에 들어가 있는가 · §6-133

        둘은 다른 값이다. `enabled` 는 설정 파일에 영구히 남고, `joined` 는
        조정 노드의 메모리에만 있어 재시작하면 `enabled` 를 따라 되돌아간다.

        스케줄은 `enabled` 를 보고 그룹으로 쏘는데, 실제 발화는 `joined` 가
        아니면 조정 노드가 거부한다 · 그 어긋남이 로그에만 남아 "스케줄이
        발화했는데 아무 일도 안 났다" 가 됐다 · §6-68 과 같은 모양이다.
        """
        snapshot = self.snapshot()
        runtime = snapshot.get('runtime') or {}
        runtime = runtime if isinstance(runtime, Mapping) else {}
        config = runtime.get('config') if isinstance(runtime.get('config'), Mapping) else {}
        return {
            'enabled': bool(config.get('enabled', False)),
            'joined': bool(runtime.get('joined', False)),
            'node_connected': bool(snapshot.get('node_connected')),
        }

    def local_execution_blocker(self) -> str:
        """Return why a local motion action conflicts with upper ownership."""
        runtime = self.snapshot().get('runtime') or {}
        execution = runtime.get('execution') if isinstance(runtime, Mapping) else {}
        connected = self._status_received_at and time.time() - self._status_received_at <= 3.0
        # 「그룹 실행 중」 판단의 주인은 `motion_common.run_state` 다 · §6-145
        if connected and run_state.group_is_active(dict(execution or {})):
            return '그룹 재생 중이라 단독 재생을 할 수 없습니다'
        return ''

    def update_settings(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        """Save project-independent DDS group settings and restart the node.

        **모션이 도는 중에는 받지 않는다** · §6-163

        이 저장은 끝에서 **연동 서비스를 재시작한다** · 도는 중에 재시작하면
        이 PC 가 그룹에서 사라지고, 남은 PC 들은 참가 PC 가 죽은 것으로 보아
        `GROUP_PARTICIPANT_FAILURE` 로 **세 대가 통째로** 선다 · 명단에서 PC
        하나 빼려던 일이 공연을 멈춘다.

        연동 탈퇴도 같은 규칙이다 · 도는 중에는 못 나간다 (§6-164) ·
        설정 저장만 아무것도 안 보고 있었다 · 같은 규칙을 준다 ·
        「그룹이 도는가」의 판정은 `run_state` 가 한다 (§6-145).
        """
        if not isinstance(payload, Mapping):
            raise ValueError('연동 설정 요청은 객체여야 합니다')
        running = self.local_execution_blocker()
        if running:
            raise ValueError(
                '그룹 재생 중에는 연동 설정을 바꿀 수 없습니다. '
                '먼저 정지한 뒤 바꾸세요'
            )
        # `joined` · 「그룹 참여」 스위치가 설정이 꺼진 PC 를 켤 때 설정과 참가를 한 번에 (83)
        allowed = {'enabled', 'joined', 'group_id', 'dds_domain_id', 'display_name', 'is_master', 'required_peers'}
        if set(payload).difference(allowed):
            raise ValueError('허용되지 않은 연동 설정 항목이 있습니다')
        for key in ('enabled', 'joined'):
            if key in payload and not isinstance(payload[key], bool):
                raise ValueError(f'{key}는 true 또는 false여야 합니다')
        current = load_group_config(self._config_path)
        config = replace(
            current,
            enabled=bool(payload.get('enabled', current.enabled)),
            joined=bool(payload.get('joined', current.joined)),
            is_master=bool(payload.get('is_master', current.is_master)),
            required_peers=tuple(str(x).strip() for x in payload.get('required_peers', current.required_peers) if str(x).strip()),
            group_id=str(payload.get('group_id', current.group_id)).strip(),
            dds_domain_id=int(payload.get('dds_domain_id', current.dds_domain_id)),
            display_name=(
                str(payload.get('display_name', current.display_name)).strip()
                or current.pc_id
            ),
        )
        # Validate the complete value through the canonical loader before use.
        save_group_config(self._config_path, config)
        config = load_group_config(self._config_path)
        restart = self._restart_coordination_service()
        if not restart['service_installed']:
            return {
                'success': True,
                'saved': True,
                'message': f'설정 저장 완료 (수동 재시작 필요: {restart["message"]})',
                'config': self._config_summary(config),
            }
        if not restart['restart_pending']:
            return {
                'success': False,
                'saved': True,
                'message': restart['message'],
                'config': self._config_summary(config),
            }
        return {
            'success': True,
            'saved': True,
            'restart_pending': True,
            'message': 'DDS 그룹 설정을 저장하고 PC 연동 서비스 재시작을 요청했습니다',
            'config': self._config_summary(config),
        }

    @staticmethod
    def _restart_coordination_service() -> Dict[str, Any]:
        service = str(
            os.environ.get('MOTION_COORDINATION_SERVICE_UNIT') or ''
        ).strip()
        unit_path = Path.home() / '.config/systemd/user/motion-coordination.service'
        if service != 'motion-coordination.service' or not unit_path.is_file():
            return {
                'service_installed': False,
                'restart_pending': False,
                'message': 'PC 연동 자동실행 서비스가 설치되지 않았습니다',
            }
        completed = subprocess.run(
            ['/usr/bin/systemctl', '--user', 'restart', '--no-block', service],
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            return {
                'service_installed': True,
                'restart_pending': False,
                'message': detail or 'PC 연동 서비스 재시작 요청 실패',
            }
        return {
            'service_installed': True,
            'restart_pending': True,
            'message': 'PC 연동 서비스 재시작 요청 완료',
        }

    def request_control(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        """Send one manual DDS group operation through the local ROS adapter."""
        if not isinstance(payload, Mapping):
            raise ValueError('연동 실행 요청은 객체여야 합니다')
        command = str(payload.get('command') or '').strip()
        allowed = {
            'join', 'leave', 'start_group', 'stop_after_cycle', 'stop_now',
            'acknowledge_group_error', 'initialize_group',
        }
        if command not in allowed:
            raise ValueError('지원하지 않는 DDS 그룹 실행 요청입니다')
        if command in {'start_group', 'initialize_group'}:
            off = run_mode_gate.motion_command_block_reason(self._node)
            if off:
                return {'success': False, 'message': off}
            # 스케줄 모드에서 사람이 누른 그룹 시작은 막는다 · 스케줄이 보낸 것만 · 수정 목록 70
            human = run_mode_gate.human_start_block_reason(self._node, dict(payload))
            if human:
                return {'success': False, 'message': human}
            repeat_error = repeat_policy.request_repeat_mode_error(payload.get('repeat_mode'))
            if repeat_error:
                return {'success': False, 'message': repeat_error}
            # 구간 재생 · 모든 PC · 스피커가 같은 시각부터 · 스케줄이 보낸 시작은 늘 통째로 · 2026-10-16
            try:
                segment = motion_segment.apply_to_payload(
                    payload, allowed=group_start_origin(payload) != 'schedule',
                )
            except ValueError as exc:
                return {'success': False, 'message': str(exc)}
        start_generation = int(self._project_generation())
        try:
            request = {'command': command}
            if command == 'stop_after_cycle':
                # 스케줄 끝이면 PC 마다 기준점 주차 → 서보 OFF · 수정 목록 36
                request['reason'] = str(payload.get('reason') or '')
            if command in {'start_group', 'initialize_group'}:
                request.update({
                    'run_mode': payload.get('run_mode', 'continuous'),
                    'repeat_mode': payload.get(
                        'repeat_mode', repeat_policy.DEFAULT_REPEAT_MODE,
                    ),
                    'dwell_sec': payload.get('dwell_sec', 0.0),
                    'target_cycle_count': payload.get('target_cycle_count', 0),
                    # 초기 위치 이동 시간 · 없으면 PC마다 조인트 매핑 값 · 2026-10-12
                    'initial_move_time_sec': payload.get('initial_move_time_sec') or 0.0,
                    # 회차 맞춤 / 각자 재생 · 수정 목록 35
                    'sync_mode': repeat_policy.normalize_group_sync_mode(
                        payload.get('sync_mode'),
                    ),
                    # 누가 시작했나 · 스케줄이 보낸 것만 `schedule_id` 가 있다 · 사람이 누른 그룹 재생은
                    # 수동 PC 도 넣는다 · 수정 목록 122
                    'started_by': group_start_origin(payload),
                    motion_segment.START_KEY: segment[motion_segment.START_KEY],
                    motion_segment.END_KEY: segment[motion_segment.END_KEY],
                })
            result = self._local_api('/control', request)
        except (OSError, ValueError) as exc:
            result = {'success': False, 'message': str(exc)}
        if int(self._project_generation()) != start_generation:
            return {
                'success': False, 'stale_project_generation': True,
                'message': '프로젝트 전환 전 시작한 그룹 실행 결과를 폐기했습니다',
            }
        return result

    def notify_planned_restart(self) -> Dict[str, Any]:
        """「프로그램 다시 시작」 직전 · 연동 노드에 「이 PC 빠짐」 을 알린다 · 수정 목록 123 · 145 ①

        브리지가 사라지는 동안 연동 노드가 그것을 고장(GROUP_PARTICIPANT_FAILURE 2등급)으로
        잠그지 않게 · 그룹이 돌면 이 PC 만 빠지고 나머지는 계속 · 답에 `still_coordinating`
        (이 PC 가 다른 PC 들의 그룹을 계속 진행) · 연동 노드가 없거나 답이 없어도 재시작은 그대로 간다.
        """
        try:
            return self._local_api('/control', {'command': 'planned_restart'})
        except (OSError, ValueError) as exc:
            return {'success': False, 'message': str(exc)}

    def notify_leaving(
        self, reason: str, *, timeout_sec: float = LEAVE_NOTICE_TIMEOUT_SEC,
    ) -> Dict[str, Any]:
        """웹 서비스가 내려간다(SIGTERM · SIGINT · systemd 다시 시작) · 「이 PC 빠짐」 · 수정 목록 145 ①

        내려가는 중이라 오래 기다리지 않는다 · 실패해도 종료는 그대로 간다 · 그때 연동 노드는
        「상태 수신 중단」 으로 보고 그룹을 세운다(잠그지 않음 · 145 ②).
        """
        try:
            return self._local_api(
                '/control', {'command': 'bridge_leaving', 'reason': str(reason or '')},
                timeout_sec=timeout_sec,
            )
        except (OSError, ValueError) as exc:
            return {'success': False, 'message': str(exc)}

    def _local_api(
        self, path: str, payload: Mapping[str, Any] | None = None,
        *, timeout_sec: float = 5.0,
    ) -> Dict[str, Any]:
        data = None
        method = 'GET'
        headers: Dict[str, str] = {}
        if payload is not None:
            data = json.dumps(dict(payload), separators=(',', ':')).encode('utf-8')
            method = 'POST'
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(
            f'http://127.0.0.1:{self._local_port}{path}',
            data=data, headers=headers, method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=float(timeout_sec)) as response:
                value = json.loads(response.read(64 * 1024).decode('utf-8'))
        except (urllib.error.URLError, OSError, UnicodeError, ValueError) as exc:
            raise OSError(f'DDS 그룹 연동 노드 응답 없음: {exc}') from exc
        if not isinstance(value, dict):
            raise ValueError('DDS 그룹 연동 노드 응답 형식 오류')
        return value

    @staticmethod
    def _config_summary(config: Any) -> Dict[str, Any]:
        return {
            'pc_id': config.pc_id,
            'display_name': config.display_name,
            'enabled': config.enabled,
            'is_master': config.is_master,
            'required_peers': list(config.required_peers),
            'group_id': config.group_id,
            'dds_domain_id': config.dds_domain_id,
            'heartbeat_sec': config.heartbeat_sec,
            'warning_timeout_sec': config.warning_timeout_sec,
            'peer_timeout_sec': config.peer_timeout_sec,
            'start_lead_sec': config.start_lead_sec,
            'schedule_ack_margin_sec': config.schedule_ack_margin_sec,
            'max_trigger_sync_uncertainty_ms': (
                config.max_trigger_sync_uncertainty_ms
            ),
            'trigger_sync_samples': config.trigger_sync_samples,
            'prepare_timeout_sec': config.prepare_timeout_sec,
            'trigger_report_timeout_sec': config.trigger_report_timeout_sec,
        }


def readiness_failure_text(context: Mapping[str, Any]) -> str:
    """준비가 안 된 **진짜 이유**를 한 줄로 · §6-297

    실행 컨텍스트는 노드마다 실패 사유를 들고 있다 · 그런데 위로 올라가는 것은
    「모터 관리 노드 상태 확인 대기 중」 같은 뭉뚱그린 말 하나뿐이었다 ·
    정작 아래에는 「motor_manager_node 시작 후 첫 모터 상태를 기다리는 중」이
    적혀 있었는데 아무도 그것을 보지 못했다.

    아는 쪽이 말하게 한다 · 뭉뚱그린 말 뒤에 노드 이름과 사유를 붙인다.
    """
    summary = str(context.get('message') or '적용 대기 중')
    failures = context.get('failures')
    if not isinstance(failures, Mapping) or not failures:
        return summary
    detail = ' · '.join(
        f'{name}: {str(reason)[:120]}'
        for name, reason in sorted(failures.items())
        if str(reason or '').strip()
    )
    return f'{summary} · {detail}' if detail else summary


def group_start_origin(payload: Mapping[str, Any]) -> str:
    """그룹 시작을 누가 보냈나 · `schedule_id` 가 있으면 스케줄 · 아니면 사람 · 수정 목록 122"""
    return 'schedule' if str(payload.get('schedule_id') or '').strip() else 'human'


#: 사람 조작 판정 · 연동 노드(선택 · 하트비트 · 마스터 자신)와 같이 쓴다 · 수정 목록 122 (나) · 136
human_operation_reason = run_state.human_operation_reason


def stop_now_not_ours(bridge: Any, execution_id: str) -> str:
    """그룹 즉시 정지가 이 PC 가 돌지 않는 실행 것인가 · 그러면 이유 · 수정 목록 136

    전에는 실행 ID 를 안 보고 무조건 세웠다 · 그룹에 안 들어간 PC(단독 재생 중이라 빠진 마스터 ·
    조그 중인 PC)에 그 그룹의 정지가 닿으면 단독 재생 · 조그가 멈췄다(실물 V-4 · V-5) ·
    **이 PC 가 단독 재생 · 사람 조작 중이고 그 실행을 돌지 않을 때만** 무시한다 · 쉬는 중이거나
    그룹 세션이 있으면(다른 번호여도 · 준비가 막 끝나 상태가 늦게 온 경우) 전처럼 세운다.
    """
    execution_id = str(execution_id or '')
    if not execution_id:
        return ''
    run = _locked_copy(bridge, '_motion_run_status', '_motion_run_lock')
    if run.get('group_execution'):
        return ''
    busy = human_operation_reason(run, _locked_copy(bridge, '_safety_status', '_safety_status_lock'))
    if not busy:
        return ''
    return f'이 PC 는 그룹 실행 {execution_id} 에 없음 · {busy} · 정지하지 않음'


def _locked_copy(bridge: Any, value_name: str, lock_name: str) -> Dict[str, Any]:
    lock = getattr(bridge, lock_name, None)
    if lock is None:
        value = getattr(bridge, value_name, None)
    else:
        with lock:
            value = getattr(bridge, value_name, None)
    return dict(value) if isinstance(value, Mapping) else {}


#: 부르는 쪽이 기다려 주는 시간에서 **떼어 둘 몫** · §6-297
#:
#: 답이 돌아가는 데도 시간이 든다 · 안쪽이 바깥 예산을 꽉 채우면, 일은 끝났는데
#: 답이 늦어 「응답 없음」이 된다.
READINESS_MARGIN_SEC = 1.0

#: 예산을 못 받았을 때 · 옛 호출과 시험을 위한 값
DEFAULT_READINESS_BUDGET_SEC = 4.0


def local_motion_readiness(
    bridge: Any, payload: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """이 PC 가 지금 그룹 모션을 시작할 수 있는가 · 못 하면 **이유를 적어** 답한다.

    **안쪽 일은 바깥이 기다려 주는 시간보다 짧아야 한다** · §6-297

    전에는 부르는 쪽이 4초를 기다리는데 여기서 최대 10초를 썼다 · 그러면 모터가
    멀쩡해도 「로컬 Web Bridge 응답 없음: timed out」이 뜬다 · 실측으로 준비
    확인이 10.2초가 걸렸고, 화면에는 브리지가 죽은 것처럼 보였다 · 정작 원인은
    모터 피드백이 끊긴 것이었는데 그 말은 어디에도 안 실렸다.

    이제 부르는 쪽이 `budget_sec` 로 자기 예산을 알려 준다 · 여기서는 그보다
    한 칸 짧게 쓴다 · 그래서 **시간이 다 되면 「왜 안 되는지」가 돌아간다**.
    """
    request = payload if isinstance(payload, Mapping) else {}
    try:
        budget = float(request.get('budget_sec') or DEFAULT_READINESS_BUDGET_SEC)
    except (TypeError, ValueError):
        budget = DEFAULT_READINESS_BUDGET_SEC
    timeout_sec = max(0.5, budget - READINESS_MARGIN_SEC)
    # 사람이 이 PC 를 만지는 중이면 그룹에 안 들어간다 · 수정 목록 122 (나)
    busy = human_operation_reason(
        _locked_copy(bridge, '_motion_run_status', '_motion_run_lock'),
        _locked_copy(bridge, '_safety_status', '_safety_status_lock'),
    )
    if busy:
        return {'success': False, 'message': busy}
    # A group prepare must not race the periodic project-context reconciler.
    # Apply and verify the context synchronously before reporting this PC ready.
    reconcile = getattr(
        getattr(bridge, '_execution_context', None), 'reconcile_blocking', None
    )
    if callable(reconcile):
        context = reconcile(timeout_sec=timeout_sec)
    else:
        context = bridge._execution_context.reconcile()
    if not context.get('ready'):
        return {
            'success': False,
            'message': (
                '현재 프로젝트의 실행 준비가 끝나지 않았습니다: '
                + readiness_failure_text(context)
            ),
        }
    try:
        selection = _local_motion_selection(bridge)
    except ValueError as exc:
        return {'success': False, 'message': str(exc)}
    # 스케줄 끝에 끈 서보를 켜고 나서 본다 · 안 그러면 「서보가 꺼져 있습니다」 로
    # 이 PC 가 그룹에서 빠진다 · 수정 목록 36
    parked = getattr(bridge, 'schedule_end_start_blocker', None)
    if callable(parked):
        reason = parked({})
        if reason:
            return {'success': False, 'message': reason}
    # 구간 재생 · 이 PC 재생 목록 1번이 구간 시작보다 짧으면 여기서 거절 → 진행 PC 가 이 PC 를 빼고 간다 · 2026-10-16
    try:
        segment = motion_segment.apply_to_payload(request)
    except ValueError as exc:
        return {'success': False, 'message': str(exc)}
    return bridge.motion_run_check({
        **selection,
        'initial_move_time_sec': None,
        'run_mode': 'once',
        'request_source': 'network_readiness',
        motion_segment.START_KEY: segment[motion_segment.START_KEY],
        motion_segment.END_KEY: segment[motion_segment.END_KEY],
    })


def _group_initial_move_time(payload: Mapping[str, Any]) -> Optional[float]:
    try:
        value = float(payload.get('initial_move_time_sec') or 0.0)
    except (TypeError, ValueError):
        return None
    return value if value > 0.0 else None


def _group_segment(payload: Mapping[str, Any]) -> Dict[str, float]:
    """연동 노드가 넘긴 구간 · 틀린 값(옛 · 깨진 명령)은 통째로 · 검사는 진행 PC 에서 이미 했다"""
    try:
        start, end = motion_segment.parse(payload)
    except ValueError:
        start, end = 0.0, 0.0
    return motion_segment.fields(start, end)


def local_motion_control(bridge: Any, payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Execute one loopback-only high-level command through motion_run_manager."""
    command = str(payload.get('command') or '')
    if command in {'stop_motion', 'stop_initialize', 'stop_now'}:
        # 그 실행을 돌지 않는 PC 의 단독 재생 · 조그는 그대로 둔다 · 수정 목록 136
        ignored = stop_now_not_ours(bridge, str(payload.get('execution_id') or ''))
        if ignored:
            return {'success': True, 'ignored': True, 'message': ignored}
        return bridge.coordination_stop_now()
    if command in {'cancel_before_start', 'group_cancel'}:
        result = bridge.motion_group_cancel({
            'execution_id': str(payload.get('execution_id') or ''),
        })
        if (
            result.get('success') is False
            and '그룹 실행 세션이 일치하지 않습니다' in str(
                result.get('message') or ''
            )
        ):
            return {
                'success': True,
                'already_released': True,
                'message': '이미 정리된 그룹 실행 세션입니다',
            }
        return result
    if command == 'group_join_commit':
        # 도는 그룹에 복귀한 PC · 합류 확정 · 수정 목록 30-3
        return bridge.motion_group_join_commit({
            'execution_id': str(payload.get('execution_id') or ''),
            'cycle_number': payload.get('cycle_number'),
        })
    if command == 'group_note':
        # 연동 노드가 남기는 기록 · 지금은 뺀 PC · 수정 목록 30-2
        return bridge.record_coordination_note(
            str(payload.get('event_type') or 'group_note'),
            str(payload.get('message') or ''),
            {
                key: payload.get(key)
                for key in ('execution_id', 'excluded', 'participants')
                if key in payload
            },
        )
    if command == 'stop_after_cycle':
        result = bridge.motion_run_stop_after_cycle({'reason': payload.get('reason') or ''})
        if (
            result.get('success') is False
            and '활성 그룹 실행이 없습니다' in str(result.get('message') or '')
        ):
            return {
                'success': True,
                'already_completed': True,
                'message': '현재 그룹 회차가 이미 완료되어 다음 회차를 시작하지 않습니다',
            }
        return result
    try:
        selection = _local_motion_selection(bridge)
    except ValueError as exc:
        return {'success': False, 'message': str(exc)}
    request = {
        **selection,
        'initial_move_time_sec': None,
        'run_mode': 'once',
        'request_source': 'network_control',
        'network_operation_id': str(payload.get('network_operation_id') or ''),
    }
    if command in {'group_prepare', 'group_join'}:
        repeat_mode = str(payload.get('repeat_mode') or '').strip()
        dwell_sec = payload.get('dwell_sec')
        initialization_only = bool(payload.get('initialization_only'))
        run_mode = str(payload.get('run_mode') or 'once').strip().lower()
        if not repeat_mode:
            run_status = bridge.motion_run_status()
            automation = (
                (run_status.get('status') or {}).get('automation')
                if isinstance(run_status, Mapping) else {}
            )
            automation = automation if isinstance(automation, Mapping) else {}
            repeat_mode = repeat_policy.normalize_repeat_mode(
                automation.get('repeat_mode')
            )
            dwell_sec = float(automation.get('dwell_sec') or 0.0)
        request.update({
            'execution_id': str(payload.get('execution_id') or ''),
            'initialize_monotonic': payload.get('initialize_monotonic'),
            'group_execution': True,
            'initialization_only': initialization_only,
            'repeat_mode': repeat_mode,
            'dwell_sec': float(dwell_sec or 0.0),
            'sync_mode': repeat_policy.normalize_group_sync_mode(
                payload.get('sync_mode'),
            ),
            'target_cycle_count': int(payload.get('target_cycle_count') or 0),
            # 마스터 재생 화면에서 고른 이동 시간 · 0 이면 None(조인트 매핑 값) · 2026-10-12
            'initial_move_time_sec': _group_initial_move_time(payload),
            # 구간 재생 · 이 PC 재생 목록 1번을 같은 시각으로 자른다 · 0/0 = 통째로 · 2026-10-16
            **_group_segment(payload),
            # Direct repetition must use the same continuity validation as a
            # local continuous run. Reinitializing policies deliberately
            # bypass that check because every cycle returns to the start pose.
            'run_mode': 'once' if initialization_only else run_mode,
        })
        if command == 'group_join':
            # 도는 그룹에 복귀 · 계획만 만들고 서 있다가 합류 확정을 기다린다 · 30-3
            request.pop('initialize_monotonic', None)
            request['join_cycle_number'] = int(payload.get('join_cycle_number') or 0)
            if request['join_cycle_number'] < 1:
                return {'success': False, 'message': '복귀 회차 번호가 필요합니다'}
        return bridge.motion_group_prepare(request)
    if command == 'group_start_at':
        request.update({
            'execution_id': str(payload.get('execution_id') or ''),
            'cycle_number': payload.get('cycle_number'),
            'start_monotonic': payload.get('start_monotonic'),
            'group_execution': True,
        })
        return bridge.motion_group_start_at(request)
    if command == 'group_initialize_at':
        request.update({
            'execution_id': str(payload.get('execution_id') or ''),
            'cycle_number': payload.get('cycle_number'),
            'initialize_monotonic': payload.get('initialize_monotonic'),
            'group_execution': True,
        })
        return bridge.motion_group_initialize_at(request)
    return {'success': False, 'message': '지원하지 않는 로컬 연동 실행 명령입니다'}


def _local_motion_selection(bridge: Any) -> Dict[str, str]:
    project_id = bridge.project_repository.require_selected_project_id()
    try:
        project = bridge.project_repository.get_project(project_id).get('project') or {}
        active = project.get('active_files') or {}
        mapping_id = str(active.get('motion_axis_matching') or '').strip()
        if not mapping_id:
            raise ValueError('조인트 매핑을 선택하세요')
        mapping_path = bridge.project_repository.export_path(
            project_id, 'motion_axis_matching', mapping_id
        )
        mapping = yaml.safe_load(mapping_path.read_text(encoding='utf-8')) or {}
        motion_id = str(
            mapping.get('motion_file_id') if isinstance(mapping, dict) else ''
        ).strip()
        if not motion_id:
            raise ValueError('애니메이션을 재생 등록하세요')
        bridge.project_repository.export_path(project_id, 'motions', motion_id)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(f'재생 파일 확인 실패: {exc}') from exc
    return {'motion_file_id': motion_id, 'mapping_file_id': mapping_id}
