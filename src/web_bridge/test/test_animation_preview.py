"""MuJoCo 미리보기 · 계산(precompute)과 재생(preview)은 현장 명령이다 · P7

로봇마다 모델·시뮬레이터가 다르므로 플랫폼은 명령 틀과 결과 경로만 안다 ·
뷰어는 **계산이 끝난 것만** 튼다 · 계산 중엔 computing(화면은 그레이) ·
실행은 발사 후 망각 · 셸을 거치지 않아 파일 이름이 명령으로 둔갑하지 않는다.
"""

from pathlib import Path
from types import SimpleNamespace

from motion_web_bridge import animation_preview

BRIDGE_DIR = Path(__file__).resolve().parents[1] / 'motion_web_bridge'
ROUTES_DIR = BRIDGE_DIR / 'routes'

GATED = (
    'precompute:\n'
    '  command:\n'
    '    - simulate\n'
    "    - '{motion_path}'\n"
    "    - '{motion_stem}.sim.csv'\n"
    "  result: '{motion_stem}.sim.npz'\n"
    'preview:\n'
    '  command:\n'
    '    - viewer\n'
    "    - '{result}'\n"
    "    - '{fps}'\n"
    'fps: 60\n'
)


def _workspace(tmp_path, config_text=None):
    if config_text is not None:
        (tmp_path / 'config').mkdir(exist_ok=True)
        (tmp_path / 'config' / 'animation_preview.yaml').write_text(
            config_text, encoding='utf-8',
        )
    return tmp_path


def _motion(tmp_path, name='demo.json'):
    motion = tmp_path / name
    motion.write_text('{}', encoding='utf-8')
    return motion


def _no_spawn(*args, **kwargs):
    raise AssertionError('실행되면 안 되는 경우다')


def setup_function(_):
    # 모듈 전역 실행부(도는 계산 기록)를 시험마다 비운다
    animation_preview._RUNNING.clear()
    animation_preview._LAST_RC.clear()
    animation_preview._PENDING_META.clear()
    animation_preview._VIEWERS.clear()


def test_without_config_the_button_says_why(tmp_path):
    result = animation_preview.launch_preview(
        _workspace(tmp_path), _motion(tmp_path), spawn=_no_spawn,
    )
    assert result['success'] is False
    assert 'animation_preview.yaml' in result['message']


def test_viewer_refuses_until_the_computation_result_exists(tmp_path):
    workspace = _workspace(tmp_path, GATED)
    motion = _motion(tmp_path)
    result = animation_preview.launch_preview(workspace, motion, spawn=_no_spawn)
    assert result['success'] is False
    assert '계산' in result['message']
    assert animation_preview.preview_state(workspace, motion)['state'] == 'missing'


def test_precompute_runs_once_and_marks_computing(tmp_path):
    workspace = _workspace(tmp_path, GATED)
    motion = _motion(tmp_path)
    spawned = []

    def spawn(args, **kwargs):
        spawned.append((args, kwargs))
        return SimpleNamespace(poll=lambda: None)   # 아직 도는 중

    first = animation_preview.launch_precompute(workspace, motion, spawn=spawn)
    assert first['success'] is True
    second = animation_preview.launch_precompute(workspace, motion, spawn=_no_spawn)
    assert '이미 계산 중' in second['message']
    assert animation_preview.preview_state(workspace, motion)['state'] == 'computing'
    # 계산 중엔 재생도 거부 · 화면은 그레이
    refused = animation_preview.launch_preview(workspace, motion, spawn=_no_spawn)
    assert refused['success'] is False and '계산 중' in refused['message']
    [(args, kwargs)] = spawned
    stem = str(motion)[: -len('.json')]
    assert args == ['simulate', str(motion), f'{stem}.sim.csv']
    assert kwargs['shell'] is False


def test_finished_computation_turns_ready_and_the_viewer_plays_the_result(tmp_path):
    workspace = _workspace(tmp_path, GATED)
    motion = _motion(tmp_path)
    stem = str(motion)[: -len('.json')]
    Path(f'{stem}.sim.npz').write_bytes(b'npz')
    assert animation_preview.preview_state(workspace, motion)['state'] == 'ready'
    spawned = []
    result = animation_preview.launch_preview(
        workspace, motion, fps=144,
        spawn=lambda args, **kwargs: spawned.append(args),
    )
    assert result['success'] is True
    [args] = spawned
    assert args == ['viewer', f'{stem}.sim.npz', '144']


