"""다이나믹셀 토크 켜기·끄기·재부팅 라우트 · 수정 목록 24 (2026-10-06)

전에는 다이나믹셀을 화면에서 되살릴 길이 없었다(전원 재투입뿐) · 한 모터씩 보낸다.
"""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from motion_web_bridge.routes.motor_routes import register_motor_routes


def _client():
    calls = []

    def dynamixel_torque_control(action, axes=None):
        calls.append((action, axes))
        return {'success': True, 'message': f'{action} sent'}

    bridge = SimpleNamespace(manual=SimpleNamespace(dynamixel_torque_control=dynamixel_torque_control))
    app = FastAPI()
    register_motor_routes(app, bridge, project_call=lambda *args, **kwargs: None)
    return TestClient(app), calls


def test_reboot_goes_to_the_one_motor_named():
    client, calls = _client()

    response = client.post('/api/motion-test/dynamixel/control', json={'action': 'reboot', 'axis': 3})

    assert response.status_code == 200
    assert response.json()['success'] is True
    assert calls == [('reboot', [3])]


def test_without_an_axis_nothing_is_sent():
    """축이 없으면 「감지된 전부」 가 되므로 화면 라우트에서는 막는다"""
    client, calls = _client()

    response = client.post('/api/motion-test/dynamixel/control', json={'action': 'reboot'})

    assert response.json() == {'success': False, 'message': 'axis is required'}
    assert calls == []


def _servo_client(success=True):
    """사람이 서보 · 토크를 켜면 운영 종료가 끈 축 기록에서 뺀다 · 수정 목록 198"""
    forgot = []

    def control(*args, **_kwargs):
        return {'success': success}

    bridge = SimpleNamespace(
        manual=SimpleNamespace(ac_servo_control=control, dynamixel_torque_control=control),
        schedule_end=SimpleNamespace(forget_powered_off=lambda kind, axes: forgot.append((kind, axes))),
    )
    app = FastAPI()
    register_motor_routes(app, bridge, project_call=lambda *args, **kwargs: None)
    return TestClient(app), forgot


def test_a_person_turning_a_servo_on_clears_it_from_the_schedule_end_record():
    client, forgot = _servo_client()
    client.post('/api/motion-test/ac-servo/control', json={'action': 'servo_on', 'axis': 2})
    client.post('/api/motion-test/ac-servo/control', json={'action': 'servo_on', 'scope': 'all'})
    client.post('/api/motion-test/ac-servo/control', json={'action': 'servo_off', 'axis': 2})
    client.post('/api/motion-test/dynamixel/control', json={'action': 'torque_on', 'axis': 5})
    assert forgot == [('ac_servo', [2]), ('ac_servo', None), ('dynamixel', [5])], '끄기는 기록을 건드리지 않는다'


def test_a_failed_servo_on_keeps_the_schedule_end_record():
    client, forgot = _servo_client(success=False)
    client.post('/api/motion-test/ac-servo/control', json={'action': 'servo_on', 'axis': 2})
    assert forgot == []
