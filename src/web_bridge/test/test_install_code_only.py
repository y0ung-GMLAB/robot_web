"""설치 스크립트 `--code-only` (웹 「모든 PC 업데이트」) · 수정 목록 82 · 실물 2026-10-08

- `rosdep check` 가 원래부터 못 푸는 이름(`ament_python` · `librtmidi-dev`)에서 실패해 「새 시스템
  패키지 필요」 로 잘못 멈췄다 · 그때 이미 서비스를 꺼서 로봇이 선 채로 남았다.
- 받은 코드에서 install.sh 가 바뀌어도 bash 는 이미 읽은 옛 함수로 계속 돌아 같은 자리에서 또 실패했다.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
INSTALL = ROOT / 'scripts/install.sh'
TEXT = INSTALL.read_text(encoding='utf-8')


def _function(name):
    match = re.search(rf'^{name}\(\) {{\n.*?^}}\n', TEXT, flags=re.M | re.S)
    assert match, name
    return match.group(0)


def test_dependency_check_runs_before_services_stop():
    main = TEXT[TEXT.index('print_step "1.'):]
    check = main.index('code_only_dependency_check')
    build = main.index('build_workspace')
    assert check < build, '서비스를 끄는 build_workspace 보다 먼저 검사'
    assert 'rosdep check' not in _function('build_workspace')


def test_code_only_keeps_the_old_build_until_the_new_one_finishes():
    body = _function('build_workspace')
    assert 'mv "${WORKSPACE_DIR}/install" "${WORKSPACE_DIR}/install.prev"' in body
    assert body.index('install.prev') < body.index('colcon build')
    recover = _function('recover_code_only_failure')
    assert 'install.prev' in recover and 'systemctl --user start' in recover
    assert 'reset -q --hard "${BEFORE_HEAD}"' in recover, '옛 빌드는 옛 코드를 가리킨다(symlink-install)'
    assert 'recover_code_only_failure' in _function('report_failure')


def test_a_changed_installer_restarts_itself_once_after_the_git_step():
    after_git = TEXT[TEXT.index('sync_git_repository\n', TEXT.index('print_step "2.')):]
    block = after_git[:after_git.index('print_step "3.')]
    assert 'script_fingerprint' in block and 'MOTION_INSTALL_REEXEC' in block
    assert 'MOTION_WEB_SKIP_GIT_PULL=1' in block and 'exec bash "${SCRIPT_PATH}"' in block
    assert 'MOTION_INSTALL_BEFORE_HEAD="${BEFORE_HEAD}"' in block, '되돌릴 버전을 넘긴다'


def test_success_leaves_a_marker_for_the_web():
    tail = TEXT[TEXT.index('print_step "설치 완료"'):]
    assert 'log/system_update/last_success.json' in tail


ROSDEP_ONLY_UNKNOWN = """\
ERROR[rosdep]: Cannot locate rosdep definition for [ament_python]
ERROR[rosdep]: Cannot locate rosdep definition for [librtmidi-dev]
"""
ROSDEP_MISSING = ROSDEP_ONLY_UNKNOWN + """\
System dependencies have not been satisfied:
apt\tlibfoo-dev
apt\tros-humble-bar
"""


@pytest.mark.skipif(shutil.which('bash') is None, reason='bash 없음')
@pytest.mark.parametrize('output, ok', [(ROSDEP_ONLY_UNKNOWN, True), (ROSDEP_MISSING, False)])
def test_only_missing_system_packages_fail_the_check(tmp_path, output, ok):
    (tmp_path / 'rosdep.out').write_text(output, encoding='utf-8', newline='\n')
    fake = tmp_path / 'bin'
    fake.mkdir()
    (fake / 'rosdep').write_text('#!/bin/bash\ncat rosdep.out\nexit 1\n', encoding='utf-8', newline='\n')
    script = ('set -Eeuo pipefail\nWORKSPACE_DIR=/nowhere\n'
              + _function('code_only_dependency_check')
              + 'code_only_dependency_check\n')
    (tmp_path / 'run.sh').write_text(script, encoding='utf-8', newline='\n')
    result = subprocess.run(
        ['bash', '-c', 'chmod +x bin/rosdep; PATH="$PWD/bin:$PATH" bash run.sh'],
        cwd=tmp_path, capture_output=True, text=True, encoding='utf-8',
    )
    text = result.stdout + result.stderr
    assert 'ament_python' in text, '모르는 이름은 참고로 보인다'
    if ok:
        assert result.returncode == 0, text
        assert '새 시스템 패키지 필요 없음' in text
    else:
        assert result.returncode != 0, text
        assert 'libfoo-dev' in text and 'ros-humble-bar' in text