def test_viewer_handle_is_kept_and_the_close_button_ends_it(tmp_path):
    """뷰어는 발사 후 망각이 아니다 · 핸들을 보관하고 「MuJoCo 창 닫기」가 끝낸다 · 7-1"""
    workspace = _workspace(tmp_path, GATED)
    motion = _motion(tmp_path)
    Path(f'{str(motion)[: -len(".json")]}.sim.npz').write_bytes(b'npz')
    events = []

    class _Viewer:
        def __init__(self):
            self.alive = True
        def poll(self):
            return None if self.alive else 0
        def terminate(self):
            events.append('terminate')
            self.alive = False
        def wait(self, timeout=None):
            return 0
        def kill(self):
            events.append('kill')

    viewer = _Viewer()
    assert animation_preview.launch_preview(
        workspace, motion, spawn=lambda *a, **k: viewer,
    )['success'] is True
    assert animation_preview.preview_state(workspace, motion)['viewer_running'] is True
    # 떠 있는 동안은 또 띄우지 않는다
    again = animation_preview.launch_preview(workspace, motion, spawn=_no_spawn)
    assert again['success'] is True and '이미 떠 있습니다' in again['message']

    stopped = animation_preview.stop_preview(motion)
    assert stopped['stopped'] == 1 and events == ['terminate']
    assert animation_preview.preview_state(workspace, motion)['viewer_running'] is False
    # 닫을 것이 없어도 실패가 아니다
    assert animation_preview.stop_preview(motion) == {
        'success': True, 'stopped': 0, 'message': '떠 있는 MuJoCo 창이 없습니다',
    }


def test_viewer_that_exited_on_its_own_is_forgotten(tmp_path):
    workspace = _workspace(tmp_path, GATED)
    motion = _motion(tmp_path)
    Path(f'{str(motion)[: -len(".json")]}.sim.npz').write_bytes(b'npz')
    animation_preview.launch_preview(
        workspace, motion, spawn=lambda *a, **k: SimpleNamespace(poll=lambda: 0),
    )
    assert animation_preview.viewer_running(motion) is False
    assert animation_preview.stop_preview()['stopped'] == 0


def test_precompute_and_viewer_output_go_to_a_log_file_not_devnull(tmp_path):
    """실패 사유가 보여야 한다 · stdout·stderr 를 log/animation_preview/ 에 남긴다 · 7-1"""
    workspace = _workspace(tmp_path, GATED)
    motion = _motion(tmp_path)
    spawned = []

    def spawn(args, **kwargs):
        spawned.append(kwargs)
        kwargs['stderr'].write(b'boom\n')
        return SimpleNamespace(poll=lambda: 1)

    animation_preview.launch_precompute(workspace, motion, spawn=spawn)
    log = animation_preview.log_path_for(workspace, motion, 'precompute')
    assert log == workspace / 'log' / 'animation_preview' / 'demo.precompute.log'
    assert log.read_bytes() == b'boom\n'
    assert spawned[0]['stdout'] is spawned[0]['stderr']
    assert spawned[0]['stderr'].closed   # 부모 쪽 핸들은 닫는다

    Path(f'{str(motion)[: -len(".json")]}.sim.npz').write_bytes(b'npz')
    animation_preview.launch_preview(workspace, motion, spawn=spawn)
    assert animation_preview.log_path_for(workspace, motion, 'preview').read_bytes() == b'boom\n'


def test_a_failed_computation_is_named_not_hidden(tmp_path):
    workspace = _workspace(tmp_path, GATED)
    motion = _motion(tmp_path)
    animation_preview.launch_precompute(
        workspace, motion,
        spawn=lambda *a, **k: SimpleNamespace(poll=lambda: 3),   # 바로 실패로 끝남
    )
    state = animation_preview.preview_state(workspace, motion)
    assert state['state'] == 'failed'
    assert '실패' in state['message']


def test_fps_only_accepts_the_four_screen_choices():
    config = {'fps': 60}
    assert animation_preview.normalized_fps(config, 144) == 144
    assert animation_preview.normalized_fps(config, 30) == 30
    # 허용 밖·쓰레기 값은 설정 기본으로
    assert animation_preview.normalized_fps(config, 999) == 60
    assert animation_preview.normalized_fps(config, 'x') == 60
    assert animation_preview.normalized_fps({'fps': 7}, None) == 60


