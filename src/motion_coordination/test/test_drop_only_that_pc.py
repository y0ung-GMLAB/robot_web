"""한 PC 의 문제는 그 PC 만 뺀다 · 나머지는 계속 · 수정 목록 178 (2026-11-08)

사용자 결정 「과부하든 뭐든 그 헤드만 정지 · 재생은 최대한 · Wi-Fi 가 한 번씩 끊겨도 운영 · 재생은
되게」 · 실물 NY 2026-11-07 · 한 PC 의 모터 상태 끊김(08:22 · 08:47)과 재부팅 중인 PC 의 하트비트
끊김(09:35)이 그룹 전체를 세우고 잠갔다.

여기서는 새 길만 본다 · 시작 어긋남 PC 고르기 · 진행 PC 자신이 빠졌다가 정상이 되면 스스로 돌아오기.
옛 시험(전체 정지 · 잠금)을 새 규칙으로 바꾼 것은 각 파일에 있다.
"""

import pytest
from motion_coordination_interfaces.msg import GroupEvent

import motion_coordination.coordination_node as coordination_node
from motion_coordination.participant_rules import spread_outliers
from test_coordination_node import _InlineThread
from test_group_rejoin import _commands, _running_master


# --------------------------------------------------------------------------- #
# 시작 어긋남 · 어긋난 PC 만
# --------------------------------------------------------------------------- #

def test_the_middle_time_is_the_reference_even_when_the_master_plays():
    """끊김 시험 F · 기준은 늘 가운데 값 · 진행 PC 한 대가 늦어도 나머지가 빠지지 않는다"""
    triggered = {'pc-a': 10.080, 'pc-b': 10.000, 'pc-c': 10.005, 'pc-d': 10.010}
    assert spread_outliers(triggered) == {}


def test_only_more_than_250ms_from_the_middle_is_picked():
    triggered = {'pc-b': 10.000, 'pc-c': 10.010, 'pc-d': 10.300}
    assert spread_outliers(triggered) == {'pc-d': 290.0}
    assert spread_outliers({'pc-b': 10.000, 'pc-c': 10.010, 'pc-d': 10.200}) == {}


def test_one_report_or_bad_values_pick_nobody():
    assert spread_outliers({'pc-a': 1.0}) == {}
    assert spread_outliers({'pc-a': 'x', 'pc-b': None}) == {}


def _start_cycle(node, times):
    node._execution.state = 'start_scheduled'
    starting = node._execution.cycle_number + 1
    for pc_id, at in times:
        node._event_callback(GroupEvent(
            group_id='stage-a', execution_id=node._execution.execution_id, pc_id=pc_id,
            event='motion_started', success=True, cycle_number=starting,
            triggered_monotonic_ns=int(at * 1_000_000_000),
        ))


def test_a_master_80ms_late_releases_nobody():
    """끊김 시험 F · 전에는 진행 PC 기준 35 ms 를 넘은 참가 PC 3대가 모두 빠졌다"""
    node = _running_master(participants=('pc-a', 'pc-b', 'pc-c', 'pc-d'))
    errors = []
    node._publish_coordination_error = lambda **kwargs: errors.append(kwargs)

    _start_cycle(node, (('pc-a', 20.080), ('pc-b', 20.000), ('pc-c', 20.005), ('pc-d', 20.010)))

    assert node._execution.participants == ('pc-a', 'pc-b', 'pc-c', 'pc-d')
    assert _commands(node, 'cancel_before_start') == [] and _commands(node, 'stop_now') == []
    assert errors == []


def test_a_far_late_starter_keeps_playing_and_merges_at_the_boundary():
    """250 ms 넘게 어긋난 PC · 연속 재생이면 풀지 않는다(연락 끊김과 같이) · 경계에서 다시 맞춘다 · 끊김 시험 J"""
    node = _running_master(participants=('pc-a', 'pc-b', 'pc-c'))
    errors = []
    node._publish_coordination_error = lambda **kwargs: errors.append(kwargs)

    _start_cycle(node, (('pc-a', 20.000), ('pc-b', 20.005), ('pc-c', 20.400)))

    assert node._execution.participants == ('pc-a', 'pc-b')
    assert '시각 어긋남' in node._execution.excluded['pc-c']
    assert 'pc-c' in node._execution.lost
    assert _commands(node, 'stop_now') == [] and _commands(node, 'cancel_before_start') == []
    assert errors == []


