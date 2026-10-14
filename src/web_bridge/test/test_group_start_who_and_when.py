"""그룹 시작 · 누가 시작했나 · 사람 조작 중 PC · 시작 미루기 · 사람이 한 재시작 · 수정 목록 122·123·124

브리지 쪽 몫만 · rclpy 없이 돈다.

- 122 · 재생 화면에서 사람이 누른 그룹 시작은 `started_by: human` 으로 연동 노드에 간다 ·
  스케줄이 보낸 것(`schedule_id`)은 `schedule` · 사람 조작 중(조그 · 페이더 · 단독 재생)인
  PC 는 준비를 거절하고 이유를 남긴다.
- 123 · 「프로그램 다시 시작」 은 재시작 전에 연동 노드에 알린다 · 브리지가 사라진 것을 고장으로
  잠그지 않게.
- 124 · 스케줄 상태에 「지금 시작하면 안 되는 이유」 를 싣는다 · 부팅 직후 앱솔루트 확인 전에는
  스케줄이 시작을 미룬다.
"""

import threading
from types import SimpleNamespace

import pytest

from motion_web_bridge import run_mode_gate
from motion_web_bridge.coordination_bridge import (
    CoordinationWebBridge,
    group_start_origin,
    human_operation_reason,
    local_motion_readiness,
)
from motion_web_bridge.motor_config_service import MotorConfigService
from motion_web_bridge.schedule_service import ScheduleService


# --------------------------------------------------------------------------- #
# 122 · 누가 시작했나
# --------------------------------------------------------------------------- #

def test_who_started_it():
    assert group_start_origin({}) == 'human'
    assert group_start_origin({'schedule_id': ''}) == 'human'
    assert group_start_origin({'schedule_id': 's1'}) == 'schedule'


