"""재생 목록 · 수정 목록 35 (2026-10-06)

A → B → C → A … 끝없이 · 사이마다 다음 애니의 첫 프레임으로 초기 위치 이동 ·
재시작은 늘 1번부터 · PC 마다 제 목록.
"""

from pathlib import Path
import tempfile
import threading
from unittest import mock

import pytest
import yaml

from motion_runtime import motion_run_rules
from motion_runtime.group_session import GroupSession
from motion_runtime.motion_automation_store import (
    MotionAutomationStore,
    default_automation_state,
)
from motion_runtime.motion_player import MotionPlayer
from motion_runtime.motion_run_manager import MotionRunManager
from motion_runtime.registered_motion_file import (
    MAX_PLAYLIST_LENGTH,
    load_registered_playlist,
    normalize_playlist,
    playlist_from_mapping,
    render_with_playlist,
    save_registered_playlist,
)


@pytest.fixture(autouse=True)
def _restore_patched_rules():
    yield
    mock.patch.stopall()


MAPPING = """name: store_a
motion_file_id: a.json
mappings:
- motion_id: Neck_Yaw
  motor_axis: 0
midi_banks: []
"""


# -- 매핑 파일의 재생 목록 칸 ------------------------------------------------ #

def test_two_or_more_items_add_a_playlist_after_the_registered_file():
    text = render_with_playlist(MAPPING, ['a.json', 'b.json', 'c.json'])
    root = yaml.safe_load(text)

    assert root['motion_file_id'] == 'a.json'
    assert root['motion_playlist'] == ['a.json', 'b.json', 'c.json']
    # 다른 주인의 칸은 글자 하나 안 바뀐다
    assert root['mappings'] == [{'motion_id': 'Neck_Yaw', 'motor_axis': 0}]
    assert root['midi_banks'] == []
    assert text.index('motion_playlist') > text.index('motion_file_id')
    assert text.index('motion_playlist') < text.index('mappings')


def test_one_item_removes_the_playlist_so_old_files_stay_as_they_were():
    listed = render_with_playlist(MAPPING, ['a.json', 'b.json'])
    single = render_with_playlist(listed, ['b.json'])

    assert 'motion_playlist' not in single
    assert yaml.safe_load(single)['motion_file_id'] == 'b.json'
    # 목록 → 하나 → 원래 파일과 같은 모양
    assert render_with_playlist(single, ['a.json']) == MAPPING


def test_replacing_a_playlist_keeps_one_block_and_duplicates():
    first = render_with_playlist(MAPPING, ['a.json', 'b.json'])
    second = render_with_playlist(first, ['c.json', 'a.json', 'c.json'])
    root = yaml.safe_load(second)

    assert second.count('motion_playlist') == 1
    assert root['motion_file_id'] == 'c.json'
    assert root['motion_playlist'] == ['c.json', 'a.json', 'c.json']


def test_playlist_at_the_end_of_the_file_round_trips():
    tail = 'name: store_a\nmappings: []\nmotion_file_id: a.json\n'
    listed = render_with_playlist(tail, ['a.json', 'b.json'])
    assert yaml.safe_load(listed)['motion_playlist'] == ['a.json', 'b.json']
    cleared = render_with_playlist(listed, [])
    root = yaml.safe_load(cleared)
    assert root['motion_file_id'] == ''
    assert 'motion_playlist' not in root
    assert root['mappings'] == []


def test_playlist_items_are_checked():
    assert normalize_playlist([' a.json ', '', None]) == ['a.json']
    for bad in (['../a.json'], ['dir\\a.json'], ['a.yaml'], 'a.json'):
        with pytest.raises(ValueError):
            normalize_playlist(bad)
    with pytest.raises(ValueError):
        normalize_playlist(['a.json'] * (MAX_PLAYLIST_LENGTH + 1))


def test_old_files_read_as_a_list_of_the_registered_file():
    assert playlist_from_mapping({'motion_file_id': 'a.json'}) == ['a.json']
    assert playlist_from_mapping({'motion_file_id': ''}) == []
    assert playlist_from_mapping({
        'motion_file_id': 'a.json', 'motion_playlist': ['a.json', 'b.json'],
    }) == ['a.json', 'b.json']
    assert playlist_from_mapping(None) == []