def test_legacy_single_command_config_plays_directly(tmp_path):
    workspace = _workspace(tmp_path, (
        'command:\n'
        '  - viewer\n'
        "  - '{motion_path}'\n"
        "  - '{fps}'\n"
    ))
    motion = _motion(tmp_path)
    assert animation_preview.preview_state(workspace, motion)['state'] == 'direct'
    spawned = []
    result = animation_preview.launch_preview(
        workspace, motion, fps=30,
        spawn=lambda args, **kwargs: spawned.append(args),
    )
    assert result['success'] is True
    assert spawned == [['viewer', str(motion), '30']]


def test_listing_annotation_marks_each_file(tmp_path):
    workspace = _workspace(tmp_path, GATED)
    files_dir = tmp_path / 'motions'
    files_dir.mkdir()
    ready = files_dir / 'ready.json'
    ready.write_text('{}', encoding='utf-8')
    Path(str(ready)[:-len('.json')] + '.sim.npz').write_bytes(b'npz')
    (files_dir / 'raw.json').write_text('{}', encoding='utf-8')
    payload = {'files': [{'id': 'ready.json'}, {'id': 'raw.json'}]}
    out = animation_preview.annotate_files(workspace, files_dir, payload)
    assert out['files'][0]['preview']['state'] == 'ready'
    assert out['files'][1]['preview']['state'] == 'missing'


def test_detail_annotation_marks_file_and_listing(tmp_path):
    """상세 응답도 목록과 같은 MuJoCo 상태 · 화면이 이 `files` 로 목록을 덮어쓴다."""
    workspace = _workspace(tmp_path, GATED)
    files_dir = tmp_path / 'motions'
    files_dir.mkdir()
    ready = files_dir / 'ready.json'
    ready.write_text('{}', encoding='utf-8')
    Path(str(ready)[:-len('.json')] + '.sim.npz').write_bytes(b'npz')
    payload = {'file': {'id': 'ready.json'}, 'files': [{'id': 'ready.json'}]}
    out = animation_preview.annotate_files(workspace, files_dir, payload)
    assert out['file']['preview']['state'] == 'ready'
    assert out['files'][0]['preview']['state'] == 'ready'


def test_bridge_launches_the_companion_when_playback_turns_running():
    """같이 보기 = 모터가 running 으로 바뀌는 그 순간 뷰어를 띄운다 ·
    초기 이동이 끝난 시점이라 양쪽 다 프레임 1 부터 출발한다."""
    bridge = (BRIDGE_DIR / 'bridge_node.py').read_text(encoding='utf-8')
    assert "payload.pop('with_mujoco', False)" in bridge
    assert 'def _arm_mujoco_companion(' in bridge
    assert 'def _maybe_launch_mujoco_companion(' in bridge
    # 상태가 들어오는 두 길목 모두에서 본다
    assert bridge.count('self._maybe_launch_mujoco_companion(') >= 2
    # 계산 안 끝났으면 예약 자체를 거절한다
    assert 'MuJoCo 같이 보기는 계산이 끝난 뒤에' in bridge
    routes = (ROUTES_DIR / 'motion_run_routes.py').read_text(encoding='utf-8')
    assert "@app.post('/api/motion-files/{file_id}/preview')" in routes
    assert "@app.post('/api/motion-files/{file_id}/preview-precompute')" in routes
    assert "@app.post('/api/motion-files/{file_id}/preview-stop')" in routes
    assert 'def stop_preview_motion_file(' in bridge
    assert routes.count('animation_preview.annotate_files') >= 2


# --------------------------------------------------------------------------- #
# 로봇 팩 · 팩 preview.yaml 우선 · {stack} {pack} 치환 · 팩이 바뀌면 다시 계산 필요
# --------------------------------------------------------------------------- #

PACK_PREVIEW = (
    'precompute:\n'
    '  command:\n'
    "    - '{stack}/scripts/sim/sim_run.py'\n"
    "    - '{pack}'\n"
    "    - '{motion_path}'\n"
    "  result: '{motion_stem}.sim.npz'\n"
    'preview:\n'
    '  command:\n'
    "    - '{stack}/scripts/sim/replay_run.py'\n"
    "    - '{result}'\n"
)


