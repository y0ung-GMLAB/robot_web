"""실물 시험용 애니메이션 · `scripts/make_test_animations.py` (2026-10-06)

rad · deg · 단위 칸 없음 세 파일이 재생 파서를 거치면 같은 값이어야 시험(6-2)이 뜻이 있다.
"""

import subprocess
import sys
from pathlib import Path

from motion_common import motion_table

SCRIPT = Path(__file__).resolve().parents[3] / 'scripts' / 'make_test_animations.py'


def _values(path, joint):
    content = path.read_text(encoding='utf-8')
    assert motion_table.validate_motion_content(content) > 0
    rows, headers, _kind, _error = motion_table.extract_rows_from_content(content)
    records = motion_table.parse_rows(rows, headers)
    records = motion_table.scale_record_values(records, motion_table.rotation_unit_from_content(content))
    return [float(record['value']) for record in records if record['motion_id'] == joint]


def test_the_three_sine_files_play_at_the_same_size(tmp_path):
    subprocess.run(
        [sys.executable, str(SCRIPT), '--out', str(tmp_path), '--joints', 'a,b,c', '--amp-deg', '20'],
        check=True, capture_output=True,
    )
    names = sorted(path.name for path in tmp_path.glob('*.json'))
    assert names == [
        't01_sine_rad.json', 't02_sine_deg.json', 't03_sine_noheader.json', 't04_far_start.json',
        't05_steps.json', 't06_too_fast.json', 't07_out_of_range.json',
    ]
    rad = _values(tmp_path / 't01_sine_rad.json', 'a')
    deg = _values(tmp_path / 't02_sine_deg.json', 'a')
    bare = _values(tmp_path / 't03_sine_noheader.json', 'a')
    assert len(rad) == len(deg) == len(bare) == 1001
    for x, y, z in zip(rad, deg, bare):
        assert abs(x - y) < 1e-6 and abs(x - z) < 1e-6
    assert rad[0] == rad[-1] == 0.0                       # 처음 = 끝 · 「바로 다음 회차」 시험용
    far = _values(tmp_path / 't04_far_start.json', 'b')
    assert far[0] != far[-1]                              # 처음 ≠ 끝 · 거절 시험용
