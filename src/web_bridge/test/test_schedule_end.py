"""스케줄 끝 · 기준점 주차 → 서보 OFF · 다음 시작 전 다시 켜기 · 수정 목록 36 (2026-10-06)"""

import json
import time
from types import SimpleNamespace

import pytest

from motion_web_bridge.schedule_end import ScheduleEndService, idle_park_skip, mode_skip, motor_turns_off_at_end


class _Clock:
    def __init__(self):
        self.now = 0.0

    def sleep(self, seconds):
        self.now += seconds

    def monotonic(self):
        return self.now


def _bridge(tmp_path, *, states, end_action='park_servo_off', flags=None, alarm=0,
            init_ok=True, motors=None):
    runtime = tmp_path / 'motion_projects' / 'p1' / 'runtime'
    runtime.mkdir(parents=True)
    (runtime / 'motion_automation.json').write_text(
        json.dumps({'schedule_end_action': end_action}), encoding='utf-8',
    )
    calls = []
    sequence = list(states)
    current = {'state': sequence[0], 'phase_started_at': 0.0}

    def motion_run_status():
        if len(sequence) > 1:
            state = sequence.pop(0)
            started = time.time() + 5 if state in ('initializing', 'initialized') else 0.0
            current.update({'state': state, 'phase_started_at': started})
        else:
            current['state'] = sequence[0]
            if sequence[0] in ('initializing', 'initialized'):
                current['phase_started_at'] = time.time() + 5
        return {'status': dict(current)}

    motors = motors if motors is not None else [
        {'controller_index': 0, 'state': 'detected', 'motor_type': 'ac_servo', 'servo_on': False},
        {'controller_index': 1, 'state': 'detected', 'motor_type': 'ac_servo', 'servo_on': False},
        {'controller_index': 2, 'state': 'detected', 'motor_type': 'dynamixel', 'transport': 'serial'},
    ]
    registry = [
        {'axis': axis, 'config': ({'schedule_end_servo_off': False} if flag is False else {})}
        for axis, flag in (flags or {}).items()
    ]

    def ac_servo_control(action, axis, scope):
        calls.append(('ac', action, axis))
        if action == 'servo_on':
            for motor in motors:
                if motor['controller_index'] == axis:
                    motor['servo_on'] = True
        return {'success': True}

    def dynamixel_torque_control(action, axes=None):
        calls.append(('dxl', action, tuple(axes or ())))
        return {'success': True}

    def motion_run_initialize(payload):
        calls.append(('initialize', payload.get('initial_mode_override'), payload.get('initial_move_time_sec')))
        return {'success': init_ok, 'message': '' if init_ok else '오프 모드'}

    bridge = SimpleNamespace(
        workspace_root=tmp_path,
        project_repository=SimpleNamespace(selected_project_id=lambda: 'p1'),
        motion_run_status=motion_run_status,
        coordination_execution_blocker=lambda: '',
        _safety_status={'servo_alarm_grade': alarm},
        _with_active_project_files=lambda payload: {**payload, 'motion_file_id': 'a.json', 'mapping_file_id': 'm.yaml'},
        motion_run_initialize=motion_run_initialize,
        _manual=SimpleNamespace(
            ac_servo_control=ac_servo_control,
            dynamixel_torque_control=dynamixel_torque_control,
        ),
        _motor_config=SimpleNamespace(load=lambda: {'registry': {'motors': registry}}),
        motion_state=lambda: {'motors': motors},
        get_logger=lambda: SimpleNamespace(info=lambda _m: None, warn=lambda _m: None),
    )
    return bridge, calls, runtime


def _service(bridge, run_mode=None):
    clock = _Clock()
    return ScheduleEndService(
        bridge,
        fill_active_files=bridge._with_active_project_files,
        ac_servo_control=bridge._manual.ac_servo_control,
        dynamixel_torque_control=bridge._manual.dynamixel_torque_control,
        load_motor_registry=lambda: bridge._motor_config.load().get('registry') or {},
        alarm_grade=lambda: bridge._safety_status.get('servo_alarm_grade'),
        run_mode=run_mode,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )


def test_finish_cycle_then_park_then_power_off_only_flagged_motors(tmp_path):
    bridge, calls, runtime = _bridge(
        tmp_path,
        states=['running', 'running', 'completed', 'initializing', 'initialized'],
        flags={1: False},   # 1번 모터는 켠 채 둔다
    )
    service = _service(bridge)

    assert service._park_and_power_off() == ''

    assert calls == [
        ('initialize', 'reference', 10.0),
        ('ac', 'servo_off', 0),
        ('dxl', 'torque_off', (2,)),
    ]
    record = json.loads((runtime / 'schedule_end_state.json').read_text(encoding='utf-8'))
    assert record['ac_servo'] == [0] and record['dynamixel'] == [2]
    status = service.status()
    assert status['state'] == 'done'
    assert '켠 채 둠(모터 설정) 1번' in status['message']


@pytest.mark.parametrize('kwargs, reason', [
    ({'states': ['running', 'error']}, '오류'),
    ({'states': ['completed'], 'alarm': 2}, '서보 알람'),
    ({'states': ['completed'], 'init_ok': False}, '기준점 이동 거절'),
    ({'states': ['completed', 'initializing', 'error']}, '끝나지 않음'),
])
def test_no_servo_off_when_parking_did_not_succeed(tmp_path, kwargs, reason):
    bridge, calls, runtime = _bridge(tmp_path, **kwargs)

    error = _service(bridge)._park_and_power_off()

    assert reason in error
    assert not any(call[0] in ('ac', 'dxl') for call in calls)
    assert not (runtime / 'schedule_end_state.json').exists()