def test_a_far_late_master_is_only_recorded():
    node = _running_master(participants=('pc-a', 'pc-b', 'pc-c'))

    _start_cycle(node, (('pc-a', 20.400), ('pc-b', 20.000), ('pc-c', 20.005)))

    assert node._execution.participants == ('pc-a', 'pc-b', 'pc-c')
    assert _commands(node, 'cancel_before_start') == []


def test_a_far_late_starter_in_a_once_run_is_dropped():
    node = _running_master(participants=('pc-a', 'pc-b', 'pc-c'), run_mode='once')

    _start_cycle(node, (('pc-a', 20.000), ('pc-b', 20.005), ('pc-c', 20.400)))

    assert node._execution.participants == ('pc-a', 'pc-b')
    assert 'pc-c' not in node._execution.lost
    [release] = _commands(node, 'cancel_before_start')
    assert release.participant_ids == ['pc-a', 'pc-c']


def test_the_spread_of_an_earlier_cycle_is_not_handled_again():
    node = _running_master(participants=('pc-a', 'pc-b', 'pc-c'))
    _start_cycle(node, (('pc-a', 20.000), ('pc-b', 20.005), ('pc-c', 20.100)))
    handled = []
    node._handle_trigger_spread_exceeded = handled.append
    node._execution.state = 'start_scheduled'
    node._execution.triggered.clear()

    node._event_callback(GroupEvent(
        group_id='stage-a', execution_id=node._execution.execution_id, pc_id='pc-a',
        event='motion_started', success=True, cycle_number=node._execution.cycle_number + 1,
        triggered_monotonic_ns=int(30.0 * 1_000_000_000),
    ))

    assert handled == [], '이 회차를 다 받기 전에는 앞 회차 편차로 다시 잡지 않는다'


# --------------------------------------------------------------------------- #
# 진행 PC 자신 · 빠졌다가 정상이 되면 스스로 돌아온다
# --------------------------------------------------------------------------- #

def _master_that_dropped_itself(monkeypatch, local):
    monkeypatch.setattr(coordination_node.threading, 'Thread', _InlineThread)
    node = _running_master()
    node._call_local_control = lambda payload, **_kwargs: (
        local.append(payload['command']) or {'success': True}
    )
    node._local_readiness = lambda: {'success': True}
    node._self_exclusion_reason = lambda: ''
    node._local_alarm_grade = lambda: 0
    node._drop_member_only({'pc-a': '로컬 그룹 실행 오류 · 모터 상태에 없음'})
    return node


def test_the_master_dropping_itself_keeps_coordinating(monkeypatch):
    local = []
    node = _master_that_dropped_itself(monkeypatch, local)

    assert node._execution.participants == ('pc-b',)
    assert node._execution.coordinator_id == 'pc-a'
    assert 'stop_now' in local, '제 모터만 세운다'
    assert _commands(node, 'stop_now') == [] and _commands(node, 'cancel_before_start') == []
    assert node._execution.execution_id in node._self_dropped_ids()


def test_the_master_rejoins_itself_at_the_next_boundary(monkeypatch):
    local = []
    node = _master_that_dropped_itself(monkeypatch, local)
    execution_id = node._execution.execution_id

    node._manage_rejoiners()

    assert node._execution.joining['pc-a']['state'] == 'preparing'
    assert 'group_join' in local, '제 로컬 웹에 바로 · DDS join 명령은 내지 않는다'
    assert _commands(node, 'join') == []

    node._event_callback(GroupEvent(
        group_id='stage-a', execution_id=execution_id, pc_id='pc-a',
        event='join_ready', success=True, cycle_number=node._execution.cycle_number,
    ))
    assert node._execution.joining['pc-a']['state'] == 'ready'

    node._admit_ready_joiners()

    assert set(node._execution.participants) == {'pc-a', 'pc-b'}
    assert 'group_join_commit' in local
    assert execution_id not in node._self_dropped_ids(), '다시 넣은 뒤에는 제 예약을 세우지 않는다'


