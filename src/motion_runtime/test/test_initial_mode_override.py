"""초기 위치 이동만 기준점으로 덮어쓸 수 있다 · 수정 목록 36 (2026-10-06)"""

from types import SimpleNamespace

import pytest

from motion_runtime.plan_builder import PlanBuilder


def _builder():
    def no_files(*_args, **_kwargs):
        raise AssertionError('덮어쓰기 검사가 파일보다 먼저다')

    manager = SimpleNamespace(
        _motion_file_path=no_files, _mapping_file_path=no_files, period_sec=0.02,
    )
    return PlanBuilder(manager)


@pytest.mark.parametrize('payload, initialization_only', [
    ({'motion_file_id': 'a.json', 'initial_mode_override': 'reference'}, False),
    ({'motion_file_id': 'a.json', 'initial_mode_override': 'first_frame'}, True),
])
def test_override_is_refused_outside_a_reference_initial_move(payload, initialization_only):
    with pytest.raises(ValueError, match='초기 방식 덮어쓰기'):
        _builder().build(payload, initialization_only=initialization_only, motors_snapshot=[])
