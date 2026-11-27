"""재시작 직후 운전 모드를 읽기 전에는 아무것도 보내지 않는다 · 수정 목록 148 (실물 2026-10-15 floating4)

실제로 일어난 일이다(W-A10 ② · 수동 모드 · 사람이 켠 그룹 연속 · `restart motion-control`).

    18:08:10  스케줄 노드 첫 점검 · 「조회 실패 [/api/schedule/status] · Connection refused」
              (브리지가 같은 서비스라 아직 8000 안 열림) → 운전 모드 = 기본값 「스케줄」
              「조회 실패 [/api/motion-run/status]」 → 상태 `''` = 도는 중
              모드가 스케줄이라 143 ③ 가드(수동 모드 안)를 건너뜀
              → 「[점검] 구간 밖인데 돌고 있다 · 회차 후 정지」
    11:25:35  같음 · status 거절 30 ms 뒤 브리지가 열려 정지 요청이 그룹 길로 성공 ·
              남은 PC 모두 회차 후 정지 · 스케줄 모드 PC 는 주차 → 서보 OFF 가 될 수 있다(W-B7)

고친 것 ① 운전 모드는 모름(None)으로 시작 · `/api/schedule/status` 를 한 번 읽기 전에는 점검하지
않는다(읽히면 간격을 기다리지 않고 바로 점검) ② 「상태를 둘 다 읽었나」 가드를 모드 분기 앞으로 ·
끔 모드 정지 · 구간 끝 주차에도.

브리지는 가짜다 · `urllib` 만 바꿔 노드의 조회 · 실패 세기 · 1초 틱은 진짜를 쓴다.
"""

import io
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import motion_schedule.motion_schedule_node as schedule_node
from motion_common.schedule_models import ScheduleItem
from motion_schedule.motion_schedule_node import RECONCILE_INTERVAL_SEC, MotionScheduleNode
from motion_schedule.schedule_engine import ScheduleEngine


class _Logger:
    def info(self, *_args): pass
    def debug(self, *_args): pass
    def warn(self, *_args): pass
    def warning(self, *_args): pass
    def error(self, *_args): pass


DAY = datetime(2026, 10, 15)
NOON = DAY.replace(hour=13)
EVENING = DAY.replace(hour=20)


class _Bridge:
    """엔드포인트마다 답 · 없으면 조회 실패(Connection refused)"""

    def __init__(self):
        self.answers = {}

    def urlopen(self, url, timeout=None):
        endpoint = url.split('127.0.0.1:8000', 1)[1]
        answer = self.answers.get(endpoint)
        if answer is None:
            raise OSError('[Errno 111] Connection refused')
        return io.BytesIO(json.dumps(answer).encode())

    def schedule_status(self, run_mode):
        self.answers['/api/schedule/status'] = {
            'status': 'ok', 'active_project_id': 'proj-a', 'run_mode': run_mode, 'start_blocker': '',
        }

    def local(self, **status):
        self.answers['/api/motion-run/status'] = dict(status)

    def group(self, **execution):
        self.answers['/api/coordination'] = {'runtime': {'joined': True, 'execution': dict(execution)}}

    def drop(self, endpoint):
        self.answers.pop(endpoint, None)


def _all_day():
    return ScheduleItem(
        schedule_id='s-all', schedule_name='하루 종일',
        start_time='00:00:00', stop_time='23:59:59',
        repeat_type='daily', enabled=True,
    )


def _day_schedule():
    return ScheduleItem(
        schedule_id='s1', schedule_name='낮 공연',
        start_time='09:00:00', stop_time='18:00:00',
        repeat_type='daily', enabled=True,
    )


def _restarted_node(tmp_path, monkeypatch, bridge, *, schedules=()):
    """막 다시 뜬 마스터 노드 · `__init__` 과 같은 처음 상태(운전 모드 모름 · 점검 시각 0)"""
    monkeypatch.setattr(schedule_node.urllib.request, 'urlopen', bridge.urlopen)
    node = MotionScheduleNode.__new__(MotionScheduleNode)
    node.projects_dir = str(tmp_path)
    node.coordination_file = str(tmp_path / 'motion_coordination.yaml')
    node.store = SimpleNamespace(
        current_project_id='proj-a',
        list_schedules=lambda: list(schedules),
        check_and_reload=lambda: None,
        load_project=lambda _project_id: None,
    )
    node.get_logger = lambda: _Logger()
    node._is_master_pc = lambda: True
    node._coordination_enabled = lambda: True
    node._coordination_joined = lambda: True
    node.status_pub = SimpleNamespace(publish=lambda _msg: None)
    node.engine = ScheduleEngine()
    # `__init__` 과 같다 · 점검 시각은 「오래전」(WSL 이 막 켜져 monotonic 이 작아도 첫 틱에 점검)
    node._last_reconcile_monotonic = -RECONCILE_INTERVAL_SEC
    node._run_mode = None
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


