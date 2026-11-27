"""웹 3D 표시 · 장면·프레임 서버 쪽 · 수정 목록 7-a (2026-10-04)

    장면    팩 지문마다 runtime/preview/scene-<지문>.json · uv + MuJoCo 로 1회 · 상태 5가지
    프레임  .sim.npz 의 t · qpos → JSON · 60 Hz 로 솎음 · 없으면 success False
"""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from motion_web_bridge import animation_preview, sim_scene

BRIDGE_DIR = Path(__file__).resolve().parents[1] / 'motion_web_bridge'
GATED = (
    'precompute:\n  command: [simulate, "{motion_path}"]\n  result: "{motion_stem}.sim.npz"\n'
    'preview:\n  command: [viewer, "{result}"]\n'
)


def _pack(workspace):
    pack = workspace / 'robot_pack'
    pack.mkdir(exist_ok=True)
    (pack / 'pack.yaml').write_text("name: demo\nversion: '1.0'\ncreated: '2026-10-04'\n", encoding='utf-8')
    (pack / 'robot.yaml').write_text('axes: []\n', encoding='utf-8')
    (pack / 'model.xml').write_text('<mujoco/>', encoding='utf-8')
    return pack


def setup_function(_):
    sim_scene._RUNNING.clear()
    sim_scene._LAST_RC.clear()


def test_without_a_pack_the_scene_is_unavailable(tmp_path):
    assert sim_scene.scene_path(tmp_path) is None
    assert sim_scene.scene_state(tmp_path)['state'] == 'unavailable'
    assert sim_scene.launch_scene_export(tmp_path)['success'] is False


def test_scene_path_follows_the_pack_fingerprint(tmp_path):
    pack = _pack(tmp_path)
    first = sim_scene.scene_path(tmp_path)
    assert first.parent == tmp_path / 'runtime' / 'preview'
    (pack / 'model.xml').write_text('<mujoco model="b"/>', encoding='utf-8')
    assert sim_scene.scene_path(tmp_path) != first


def test_export_runs_the_uv_command_once_and_turns_ready_when_the_file_appears(tmp_path):
    _pack(tmp_path)
    spawned = []

    def spawn(args, **kwargs):
        spawned.append((args, kwargs))
        return SimpleNamespace(poll=lambda: None)

    assert sim_scene.scene_state(tmp_path)['state'] == 'missing'
    started = sim_scene.launch_scene_export(tmp_path, spawn=spawn)
    assert started['success'] is True
    assert sim_scene.scene_state(tmp_path)['state'] == 'computing'
    again = sim_scene.launch_scene_export(tmp_path, spawn=lambda *a, **k: pytest.fail('두 번 돌면 안 된다'))
    assert again['success'] is True
    [(args, kwargs)] = spawned
    assert args[:3] == ['uv', 'run', '--no-project'] and '--with=mujoco' in args
    assert args[-3].endswith('scripts/sim/export_scene.py')
    assert args[-2] == str(tmp_path / 'robot_pack')
    assert args[-1] == str(sim_scene.scene_path(tmp_path))
    assert kwargs['shell'] is False and kwargs['stderr'] is kwargs['stdout']
    # 출력은 기록 파일로 간다 (7-1 과 같은 자리)
    assert animation_preview.log_path_for(tmp_path, Path('scene.json'), 'scene').exists()

    path = sim_scene.scene_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"version": 1, "bodies": []}', encoding='utf-8')
    sim_scene._RUNNING.clear()
    assert sim_scene.scene_state(tmp_path)['state'] == 'ready'
    assert sim_scene.read_scene(tmp_path) == {'version': 1, 'bodies': []}


def test_a_failed_export_is_named(tmp_path):
    _pack(tmp_path)
    sim_scene.launch_scene_export(tmp_path, spawn=lambda *a, **k: SimpleNamespace(poll=lambda: 2))
    state = sim_scene.scene_state(tmp_path)
    assert state['state'] == 'failed' and '코드 2' in state['message']


def test_scene_command_can_come_from_the_preview_config(tmp_path):
    _pack(tmp_path)
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / 'animation_preview.yaml').write_text(
        GATED + "scene:\n  command: [my_export, '{pack}', '{result}']\n", encoding='utf-8',
    )
    spawned = []
    sim_scene.launch_scene_export(tmp_path, spawn=lambda args, **k: spawned.append(args) or SimpleNamespace(poll=lambda: None))
    assert spawned == [['my_export', str(tmp_path / 'robot_pack'), str(sim_scene.scene_path(tmp_path))]]


