"""ROS 버전 = OS 버전 · scripts/lib/ros_distro.sh · polkit 규칙 · 2026-10-27 (jazzy)

22.04 → humble · 24.04 → jazzy · 설치·서비스 스크립트가 모두 이 파일로 ROS 환경을 고른다.
24.04 polkit 124 는 .pkla 를 안 읽어서 같은 허용을 rules.d JS 규칙으로 쓴다.
"""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
LIB = ROOT / 'scripts' / 'lib' / 'ros_distro.sh'
SITE = ROOT / 'scripts' / 'setup' / 'site.sh'

pytestmark = pytest.mark.skipif(not shutil.which('bash'), reason='bash 필요')

# /etc/os-release · /opt/ros 대신 가짜 자리를 읽게 (ROBOT_OS_RELEASE · ROBOT_ROS_ROOT)
DISTRO = r'''
set -euo pipefail
unset ROBOT_ROS_DISTRO
source "$1"
echo "${ROBOT_ROS_DISTRO} ${ROBOT_ROS_SETUP##*/opt-ros/}"
robot_os_supported && echo supported || echo unsupported
'''


def _distro(tmp_path, os_release, installed=()):
    release = tmp_path / 'os-release'
    release.write_text(os_release, encoding='utf-8')
    ros = tmp_path / 'opt-ros'
    for name in installed:
        (ros / name).mkdir(parents=True)
        (ros / name / 'setup.bash').write_text('', encoding='utf-8')
    env = dict(os.environ, ROBOT_OS_RELEASE=release.as_posix(), ROBOT_ROS_ROOT=ros.as_posix())
    out = subprocess.run(['bash', '-c', DISTRO, 'x', LIB.as_posix()], env=env,
                         capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout.split('\n')


@pytest.mark.parametrize('version,distro', [('22.04', 'humble'), ('24.04', 'jazzy')])
def test_os_version_picks_the_ros_distro(tmp_path, version, distro):
    first, second, _ = _distro(tmp_path, f'ID=ubuntu\nVERSION_ID="{version}"\n')
    assert first.split()[0] == distro
    assert first.endswith(f'{distro}/setup.bash')
    assert second == 'supported'


def test_unknown_os_uses_what_is_installed_and_is_not_supported(tmp_path):
    first, second, _ = _distro(tmp_path, 'ID=debian\nVERSION_ID="12"\n', installed=('jazzy',))
    assert first.split()[0] == 'jazzy'
    assert second == 'unsupported'


POLKIT = r'''
set -uo pipefail
source "$1" >/dev/null 2>&1
site_write_root_file() { cat > "$1"; }
site_run() { :; }
SITE_POLKIT_MODE=rules SITE_POLKIT_RULES_FILE="$2/r.rules" site_web_admin_permissions tester >/dev/null
SITE_POLKIT_MODE=pkla SITE_POLKIT_FILE="$2/p.pkla" site_web_admin_permissions tester >/dev/null
SITE_POLKIT_MODE=rules SITE_POLKIT_RULES_FILE="$2/r.rules" site_web_admin_permissions tester
'''


def test_polkit_writes_js_rules_on_new_polkit_and_pkla_on_old(tmp_path):
    out = subprocess.run(['bash', '-c', POLKIT, 'x', SITE.as_posix(), tmp_path.as_posix()],
                         capture_output=True, text=True, encoding='utf-8', timeout=30)
    rules = (tmp_path / 'r.rules').read_text(encoding='utf-8')
    assert 'subject.user == "tester"' in rules
    assert 'org.freedesktop.NetworkManager.' in rules and 'org.freedesktop.timedate1.set-timezone' in rules
    assert 'polkit.Result.YES' in rules
    assert 'Identity=unix-user:tester' in (tmp_path / 'p.pkla').read_text(encoding='utf-8')
    assert '이미 허용됨' in out.stdout   # 두 번째는 그대로 둔다(멱등)


def test_every_service_script_takes_ros_from_the_shared_file():
    scripts = [
        'scripts/install.sh', 'scripts/install_speaker.sh', 'scripts/build_and_restart.sh', 'scripts/ship.sh',
        'speaker_app/run.sh', 'src/web_bridge/deploy/install_user_service.sh',
        'src/web_bridge/deploy/run_user_service.sh', 'src/web_bridge/deploy/run_motor_service.sh',
        'src/web_bridge/deploy/run_motor_user_service.sh',
        'src/motion_coordination/deploy/run_coordination_user_service.sh',
    ]
    for name in scripts:
        text = (ROOT / name).read_text(encoding='utf-8')
        assert 'lib/ros_distro.sh' in text, name
        # 남은 humble 경로는 파일이 없을 때 쓰는 대비값 한 줄뿐
        leftovers = [line for line in text.splitlines()
                     if '/opt/ros/humble' in line and 'ros_distro.sh' not in line]
        assert not leftovers, (name, leftovers)
