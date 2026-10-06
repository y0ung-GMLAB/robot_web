"""프로젝트 폴더는 `motion_common.paths` 하나가 정한다 · 수정 목록 32 (2026-10-06)

전에는 브리지·실행 노드가 파라미터로 받고 스케줄 노드는 함수로 계산했다 · 파라미터만
바꾸면 스케줄이 다른 폴더를 봐서 아무 일도 안 일어났다.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_no_node_or_launch_takes_a_projects_dir_parameter():
    sources = [
        *ROOT.glob('src/*/launch/*.py'),
        ROOT / 'src/web_bridge/motion_web_bridge/bridge_node.py',
        ROOT / 'src/motion_runtime/motion_runtime/motion_mapping_manager.py',
        ROOT / 'src/motion_runtime/motion_runtime/motion_run_manager.py',
        ROOT / 'scripts/restart_motion_monitor.sh',
    ]
    offenders = [
        str(path.relative_to(ROOT)) for path in sources
        if "'motion_projects_dir'" in path.read_text(encoding='utf-8').replace(
            "'motion_projects_dir': str(Path(getattr(self, 'motion_projects_dir'", ''
        ) or 'motion_projects_dir:=' in path.read_text(encoding='utf-8')
    ]
    assert offenders == []
