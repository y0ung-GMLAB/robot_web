"""재생 중 「프로그램 다시 시작」 · 묻고 · 멈추고 · 다시 시작 · 웹이 내려갈 때 연동에 알림 · 수정 목록 144 · 145 ①

실물 2026-10-14 11:35 floating4 (V-28 ③) · 그룹 연속 중 `POST /api/system/program/restart` → HTTP 400
「애니메이션이 동작 중(waiting)이라 프로젝트를 변경할 수 없습니다」 · 프로젝트를 바꾸는 일이 아닌데
프로젝트 변경 잠금에 걸렸고, 사람은 무엇을 해야 하는지 몰랐다.

rclpy 없이 돈다.
"""

import threading
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from motion_web_bridge import motor_config_rules
from motion_web_bridge.coordination_bridge import CoordinationWebBridge, LeaveNotice
from motion_web_bridge.motor_config_service import MotorConfigService
from motion_web_bridge.routes import system_routes

REPO = Path(__file__).resolve().parents[3]


class _Bridge:
    """재생 상태 · 정지 · 연동 창구만 가진 껍데기"""

    def __init__(self, state='idle', *, group='', notice=None, stops=True):
        self.events = []
        self.state = state
        self._group = group
        self._notice = notice if notice is not None else {'success': True}
        self._stops = stops
        self.coordination = SimpleNamespace(
            notify_planned_restart=self._notify,
            local_execution_blocker=lambda: self._group,
        )

    def _notify(self):
        self.events.append('notify')
        return dict(self._notice)

    def snapshot(self):
        return {}

    def settle_stopping_run_state(self, _message):
        return False

    def cached_run_status(self):
        return {'state': self.state}

    def request_safety_stop(self, emergency):
        self.events.append(('safety_stop', emergency))
        return {'success': True}

    def motion_run_stop(self):
        self.events.append('motion_run_stop')
        if self._stops:
            self.state = 'stopped'
        return {'success': True}


def _service(monkeypatch, bridge, *, motor_job=False):
    service = MotorConfigService.__new__(MotorConfigService)
    service.bridge = bridge
    service.project = SimpleNamespace(motor_job_running=lambda: motor_job)
    monkeypatch.setenv('MOTION_CONTROL_SERVICE_UNIT', 'motion-control.service')
    monkeypatch.setenv('MOTION_MOTOR_SERVICE_UNIT', 'motion-motor.service')
    monkeypatch.setenv('MOTION_COORDINATION_SERVICE_UNIT', 'motion-coordination.service')
    monkeypatch.setattr(
        motor_config_rules, 'schedule_managed_service_restart',
        lambda *services: bridge.events.append(('restart', services)),
    )
    return service


BOTH = ('restart', ('motion-control.service', 'motion-coordination.service'))


def test_idle_restarts_right_away(monkeypatch):
    bridge = _Bridge('idle')
    result = _service(monkeypatch, bridge).restart_managed_program({})

    assert result['success'] is True
    assert result['stopped_playback'] is False
    assert bridge.events == ['notify', BOTH]


def test_playing_is_refused_with_a_clear_reason_and_a_flag(monkeypatch):
    for state in ('running', 'initializing', 'waiting'):
        bridge = _Bridge(state)
        result = _service(monkeypatch, bridge).restart_managed_program({})

        assert result['success'] is False, state
        assert result['needs_stop'] is True
        assert result['run_state'] == state
        assert result['message'] == '재생 중입니다 · 정지하고 다시 시작하려면 확인하세요'
        assert '프로젝트' not in result['message']
        assert bridge.events == [], '묻기 전에는 아무것도 안 한다(알림 · 정지 · 재시작 없음)'


def test_a_group_run_still_preparing_counts_as_playing(monkeypatch):
    """그룹 준비 단계 · 이 PC 로컬 재생은 아직 서 있다 · 그래도 묻는다"""
    bridge = _Bridge('idle', group='그룹 재생 중이라 단독 재생을 할 수 없습니다')
    result = _service(monkeypatch, bridge).restart_managed_program({})
    assert result['needs_stop'] is True
    assert result['run_state'] == 'group'