def test_the_node_starts_with_the_run_mode_unknown():
    """`__init__` 이 기본값(스케줄)을 넣지 않는다 · 시험의 처음 상태가 실제와 같다는 확인"""
    source = (
        Path(__file__).resolve().parents[1] / 'motion_schedule' / 'motion_schedule_node.py'
    ).read_text(encoding='utf-8')
    init = source[source.index('def __init__('):source.index('def _is_master_pc(')]
    assert 'self._run_mode = None' in init
    assert 'DEFAULT_RUN_MODE' not in source.replace('`DEFAULT_RUN_MODE`', '')


@pytest.mark.parametrize('local_readable', [False, True])
def test_w_a10_first_tick_status_fails_human_group_readable_sends_nothing(tmp_path, monkeypatch, local_readable):
    """W-A10 ② · status 거절 · 연동은 읽힘(사람이 켠 그룹) · 모드를 모르니 아무것도 안 보낸다"""
    bridge = _Bridge()
    node = _restarted_node(tmp_path, monkeypatch, bridge)
    if local_readable:
        bridge.local(state='running', group_execution=True)
    bridge.group(execution_id='exec-h', state='running', started_by='human')

    for _ in range(3):
        node._on_timer_tick()

    assert node.sent == [], '운전 모드를 읽기 전에 무언가 보냈다'
    assert node._run_mode is None


def test_w_a10_first_tick_with_a_schedule_started_group_still_waits_for_the_mode(tmp_path, monkeypatch):
    """누가 켰든 · 모드를 모르면 정하지 않는다(스케줄이 켠 그룹도 모드를 읽은 뒤 첫 점검에)"""
    bridge = _Bridge()
    node = _restarted_node(tmp_path, monkeypatch, bridge)
    bridge.local(state='running', group_execution=True)
    bridge.group(execution_id='exec-s', state='running', started_by='schedule')

    node._on_timer_tick()

    assert node.sent == []


def test_first_tick_everything_fails_sends_nothing(tmp_path, monkeypatch):
    """브리지가 아직 안 뜸 · 모드 · 상태 · 연동 다 못 읽음 → 아무것도 안 보낸다(18:08:10)"""
    bridge = _Bridge()
    node = _restarted_node(tmp_path, monkeypatch, bridge)

    for _ in range(3):
        node._on_timer_tick()

    assert node.sent == []


def test_no_start_inside_the_window_before_the_mode_is_read(tmp_path, monkeypatch):
    """구간 안 · 멈춤 · 모드를 모르면 시작도 안 보낸다(수동 모드 PC 가 돌기 시작하면 안 된다) · 읽히면 그 틱에"""
    bridge = _Bridge()
    node = _restarted_node(tmp_path, monkeypatch, bridge, schedules=[_all_day()])
    bridge.local(state='stopped')
    bridge.group(execution_id='', state='idle')

    node._on_timer_tick()
    assert node.sent == []

    bridge.schedule_status('schedule')
    node._on_timer_tick()
    assert [payload.get('command') for _endpoint, payload in node.sent] == ['start_group'], \
        '모드를 읽은 틱에 바로 점검해야 한다(간격을 기다리지 않는다)'


def test_manual_mode_read_after_the_first_tick_leaves_the_human_group_alone(tmp_path, monkeypatch):
    """첫 틱 실패 → 다음 틱에 「수동」 을 읽음 · 사람이 켠 그룹은 그대로(143 그대로)"""
    bridge = _Bridge()
    node = _restarted_node(tmp_path, monkeypatch, bridge)
    bridge.local(state='running', group_execution=True)
    bridge.group(execution_id='exec-h', state='running', started_by='human')

    node._on_timer_tick()
    bridge.schedule_status('manual')
    node._on_timer_tick()

    assert node._run_mode == 'manual'
    assert node._last_reconcile_monotonic > -RECONCILE_INTERVAL_SEC, '모드를 읽은 뒤 점검이 돌지 않았다'
    assert node.sent == []


