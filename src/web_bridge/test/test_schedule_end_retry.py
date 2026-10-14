"""구간 끝 주차가 거절·실패하면 · 기록 → 1분 뒤 다시 → 3번째도 안 되면 그 자리에서 서보 OFF · 수정 목록 131

실물 V-19 (2026-10-13 19:41 floating4) · 초기 위치 이동이 「실행 컨텍스트 적용 대기」 로 거절됐는데
모터 기록 · 화면 어디에도 안 남고 다시 시도도 없어 밤새 서보가 켜져 있었다.
"""

import json
import time
from types import SimpleNamespace

import pytest

from motion_web_bridge import schedule_end as se
from motion_web_bridge.schedule_end import ScheduleEndService

REFUSED = {'success': False, 'message': 'motion run command failed: 현재 프로젝트 실행 컨텍스트 적용 대기 중입니다'}


# --------------------------------------------------------------------------- #
# 판단 · 순수 함수
# --------------------------------------------------------------------------- #

def test_three_attempts_then_give_up():
    assert se.after_failure(1) == se.RETRY
    assert se.after_failure(2) == se.RETRY
    assert se.after_failure(3) == se.GIVE_UP
    assert se.after_failure(7) == se.GIVE_UP, '기록이 넘쳐도 끝없이 돌지 않는다'


@pytest.mark.parametrize('kwargs, reason', [
    ({'start_requested': True}, '시작 요청'),
    ({'run_mode': 'manual'}, '수동 모드'),
    ({'run_mode': 'off'}, '끔 모드'),
    ({'running': True}, '재생이 돌고'),
    ({'in_window': True}, '운영 구간이 다시'),
])
def test_retry_stops_when_someone_takes_the_robot(kwargs, reason):
    base = {'run_mode': 'schedule', 'running': False, 'in_window': False, 'start_requested': False}
    assert reason in se.retry_cancel_reason(**{**base, **kwargs})


def test_retry_goes_on_when_nothing_changed_or_mode_is_unreadable():
    base = {'running': False, 'in_window': False, 'start_requested': False}
    assert se.retry_cancel_reason(run_mode='schedule', **base) == ''
    assert se.retry_cancel_reason(run_mode='', **base) == '', '못 읽음 · 시도가 다시 거른다'
    assert se.retry_cancel_reason(run_mode=None, **base) == '', '모드를 안 읽는 배선'


def _give_up(**kwargs):
    base = {'run_mode': 'schedule', 'running': False, 'in_window': False, 'start_requested': False,
            'alarm_grade': 0, 'servo_on_targets': 2}
    return se.give_up_step(**{**base, **kwargs})


def test_give_up_turns_servos_off_in_place_only_when_safe():
    assert _give_up() == (se.GIVE_UP_SERVO_OFF, '')
    assert _give_up(run_mode=None)[0] == se.GIVE_UP_SERVO_OFF
    assert _give_up(start_requested=True)[0] == se.GIVE_UP_CANCEL, '사람이 시작했다'
    assert _give_up(run_mode='manual')[0] == se.GIVE_UP_CANCEL, '수동으로 바뀌었다'
    assert _give_up(running=True)[0] == se.GIVE_UP_CANCEL
    assert _give_up(in_window=True)[0] == se.GIVE_UP_CANCEL
    step, why = _give_up(alarm_grade=2)
    assert step == se.GIVE_UP_KEEP and '알람 처리' in why, '알람 정지가 이미 맡았다'
    assert _give_up(run_mode='')[0] == se.GIVE_UP_KEEP, '모드를 못 읽으면 끄지 않는다'
    assert _give_up(servo_on_targets=0)[0] == se.GIVE_UP_NOTHING


