"""시뮬 로더가 실물처럼 시간 열로 20 ms 보간한다 · 수정 목록 8 (2026-10-06)"""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# 모듈 수준 `pytest.importorskip` 은 pytest 6.2.5(우분투 22.04)에서 수집 전체를 끊었다
# (`pytest` 그대로 0건 수집) · 표시(skipif)로 이 파일만 건너뛴다 · 수정 목록 63
HAS_MUJOCO = importlib.util.find_spec('mujoco') is not None
pytestmark = pytest.mark.skipif(not HAS_MUJOCO, reason='mujoco 가 없다')
if HAS_MUJOCO:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts' / 'sim'))
    import sim_core  # noqa: E402

ROBOT = SimpleNamespace(axes=[SimpleNamespace(joint='j1', motion_id='a')])


def _write(path, rows):
    lines = [json.dumps({'type': 'motion_header', 'rotation_unit': 'deg'})]
    lines += [json.dumps(row) for row in rows]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def test_irregular_rows_are_resampled_every_20_ms(tmp_path):
    # 0 s · 0.1 s 두 줄 · 실물은 그 사이를 20 ms 로 잇는다 · 전에는 두 프레임으로 끝났다
    path = _write(tmp_path / 'm.json', [[1, 0.0, 'a', 0.0], [2, 0.1, 'a', 10.0]])

    targets, count = sim_core.load_motion(path, ROBOT)

    assert count == 6
    assert targets['j1'] == pytest.approx([0.0, 2.0, 4.0, 6.0, 8.0, 10.0])


def test_regular_50_fps_files_keep_one_setpoint_per_row(tmp_path):
    rows = [[index + 1, round(index * 0.02, 3), 'a', float(index)] for index in range(5)]
    targets, count = sim_core.load_motion(_write(tmp_path / 'r.json', rows), ROBOT)
    assert count == 5
    assert targets['j1'] == pytest.approx([0.0, 1.0, 2.0, 3.0, 4.0])
