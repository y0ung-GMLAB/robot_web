"""시뮬 로더가 실물처럼 시간 열로 20 ms 보간한다 · 수정 목록 8 (2026-10-06)"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip('mujoco')
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