def test_resume_continues_only_a_fresh_retry():
    now = 10_000.0
    assert se.resume_step(None, now) == se.RESUME_NONE
    assert se.resume_step({'state': 'gave_up'}, now) == se.RESUME_NOTICE
    assert se.resume_step({'state': 'retrying', 'attempts': 2, 'updated_at': now - 90}, now) == se.RESUME_RETRY
    assert se.resume_step({'state': 'retrying', 'attempts': 2, 'updated_at': now - 3600}, now) == se.RESUME_DROP
    assert se.resume_step({'state': 'retrying', 'attempts': 2, 'updated_at': now + 600}, now) == se.RESUME_DROP
    assert se.resume_step({'state': 'retrying', 'attempts': 'x', 'updated_at': now}, now) == se.RESUME_DROP
    assert se.resume_step({'state': '???'}, now) == se.RESUME_DROP


def test_notice_wording_and_colour():
    retry = se.end_notice('retry_wait', attempts=1, reason='기준점 이동 거절')
    assert retry['tone'] == 'warn' and retry['title'] == '구간 끝 주차 실패 · 1/3회'
    assert '1분 뒤' in retry['detail']
    off = se.end_notice('gave_up', reason='기준점 이동 거절')
    assert off['tone'] == 'warn' and '그 자리에서 서보 끔' in off['title'] and '처짐' in off['detail']
    kept = se.end_notice('gave_up', reason='r', detail='서보 알람', bad=True)
    assert kept['tone'] == 'bad' and '켜진 채' in kept['title']
    assert se.end_notice('done') is None


# --------------------------------------------------------------------------- #
# 흐름 · 스레드 없이 그대로 돈다(가짜 시계)
# --------------------------------------------------------------------------- #

def _on(axis, servo_on=True):
    return {'controller_index': axis, 'state': 'detected', 'motor_type': 'ac_servo', 'servo_on': servo_on}


class _Robot:
    def __init__(self, tmp_path, *, motors=None, flags=None, alarm=0, replies=(), arrive=True):
        self.runtime = tmp_path / 'motion_projects' / 'p1' / 'runtime'
        self.runtime.mkdir(parents=True)
        (self.runtime / 'motion_automation.json').write_text(
            json.dumps({'schedule_end_action': 'park_servo_off'}), encoding='utf-8',
        )
        self.motors = motors if motors is not None else [_on(0), _on(1)]
        self.registry = [
            {'axis': axis, 'config': {'schedule_end_servo_off': False}}
            for axis, flag in (flags or {}).items() if flag is False
        ]
        self.alarm = alarm
        self.mode = 'schedule'
        self.window = False
        self.state = 'idle'
        self.phase_started_at = 0.0
        self.replies = list(replies)
        self.arrive = arrive
        self.calls = []
        self.events = []
        self.attempts_seen = []
        self.after_init = None
        self.after_stop = None
        self.now = 0.0
        self.bridge = SimpleNamespace(
            workspace_root=tmp_path,
            project_repository=SimpleNamespace(selected_project_id=lambda: 'p1'),
            motion_run_status=lambda: {'status': {'state': self.state, 'phase_started_at': self.phase_started_at}},
            coordination_execution_blocker=lambda: '',
            motion_run_initialize=self._initialize,
            motion_run_stop=self._stop,
            motion_state=lambda: {'motors': self.motors},
            get_logger=lambda: SimpleNamespace(info=lambda _m: None, warn=lambda _m: None),
        )

    def _initialize(self, payload):
        assert payload['request_source'] == 'schedule_end'
        record = json.loads((self.runtime / se.RETRY_FILE).read_text(encoding='utf-8'))
        self.attempts_seen.append(record['attempts'])   # 시도 **전에** 센 횟수
        self.calls.append(('initialize', self.now))
        reply = self.replies.pop(0) if self.replies else {'success': True}
        if reply.get('success') is not False:
            self.state = 'initialized' if self.arrive else 'initializing'
            self.phase_started_at = time.time() + 5
        if self.after_init:
            self.after_init()
        return reply

    def _stop(self):
        self.calls.append(('stop',))
        self.state = 'stopped'
        if self.after_stop:
            self.after_stop()

    def ac(self, action, axis, _scope):
        self.calls.append(('ac', action, axis))
        for motor in self.motors:
            if motor['controller_index'] == axis:
                motor['servo_on'] = action == 'servo_on'
        return {'success': True}

    def dxl(self, action, axes=None):
        self.calls.append(('dxl', action, tuple(axes or ())))
        return {'success': True}

    def retry_record(self):
        path = self.runtime / se.RETRY_FILE
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

    def event_types(self):
        return [event_type for event_type, _content in self.events]

    def moves(self):
        return [call for call in self.calls if call[0] in ('initialize', 'ac', 'dxl', 'stop')]


