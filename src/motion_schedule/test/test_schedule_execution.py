"""스케줄이 실제로 어디로 무엇을 보내는가 · §6-132.

`test_schedule_targets` 는 소스 문자열을 본다 · 계약이 바뀐 것은 잡지만
**부르면 무슨 일이 나는지**는 못 잡는다. 여기서는 노드를 세워 실제로 부른다.

화면(연동 탭 정리·스케줄 일원화)을 손대기 전에 지금 되는 것을 잠근다.
"""

import json
from types import SimpleNamespace

import pytest

from motion_common.schedule_models import ScheduleItem
import motion_schedule.motion_schedule_node as schedule_node
from motion_schedule.motion_schedule_node import MotionScheduleNode


class _Logger:
    def info(self, *_args): pass
    def debug(self, *_args): pass
    def warn(self, *_args): pass        # 조회 실패를 여기에 적는다 · §6-271
    def warning(self, *_args): pass
    def error(self, *_args): pass


def _node(tmp_path, *, coordination_enabled, is_master=True):
    node = MotionScheduleNode.__new__(MotionScheduleNode)
    node.projects_dir = str(tmp_path)
    node.workspace_dir = str(tmp_path)
    node.coordination_file = str(tmp_path / 'motion_coordination.yaml')
    node._master_role_cache = None
    node._master_role_stamp = None
    # 마지막으로 거부당한 시도 · §6-147 · `__init__` 과 같이 둔다
    node._last_failure = {}
    node.store = SimpleNamespace(
        current_project_id='proj-a',
        list_schedules=lambda: [],
        check_and_reload=lambda: False,
        load_project=lambda _project_id: None,
    )
    node.get_logger = lambda: _Logger()
    node._coordination_enabled = lambda: coordination_enabled
    # 「쓰겠다」와 「지금 묶여 있다」는 다르다 · §6-266 · 시험에서는 같이 준다
    node._coordination_joined = lambda: coordination_enabled
    node._is_master_pc = lambda: is_master
    node.sent = []
    node._send_http_request = lambda endpoint, payload: (
        node.sent.append((endpoint, payload)) or True
    )
    return node


def _item():
    return ScheduleItem(schedule_id='s1', schedule_name='아침 공연')


def test_group_start_goes_to_the_coordination_endpoint(tmp_path):
    node = _node(tmp_path, coordination_enabled=True)

    node._execute_start(_item())

    endpoint, payload = node.sent[0]
    assert endpoint == '/api/coordination/control'
    assert payload['command'] == 'start_group'
    assert payload['schedule_id'] == 's1'


def test_local_start_goes_to_the_motion_run_endpoint(tmp_path):
    """연동을 쓰지 않는 PC · 그룹 명령을 보내면 매번 실패했다 · §6-68"""
    node = _node(tmp_path, coordination_enabled=False)

    node._execute_start(_item())

    endpoint, payload = node.sent[0]
    assert endpoint == '/api/motion-run/start'
    assert 'command' not in payload, '단독 경로는 그룹 명령을 싣지 않는다'
    assert payload['schedule_id'] == 's1'


def test_start_does_not_pick_a_motion_file(tmp_path):
    """스케줄은 **이미 등록된 모션**을 켜고 끌 뿐이다 · 파일은 고르지 않는다.

    브리지가 프로젝트의 활성 파일로 채운다 (`_with_active_project_files`).
    """
    for enabled in (True, False):
        node = _node(tmp_path, coordination_enabled=enabled)
        node._execute_start(_item())
        _endpoint, payload = node.sent[0]
        assert 'motion_file_id' not in payload
        assert 'mapping_file_id' not in payload


def test_start_is_continuous_play(tmp_path):
    """시각이 되면 「연속 시작」을 누르는 것과 같다."""
    node = _node(tmp_path, coordination_enabled=False)

    node._execute_start(_item())

    _endpoint, payload = node.sent[0]
    assert payload['run_mode'] == 'continuous'
    assert payload['target_cycle_count'] == 0


