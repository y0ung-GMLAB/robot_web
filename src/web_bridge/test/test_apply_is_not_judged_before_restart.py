"""수정 목록 129 (실물 2026-10-13 20:15) · 「적용」 이 재시작을 요청하기 전에는 실행 검증을 하지 않는다

브리지의 0.2 s 작업 점검이 준비 중인 적용(phase preparing · prepared)을 옛 Motor Manager 의
「준비됨」 으로 보고 검증 → 실행 설정 경로가 아직 없어 실패로 닫았다 · 적용은 「진행 중인 모터 작업이
일치하지 않습니다」 로 끝났다.
"""

import time
from types import SimpleNamespace

import pytest

from motion_web_bridge import motor_config_rules
from motion_web_bridge.motor_runtime_service import MotorRuntimeService


class Runtime:
    def __init__(self, phase):
        now = time.time()
        self.operation = {
            'operation_id': 'op-1', 'type': 'motor_apply', 'status': 'running', 'phase': phase,
            'started_at': now - 0.1, 'deadline_at': now + 40.0, 'details': {},
        }
        self.finished = []

    def motor_operation_status(self):
        return dict(self.operation)

    def finish_motor_operation(self, operation_id, result, **kwargs):
        self.finished.append((operation_id, result, kwargs))
        return {**self.operation, 'status': result}


def _service(runtime):
    service = MotorRuntimeService.__new__(MotorRuntimeService)
    service.repository = SimpleNamespace(runtime=runtime)
    service.bridge = SimpleNamespace(_bridge_started_at=0.0)
    return service


@pytest.fixture
def readiness_fails(monkeypatch):
    calls = []

    def fake(*args, **kwargs):
        calls.append(args)
        return {'ready': False, 'failed': True, 'error': '검증할 Motor Manager 실행 설정 경로가 없습니다'}

    monkeypatch.setattr(motor_config_rules, 'motor_operation_runtime_readiness', fake)
    return calls


@pytest.mark.parametrize('phase', ['preparing', 'prepared'])
def test_an_apply_before_restart_is_left_alone_while_the_old_motor_program_runs(phase, readiness_fails):
    runtime = Runtime(phase)
    old_program = {'phase': 'ready'}
    fresh = {'last_motor_status_at': time.time()}     # 옛 Motor Manager 가 아직 상태를 보냄
    _service(runtime).reconcile_operation_status(old_program, fresh, {})
    assert runtime.finished == []
    assert readiness_fails == []


def test_after_the_restart_request_the_apply_is_judged_as_before(readiness_fails):
    runtime = Runtime('restart_requested')
    _service(runtime).reconcile_operation_status({'phase': 'ready'}, {'last_motor_status_at': time.time()}, {})
    assert readiness_fails and runtime.finished and runtime.finished[0][1] == 'failure'