def _service(robot, on_sleep=None):
    def sleep(seconds):
        robot.now += seconds
        if on_sleep:
            on_sleep()

    service = ScheduleEndService(
        robot.bridge,
        fill_active_files=lambda payload: {**payload, 'motion_file_id': 'a.json', 'mapping_file_id': 'm.yaml'},
        ac_servo_control=robot.ac,
        dynamixel_torque_control=robot.dxl,
        load_motor_registry=lambda: {'motors': robot.registry},
        alarm_grade=lambda: robot.alarm,
        run_mode=lambda: robot.mode,
        in_window=lambda: robot.window,
        record_event=lambda event_type, content, _details: robot.events.append((event_type, content)),
        sleep=sleep,
        monotonic=lambda: robot.now,
    )
    # 스레드 대신 그 자리에서 · 결과를 바로 본다
    service._spawn = lambda attempts, error, wait_first=False: service._run(attempts, error, wait_first)
    return service


def test_v19_refused_three_times_then_servos_off_in_place_and_next_start_restores(tmp_path):
    robot = _Robot(tmp_path, replies=[REFUSED] * 3, flags={1: False})
    service = _service(robot)

    service.begin()

    inits = [call for call in robot.calls if call[0] == 'initialize']
    assert len(inits) == 3
    assert inits[1][1] - inits[0][1] >= se.RETRY_INTERVAL_SEC, '약 1분 간격'
    assert robot.attempts_seen == [1, 2, 3], '시도 전에 센다 · 다시 켜져도 이어 센다'
    assert robot.moves()[-1] == ('ac', 'servo_off', 0), '「끝나면 서보 끄기」 켠 모터만'
    assert ('ac', 'servo_off', 1) not in robot.calls
    assert robot.event_types() == ['schedule_end_park_failed'] * 3 + ['schedule_end_servo_off_in_place']
    assert robot.events[0][1].startswith('구간 끝 주차 실패 · 기준점 이동 거절 · ')
    assert '실행 컨텍스트 적용 대기' in robot.events[0][1]
    assert robot.events[-1][1].startswith('주차 못 하고 그 자리에서 서보 끔 · 기준점 이동 거절')
    status = service.status()
    assert status['state'] == 'gave_up'
    assert status['notice']['tone'] == 'warn' and '그 자리에서 서보 끔' in status['notice']['title']
    assert robot.retry_record()['state'] == 'gave_up', '브리지가 다시 켜져도 알림이 남는다'
    powered = json.loads((robot.runtime / se.STATE_FILE).read_text(encoding='utf-8'))
    assert powered['ac_servo'] == [0], '다음 시작 때 다시 켠다'

    # 다음 시작 · 끈 서보를 켜고 알림을 거둔다
    assert service.start_blocker() == ''
    assert ('ac', 'servo_on', 0) in robot.calls
    assert service.status().get('notice') is None
    assert robot.retry_record() is None


def test_refused_once_then_parks_and_powers_off(tmp_path):
    robot = _Robot(tmp_path, replies=[REFUSED])
    service = _service(robot)

    service.begin()

    assert [call[0] for call in robot.moves()] == ['initialize', 'initialize', 'ac', 'ac']
    assert robot.event_types() == ['schedule_end_park_failed', 'schedule_end_parked']
    assert '2번째 시도' in robot.events[-1][1]
    assert service.status()['state'] == 'done' and not service.status().get('notice')
    assert robot.retry_record() is None