def _pack(workspace, preview=PACK_PREVIEW, version='1.0', model='<mujoco/>'):
    pack = workspace / 'robot_pack'
    pack.mkdir(exist_ok=True)
    (pack / 'pack.yaml').write_text(
        f"name: demo\nversion: '{version}'\ncreated: '2026-10-02'\n", encoding='utf-8',
    )
    (pack / 'robot.yaml').write_text('axes: []\n', encoding='utf-8')
    (pack / 'model.xml').write_text(model, encoding='utf-8')
    if preview is not None:
        (pack / 'preview.yaml').write_text(preview, encoding='utf-8')
    return pack


def _finished_run(spawned):
    def spawn(args, **kwargs):
        spawned.append((args, kwargs))
        return SimpleNamespace(poll=lambda: 0)
    return spawn


def test_pack_preview_wins_over_the_pc_config(tmp_path):
    workspace = _workspace(tmp_path, GATED)
    pack = _pack(workspace)
    motion = _motion(tmp_path)
    spawned = []
    result = animation_preview.launch_precompute(workspace, motion, spawn=_finished_run(spawned))
    assert result['success'] is True
    [(args, kwargs)] = spawned
    assert args == [f'{workspace}/scripts/sim/sim_run.py', str(pack), str(motion)]
    assert kwargs['cwd'] == str(pack)          # 팩 쪽 cwd 기본값 = 팩 폴더


def test_pc_config_is_used_when_the_pack_has_no_preview(tmp_path):
    workspace = _workspace(tmp_path, GATED)
    _pack(workspace, preview=None)
    config = animation_preview.preview_config(workspace)
    assert config['_source'] == 'config'
    assert config['precompute']['command'][0] == 'simulate'


def test_result_from_the_same_pack_is_ready(tmp_path):
    workspace = _workspace(tmp_path)
    _pack(workspace)
    motion = _motion(tmp_path)
    animation_preview.launch_precompute(workspace, motion, spawn=_finished_run([]))
    result = Path(str(motion)[:-len('.json')] + '.sim.npz')
    result.write_bytes(b'npz')
    state = animation_preview.preview_state(workspace, motion)   # 거두면서 meta 기록
    assert state['state'] == 'ready'
    meta = animation_preview.meta_path_for(result)
    assert meta.name == 'demo.sim.meta.json'
    assert '"version": "1.0"' in meta.read_text(encoding='utf-8')


def test_changing_the_pack_marks_results_stale_but_viewable(tmp_path):
    workspace = _workspace(tmp_path)
    _pack(workspace)
    motion = _motion(tmp_path)
    animation_preview.launch_precompute(workspace, motion, spawn=_finished_run([]))
    Path(str(motion)[:-len('.json')] + '.sim.npz').write_bytes(b'npz')
    assert animation_preview.preview_state(workspace, motion)['state'] == 'ready'

    _pack(workspace, version='2.0', model='<mujoco model="new"/>')
    state = animation_preview.preview_state(workspace, motion)
    assert state['state'] == 'stale'
    assert 'demo 1.0' in state['message']
    spawned = []
    viewed = animation_preview.launch_preview(
        workspace, motion, spawn=lambda args, **kwargs: spawned.append(args),
    )
    assert viewed['success'] is True and spawned


def test_failed_recompute_does_not_bless_the_old_result(tmp_path):
    workspace = _workspace(tmp_path)
    _pack(workspace)
    motion = _motion(tmp_path)
    Path(str(motion)[:-len('.json')] + '.sim.npz').write_bytes(b'npz')   # 팩 기록 없는 옛 결과
    assert animation_preview.preview_state(workspace, motion)['state'] == 'stale'
    animation_preview.launch_precompute(
        workspace, motion, spawn=lambda *a, **k: SimpleNamespace(poll=lambda: 1),
    )
    assert animation_preview.preview_state(workspace, motion)['state'] == 'stale'


def test_without_a_pack_nothing_is_stale(tmp_path):
    workspace = _workspace(tmp_path, GATED)
    motion = _motion(tmp_path)
    Path(str(motion)[:-len('.json')] + '.sim.npz').write_bytes(b'npz')
    assert animation_preview.preview_state(workspace, motion)['state'] == 'ready'
