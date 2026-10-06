"""화면 없는 시작(스케줄)은 재생 목록 1번부터 · 수정 목록 35 (2026-10-06)

스케줄은 무엇을 돌릴지 모른다 · 브리지가 채운다. 채울 값은 매핑 파일의
재생 등록(`motion_file_id` = 목록 1번)이다 · 프로젝트의 활성 애니(마지막에
화면에서 고른 파일)가 목록 밖이면 재생 계획이 「재생 등록에 없는 애니」로
거절한다.
"""

import threading
from types import SimpleNamespace

from motion_web_bridge.bridge_node import MotionWebBridge


def _bridge(tmp_path, mapping_text):
    mapping_file = tmp_path / 'store_a.yaml'
    mapping_file.write_text(mapping_text, encoding='utf-8')
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge._lock = threading.RLock()
    bridge.project_repository = SimpleNamespace(
        selected_project_id=lambda: 'project-1',
        execution_context=lambda _project_id: {'files': {
            'motions': {'name': 'last_viewed.json'},
            'motion_axis_matching': {'name': 'store_a.yaml'},
        }},
        export_path=lambda _project, _kind, name: tmp_path / name,
    )
    return bridge


def test_missing_motion_file_is_filled_with_the_first_playlist_item(tmp_path):
    bridge = _bridge(
        tmp_path,
        'motion_file_id: a.json\nmotion_playlist:\n- a.json\n- b.json\nmappings: []\n',
    )

    filled = bridge._with_active_project_files({'run_mode': 'continuous'})

    assert filled['motion_file_id'] == 'a.json'
    assert filled['mapping_file_id'] == 'store_a.yaml'


def test_explicit_motion_file_is_kept(tmp_path):
    bridge = _bridge(tmp_path, 'motion_file_id: a.json\nmappings: []\n')

    filled = bridge._with_active_project_files({'motion_file_id': 'b.json'})

    assert filled['motion_file_id'] == 'b.json'


def test_without_registration_the_active_file_is_used_as_before(tmp_path):
    bridge = _bridge(tmp_path, 'motion_file_id: ""\nmappings: []\n')

    assert bridge._with_active_project_files({})['motion_file_id'] == 'last_viewed.json'