def test_save_writes_only_when_changed(tmp_path):
    mapping_file = tmp_path / 'store_a.yaml'
    mapping_file.write_text(MAPPING, encoding='utf-8')

    save_registered_playlist(mapping_file, ['a.json', 'b.json'], tmp_path / 'backup')
    assert load_registered_playlist(mapping_file) == ['a.json', 'b.json']
    assert save_registered_playlist(
        mapping_file, ['a.json', 'b.json'], tmp_path / 'backup',
    ) is None


# -- 재생기 ------------------------------------------------------------------ #

class _Logger:
    def error(self, _message):
        pass

    warn = warning = info = debug = error


def _manager():
    manager = MotionRunManager.__new__(MotionRunManager)
    manager._player = MotionPlayer(manager)
    manager.period_sec = 0.001
    manager._run_lock = threading.RLock()
    manager._stop_event = threading.Event()
    manager._graceful_stop_event = threading.Event()
    manager._status = motion_run_rules._empty_status()
    manager._execution_context = {}
    manager._execution_context_ready = True
    manager._automation_state = dict(default_automation_state())
    manager._automation_runtime = {'state': 'ready', 'message': '', 'stop_after_cycle': False}
    manager._automation_project_id = 'project'
    manager.motion_projects_dir = Path(tempfile.mkdtemp(prefix='playlist-'))
    manager._automation_store = MotionAutomationStore(manager.motion_projects_dir)
    manager._live_overrides = {}
    manager._live_override_lock = threading.Lock()
    manager._publish_status = lambda: None
    manager._player._require_playback_command_allowed = lambda axes=None: None
    manager._current_motors = lambda: []
    manager._player._prepare_motion_stream = lambda _motors, _axes: None
    manager._player._publish_motion_setpoints = lambda *_args, **_kwargs: None
    mock.patch.object(motion_run_rules, '_sleep_until', lambda _deadline: None).start()
    manager._player._current_servo_alarm_grade = lambda: 0
    manager.get_logger = lambda: _Logger()
    return manager


def _plan(name, *, playlist=('a.json', 'b.json', 'c.json'), target=0, init=False):
    return {
        'name': f'init:{name}' if init else name,
        'project_id': 'project',
        'request_source': 'motion_run',
        'motion_file_id': name,
        'mapping_file_id': 'store_a.yaml',
        'motion_playlist': list(playlist),
        'run_mode': 'continuous',
        'automation_run': False,
        'repeat_mode': 'direct',
        'dwell_sec': 0.0,
        'synchronized_repeat_count': 0,
        'axes': [],
        'samples': [{'time_sec': 0.0, 'positions': {}, 'motion_values': {}}],
        'warnings': [],
        'capabilities': {},
        'summary': {'duration_sec': 0.0, 'sample_count': 1, 'target_cycle_count': target},
    }


def _builder(manager, built, *, target=0, broken=''):
    def build(payload, initialization_only=False, motors_snapshot=None):
        name = payload['motion_file_id']
        if name == broken:
            raise ValueError('파일이 깨졌습니다')
        built.append((name, initialization_only))
        return _plan(name, target=target, init=initialization_only)

    manager._plan_builder = mock.Mock(build=build)


def test_every_item_is_built_once_at_start_in_list_order():
    manager = _manager()
    built = []
    _builder(manager, built)
    first = _plan('a.json', playlist=('a.json', 'b.json', 'a.json'))

    entries = manager._player._build_playlist_entries(
        {'motion_file_id': 'a.json'}, first, _plan('a.json', init=True), [],
    )

    assert [plan['motion_file_id'] for plan, _ in entries] == ['a.json', 'b.json', 'a.json']
    assert [plan['playlist_index'] for plan, _ in entries] == [0, 1, 2]
    assert [init['playlist_index'] for _, init in entries] == [0, 1, 2]
    # 첫 항목은 이미 만든 계획 · 같은 파일 두 번은 한 번만 계산
    assert built == [('b.json', False), ('b.json', True)]
    assert entries[0][0]['samples'] is entries[2][0]['samples']


def test_broken_item_refuses_the_start_and_names_the_file():
    manager = _manager()
    _builder(manager, [], broken='c.json')

    with pytest.raises(ValueError, match='3번 c.json'):
        manager._player._build_playlist_entries(
            {'motion_file_id': 'a.json'}, _plan('a.json'), _plan('a.json', init=True), [],
        )


