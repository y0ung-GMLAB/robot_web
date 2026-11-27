"""매핑을 열 때 주는 버전은 파일 그대로 · 수정 목록 105 (실물 2026-10-12 · floating4)

검사(`_validate_mapping`)가 「첫 프레임」 줄에 재생 목록 첫 애니메이션의 첫 프레임 값을 써 넣는다 ·
전에는 그 뒤에 버전을 세어 화면에 줬고 저장 때는 파일 그대로로 세어 비교해서, 매핑을 하나도
안 바꾸고 저장해도 「화면을 불러온 뒤 변경됐습니다」 로 거절됐다(0.0 ↔ −1.5e-08).
"""

import yaml

from motion_runtime.motion_mapping_manager import MotionMappingManager


def _manager(tmp_path):
    manager = MotionMappingManager.__new__(MotionMappingManager)
    manager.mappings_dir = tmp_path
    manager._list_mappings = lambda: {}

    def first_frame_writes(mapping, include_motion_file=True):
        # 진짜 검사처럼 첫 프레임 값을 그 자리에 써 넣는다
        if include_motion_file:
            for row in mapping.get('mappings') or []:
                if row.get('initial_mode') == 'first_frame':
                    row['initial_motion_position_rad'] = -1.5e-08
        return {'valid': True, 'message': 'ok'}

    manager._validate_mapping = first_frame_writes
    return manager


def test_the_revision_given_on_load_is_the_one_save_compares_with(tmp_path):
    doc = {
        'name': 'motion_axis',
        'motion_file_id': 'dir_test.json',
        'mappings': [{'motion_id': 'f4_eye_pitch', 'enabled': True, 'motor_axis': 0,
                      'initial_mode': 'first_frame', 'initial_motion_position_rad': 0.0}],
    }
    path = tmp_path / 'motion_axis.yaml'
    path.write_text(yaml.safe_dump(doc), encoding='utf-8')
    manager = _manager(tmp_path)

    loaded = manager._load_mapping('motion_axis.yaml')

    on_disk = manager._normalize_mapping(yaml.safe_load(path.read_text(encoding='utf-8')), fallback_name='motion_axis')
    assert loaded['file']['mapping_revision'] == MotionMappingManager._mapping_revision(on_disk)
    # 화면에 주는 값은 지금처럼 첫 프레임 값
    assert loaded['mapping']['mappings'][0]['initial_motion_position_rad'] == -1.5e-08
