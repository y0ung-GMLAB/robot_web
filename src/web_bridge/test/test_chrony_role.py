"""시간표 재생 · PC 시계 맞추기 역할 스크립트 · 수정 목록 186 (2026-11-09)

마스터 = 인터넷 NTP + 같은 망 기준(local stratum) · 그 밖 = 인터넷 + 마스터 · /etc 는 실제로 안 건드린다(DRY_RUN).
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / 'scripts' / 'chrony_role.sh'


def _run(*args):
    env = {**os.environ, 'ROBOT_CHRONY_DRY_RUN': '1'}
    return subprocess.run(['bash', str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=20)


def test_the_master_serves_the_lan_even_without_internet():
    result = _run('master')
    assert result.returncode == 0
    assert 'local stratum 10' in result.stdout
    assert 'allow 192.168.0.0/16' in result.stdout
    assert 'makestep 1 3' in result.stdout, '부팅 직후만 크게 맞춤'


def test_other_pcs_follow_the_master_too():
    result = _run('follow', 'floating1.local')
    assert result.returncode == 0
    assert 'server floating1.local iburst prefer' in result.stdout
    assert 'local stratum' not in result.stdout


@pytest.mark.parametrize('bad', ['', 'a b', 'x;rm -rf /'])
def test_a_bad_master_address_is_refused(bad):
    result = _run('follow', bad) if bad else _run('follow')
    assert result.returncode != 0


def test_scripts_parse():
    for path in (SCRIPT, ROOT / 'scripts' / 'check.sh'):
        assert subprocess.run(['bash', '-n', str(path)], capture_output=True).returncode == 0, path