def test_stop_is_stop_after_cycle_on_both_scopes(tmp_path):
    """종료 시각에는 「현재 회차 후 정지」다 · 중간에 끊지 않는다."""
    group = _node(tmp_path, coordination_enabled=True)
    # 그룹 길은 **그룹 실행이 돌 때만** · 수정 목록 115
    group._group_execution = lambda: {'state': 'running', 'execution_id': 'exec-a'}
    group._execute_stop_after_cycle(_item())
    assert group.sent[0][0] == '/api/coordination/control'
    assert group.sent[0][1]['command'] == 'stop_after_cycle'

    local = _node(tmp_path, coordination_enabled=False)
    local._execute_stop_after_cycle(_item())
    assert local.sent[0][0] == '/api/motion-run/stop-after-cycle'


def test_a_solo_run_on_a_joined_pc_is_stopped_on_the_local_path(tmp_path):
    """실물 R-43 · 연동 묶임 · 사람이 켠 단독 연속 · 그룹 길로만 보내 「활성 그룹 실행이 없습니다」 · 수정 목록 115"""
    node = _node(tmp_path, coordination_enabled=True)
    node._group_execution = lambda: {}

    node._execute_stop_after_cycle(None, reason='schedule_end')

    assert [endpoint for endpoint, _ in node.sent] == ['/api/motion-run/stop-after-cycle']
    # 스케줄 끝 동작(기준점 주차 → 서보 OFF)도 단독 길에서 같이 · 브리지가 `reason` 을 본다
    assert node.sent[0][1]['reason'] == 'schedule_end'


def test_a_refused_group_stop_falls_back_to_the_local_path(tmp_path):
    """그룹 길이 거절하면(그 사이 그룹이 끝남) 단독 길로 다시 · 수정 목록 115"""
    node = _node(tmp_path, coordination_enabled=True)
    node._group_execution = lambda: {'state': 'running', 'execution_id': 'exec-a'}
    node._send_http_request = lambda endpoint, payload: (
        node.sent.append((endpoint, payload)) or endpoint != '/api/coordination/control'
    )

    node._execute_stop_after_cycle(None, reason='schedule_end')

    assert [endpoint for endpoint, _ in node.sent] == [
        '/api/coordination/control', '/api/motion-run/stop-after-cycle',
    ]


def test_an_accepted_start_does_not_wipe_the_failure_count(tmp_path):
    """받아들여진 시작은 아직 성공이 아니다 · 실제로 돌아야 지운다 · 수정 목록 124"""
    node = _node(tmp_path, coordination_enabled=True)
    node._last_failure = {'endpoint': '시작 뒤 재생 없음', 'message': '준비 안 됨', 'count': 2}

    def accept(endpoint, payload):
        node.sent.append((endpoint, payload))
        node._last_failure = {}     # 진짜 `_send_http_request` 는 받아들여지면 지운다
        return True

    node._send_http_request = accept
    node._execute_start(_item())

    assert node._last_failure['count'] == 2
    assert node._start_pending is True


def test_a_slave_pc_never_fires_its_own_schedule(tmp_path, monkeypatch):
    """연동 슬레이브는 마스터 명령을 따른다 · 제 스케줄도 점검도 하지 않는다."""
    # 주기 틱은 활성 프로젝트를 브리지에 물어본다 · 시험은 망을 타지 않는다
    monkeypatch.setattr(
        schedule_node.urllib.request, 'urlopen',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError('시험은 망을 안 탄다')),
    )
    node = _node(tmp_path, coordination_enabled=True, is_master=False)
    node._last_reconcile_monotonic = 0.0
    node._run_mode = 'schedule'
    node._reconcile = lambda _now: pytest.fail('슬레이브는 점검하지 않는다')
    node._publish_status = lambda _now: pytest.fail('슬레이브는 여기까지 오지 않는다')

    node._on_timer_tick()

    assert node.sent == []


def test_status_reports_the_master_role_and_count(tmp_path):
    node = _node(tmp_path, coordination_enabled=True)
    node.store.list_schedules = lambda: [_item(), _item()]
    node.engine = SimpleNamespace(active=lambda _now, _schedules: None)
    node._run_mode = 'schedule'
    published = []
    node.status_pub = SimpleNamespace(publish=lambda msg: published.append(msg.data))

    from datetime import datetime
    node._publish_status(datetime.now().astimezone())

    status = json.loads(published[0])
    assert status['is_master'] is True
    assert status['schedule_count'] == 2