def _write_npz(motion, hz=100.0, seconds=2.0, nq=3):
    n = int(seconds * hz) + 1
    t = np.arange(n) / hz
    qpos = np.stack([np.sin(t), np.cos(t), t], axis=1)
    np.savez(f'{str(motion)[:-5]}.sim.npz', t=t, qpos=qpos, n_frames=100, ref='pp')
    return t, qpos


def test_frames_are_read_from_the_npz_and_thinned_to_sixty_hertz(tmp_path):
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / 'animation_preview.yaml').write_text(GATED, encoding='utf-8')
    motion = tmp_path / 'show.json'
    motion.write_text('{}', encoding='utf-8')
    t, qpos = _write_npz(motion)

    payload = sim_scene.frames_payload(tmp_path, motion)

    assert payload['success'] is True
    assert payload['nq'] == 3 and payload['n_frames'] == 100 and payload['ref'] == 'pp'
    assert payload['duration_sec'] == 2.0
    assert payload['hz'] == 50.0                      # 100 Hz → 2배 솎음
    assert len(payload['t']) == len(payload['qpos']) == 101
    assert payload['t'][1] == 0.02
    assert payload['qpos'][0] == [0.0, 1.0, 0.0]


def test_missing_result_or_config_says_so(tmp_path):
    motion = tmp_path / 'show.json'
    motion.write_text('{}', encoding='utf-8')
    assert sim_scene.frames_payload(tmp_path, motion)['success'] is False
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / 'animation_preview.yaml').write_text(GATED, encoding='utf-8')
    missing = sim_scene.frames_payload(tmp_path, motion)
    assert missing['success'] is False and 'MuJoCo 계산' in missing['message']


def test_routes_and_bridge_methods_exist_for_the_screen():
    routes = (BRIDGE_DIR / 'routes' / 'motion_run_routes.py').read_text(encoding='utf-8')
    bridge = (BRIDGE_DIR / 'bridge_node.py').read_text(encoding='utf-8')
    for route in ("'/api/preview/scene'", "'/api/preview/scene/export'", "'/api/preview/scene/data'",
                  "'/api/motion-files/{file_id}/preview-frames'"):
        assert route in routes, route
    for method in ('def preview_scene_state(', 'def preview_scene_export(', 'def preview_scene_path(',
                   'def preview_motion_frames('):
        assert method in bridge, method


# Blender 뷰 · 팩의 scene.glb 를 그대로 내준다 · 수정 목록 50

def test_blender_scene_is_reported_only_when_the_pack_has_one(tmp_path):
    assert sim_scene.scene_state(tmp_path)['blender'] == {'available': False}
    pack = _pack(tmp_path)
    assert sim_scene.blender_scene_path(tmp_path) is None
    assert sim_scene.scene_state(tmp_path)['blender'] == {'available': False}
    (pack / 'scene.glb').write_bytes(b'glTF' + b'\x00' * 20)
    info = sim_scene.scene_state(tmp_path)['blender']
    assert info['available'] is True
    assert info['size_bytes'] == 24
    assert len(info['fingerprint']) == 16
    assert sim_scene.blender_scene_path(tmp_path) == pack / 'scene.glb'
    # MuJoCo 장면 상태는 그대로 · Blender 뷰는 계산 없이 따로
    assert sim_scene.scene_state(tmp_path)['state'] == 'missing'


def test_blender_scene_route_streams_the_file():
    routes = (BRIDGE_DIR / 'routes' / 'motion_run_routes.py').read_text(encoding='utf-8')
    assert "@app.get('/api/preview/blender-scene')" in routes
    assert "media_type='model/gltf-binary'" in routes
    bridge = (BRIDGE_DIR / 'bridge_node.py').read_text(encoding='utf-8')
    assert 'return sim_scene.blender_scene_path(self.workspace_root)' in bridge


def test_blender_scene_names_the_animations_it_holds(tmp_path):
    """수정 목록 60 · pack.yaml scene_glb.animations · 없으면 빈 목록(화면이 Blender 뷰를 끈다)"""
    from motion_common import robot_pack

    pack = _pack(tmp_path)
    (pack / 'scene.glb').write_bytes(b'glTF' + b'\x00' * 20)
    assert sim_scene.scene_state(tmp_path)['blender']['animations'] == []
    text = (pack / 'pack.yaml').read_text(encoding='utf-8')
    (pack / 'pack.yaml').write_text(text + '\nscene_glb:\n  animations: [floating_narration_all]\n', encoding='utf-8')
    assert sim_scene.scene_state(tmp_path)['blender']['animations'] == ['floating_narration_all']
    assert robot_pack.scene_glb_animations(pack) == ['floating_narration_all']
