"""시간표 재생 · 연동 노드 쪽 · 수정 목록 186 (2026-11-09)

마스터가 설정을 만들고 보낸다 · 슬레이브는 높은 버전을 저장 · 사람 명령은 묶음의 칸 · 스케줄 노드는 시간표
실행을 「도는 중」 으로 본다 · 신호 재생 실행이 도는 동안에는 시간표가 손대지 않는다.
"""

import json
import time
from types import SimpleNamespace

from motion_coordination import timetable
from motion_coordination.clock_driver import ClockDriver
from motion_coordination.timetable import MODE_CLOCK, TimetableConfig
from motion_coordination.timetable_node import TIMETABLE_STOP_COMMAND
from test_coordination_node import _member, _node, _Publisher

DAILY_ALL_DAY = {
    'schedule_id': 's1', 'schedule_name': '하루', 'start_time': '00:00:00', 'stop_time': '23:59:59',
    'repeat_type': 'daily', 'enabled': True,
}


def _tt_node(tmp_path, *, master=True, config=None):
    node = _node()
    node._config.is_master = master
    node._joined = True
    node._timetable_path = tmp_path / 'group_timetable.json'
    node._timetable = config or TimetableConfig()
    node._timetable_pub = _Publisher()
    node._command_pub = _Publisher()
    node._timetable_peers = {}
    calls = []
    node._local_calls = calls

    def control(payload, **_kwargs):
        calls.append(dict(payload))
        return {'success': True}

    node._call_local_control = control
    node._warn = lambda _text: None
    node._clock_driver = ClockDriver(control, info=lambda _t: None, warn=lambda _t: None)
    node._local_status = {
        'operation_mode': 'schedule', 'schedule_items': [DAILY_ALL_DAY], 'motion_playlist': ['a.json'],
        'cycle_need_sec': 925.0, 'motion_run_status': {'state': 'stopped'},
    }
    return node


def test_the_master_builds_and_sends_the_bundle(tmp_path):
    node = _tt_node(tmp_path)
    node._registry.update(_member('pc-b'))
    node._timetable_peers = {'pc-b': {'report': {'need': 935.0}, 'delays': []}}
    node._timetable_upkeep()
    config = node._timetable
    assert config.version == 1 and config.issued_by == 'pc-a'
    assert config.schedule_enabled and config.schedules == (DAILY_ALL_DAY,)
    assert config.auto_period_sec == 950.0, '가장 긴 PC(935) + 회차 사이 6 + 2 → 10 s 올림(188)'
    assert config.playlist == ('a.json',)
    assert timetable.load(node._timetable_path) == config, '마스터도 디스크에'
    assert node._timetable_pub.messages and node._timetable_pub.messages[-1].version == 1
    node._timetable_upkeep_at = 0.0
    node._timetable_upkeep()
    assert node._timetable.version == 1, '바뀐 것이 없으면 버전 그대로'


def test_a_slave_keeps_the_highest_version_on_disk(tmp_path):
    node = _tt_node(tmp_path, master=False)
    incoming = TimetableConfig(version=4, issued_by='pc-m', mode=MODE_CLOCK, auto_period_sec=930.0)
    message = SimpleNamespace(group_id='stage-a', pc_id='pc-m', body=timetable.body_text(incoming))
    node._timetable_callback(message)
    assert node._timetable == incoming and timetable.load(node._timetable_path) == incoming
    older = SimpleNamespace(group_id='stage-a', pc_id='pc-m',
                            body=timetable.body_text(TimetableConfig(version=2, issued_by='pc-m')))
    node._timetable_callback(older)
    assert node._timetable.version == 4


def test_only_the_master_changes_the_mode_and_a_short_period_is_refused(tmp_path):
    node = _tt_node(tmp_path, config=TimetableConfig(version=1, issued_by='pc-a', auto_period_sec=930.0))
    result = node._handle_local_request({'command': 'timetable_set', 'mode': MODE_CLOCK, 'period_sec': 1000})
    assert result['success'] and node._timetable.clock and node._timetable.period_sec == 1000.0
    refused = node._handle_local_request({'command': 'timetable_set', 'period_sec': 900})
    assert not refused['success'] and '최소 930' in refused['message']
    slave = _tt_node(tmp_path, master=False)
    assert not slave._handle_local_request({'command': 'timetable_set', 'mode': MODE_CLOCK})['success']


