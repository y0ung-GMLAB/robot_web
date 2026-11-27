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


def test_factory_reset_sends_sdo_through_the_shared_mailbox_guard(monkeypatch):
    """수정 목록 139 ④ · `minas_factory_reset.py` 의 SDO 도 웹 · 감시 노드와 같은 잠금 · 버스 설정 중이면 안 보냄"""
    import importlib.util

    from motion_common import ethercat_mailbox

    spec = importlib.util.spec_from_file_location('minas_factory_reset_under_test', ROOT / 'scripts' / 'minas_factory_reset.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    sent = []
    monkeypatch.setattr(ethercat_mailbox, 'configuring', lambda **_kw: False)
    monkeypatch.setattr(subprocess, 'run', lambda command, **kwargs: (
        sent.append(list(command)) or subprocess.CompletedProcess(command, 0, stdout='0x0001 1\n', stderr='')
    ))
    assert module.upload(0, 1, 0x3015, 0, 'int16') == (1, '')
    assert sent[-1][:2] == ['ethercat', 'upload']

    # 버스 설정 중 · 보내지 않고 「잠시 뒤 다시」 로 돌려준다
    monkeypatch.setattr(ethercat_mailbox, 'configuring', lambda **_kw: True)
    before = len(sent)
    value, error = module.upload(0, 1, 0x3015, 0, 'int16')
    assert value is None and ethercat_mailbox.CONFIGURING_MESSAGE in error
    assert len(sent) == before
    with pytest.raises(RuntimeError):
        module.download(0, 1, 0x3015, 0, 'int16', 1)
    assert len(sent) == before