def test_stale_initialized_state_is_not_taken_as_arrival(tmp_path):
    # 보내기 전부터 남아 있던 「초기 위치 완료」(옛 시각) 는 도달로 치지 않는다
    bridge, calls, _runtime = _bridge(tmp_path, states=['initialized'])
    bridge.motion_run_status = lambda: {'status': {'state': 'initialized', 'phase_started_at': 1.0}}

    error = _service(bridge)._park_and_power_off()

    assert error == '기준점 도달 확인 시간 초과'
    assert not any(call[0] == 'ac' for call in calls)


def test_hold_setting_keeps_the_old_behaviour(tmp_path):
    bridge, calls, _runtime = _bridge(tmp_path, states=['running'], end_action='hold')

    status = _service(bridge).begin()

    assert status['state'] == 'skipped'
    assert calls == []


def test_next_start_turns_on_only_what_schedule_end_turned_off(tmp_path):
    bridge, calls, runtime = _bridge(tmp_path, states=['idle'])
    (runtime / 'schedule_end_state.json').write_text(
        json.dumps({'ac_servo': [0], 'dynamixel': [2]}), encoding='utf-8',
    )
    service = _service(bridge)

    assert service.start_blocker() == ''

    assert calls == [('ac', 'servo_on', 0), ('dxl', 'torque_on', (2,))]
    assert not (runtime / 'schedule_end_state.json').exists()
    # 한 번 켰으면 다음 시작은 아무것도 안 한다
    assert service.start_blocker() == '' and len(calls) == 2


def test_start_is_refused_while_parking(tmp_path):
    bridge, _calls, _runtime = _bridge(tmp_path, states=['running'])
    service = _service(bridge)
    service._set('parking', '기준점 이동 중')

    assert '운영 종료 동작' in service.start_blocker()


def test_motor_flag_defaults_to_power_off():
    assert motor_turns_off_at_end({}) is True
    assert motor_turns_off_at_end({'config': {}}) is True
    assert motor_turns_off_at_end({'config': {'schedule_end_servo_off': False}}) is False


# --------------------------------------------------------------------------- #
# 구간 끝에 멈춰 있던 로봇 · 사용자 2026-10-13
# --------------------------------------------------------------------------- #

def _on(axis, motor_type='ac_servo', servo_on=True):
    return {'controller_index': axis, 'state': 'detected', 'motor_type': motor_type, 'servo_on': servo_on}


def test_idle_park_needs_servos_on_no_alarm_and_a_motor_to_turn_off():
    assert idle_park_skip([_on(0), _on(1)], {}, 0) is None
    assert idle_park_skip([_on(0)], {}, 2)[0] == 'failed', '알람이면 주차하지 않는다'
    assert idle_park_skip([_on(0), _on(1)], {0: False, 1: False}, 0)[0] == 'skipped', '끌 모터가 없다(모터 설정)'
    assert idle_park_skip([_on(0, servo_on=False), _on(1, servo_on=False)], {}, 0)[0] == 'skipped', '이미 꺼짐'
    state, message = idle_park_skip([_on(0), _on(1, servo_on=False)], {}, 0)
    assert state == 'failed' and '1번' in message, '억지로 켜지 않는다'
    assert idle_park_skip([_on(0), _on(1, servo_on=False)], {1: False}, 0) is None, '켠 채 둘 모터는 안 본다'


def test_only_a_schedule_mode_pc_parks():
    assert mode_skip(None) is None, '모드를 안 읽는 배선(옛 동작)'
    assert mode_skip('schedule') is None
    assert mode_skip('manual')[0] == 'skipped'
    assert mode_skip('off')[0] == 'skipped'
    assert mode_skip('')[0] == 'failed', '못 읽으면 움직이지 않는다'


def test_a_stopped_robot_is_parked_and_powered_off(tmp_path):
    motors = [_on(0), _on(1)]
    bridge, calls, _runtime = _bridge(tmp_path, states=['idle', 'idle', 'initializing', 'initialized'], motors=motors)
    service = _service(bridge, run_mode=lambda: 'schedule')

    assert service._skip() is None
    assert service._park_and_power_off() == ''
    assert calls == [('initialize', 'reference', 10.0), ('ac', 'servo_off', 0), ('ac', 'servo_off', 1)]


@pytest.mark.parametrize('kwargs, run_mode, state', [
    ({'motors': [_on(0), _on(1)]}, 'manual', 'skipped'),
    # 지금 주차할 수 없는 것은 첫 실패로 센다 · 1분 뒤 다시 · 수정 목록 131 (흐름은 test_schedule_end_retry)
    ({'motors': [_on(0, servo_on=False), _on(1)]}, 'schedule', 'retry_wait'),
    ({'motors': [_on(0)], 'alarm': 1}, 'schedule', 'retry_wait'),
    ({'motors': [_on(0)], 'flags': {0: False}}, 'schedule', 'skipped'),
])
def test_a_stopped_robot_that_cannot_park_is_left_alone(tmp_path, kwargs, run_mode, state):
    bridge, calls, _runtime = _bridge(tmp_path, states=['idle'], **kwargs)
    service = _service(bridge, run_mode=lambda: run_mode)
    service._spawn = lambda *_args, **_kwargs: None   # 다시 시도 스레드는 띄우지 않는다

    status = service.begin()

    assert status['state'] == state
    assert calls == [], '움직이지도 끄지도 않는다'


def test_a_running_robot_keeps_the_old_path_even_with_the_mode_reader(tmp_path):
    bridge, _calls, _runtime = _bridge(tmp_path, states=['running'], motors=[_on(0, servo_on=False)])
    assert _service(bridge, run_mode=lambda: 'schedule')._skip() is None, '도는 중 · 회차 끝을 기다린다'