def test_a_human_start_goes_the_signal_way_even_in_clock_mode(tmp_path):
    """사람이 누른 그룹 재생은 신호 재생 · 시간표 묶음은 그대로 · 사용자 2026-11-09 (Q9 변경)"""
    config = TimetableConfig(version=1, issued_by='pc-a', mode=MODE_CLOCK, auto_period_sec=930.0, schedule_enabled=False)
    node = _tt_node(tmp_path, config=config)
    node._local_status['operation_mode'] = 'manual'
    started = []
    node._start_group_execution = lambda **kwargs: started.append(kwargs) or {'success': True, 'message': '신호'}
    result = node._handle_local_request({'command': 'start_group', 'started_by': 'human'})
    assert result == {'success': True, 'message': '신호'} and len(started) == 1
    assert node._timetable == config, '시간표 묶음은 손대지 않는다'
    initialized = node._handle_local_request({'command': 'initialize_group', 'started_by': 'human'})
    assert initialized['success'] and started[-1]['initialization_only'] is True


def test_a_human_start_waits_until_no_pc_holds_a_timetable_cycle(tmp_path):
    """마스터를 수동으로 바꿔도 PC 들은 도는 회차를 마친다 · 그동안 사람 시작은 거절 · 즉시 정지는 그 회차에 닿는다"""
    node = _tt_node(tmp_path, config=TimetableConfig(
        version=3, issued_by='pc-a', mode=MODE_CLOCK, auto_period_sec=600.0, schedule_enabled=False,
        schedules=(DAILY_ALL_DAY,),
    ))
    node._local_status['operation_mode'] = 'manual'
    node._registry.update(_member('pc-b'))
    node._timetable_peers = {'pc-b': {'report': {'run': {'plan_id': 'tt-s1700000000'}}, 'delays': []}}
    node._start_group_execution = lambda **_kwargs: {'success': True}
    refused = node._handle_local_request({'command': 'start_group', 'started_by': 'human'})
    assert not refused['success'] and 'pc-b' in refused['message'] and '즉시 정지' in refused['message']
    assert not node._handle_local_request({'command': 'initialize_group', 'started_by': 'human'})['success']
    execution = node.snapshot()['execution']
    assert execution['execution_id'] == 'tt-s1700000000', '화면에 도는 중 · 정지 버튼이 남는다'
    stopped = node._handle_local_request({'command': 'stop_now'})
    assert stopped['success'] and node._timetable.stop == {'plan_id': 'tt-s1700000000', 'mode': 'now'}
    choice = timetable.choose(node._timetable, time.time(), operation_mode='schedule')
    assert choice.timeline is None and choice.stopped_plan_id == 'tt-s1700000000', '슬레이브 드라이버가 세운다'
    node._timetable_peers['pc-b']['report'] = {'run': {'plan_id': ''}}
    assert node._handle_local_request({'command': 'start_group', 'started_by': 'human'})['success']


def test_a_human_start_is_refused_while_the_schedule_timetable_runs(tmp_path):
    node = _tt_node(tmp_path, config=TimetableConfig(
        version=1, issued_by='pc-a', mode=MODE_CLOCK, auto_period_sec=600.0, schedule_enabled=True,
        schedules=(DAILY_ALL_DAY,), start_lead_sec=0.0,
    ))
    node._start_group_execution = lambda **_kwargs: {'success': True}
    refused = node._handle_local_request({'command': 'start_group', 'started_by': 'human'})
    assert not refused['success'] and '수동 모드' in refused['message']


def test_a_schedule_start_keeps_the_schedule_timeline_and_the_schedule_node_sees_it_running(tmp_path):
    node = _tt_node(tmp_path, config=TimetableConfig(
        version=1, issued_by='pc-a', mode=MODE_CLOCK, auto_period_sec=600.0, schedule_enabled=True,
        schedules=(DAILY_ALL_DAY,), start_lead_sec=0.0,
    ))
    result = node._handle_local_request({'command': 'start_group', 'started_by': 'schedule'})
    assert result['success']
    execution = node.snapshot()['execution']
    assert execution['execution_id'].startswith('tt-s') and execution['state'] in {'running', 'waiting'}
    assert execution['started_by'] == 'schedule'


def test_a_slave_stop_asks_the_master_and_the_master_writes_it(tmp_path):
    config = TimetableConfig(
        version=1, issued_by='pc-m', mode=MODE_CLOCK, auto_period_sec=600.0, schedule_enabled=True,
        schedules=(DAILY_ALL_DAY,), start_lead_sec=0.0,
    )
    slave = _tt_node(tmp_path, master=False, config=config)
    slave._config.pc_id = 'pc-b'
    slave._handle_local_request({'command': 'stop_after_cycle'})
    request = slave._command_pub.messages[-1]
    assert request.command == TIMETABLE_STOP_COMMAND and request.stop_reason == 'after_cycle'
    master = _tt_node(tmp_path, config=config)
    request.group_id = 'stage-a'
    master._command_callback(request)
    assert master._timetable.stop['mode'] == 'after_cycle' and master._timetable.version == 2


