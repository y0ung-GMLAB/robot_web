"""저장소 scripts/ 의 손으로 돌리는 도구가 PYTHONPATH 없이 뜨나 · 실물 S-0c(2026-10-14)

`minas_factory_reset.py` 가 `motion_common` 을 못 찾아 시작도 못 했다(125 에서 drive_params 가
motion_common.ethercat_mailbox 를 쓰게 됨) · 미니 PC 에서 ROS 를 source 하지 않은 터미널 그대로 돌린다.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('script', ['minas_factory_reset.py', 'convert_motion_unit.py'])
def test_script_starts_without_pythonpath(script):
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
    env['PYTHONUTF8'] = '1'
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / script), '--help'],
        capture_output=True, text=True, timeout=60, env=env, cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stderr[-800:]