def test_the_master_waits_while_its_own_problem_lasts(monkeypatch):
    local = []
    node = _master_that_dropped_itself(monkeypatch, local)
    node._local_alarm_grade = lambda: 2

    node._manage_rejoiners()

    assert 'pc-a' not in node._execution.joining
    assert 'group_join' not in local


def test_a_failed_self_rejoin_never_releases_the_running_group(monkeypatch):
    local = []
    node = _master_that_dropped_itself(monkeypatch, local)
    node._local_readiness = lambda: {'success': False, 'message': '모터 상태 대기'}

    node._manage_rejoiners()

    assert 'pc-a' not in node._execution.joining
    assert 'group_cancel' in local, '제 로컬 계획만 버린다'
    assert _commands(node, 'cancel_before_start') == [], '도는 그룹을 풀지 않는다'
    assert node._execution.participants == ('pc-b',)
    assert node._join_retry_after['pc-a'] > 0


def test_a_participant_only_reports_its_own_problem(monkeypatch):
    """참가 PC 는 다른 PC 의 문제로 아무것도 하지 않는다 · 진행 PC 가 정한다"""
    monkeypatch.setattr(coordination_node.threading, 'Thread', _InlineThread)
    node = _running_master()
    node._config = type(node._config)(**{**vars(node._config), 'pc_id': 'pc-b'}) \
        if not hasattr(node._config, '__dataclass_fields__') else node._config
    node._execution.coordinator_id = 'pc-z'
    published = []
    node._exclude_participants = lambda *args, **kwargs: pytest.fail('진행 PC 가 아니다')
    node._publish_runtime_event = lambda *args, **kwargs: published.append(args)

    node._drop_member_only({'pc-c': '통신 단절'})

    assert published == []


# --------------------------------------------------------------------------- #
# 끊김 시험 H · 마스터 자기 모터 문제 · 그룹은 시작하고 마스터만 빠진다
# --------------------------------------------------------------------------- #

def _idle_master():
    from test_coordination_node import _member, _node, _Publisher
    node = _node()
    node._joined = True
    node._command_pub = _Publisher()
    node._event_pub = _Publisher()
    node._registry.update(_member('pc-b'))
    node._registry.update(_member('pc-c'))
    node._call_local_control = lambda payload, **_kwargs: {'success': True}
    node._begin_trigger_sync = lambda _action: None
    node._local_readiness = lambda: {'success': True}
    return node


def test_a_master_servo_alarm_no_longer_blocks_the_group_start():
    node = _idle_master()
    node._local_alarm_grade = lambda: 2

    result = node._start_group_execution(request={'started_by': 'schedule'})

    assert result['participants'] == ['pc-b', 'pc-c']
    assert 'Servo 알람 2등급' in result['excluded']['pc-a']
    assert node._execution.execution_id in node._self_dropped_ids(), '나으면 경계에서 스스로 들어간다'


def test_the_schedule_can_tell_the_master_to_sit_out():
    node = _idle_master()
    node._local_alarm_grade = lambda: 0

    result = node._start_group_execution(request={
        'started_by': 'schedule', 'coordinator_sits_out': '긴급정지 잠김 상태입니다.',
    })

    assert result['participants'] == ['pc-b', 'pc-c']
    assert result['excluded']['pc-a'] == '긴급정지 잠김 상태입니다.'


# --------------------------------------------------------------------------- #
# 끊김 시험 J · 모터가 멀쩡한 이유로 빠지면 그 회차를 끝까지 재생 · 모터 문제면 지금처럼 바로
# --------------------------------------------------------------------------- #

def _keeps_playing(node, pc_id='pc-c'):
    return pc_id in node._execution.lost and _commands(node, 'cancel_before_start') == []


def _stopped_now(node, pc_id='pc-c'):
    return any(pc_id in release.participant_ids for release in _commands(node, 'cancel_before_start'))


def _reason_late_start(node):
    _start_cycle(node, (('pc-a', 20.000), ('pc-b', 20.005), ('pc-c', 20.400)))


def _reason_missing_start_report(node):
    import time as _time
    node._execution.state = 'start_scheduled'
    node._execution.triggered = {'pc-a': 1.0, 'pc-b': 1.0}
    node._execution.motion_start_report_deadline = _time.monotonic() - 0.1
    node._enforce_motion_start_report_deadline()


