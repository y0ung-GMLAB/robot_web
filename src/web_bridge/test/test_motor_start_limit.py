"""모터 서비스 되풀이 재기동 상한 · 60초에 5번 · 넘으면 78 · 수정 목록 65 (실물 2026-10-07)

systemd 249 사용자 유닛에서 `StartLimitBurst` 가 안 걸렸다 · 실행 스크립트가 직접 센다.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from motion_web_bridge.motor_restart_coordinator import MotorRestartCoordinator

DEPLOY = Path(__file__).resolve().parents[1] / 'deploy'


def _check(tmp_path, burst=5, window=60):
    helper = (DEPLOY / 'start_limit.sh').read_text(encoding='utf-8')
    (tmp_path / 'helper.sh').write_text(helper, encoding='utf-8', newline='\n')
    # `$?` 를 쓰지 않는다 · 윈도우 WSL bash.exe 가 바깥에서 먼저 0 으로 바꿔 버린다
    script = (f'source helper.sh; if start_limit_check starts {burst} {window}; '
              'then echo rc=0; else echo rc=1; fi')
    result = subprocess.run(['bash', '-c', script], cwd=tmp_path, capture_output=True,
                            text=True, encoding='utf-8')
    return result.stdout.strip(), result.stderr


@pytest.mark.skipif(shutil.which('bash') is None, reason='bash 없음')
def test_the_sixth_start_within_a_minute_is_refused(tmp_path):
    for _ in range(5):
        out, _err = _check(tmp_path)
        assert out == 'rc=0'
    out, err = _check(tmp_path)
    assert out == 'rc=1'
    assert '되풀이' in err and '모터 재시작' in err


@pytest.mark.skipif(shutil.which('bash') is None, reason='bash 없음')
def test_old_starts_fall_out_of_the_window(tmp_path):
    (tmp_path / 'starts').write_text('1\n2\n3\n4\n5\n', encoding='utf-8', newline='\n')   # 1970 년 · 오래됨
    out, _err = _check(tmp_path)
    assert out == 'rc=0'
    assert len((tmp_path / 'starts').read_text(encoding='utf-8').split()) == 1


def test_the_runner_stops_with_the_code_the_unit_will_not_restart():
    runner = (DEPLOY / 'run_motor_user_service.sh').read_text(encoding='utf-8')
    unit = (DEPLOY / 'motion-motor.service.in').read_text(encoding='utf-8')
    assert 'start_limit_check "$(start_limit_file motor)"' in runner
    assert runner.index('start_limit_check') < runner.index('exec "${SERVICE_EXECUTABLE}"')
    assert 'exit 78' in runner and 'RestartPreventExitStatus=78' in unit


def test_a_web_restart_clears_the_count(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path))
    path = Path(MotorRestartCoordinator.start_limit_path('motion-motor.service'))
    assert path == tmp_path / 'robot-web' / 'motor-starts'
    path.parent.mkdir(parents=True)
    path.write_text('1\n', encoding='utf-8')
    MotorRestartCoordinator._clear_start_limit('motion-motor.service')
    assert not path.exists()
