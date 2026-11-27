"""재시작 직후에도 「누가 켰나」 를 안다 · 수정 목록 143 (실물 V-28 · 2026-10-14 floating4)

실제로 일어난 일이다.

    11:30:09  「장비에 적용」 재시작 뒤 첫 점검 · 런타임 상태를 아직 못 읽음
              (모르는 상태 = 도는 중) → 「수동 모드에서 사람이 켠 재생 · 그대로 둠」
              → 「스케줄이 켰나」 기억은 모름(None) 그대로
    11:32:06  수동 모드 · 사람이 그룹 연속 시작
    11:32:11  다음 점검 · 그룹은 기억만 봤고 모름 = 스케줄이 켠 것(106 「모르면 멈춤」)
              → 「[점검] 구간 밖인데 돌고 있다 · 회차 후 정지」 · 초기 위치 중 그룹 취소

고친 것 · 그룹은 연동 상태의 `started_by`(진행 PC 의 연동 노드가 시작 요청에서 받아 둔다 ·
스케줄 노드가 재시작해도 남는다)를 기억보다 먼저 믿는다 · 상태를 못 읽은 점검은 기억을 바꾸지도,
수동 모드에서 정지를 정하지도 않는다.

브리지는 가짜다 · `urllib` 만 바꿔 노드의 조회 · 실패 세기는 진짜를 쓴다.
"""

import io
import json
from datetime import datetime
from types import SimpleNamespace

import motion_schedule.motion_schedule_node as schedule_node
from motion_common.schedule_models import ScheduleItem
from motion_schedule.motion_schedule_node import MotionScheduleNode
from motion_schedule.schedule_engine import ScheduleEngine


class _Logger:
    def info(self, *_args): pass
    def debug(self, *_args): pass
    def warn(self, *_args): pass
    def warning(self, *_args): pass
    def error(self, *_args): pass


DAY = datetime(2026, 10, 14)
NOON = DAY.replace(hour=13)
EVENING = DAY.replace(hour=20)


class _Bridge:
    """엔드포인트마다 답 · None 이면 조회 실패(재시작 직후 · 브리지가 아직 안 뜸)"""

    def __init__(self):
        self.answers = {}

    def urlopen(self, url, timeout=None):
        endpoint = url.split('127.0.0.1:8000', 1)[1]
        answer = self.answers.get(endpoint)
        if answer is None:
            raise OSError('connection refused')
        return io.BytesIO(json.dumps(answer).encode())

    def down(self):
        self.answers = {}

    def local(self, **status):
        self.answers['/api/motion-run/status'] = dict(status)

    def group(self, **execution):
        self.answers['/api/coordination'] = {'runtime': {'joined': True, 'execution': dict(execution)}}


def _day_schedule():
    return ScheduleItem(
        schedule_id='s1', schedule_name='낮 공연',
        start_time='09:00:00', stop_time='18:00:00',
        repeat_type='daily', enabled=True,
    )


def _fresh_node(tmp_path, monkeypatch, bridge, *, run_mode):
    """`__init__` 과 같은 처음 상태 · 「스케줄이 켰나」 는 모름"""
    monkeypatch.setattr(schedule_node.urllib.request, 'urlopen', bridge.urlopen)
    node = MotionScheduleNode.__new__(MotionScheduleNode)
    node.projects_dir = str(tmp_path)
    node.coordination_file = str(tmp_path / 'motion_coordination.yaml')
    node.store = SimpleNamespace(
        current_project_id='proj-a',
        list_schedules=lambda: [_day_schedule()],
    )
    node.get_logger = lambda: _Logger()
    node._coordination_enabled = lambda: True
    node._coordination_joined = lambda: True
    node.engine = ScheduleEngine()
    node._run_mode = run_mode
    node._last_failure = {}
    node._schedule_started = None
    node._read_failures = {}
    node._start_blocker = ''
    node._start_pending = False
    node.sent = []
    node._send_http_request = lambda endpoint, payload: (
        node.sent.append((endpoint, payload)) or True
    )
    return node


def _stops(node):
    return [
        (endpoint, payload) for endpoint, payload in node.sent
        if 'stop' in endpoint or payload.get('command') == 'stop_after_cycle'
    ]


def test_v28_human_group_after_restart_is_not_stopped(tmp_path, monkeypatch):
    """재시작 → 못 읽은 첫 점검 → 사람이 수동 모드에서 그룹 시작 → 다음 점검이 멈추지 않는다"""
    bridge = _Bridge()
    node = _fresh_node(tmp_path, monkeypatch, bridge, run_mode='manual')

    bridge.down()
    node._reconcile(EVENING)
    assert node.sent == [], '못 읽은 점검이 무언가 보냈다'
    assert node._schedule_started is None, '못 읽은 점검이 기억을 바꿨다'

    bridge.local(state='initializing', group_execution=True)
    bridge.group(execution_id='exec-h', state='initializing', started_by='human')
    node._reconcile(EVENING.replace(minute=1))
    node._reconcile(EVENING.replace(minute=2))

    assert _stops(node) == [], '사람이 켠 그룹을 구간 밖이라고 멈췄다'