def test_the_schedule_end_park_still_goes_the_signal_way_when_nothing_plays(tmp_path):
    node = _tt_node(tmp_path, config=TimetableConfig(version=1, issued_by='pc-a', mode=MODE_CLOCK))
    assert node._timetable_routes_stop('') is True
    assert node._timetable_routes_stop('schedule_end') is False, '도는 시간표가 없으면 운영 끝 주차는 그대로'


def test_heartbeat_carries_the_version_and_the_need(tmp_path):
    node = _tt_node(tmp_path, config=TimetableConfig(version=7, issued_by='pc-a'))
    node._heartbeat_pub = _Publisher()
    node._heartbeat_tick()
    message = node._heartbeat_pub.messages[-1]
    assert message.timetable_version == 7
    assert json.loads(message.timetable_report)['need'] == 925.0


def test_the_clock_offset_comes_from_the_fastest_heartbeat(tmp_path):
    node = _tt_node(tmp_path)
    now = time.time()
    for delay in (0.030, 0.004, 0.050):
        sent = now - delay - 0.120   # 그 PC 시계가 120 ms 늦다
        node._note_timetable_heartbeat(SimpleNamespace(
            pc_id='pc-b', boot_id='b', timetable_version=1, timetable_report='{"need": 1}',
            sent_at=SimpleNamespace(sec=int(sent), nanosec=int((sent % 1) * 1e9)),
        ))
    offset = node._peer_clock_offsets_ms()['pc-b']
    assert -130.0 < offset < -115.0
    assert node._timetable_snapshot()['clock_warnings'] == ['pc-b'], '100 ms 넘음 · 표시'


def test_the_timetable_waits_while_a_signal_execution_runs(tmp_path):
    node = _tt_node(tmp_path, config=TimetableConfig(
        version=1, issued_by='pc-a', mode=MODE_CLOCK, auto_period_sec=600.0, schedule_enabled=True,
        schedules=(DAILY_ALL_DAY,), start_lead_sec=0.0,
    ))
    node._timetable_upkeep_at = time.monotonic()
    node._execution.execution_id = 'exec-signal'
    node._drive_timetable()
    assert node._local_calls == []


def test_a_pc_in_another_timezone_is_shown_but_keeps_playing(tmp_path):
    node = _tt_node(tmp_path, config=TimetableConfig(
        version=2, issued_by='pc-a', mode=MODE_CLOCK, timezone='America/New_York', auto_period_sec=600.0,
    ))
    node._local_status['timezone'] = 'America/New_York'
    assert json.loads(node._timetable_heartbeat()[1])['tz'] == 'America/New_York'
    node._note_timetable_heartbeat(SimpleNamespace(
        pc_id='pc-b', boot_id='b', timetable_version=2,
        timetable_report=json.dumps({'need': 1, 'tz': 'Asia/Seoul'}), sent_at=SimpleNamespace(sec=0, nanosec=0),
    ))
    node._note_timetable_heartbeat(SimpleNamespace(
        pc_id='pc-c', boot_id='c', timetable_version=2,
        timetable_report=json.dumps({'need': 1, 'tz': 'America/New_York'}), sent_at=SimpleNamespace(sec=0, nanosec=0),
    ))
    snapshot = node._timetable_snapshot()
    assert snapshot['timezone_mismatches'] == ['pc-b']
    assert snapshot['peers']['pc-b']['timezone'] == 'Asia/Seoul'
    assert snapshot['local_timezone_mismatch'] is False
    node._local_status['timezone'] = 'Europe/Berlin'
    assert node._timetable_snapshot()['local_timezone_mismatch'] is True


def test_a_timetable_run_keeps_the_local_status_read_fast(tmp_path):
    """시간표 실행 중에는 50 ms 로 읽는다 · 전에는 0.5 s 라 초기 이동 끝을 늦게 봤다 · 수정 목록 188"""
    node = _tt_node(tmp_path)
    node._local_status = {'motion_run_status': {
        'group_execution': True, 'execution_id': 'tt-s1', 'state': 'cycle_ready', 'phase': 'group_cycle_initialized',
    }}
    assert node._timetable_run_live() is True
    node._local_status = {'motion_run_status': {
        'group_execution': True, 'execution_id': 'tt-s1', 'state': 'stopped', 'phase': 'stopped',
    }}
    assert node._timetable_run_live() is False, '끝난 시간표 실행은 빨리 읽을 까닭이 없다'
    node._local_status = {'motion_run_status': {
        'group_execution': True, 'execution_id': 'exec-a', 'state': 'running', 'phase': 'running',
    }}
    assert node._timetable_run_live() is False, '신호 재생은 실행이 있어 따로 빨리 읽는다'