def _service(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(run_mode_gate, 'current_run_mode', lambda _node: mode)
    service = CoordinationWebBridge(SimpleNamespace(), tmp_path, lambda: 1)
    calls = []
    service._local_api = lambda path, payload=None: (
        calls.append((path, payload)) or {'success': True}
    )
    return service, calls


def test_a_human_group_start_says_so(tmp_path, monkeypatch):
    service, calls = _service(tmp_path, monkeypatch, 'manual')

    assert service.request_control({'command': 'start_group'})['success'] is True

    assert calls[0][1]['started_by'] == 'human'


def test_a_schedule_group_start_says_so(tmp_path, monkeypatch):
    service, calls = _service(tmp_path, monkeypatch, 'schedule')

    assert service.request_control({'command': 'start_group', 'schedule_id': 's1'})['success'] is True

    assert calls[0][1]['started_by'] == 'schedule'


# --------------------------------------------------------------------------- #
# 122 (나) · 사람 조작 중인 PC 는 그룹에 안 들어간다
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('run, safety, expected', [
    ({'state': 'running'}, {}, '사람 조작 중 · 단독 재생'),
    ({'state': 'initializing'}, {}, '사람 조작 중 · 단독 재생'),
    ({}, {'manual_activity_modes': ['jog']}, '사람 조작 중 · 조그 이동'),
    ({}, {'manual_activity_modes': ['action']}, '사람 조작 중 · 목표 위치 이동'),
    ({}, {'command_owner': 'stream'}, '사람 조작 중 · 페이더'),
])
def test_a_pc_a_person_is_operating_refuses_to_join(run, safety, expected):
    assert human_operation_reason(run, safety) == expected


@pytest.mark.parametrize('run, safety', [
    ({}, {}),
    ({'state': 'idle'}, {'command_owner': 'none'}),
    ({'state': 'stopped'}, {'manual_activity_modes': []}),
    ({'state': 'initialized'}, {'command_owner': 'playback'}),   # 초기 위치에서 대기 · 쉬는 중
    ({'state': 'running', 'group_execution': True}, {}),         # 그룹 재생은 사람 조작이 아니다
])
def test_a_resting_pc_joins(run, safety):
    assert human_operation_reason(run, safety) == ''


class _NeverAsked:
    def reconcile_blocking(self, timeout_sec):
        raise AssertionError('사람 조작 중이면 준비를 더 보지 않는다')


def test_readiness_refuses_while_a_person_jogs():
    bridge = SimpleNamespace(
        _execution_context=_NeverAsked(),
        _motion_run_lock=threading.Lock(), _motion_run_status={'state': 'idle'},
        _safety_status_lock=threading.Lock(), _safety_status={'manual_activity_modes': ['jog']},
    )

    result = local_motion_readiness(bridge, {'budget_sec': 6.0})

    assert result == {'success': False, 'message': '사람 조작 중 · 조그 이동'}


# --------------------------------------------------------------------------- #
# 123 · 사람이 누른 재시작은 연동 노드에 먼저 알린다
# --------------------------------------------------------------------------- #

def test_planned_restart_is_sent_to_the_coordination_node(tmp_path):
    service = CoordinationWebBridge(SimpleNamespace(), tmp_path, lambda: 1)
    calls = []
    service._local_api = lambda path, payload=None: (
        calls.append((path, payload)) or {'success': True}
    )

    assert service.notify_planned_restart()['success'] is True
    assert calls == [('/control', {'command': 'planned_restart'})]


def test_planned_restart_never_blocks_the_restart(tmp_path):
    service = CoordinationWebBridge(SimpleNamespace(), tmp_path, lambda: 1)

    def down(*_args, **_kwargs):
        raise OSError('DDS 그룹 연동 노드 응답 없음')

    service._local_api = down

    assert service.notify_planned_restart()['success'] is False


def test_program_restart_tells_the_coordination_node_first(monkeypatch):
    events = []
    bridge = SimpleNamespace(
        snapshot=lambda: {},
        cached_run_status=lambda: {'state': 'idle'},
        coordination=SimpleNamespace(
            notify_planned_restart=lambda: events.append('notify') or {'success': True},
            local_execution_blocker=lambda: '',
        ),
    )
    service = MotorConfigService.__new__(MotorConfigService)
    service.bridge = bridge
    service.project = SimpleNamespace(motor_job_running=lambda: False)
    service.clear_stopping_release_state = lambda: None
    monkeypatch.setenv('MOTION_CONTROL_SERVICE_UNIT', 'motion-control.service')
    monkeypatch.setenv('MOTION_MOTOR_SERVICE_UNIT', 'motion-motor.service')
    monkeypatch.setenv('MOTION_COORDINATION_SERVICE_UNIT', 'motion-coordination.service')
    from motion_web_bridge import motor_config_rules
    monkeypatch.setattr(
        motor_config_rules, 'schedule_managed_service_restart',
        lambda *services: events.append(('restart', services)),
    )

    result = service.restart_managed_program()

    assert result['success'] is True
    assert events[0] == 'notify', '재시작보다 먼저 알린다'
    assert events[1] == ('restart', ('motion-control.service', 'motion-coordination.service'))


# --------------------------------------------------------------------------- #
# 124 · 스케줄은 준비가 끝날 때까지 시작을 미룬다
# --------------------------------------------------------------------------- #

class _Store:
    current_project_id = 'p'
    mode = 'schedule'

    def load_project(self, _project_id):
        pass

    def list_schedules(self):
        return []


def _schedule_service(monkeypatch, blocker):
    from motion_web_bridge import schedule_service
    monkeypatch.setattr(
        schedule_service, 'resolve_master_role',
        lambda **_kwargs: SimpleNamespace(is_master=True, reason=''),
    )
    bridge = SimpleNamespace(
        project_repository=SimpleNamespace(
            selected_project_id=lambda: 'p', require_selected_project_id=lambda: 'p',
        ),
    )
    if blocker is not None:
        bridge.motor_action_blocker = blocker
    return ScheduleService(bridge, store=_Store())


def test_the_schedule_status_says_why_not_to_start_yet(monkeypatch):
    service = _schedule_service(
        monkeypatch, lambda: '앱솔루트 미확인 · 2번 모터 확인 불가',
    )
    assert service.status()['start_blocker'] == '앱솔루트 미확인 · 2번 모터 확인 불가'


def test_ready_means_an_empty_blocker(monkeypatch):
    assert _schedule_service(monkeypatch, lambda: '').status()['start_blocker'] == ''


def test_a_broken_reader_does_not_hold_the_schedule(monkeypatch):
    def explode():
        raise RuntimeError('상태 없음')

    assert _schedule_service(monkeypatch, explode).status()['start_blocker'] == ''
    assert _schedule_service(monkeypatch, None).status()['start_blocker'] == ''
