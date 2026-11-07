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

def test_the_masters_own_time_is_the_reference_when_it_plays():
    triggered = {'pc-a': 10.000, 'pc-b': 10.010, 'pc-c': 10.120}
    assert spread_outliers(triggered, reference_pc='pc-a', tolerance_ms=70.0) == {'pc-c': 120.0}


def test_without_the_master_the_middle_time_is_the_reference():
    triggered = {'pc-b': 10.000, 'pc-c': 10.010, 'pc-d': 10.200}
    assert spread_outliers(triggered, reference_pc='pc-a', tolerance_ms=70.0) == {'pc-d': 190.0}


def test_within_half_the_tolerance_nobody_is_picked():
    triggered = {'pc-a': 10.000, 'pc-b': 10.034}
    assert spread_outliers(triggered, reference_pc='pc-a', tolerance_ms=70.0) == {}


def test_one_report_or_bad_values_pick_nobody():
    assert spread_outliers({'pc-a': 1.0}, reference_pc='pc-a') == {}
    assert spread_outliers({'pc-a': 'x', 'pc-b': None}, reference_pc='pc-a') == {}


def test_a_late_starter_is_dropped_and_the_rest_keep_playing():
    node = _running_master(participants=('pc-a', 'pc-b', 'pc-c'))
    node._execution.state = 'start_scheduled'
    errors = []
    node._publish_coordination_error = lambda **kwargs: errors.append(kwargs)
    starting = node._execution.cycle_number + 1
    for pc_id, at in (('pc-a', 20.000), ('pc-b', 20.005), ('pc-c', 20.150)):
        node._event_callback(GroupEvent(
            group_id='stage-a', execution_id=node._execution.execution_id, pc_id=pc_id,
            event='motion_started', success=True, cycle_number=starting,
            triggered_monotonic_ns=int(at * 1_000_000_000),
        ))

    assert node._execution.participants == ('pc-a', 'pc-b')
    assert '시각 어긋남' in node._execution.excluded['pc-c']
    assert _commands(node, 'stop_now') == []
    assert errors == []


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