def test_normal_window_end_parks_without_any_notice(tmp_path):
    robot = _Robot(tmp_path)
    robot.state = 'completed'   # 회차 후 정지로 막 멈춘 로봇
    service = _service(robot)

    service.begin()

    assert [call[0] for call in robot.moves()] == ['initialize', 'ac', 'ac']
    assert robot.events == [], '정상이면 운영 로그에 따로 안 남긴다(초기 위치 이동 기록이 남는다)'
    assert service.status()['state'] == 'done'
    assert robot.retry_record() is None


@pytest.mark.parametrize('change, reason', [
    (lambda robot: setattr(robot, 'mode', 'manual'), '수동 모드로 바뀜'),
    (lambda robot: setattr(robot, 'window', True), '운영 구간이 다시 시작됨'),
    (lambda robot: setattr(robot, 'state', 'running'), '재생이 돌고 있음'),
])
def test_retry_is_cancelled_when_someone_takes_over(tmp_path, change, reason):
    robot = _Robot(tmp_path, replies=[REFUSED] * 3)
    robot.after_init = lambda: change(robot)
    service = _service(robot)

    service.begin()

    assert [call[0] for call in robot.moves()] == ['initialize'], '다시 움직이지도 끄지도 않는다'
    assert robot.event_types() == ['schedule_end_park_failed', 'schedule_end_retry_cancelled']
    assert reason in robot.events[-1][1]
    assert service.status()['state'] == 'cancelled' and not service.status().get('notice')
    assert robot.retry_record() is None


def test_a_start_request_while_waiting_cancels_the_retry(tmp_path):
    robot = _Robot(tmp_path, replies=[REFUSED] * 3)
    started = []

    def press_start():
        if not started and service.status()['state'] == 'retry_wait':
            started.append(service.start_blocker())

    service = _service(robot, on_sleep=press_start)

    service.begin()

    assert started == [''], '기다리는 중에는 시작을 막지 않는다'
    assert [call[0] for call in robot.moves()] == ['initialize']
    assert robot.event_types()[-1] == 'schedule_end_retry_cancelled'
    assert '시작 요청' in robot.events[-1][1]
    assert not service.status().get('notice')


def test_alarm_keeps_failing_then_servos_are_left_to_the_alarm_handling(tmp_path):
    robot = _Robot(tmp_path, alarm=2)
    service = _service(robot)

    service.begin()

    assert robot.moves() == [], '알람 · 움직이지도 끄지도 않는다'
    assert robot.event_types() == ['schedule_end_park_failed'] * 3 + ['schedule_end_gave_up']
    status = service.status()
    assert status['state'] == 'gave_up' and status['notice']['tone'] == 'bad'
    assert '알람 처리' in status['notice']['detail']


def test_a_motor_switched_off_by_hand_is_not_touched_by_the_in_place_servo_off(tmp_path):
    robot = _Robot(tmp_path, motors=[_on(0, servo_on=False), _on(1)])
    service = _service(robot)

    service.begin()

    assert robot.moves() == [('ac', 'servo_off', 1)], '주차는 안 하고 켜진 것만 끈다'
    powered = json.loads((robot.runtime / se.STATE_FILE).read_text(encoding='utf-8'))
    assert powered['ac_servo'] == [1], '사람이 끈 0번은 다음 시작 때 켜지 않는다'


def test_servos_already_off_at_retry_means_nothing_left_to_do(tmp_path):
    robot = _Robot(tmp_path, replies=[REFUSED] * 3)
    robot.after_init = lambda: [motor.update(servo_on=False) for motor in robot.motors]   # 사람이 껐다
    service = _service(robot)

    service.begin()

    assert [call[0] for call in robot.moves()] == ['initialize']
    assert service.status()['state'] == 'skipped' and not service.status().get('notice')
    assert robot.retry_record() is None