def test_single_file_and_one_shot_runs_keep_the_old_path():
    manager = _manager()
    _builder(manager, [])
    once = {**_plan('a.json'), 'run_mode': 'once'}
    single = _plan('a.json', playlist=('a.json',))
    other = _plan('b.json')  # 목록 1번이 아닌 파일 · 목록을 쓰지 않는다

    for plan in (once, single, other):
        assert manager._player._build_playlist_entries({}, plan, plan, []) == []


def test_playlist_plays_in_order_and_moves_to_each_first_frame_between():
    manager = _manager()
    _builder(manager, [], target=4)
    order = []
    inits = []

    def trace_begin(plan, _cycle):
        status = manager.status()
        order.append((plan['motion_file_id'], status['motion_file_id'], status['playlist_index']))

    def initialize(plan):
        inits.append(plan['name'])
        manager._status = {**manager._status, 'state': 'initialized'}

    manager._player._trace_begin = trace_begin
    manager._player._run_initialization = initialize
    first = _plan('a.json', target=4)
    entries = manager._player._build_playlist_entries(
        {'motion_file_id': 'a.json'}, first, _plan('a.json', init=True), [],
    )

    manager._player._run_motion(entries[0][0], entries[0][1], entries)

    assert order == [
        ('a.json', 'a.json', 0),
        ('b.json', 'b.json', 1),
        ('c.json', 'c.json', 2),
        ('a.json', 'a.json', 0),
    ]
    # 반복 방식이 「바로 다음」이어도 파일이 바뀌면 늘 초기 위치 이동
    assert inits == ['init:b.json', 'init:c.json', 'init:a.json']
    assert manager.status()['state'] == 'completed'
    assert manager.status()['cycle_count'] == 4


def test_independent_group_counts_its_own_cycles():
    manager = _manager()
    cycles = []
    manager._player._trace_begin = lambda plan, cycle: cycles.append(
        motion_run_rules._playback_cycle_number(plan, cycle)
    )
    plan = {
        **_plan('a.json', playlist=('a.json',), target=3),
        'group_execution': True,
        'group_cycle_number': 1,
        'independent_group': True,
    }

    manager._player._run_motion(plan)

    assert cycles == [1, 2, 3]


# -- 그룹 · 각자 재생 --------------------------------------------------------- #

def test_independent_session_hands_the_list_to_the_local_loop_then_reports_stop():
    manager = _manager()
    manager._run_thread = None
    session = GroupSession(manager, run_lock=manager._run_lock)
    session.session = {'active': True, 'execution_id': 'exec-1'}
    calls = []

    def run_motion(plan, init, entries=None):
        calls.append((plan, init, entries))
        manager._status = {**manager._status, 'state': 'completed', 'message': '모션 실행 완료'}

    manager._player._run_motion = run_motion
    entries = [
        (_plan('a.json'), _plan('a.json', init=True)),
        (_plan('b.json'), _plan('b.json', init=True)),
    ]
    context = {
        'scheduled_start_at': 0.0, 'group_execution': True,
        'execution_id': 'exec-1', 'group_cycle_number': 1,
    }

    session._run_independent(entries[0][0], entries[0][1], entries, context)

    plan, init, handed = calls[0]
    assert plan['motion_file_id'] == 'a.json'
    assert init['name'] == 'init:a.json'
    assert [item[0]['motion_file_id'] for item in handed] == ['a.json', 'b.json']
    assert all(item[0]['independent_group'] and item[1]['execution_id'] == 'exec-1' for item in handed)
    # 끝나면 「정지」 단계 · 조정 노드가 이것을 보고 그룹 해제를 센다
    assert manager.status()['phase'] == 'stopped'
    assert session.session['independent'] is True


def test_independent_stop_after_cycle_does_not_cut_the_move_between_items():
    manager = _manager()
    session = GroupSession(manager, run_lock=manager._run_lock)
    session.session = {'active': True, 'execution_id': 'exec-1', 'independent': True}

    assert session.request_stop_after_cycle({'state': 'initializing'}) is True
    assert manager._graceful_stop_event.is_set()
    assert not manager._stop_event.is_set()

    session.session = {'active': True, 'execution_id': 'exec-2'}
    manager._graceful_stop_event.clear()
    session.request_stop_after_cycle({'state': 'initializing'})
    assert manager._stop_event.is_set()  # 회차 맞춤은 옛 동작 그대로