def test_v28_human_group_is_left_alone_even_when_the_coordination_read_is_late(tmp_path, monkeypatch):
    """사람이 켠 그룹 · 연동 상태만 한 번 못 읽음 · 그 점검은 정하지 않고 다음 점검에 바로 안다"""
    bridge = _Bridge()
    node = _fresh_node(tmp_path, monkeypatch, bridge, run_mode='manual')
    bridge.local(state='running', group_execution=True)

    node._reconcile(EVENING)
    assert _stops(node) == []

    bridge.group(execution_id='exec-h', state='running', started_by='human')
    node._reconcile(EVENING.replace(minute=1))
    assert _stops(node) == []


def test_a_schedule_started_group_survives_a_node_restart_and_stops_at_window_end(tmp_path, monkeypatch):
    """스케줄이 켠 그룹 · 스케줄 노드 재시작(기억 없음) · 도중에 수동으로 · 구간 끝에 멈춘다(17:58 사고)"""
    bridge = _Bridge()
    before = _fresh_node(tmp_path, monkeypatch, bridge, run_mode='schedule')
    bridge.local(state='stopped')
    bridge.group(execution_id='', state='idle')
    before._reconcile(NOON)
    assert before.sent[0][1]['command'] == 'start_group'
    assert before.sent[0][1]['schedule_id'] == 's1'

    # 노드 재시작 · 그사이 그룹은 연동 노드에서 계속 돈다 · 사람이 수동으로 바꿈
    after = _fresh_node(tmp_path, monkeypatch, bridge, run_mode='manual')
    bridge.down()
    after._reconcile(EVENING)
    assert _stops(after) == [], '못 읽은 점검은 정하지 않는다'

    bridge.local(state='running', group_execution=True)
    bridge.group(execution_id='exec-s', state='running', started_by='schedule')
    after._reconcile(EVENING.replace(minute=1))

    stops = _stops(after)
    assert len(stops) == 1, '재시작 전에 스케줄이 켠 그룹이 구간 끝에 안 멈췄다'
    assert stops[0][0] == '/api/coordination/control'


def test_the_coordination_answer_beats_an_old_memory(tmp_path, monkeypatch):
    """스케줄이 켠 그룹이 끝나고 1분 안에 사람이 새 그룹을 켬 · 기억(켰음)이 남아 있어도 연동 답을 믿는다"""
    bridge = _Bridge()
    node = _fresh_node(tmp_path, monkeypatch, bridge, run_mode='manual')
    node._schedule_started = True
    bridge.local(state='running', group_execution=True)
    bridge.group(execution_id='exec-h2', state='running', started_by='human')

    node._reconcile(EVENING)

    assert _stops(node) == []
    assert node._schedule_started is False


def test_an_unreadable_group_state_does_not_wipe_the_memory(tmp_path, monkeypatch):
    """스케줄이 그룹을 막 켰다(로컬은 아직 stopped) · 연동 상태를 못 읽은 점검은 「멈춤」 을 본 것이 아니다"""
    bridge = _Bridge()
    node = _fresh_node(tmp_path, monkeypatch, bridge, run_mode='manual')
    node._schedule_started = True
    bridge.local(state='stopped')

    node._reconcile(NOON)

    assert node._schedule_started is True


def test_a_readable_stop_still_resets_the_memory(tmp_path, monkeypatch):
    bridge = _Bridge()
    node = _fresh_node(tmp_path, monkeypatch, bridge, run_mode='manual')
    bridge.local(state='stopped')
    bridge.group(execution_id='', state='idle')

    node._reconcile(EVENING)

    assert node._schedule_started is False


def test_a_read_group_without_starter_and_no_memory_is_still_stopped(tmp_path, monkeypatch):
    """수정 목록 106 그대로 · 상태는 읽었는데 누가 켰는지 모름(옛 연동 노드 · 다른 PC 가 진행) → 멈추는 쪽"""
    bridge = _Bridge()
    node = _fresh_node(tmp_path, monkeypatch, bridge, run_mode='manual')
    bridge.local(state='running', group_execution=True)
    bridge.group(execution_id='exec-x', state='running')

    node._reconcile(EVENING)

    assert len(_stops(node)) == 1


def test_schedule_mode_waits_for_a_readable_state_before_stopping(tmp_path, monkeypatch):
    """스케줄 모드도 못 읽은 상태(`''` = 도는 중으로 친 것)로는 멈추지 않는다 · 읽히면 멈춘다 · 수정 목록 148 ②

    전에는 이 가드가 수동 모드 안에만 있어 스케줄 모드는 못 읽은 채 정지를 보냈다(실물 W-A10 ②).
    """
    bridge = _Bridge()
    node = _fresh_node(tmp_path, monkeypatch, bridge, run_mode='schedule')
    bridge.down()

    node._reconcile(EVENING)
    assert _stops(node) == [], '못 읽은 점검이 정지를 보냈다'

    bridge.local(state='running')
    bridge.group(execution_id='', state='idle')
    node._reconcile(EVENING.replace(minute=1))
    assert len(_stops(node)) == 1, '읽은 뒤에는 스케줄 모드라 누가 켰든 멈춘다'