def test_park_timeout_stops_the_stuck_move_and_retries(tmp_path):
    robot = _Robot(tmp_path, arrive=False)
    robot.after_stop = lambda: setattr(robot, 'arrive', True)
    service = _service(robot)

    service.begin()

    assert [call[0] for call in robot.moves()] == ['initialize', 'stop', 'initialize', 'ac', 'ac']
    assert '기준점 도달 확인 시간 초과' in robot.events[0][1]
    assert service.status()['state'] == 'done'


def test_repeated_window_end_calls_do_not_restart_the_count(tmp_path):
    robot = _Robot(tmp_path)
    service = _service(robot)
    service._thread = SimpleNamespace(is_alive=lambda: True)
    service._set('retry_wait', '구간 끝 주차 실패', notice={'tone': 'warn', 'title': 't'})

    assert service.begin()['state'] == 'retry_wait'
    assert robot.moves() == []


def test_bridge_restart_continues_the_count_instead_of_starting_over(tmp_path):
    robot = _Robot(tmp_path, replies=[REFUSED] * 3)
    (robot.runtime / se.RETRY_FILE).write_text(json.dumps({
        'state': 'retrying', 'attempts': 2, 'reason': '기준점 이동 거절', 'updated_at': time.time() - 30,
    }), encoding='utf-8')
    service = _service(robot)

    service.resume()

    assert [call[0] for call in robot.moves()] == ['initialize', 'ac', 'ac'], '세 번째 한 번 · 그 뒤 그 자리에서 끔'
    assert robot.calls[0][1] >= se.RETRY_INTERVAL_SEC, '켜진 직후가 아니라 1분 뒤'
    assert robot.attempts_seen == [3]
    assert service.status()['state'] == 'gave_up'


def test_bridge_restart_after_the_last_attempt_only_decides_the_servo_off(tmp_path):
    robot = _Robot(tmp_path)
    (robot.runtime / se.RETRY_FILE).write_text(json.dumps({
        'state': 'retrying', 'attempts': 3, 'reason': '기준점 이동 거절', 'updated_at': time.time(),
    }), encoding='utf-8')
    service = _service(robot)

    service.resume()

    assert [call[0] for call in robot.moves()] == ['ac', 'ac'], '다시 주차하지 않는다'


def test_old_retry_record_is_dropped_on_restart(tmp_path):
    robot = _Robot(tmp_path)
    (robot.runtime / se.RETRY_FILE).write_text(json.dumps({
        'state': 'retrying', 'attempts': 1, 'reason': 'r', 'updated_at': time.time() - 6 * 3600,
    }), encoding='utf-8')
    service = _service(robot)

    service.resume()

    assert robot.moves() == []
    assert robot.retry_record() is None
    assert robot.event_types() == ['schedule_end_retry_dropped']


def test_give_up_notice_survives_restart_and_a_later_quiet_window_end(tmp_path):
    robot = _Robot(tmp_path, motors=[_on(0, servo_on=False)])
    notice = se.end_notice('gave_up', reason='기준점 이동 거절')
    (robot.runtime / se.RETRY_FILE).write_text(json.dumps({
        'state': 'gave_up', 'attempts': 3, 'reason': '기준점 이동 거절',
        'message': '운영 종료 · 주차 못 하고 그 자리에서 서보 끔', 'notice': notice, 'updated_at': 1.0,
    }), encoding='utf-8')
    service = _service(robot)

    service.resume()
    assert service.status()['notice'] == notice

    # 다음 구간 끝 · 서보가 이미 꺼져 있어 할 일 없음 · 알림은 그대로
    service.begin()
    assert service.status()['notice'] == notice
    assert robot.retry_record()['state'] == 'gave_up'

    # 다음 시작이 거둔다
    service.start_blocker()
    assert not service.status().get('notice')
    assert robot.retry_record() is None