def _reason_motor_error(node):
    node._event_callback(GroupEvent(
        group_id='stage-a', execution_id=node._execution.execution_id, pc_id='pc-c',
        event='error', success=False, message='모터 상태에 없음', cycle_number=node._execution.cycle_number,
    ))


def _reason_servo_alarm_stop(node):
    node._event_callback(GroupEvent(
        group_id='stage-a', execution_id=node._execution.execution_id, pc_id='pc-c',
        event='stopped', success=True, message='Servo 알람', cycle_number=node._execution.cycle_number,
    ))


@pytest.mark.parametrize('cause, keeps', [
    (_reason_late_start, True),               # 시작 시각 어긋남 (F)
    (_reason_missing_start_report, True),     # 시작 보고만 못 받음 (망)
    (_reason_motor_error, False),             # 모터 상태 끊김 · 오류
    (_reason_servo_alarm_stop, False),        # 그 PC 가 먼저 섬(알람 · 과부하 · 긴급정지)
])
def test_which_reasons_keep_the_clip_playing(monkeypatch, cause, keeps):
    monkeypatch.setattr(coordination_node.threading, 'Thread', _InlineThread)
    node = _running_master(participants=('pc-a', 'pc-b', 'pc-c'))

    cause(node)

    assert 'pc-c' not in node._execution.participants
    assert _keeps_playing(node) is keeps
    assert _stopped_now(node) is (not keeps)


# --------------------------------------------------------------------------- #
# 끊김 시험 M · 다중 마스터 · 중복 PC ID 는 재생을 세우지 않는다 · 표시만 · 문제 PC 만 빠진다
# --------------------------------------------------------------------------- #

def test_a_second_master_does_not_stop_the_running_group():
    from test_coordination_node import _member
    node = _running_master(participants=('pc-a', 'pc-b', 'pc-c'))
    node._alarm_pub = type(node._command_pub)()
    node._registry.update(_member('pc-z', is_master=True))
    execution_id = node._execution.execution_id

    node._check_multiple_masters()

    assert node._execution.execution_id == execution_id
    assert _commands(node, 'stop_now') == []
    assert node._coordination_error['code'] == 'MULTIPLE_MASTERS'


def test_only_the_lower_numbered_master_starts_and_the_display_clears_itself():
    from test_coordination_node import _member
    node = _idle_master()
    node._alarm_pub = type(node._command_pub)()
    node._local_alarm_grade = lambda: 0
    node._registry.update(_member('pc-0', is_master=True))
    node._check_multiple_masters()

    with pytest.raises(ValueError, match='번호가 낮은 pc-0'):
        node._start_group_execution(request={'started_by': 'schedule'})

    node._registry._members.pop('pc-0')
    node._check_multiple_masters()
    assert node._coordination_error == {}
    assert node._start_group_execution(request={'started_by': 'schedule'})['success'] is True


def test_the_lower_numbered_master_keeps_starting_while_shown():
    from test_coordination_node import _member
    node = _idle_master()
    node._alarm_pub = type(node._command_pub)()
    node._local_alarm_grade = lambda: 0
    node._registry.update(_member('pc-z', is_master=True))
    node._check_multiple_masters()

    assert node._start_group_execution(request={'started_by': 'schedule'})['success'] is True
    assert node._coordination_error['code'] == 'MULTIPLE_MASTERS', '원인이 풀릴 때까지 표시'


def test_a_duplicate_pc_id_takes_only_this_pc_out(monkeypatch):
    monkeypatch.setattr(coordination_node.threading, 'Thread', _InlineThread)
    node = _running_master(participants=('pc-a', 'pc-b', 'pc-c'))
    node._alarm_pub = type(node._command_pub)()
    node._self_exclusion_reason = lambda: ''
    execution_id = node._execution.execution_id

    node._handle_duplicate_pc_id('boot-other')

    assert node._execution.execution_id == execution_id, '나머지는 계속'
    assert 'pc-a' not in node._execution.participants
    assert _commands(node, 'stop_now') == []
    assert node._coordination_error['code'] == 'DUPLICATE_PC_ID'