def test_a_group_initial_move_waiting_for_start_counts_as_playing(monkeypatch):
    bridge = _Bridge('initialized')
    bridge.cached_run_status = lambda: {'state': 'initialized', 'group_execution': True}
    result = _service(monkeypatch, bridge).restart_managed_program({})
    assert result['needs_stop'] is True


def test_stop_first_tells_the_group_then_stops_then_restarts(monkeypatch):
    bridge = _Bridge('running')
    result = _service(monkeypatch, bridge).restart_managed_program({'stop_first': True})

    assert result['success'] is True
    assert result['stopped_playback'] is True
    # 연동에 먼저 알린다(이 PC 만 빠짐) → 「정지」 버튼과 같은 정지(서보 유지 · emergency=False) → 재시작
    assert bridge.events == [
        'notify', ('safety_stop', False), 'motion_run_stop', BOTH,
    ]
    assert '재생을 정지했습니다' in result['message']


def test_a_master_still_coordinating_others_keeps_its_coordination_service(monkeypatch):
    bridge = _Bridge('running', notice={'success': True, 'still_coordinating': True})
    result = _service(monkeypatch, bridge).restart_managed_program({'stop_first': True})

    assert result['success'] is True
    assert bridge.events[-1] == ('restart', ('motion-control.service',))
    assert '연동 서비스는 다른 PC 그룹을 진행 중이라 다시 시작하지 않음' in result['message']


def test_a_master_that_only_coordinates_has_nothing_local_to_stop(monkeypatch):
    """바빠서 빠진 마스터 · 로컬은 쉼 · 그룹은 돈다 · 묻고 · 알리고 · 로컬 정지 없이 웹만 다시 시작"""
    bridge = _Bridge(
        'idle', group='그룹 재생 중이라 단독 재생을 할 수 없습니다',
        notice={'success': True, 'still_coordinating': True},
    )
    service = _service(monkeypatch, bridge)
    assert service.restart_managed_program({})['needs_stop'] is True

    result = service.restart_managed_program({'stop_first': True})

    assert result['success'] is True
    assert result['stopped_playback'] is False
    assert bridge.events == ['notify', ('restart', ('motion-control.service',))]
    assert '재생을 정지했습니다' not in result['message']


def test_the_wait_for_the_stop_is_bounded(monkeypatch):
    bridge = _Bridge('running', stops=False)
    service = _service(monkeypatch, bridge)
    service.RESTART_STOP_WAIT_SEC = 0.2

    result = service.restart_managed_program({'stop_first': True})

    assert result['success'] is True
    assert bridge.events[-1] == BOTH, '정지를 확인 못 해도 다시 시작은 간다'
    assert '0.2 s 안에 정지 확인 못 함(running)' in result['message']


def test_only_a_literal_true_means_stop_first(monkeypatch):
    bridge = _Bridge('running')
    result = _service(monkeypatch, bridge).restart_managed_program({'stop_first': 'yes'})
    assert result['needs_stop'] is True


def test_a_motor_job_in_progress_is_refused_in_plain_words(monkeypatch):
    bridge = _Bridge('idle')
    result = _service(monkeypatch, bridge, motor_job=True).restart_managed_program({'stop_first': True})

    assert result['success'] is False
    assert result['message'] == '모터 설정·검색·재시작 작업이 진행 중입니다 · 끝난 뒤 다시 시작하세요'
    assert 'needs_stop' not in result
    assert bridge.events == []


# --------------------------------------------------------------------------- #
# 길목 · 프로젝트 변경 잠금 밖 · 몸통 그대로 넘긴다
# --------------------------------------------------------------------------- #

