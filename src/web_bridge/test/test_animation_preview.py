"""애니메이션 미리보기 · 현장이 정한 명령에 경로만 끼워 띄운다 · P7

플랫폼은 시뮬레이터를 모른다 · 설정이 없으면 버튼이 사유를 말하고,
실행은 발사 후 망각이다(뷰어를 기다리면 브리지가 묶인다) · 셸을 거치지
않아 파일 이름이 명령으로 둔갑하지 않는다.
"""

from pathlib import Path

from motion_web_bridge import animation_preview

BRIDGE_DIR = Path(__file__).resolve().parents[1] / 'motion_web_bridge'
ROUTES_DIR = BRIDGE_DIR / 'routes'


def _workspace(tmp_path, config_text=None):
    if config_text is not None:
        (tmp_path / 'config').mkdir()
        (tmp_path / 'config' / 'animation_preview.yaml').write_text(
            config_text, encoding='utf-8',
        )
    return tmp_path


def _motion(tmp_path):
    motion = tmp_path / 'demo.json'
    motion.write_text('{}', encoding='utf-8')
    return motion


def test_without_config_the_button_says_why(tmp_path):
    result = animation_preview.launch_preview(
        _workspace(tmp_path), _motion(tmp_path), spawn=lambda *a, **k: None,
    )
    assert result['success'] is False
    assert 'animation_preview.yaml' in result['message']


def test_placeholders_are_filled_and_no_shell_is_used(tmp_path):
    workspace = _workspace(tmp_path, (
        'command:\n'
        '  - viewer\n'
        "  - '{motion_path}'\n"
        "  - '{fps}'\n"
        'fps: 42\n'
    ))
    motion = _motion(tmp_path)
    calls = []

    def spawn(args, **kwargs):
        calls.append((args, kwargs))

    result = animation_preview.launch_preview(workspace, motion, spawn=spawn)
    assert result['success'] is True
    [(args, kwargs)] = calls
    assert args == ['viewer', str(motion), '42']
    assert kwargs['shell'] is False
    assert kwargs['cwd'] == str(workspace)


def test_cwd_from_config_and_missing_file_is_refused(tmp_path):
    workspace = _workspace(tmp_path, (
        'command:\n'
        '  - viewer\n'
        "  - '{motion_path}'\n"
        f'cwd: {tmp_path}\n'
    ))
    missing = tmp_path / '없는파일.json'
    result = animation_preview.launch_preview(
        workspace, missing, spawn=lambda *a, **k: None,
    )
    assert result['success'] is False
    assert '없는파일' in result['message']


def test_a_broken_config_counts_as_not_configured(tmp_path):
    workspace = _workspace(tmp_path, 'command: 문자열하나\n')
    result = animation_preview.launch_preview(
        workspace, _motion(tmp_path), spawn=lambda *a, **k: None,
    )
    assert result['success'] is False
    assert 'animation_preview.yaml' in result['message']


def test_route_and_bridge_are_wired():
    bridge = (BRIDGE_DIR / 'bridge_node.py').read_text(encoding='utf-8')
    assert 'def preview_motion_file(self, file_id' in bridge
    assert 'animation_preview.launch_preview(self.workspace_root, motion_path)' in bridge
    routes = (ROUTES_DIR / 'motion_run_routes.py').read_text(encoding='utf-8')
    assert "@app.post('/api/motion-files/{file_id}/preview')" in routes