def test_after_the_mode_is_read_schedule_mode_stops_a_schedule_started_group(tmp_path, monkeypatch):
    """모드를 읽은 뒤에는 전과 같다 · 스케줄 모드 · 구간 밖 · 스케줄이 켠 그룹 → 그룹 길 회차 후 정지(주차)"""
    bridge = _Bridge()
    node = _restarted_node(tmp_path, monkeypatch, bridge)
    bridge.local(state='running', group_execution=True)
    bridge.group(execution_id='exec-s', state='running', started_by='schedule')

    node._on_timer_tick()
    assert node.sent == []

    bridge.schedule_status('schedule')
    node._on_timer_tick()

    stops = _stops(node)
    assert len(stops) == 1
    endpoint, payload = stops[0]
    assert endpoint == '/api/coordination/control'
    assert payload['command'] == 'stop_after_cycle'
    assert payload['reason'] == 'schedule_end'


def test_after_the_mode_is_read_an_unknown_starter_is_still_stopped(tmp_path, monkeypatch):
    """106 그대로 · 수동 모드 · 상태는 읽었는데 누가 켰는지 모름(옛 연동 노드 · 다른 PC 진행) → 멈추는 쪽"""
    bridge = _Bridge()
    node = _restarted_node(tmp_path, monkeypatch, bridge)
    bridge.schedule_status('manual')
    bridge.local(state='running', group_execution=True)
    bridge.group(execution_id='exec-x', state='running')

    node._on_timer_tick()

    assert len(_stops(node)) == 1


def test_a_later_status_failure_keeps_the_mode_it_read(tmp_path, monkeypatch):
    """한 번 읽은 뒤의 조회 실패는 직전 값(§6-271 그대로) · 모름으로 되돌아가지 않는다"""
    bridge = _Bridge()
    node = _restarted_node(tmp_path, monkeypatch, bridge)
    bridge.schedule_status('manual')
    bridge.local(state='stopped')
    bridge.group(execution_id='', state='idle')
    node._on_timer_tick()

    bridge.drop('/api/schedule/status')
    node._on_timer_tick()

    assert node._run_mode == 'manual'


# -- ② 가드는 모드와 상관없이 · 끔 모드 정지 · 구간 끝 주차에도 ------------------------------------ #

def _read_node(tmp_path, monkeypatch, bridge, *, run_mode, schedules):
    node = _restarted_node(tmp_path, monkeypatch, bridge, schedules=schedules)
    node._run_mode = run_mode
    return node


def test_off_mode_does_not_stop_on_an_unreadable_state(tmp_path, monkeypatch):
    """끔 모드 · 구간 안 · 런타임 상태 못 읽음(`''` = 도는 중) → 정지 안 보냄 · 읽히면 보냄"""
    bridge = _Bridge()
    node = _read_node(tmp_path, monkeypatch, bridge, run_mode='off', schedules=[_day_schedule()])
    bridge.group(execution_id='', state='idle')

    node._reconcile(NOON)
    assert node.sent == []

    bridge.local(state='running')
    node._reconcile(NOON.replace(minute=1))
    assert len(_stops(node)) == 1


def test_window_end_idle_park_waits_for_the_group_state(tmp_path, monkeypatch):
    """스케줄 모드 · 구간 끝 · 로컬은 멈춤인데 연동을 못 읽음(준비 중인 그룹일 수 있다) → 주차 미룸 · 읽히면 한 번"""
    bridge = _Bridge()
    node = _read_node(tmp_path, monkeypatch, bridge, run_mode='schedule', schedules=[_day_schedule()])
    bridge.local(state='running')
    bridge.group(execution_id='', state='idle')
    node._reconcile(NOON)
    assert node.sent == []

    bridge.local(state='stopped')
    bridge.drop('/api/coordination')
    node._reconcile(EVENING)
    assert node.sent == [], '그룹 상태를 못 읽었는데 주차를 보냈다'

    bridge.group(execution_id='', state='idle')
    node._reconcile(EVENING.replace(minute=1))
    node._reconcile(EVENING.replace(minute=2))
    assert node.sent == [('/api/coordination/control', {
        'command': 'stop_after_cycle', 'schedule_id': 'window_end', 'reason': 'schedule_end',
    })]