def _client(monkeypatch, tmp_path, restart):
    monkeypatch.setattr(system_routes, 'get_package_share_directory', lambda _name: str(tmp_path))
    monkeypatch.setenv('MOTION_WORKSPACE', str(REPO))
    app = FastAPI()
    bridge = SimpleNamespace(motor_config=SimpleNamespace(restart_managed_program=restart))
    system_routes.register_system_routes(
        app, bridge=bridge,
        project_call=lambda *_args: (_ for _ in ()).throw(AssertionError('프로젝트 변경 잠금을 지나면 안 됨')),
    )
    return TestClient(app)


def test_the_route_passes_the_body_and_keeps_the_refusal_readable(monkeypatch, tmp_path):
    seen = []

    def restart(body):
        seen.append(body)
        if body.get('stop_first') is True:
            return {'success': True, 'message': '상위 프로그램 재시작을 시작했습니다'}
        return {'success': False, 'needs_stop': True, 'message': '재생 중입니다 · 정지하고 다시 시작하려면 확인하세요'}

    client = _client(monkeypatch, tmp_path, restart)

    first = client.post('/api/system/program/restart', json={})
    assert first.status_code == 200
    assert first.json()['needs_stop'] is True
    second = client.post('/api/system/program/restart', json={'stop_first': True})
    assert second.json()['success'] is True
    empty = client.post('/api/system/program/restart')         # 옛 화면 · 몸통 없음
    assert empty.status_code == 200
    assert seen == [{}, {'stop_first': True}, {}]


# --------------------------------------------------------------------------- #
# 145 ① · 웹 서비스가 내려갈 때 연동 노드에 「이 PC 빠짐」
# --------------------------------------------------------------------------- #

def test_leaving_is_sent_to_the_coordination_node_with_a_short_wait(tmp_path):
    service = CoordinationWebBridge(SimpleNamespace(), tmp_path, lambda: 1)
    calls = []
    service._local_api = lambda path, payload=None, *, timeout_sec=5.0: (
        calls.append((path, payload, timeout_sec)) or {'success': True}
    )

    assert service.notify_leaving('웹 서비스 다시 시작')['success'] is True
    assert calls == [('/control', {'command': 'bridge_leaving', 'reason': '웹 서비스 다시 시작'}, 1.5)]


def test_leaving_never_blocks_the_shutdown(tmp_path):
    service = CoordinationWebBridge(SimpleNamespace(), tmp_path, lambda: 1)

    def down(*_args, **_kwargs):
        raise OSError('DDS 그룹 연동 노드 응답 없음')

    service._local_api = down
    assert service.notify_leaving('웹 서비스 다시 시작')['success'] is False


def test_the_leave_notice_goes_once_however_often_the_signal_comes():
    sent = []
    gate = threading.Event()

    def send():
        sent.append('leave')
        gate.wait(1.0)
        return {'success': True}

    notice = LeaveNotice(send)
    notice.send()          # SIGINT (systemd)
    notice.send()          # SIGINT (ros2 launch 가 넘김)
    gate.set()
    notice.send()          # 종료 끝
    notice.wait(1.0)

    assert sent == ['leave']
    assert notice.result == {'success': True}


def test_a_failing_leave_notice_is_swallowed():
    def send():
        raise RuntimeError('연동 노드 없음')

    notice = LeaveNotice(send)
    notice.send()
    notice.wait(1.0)
    assert notice.result['success'] is False


def test_the_bridge_sends_the_notice_on_the_exit_signal():
    """uvicorn 이 신호마다 부르는 `handle_exit` 에서 먼저 알린다 · 종료 끝에서 한 번 더(한 번만 감)"""
    text = (REPO / 'src/web_bridge/motion_web_bridge/bridge_node.py').read_text(encoding='utf-8')
    start = text.index('class _LeaveNoticeServer(uvicorn.Server):')
    body = text[start:text.index('\ndef main(', start)]
    assert 'def handle_exit(self, sig, frame)' in body
    assert body.index('self._on_exit()') < body.index('super().handle_exit(sig, frame)')
    main = text[text.index('\ndef main('):]
    assert '_LeaveNoticeServer(config, leave_notice.send).run()' in main
    assert main.index('leave_notice.wait()') < main.index('bridge.destroy_node()')
