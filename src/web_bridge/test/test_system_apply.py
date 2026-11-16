"""fwupd 끄기(수정 목록 210) · 웹 업데이트용 시스템 설정 고정 도우미(수정 목록 211)

210 · NY floating3 2026-11-10 14:05:52~54 · fwupd-refresh.timer 가 fwupd 를 깨운 2초 동안 EtherCAT 프레임이
      빠짐(최장 30 ms) · 로봇 PC · 스피커 PC 에서 fwupd.service · fwupd-refresh.timer 를 mask
211 · 웹 「모든 PC 업데이트」(install.sh --code-only)는 sudo -n 이라 /etc 를 못 써서 시스템 설정을 PC 마다 사람이 쳤다 ·
      첫 설치 때 root 것인 고정 도우미(/usr/local/sbin/robot-web-system-apply) + 그 명령 하나만 인자 없이
      허용하는 sudoers 한 줄을 깔고 웹 업데이트가 그것을 부른다 · 도우미는 저장소를 읽지도 실행하지도 않는다

여기서는 가짜 systemctl · nmcli · ip · modinfo · sudo 로 실제 함수와 도우미 스크립트를 돌린다 · 실물은 미니 PC 에서.
"""

import grp
import os
import pwd
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[3]
SCRIPTS = WORKSPACE / 'scripts'
SITE = SCRIPTS / 'setup' / 'site.sh'
HELPER = SCRIPTS / 'setup' / 'robot-web-system-apply.sh'
ALLOW = SCRIPTS / 'allow_system_apply.sh'
INSTALL = SCRIPTS / 'install.sh'
SPEAKER = SCRIPTS / 'install_speaker.sh'
CHECK = SCRIPTS / 'check.sh'

LINUX_SHELL = Path('/usr/bin/awk').exists() and shutil.which('flock') is not None
pytestmark = pytest.mark.skipif(not LINUX_SHELL, reason='리눅스 셸에서')

ECAT_MAC = '84:47:09:81:DB:23'


def _bash(script, env=None, timeout=60):
    return subprocess.run(
        ['bash', '-c', script], capture_output=True, text=True, timeout=timeout,
        cwd=str(WORKSPACE), env={**os.environ, **(env or {})},
    )


def _fake(directory, name, body):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f'#!/bin/sh\n{body}\n', encoding='utf-8')
    path.chmod(0o755)
    return path


def _me():
    return f'{pwd.getpwuid(os.getuid()).pw_name}:{grp.getgrgid(os.getgid()).gr_name}'


def _fake_systemctl(fake, tmp_path, units):
    """is-enabled 은 units/<이름> 파일 내용 · 없으면 「없음」 · mask --now 는 masked 로 적음"""
    unit_dir = tmp_path / 'units'
    unit_dir.mkdir(exist_ok=True)
    for name, state in units.items():
        (unit_dir / name).write_text(f'{state}\n', encoding='utf-8')
    _fake(fake, 'systemctl', f'''echo "systemctl $*" >> "{tmp_path}/systemctl.log"
case "$1" in
  is-enabled)
    f="{unit_dir}/$2"
    if [ -f "$f" ]; then cat "$f"; [ "$(cat "$f")" = masked ] && exit 1; exit 0; fi
    echo "Failed to get unit file state for $2: No such file or directory" >&2; exit 1 ;;
  mask)
    shift; [ "$1" = "--now" ] && shift
    for u in "$@"; do echo masked > "{unit_dir}/$u"; done; exit 0 ;;
esac
exit 0''')
    return unit_dir


# ------------------------------------------------------------------ #
# 210 · site.sh · fwupd 끄기
# ------------------------------------------------------------------ #

def _fwupd_env(tmp_path, units, fake_sudo='exec "$@"'):
    fake = tmp_path / 'bin'
    _fake(fake, 'sudo', fake_sudo)
    unit_dir = _fake_systemctl(fake, tmp_path, units)
    return {'PATH': f'{fake}{os.pathsep}{os.environ["PATH"]}'}, unit_dir


def _site(call, env):
    result = _bash(f'set -Eeuo pipefail; source "{SITE}"; {call}', env)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def _mask_calls(tmp_path):
    log = tmp_path / 'systemctl.log'
    if not log.exists():
        return []
    return [line for line in log.read_text(encoding='utf-8').splitlines() if ' mask ' in f' {line} ']


def test_fwupd_is_masked_once(tmp_path):
    env, unit_dir = _fwupd_env(tmp_path, {'fwupd.service': 'static', 'fwupd-refresh.timer': 'enabled'})
    assert _site('site_fwupd_off_ok', env).strip() == '0'
    assert 'sudo systemctl mask --now fwupd.service fwupd-refresh.timer' in _site('site_fwupd_detail', env)
    first = _site('site_fwupd_off', env)
    assert _mask_calls(tmp_path) == ['systemctl mask --now fwupd.service fwupd-refresh.timer']
    assert '끔' in first and 'unmask' in first
    assert (unit_dir / 'fwupd.service').read_text(encoding='utf-8').strip() == 'masked'
    # 두 번째 · 아무것도 안 함
    second = _site('site_fwupd_off', env)
    assert '이미 꺼짐' in second and len(_mask_calls(tmp_path)) == 1
    assert _site('site_fwupd_off_ok', env).strip() == '1'
    assert 'masked' in _site('site_fwupd_detail', env) and 'sudo' not in _site('site_fwupd_detail', env)


def test_fwupd_absent_is_skipped_and_passes_the_check(tmp_path):
    env, _ = _fwupd_env(tmp_path, {})
    out = _site('site_fwupd_off', env)
    assert 'fwupd 없음 · 건너뜀' in out and _mask_calls(tmp_path) == []
    assert _site('site_fwupd_off_ok', env).strip() == '1'
    assert '해당 없음' in _site('site_fwupd_detail', env)


def test_fwupd_not_found_from_newer_systemd_counts_as_absent(tmp_path):
    env, _ = _fwupd_env(tmp_path, {'fwupd.service': 'not-found', 'fwupd-refresh.timer': 'not-found'})
    assert 'fwupd 없음' in _site('site_fwupd_off', env)
    assert _mask_calls(tmp_path) == []


def test_fwupd_only_the_unmasked_unit_is_masked(tmp_path):
    env, _ = _fwupd_env(tmp_path, {'fwupd.service': 'masked', 'fwupd-refresh.timer': 'enabled'})
    _site('site_fwupd_off', env)
    assert _mask_calls(tmp_path) == ['systemctl mask --now fwupd-refresh.timer']


def test_fwupd_dry_run_prints_only(tmp_path):
    env, unit_dir = _fwupd_env(tmp_path, {'fwupd.service': 'static', 'fwupd-refresh.timer': 'enabled'})
    out = _site('site_fwupd_off', {**env, 'SITE_DRY_RUN': '1'})
    assert '[dry-run] sudo systemctl mask --now fwupd.service fwupd-refresh.timer' in out
    assert _mask_calls(tmp_path) == []
    assert (unit_dir / 'fwupd-refresh.timer').read_text(encoding='utf-8').strip() == 'enabled'


def test_fwupd_without_sudo_warns_with_the_command_and_install_goes_on(tmp_path):
    env, _ = _fwupd_env(tmp_path, {'fwupd.service': 'static', 'fwupd-refresh.timer': 'enabled'},
                        fake_sudo='echo "sudo: a password is required" >&2; exit 1')
    result = _bash(
        f'set -Eeuo pipefail; trap \'echo TRAP >&2; exit 9\' ERR; source "{SITE}"; '
        'sudo() { command sudo -n "$@"; }; '
        'site_fwupd_off || echo "계속"; echo 끝', env)
    assert result.returncode == 0, result.stderr
    assert 'TRAP' not in result.stderr
    assert result.stdout.strip().splitlines()[-2:] == ['계속', '끝']
    assert 'sudo systemctl mask --now fwupd.service fwupd-refresh.timer' in result.stderr


def test_fwupd_step_is_wired_into_site_install_speaker_and_check():
    site = SITE.read_text(encoding='utf-8')
    interruptions = site.split('site_disable_interruptions() {', 1)[1].split('\n}\n', 1)[0]
    assert 'site_fwupd_off || true' in interruptions, '로봇 PC(--site) · 스피커 PC 첫 설치'
    assert 'site_disable_interruptions' in SPEAKER.read_text(encoding='utf-8')
    install = INSTALL.read_text(encoding='utf-8')
    step = install.split('print_step "2-1. 시스템 설정', 1)[1].split('print_step', 1)[0]
    terminal = step.split('else', 1)[1]
    assert 'site_fwupd_off ||' in terminal, '터미널 설치(옵션 없이) · 이미 설치된 PC 도'
    assert 'site_fwupd_off_ok' in site.split('site_selfcheck() {', 1)[1]
    check = CHECK.read_text(encoding='utf-8')
    assert 'site_fwupd_off_ok' in check and '"fwupd 꺼짐"' in check


# ------------------------------------------------------------------ #
# 211 · 고정 도우미 스크립트 (root 로 도는 것)
# ------------------------------------------------------------------ #

def _helper_env(tmp_path, *, rtw88=('N', 'N'), mac=ECAT_MAC, nm_done=False, link_up=True,
                units=None, patched=True, ethercat_installed=True, rebuild_rc=0):
    """가짜 PC · RWSA_TEST=1 (root 아님) 일 때만 도우미가 RWSA_* 자리를 받는다"""
    fake = tmp_path / 'bin'
    sys_dir = tmp_path / 'sys'
    sys_dir.mkdir()
    if rtw88:
        for module, param, value in (('rtw88_pci', 'disable_aspm', rtw88[0]), ('rtw88_core', 'disable_lps_deep', rtw88[1])):
            (sys_dir / module / 'parameters').mkdir(parents=True)
            (sys_dir / module / 'parameters' / param).write_text(f'{value}\n', encoding='utf-8')
    etc = tmp_path / 'etc'
    etc.mkdir(mode=0o755)
    conf = etc / 'system-apply.conf'
    if mac is not None:
        conf.write_text(f'# 시험\nETHERCAT_MAC={mac.lower() if mac != "none" else "none"}\n', encoding='utf-8')
        conf.chmod(0o644)
    nm_conf = tmp_path / 'nm.conf'
    if nm_done:
        nm_conf.write_text(f'[keyfile]\nunmanaged-devices=mac:{ECAT_MAC.lower()}\n', encoding='utf-8')
    flags = tmp_path / 'link_flags'
    flags.write_text('<BROADCAST,MULTICAST,UP,LOWER_UP>' if link_up else '<BROADCAST,MULTICAST>', encoding='utf-8')
    _fake(fake, 'nmcli', f'echo "nmcli $*" >> "{tmp_path}/nmcli.log"\n'
                         f'case "$*" in *reload*) echo "<BROADCAST,MULTICAST>" > "{flags}" ;; esac\nexit 0')
    _fake(fake, 'ip', f'case "$*" in *" set "*) echo "ip $*" >> "{tmp_path}/ip.log"; '
                      f'echo "<BROADCAST,MULTICAST,UP,LOWER_UP>" > "{flags}" ;; '
                      f'*) echo "lo UNKNOWN 00:00:00:00:00:00 <LOOPBACK,UP>"; '
                      f'echo "enp1s0 UP {ECAT_MAC.lower()} $(cat "{flags}")"; '
                      'echo "wlp3s0 UP 0c:cd:b4:67:6f:39 <BROADCAST,MULTICAST,UP>" ;; esac')
    _fake(fake, 'ethercat', 'echo "0  0:0  OP  +  MADLN05BE"')
    _fake_systemctl(fake, tmp_path, units if units is not None else
                    {'fwupd.service': 'static', 'fwupd-refresh.timer': 'enabled'})
    marker = tmp_path / 'built'
    if ethercat_installed:
        sdo = f'[ -f "{marker}" ] && echo "sdo_dict:x (uint)"' if not patched else 'echo "sdo_dict:x (uint)"'
        _fake(fake, 'modinfo', f'case "$1" in -p) echo "debug_level:x (uint)"; {sdo} ;; esac\nexit 0')
    else:
        _fake(fake, 'modinfo', 'echo "modinfo: ERROR: Module ec_master not found." >&2\nexit 1')
    sbin = tmp_path / 'sbin'
    sbin.mkdir(mode=0o755)
    rebuild = sbin / 'ethercat-rebuild'
    if ethercat_installed:
        rebuild.write_text(f'#!/bin/sh\necho "재빌드 HOME=$HOME ENV_X=${{ENV_X:-}}"\n'
                           f'[ {rebuild_rc} = 0 ] && touch "{marker}"\nexit {rebuild_rc}\n', encoding='utf-8')
        rebuild.chmod(0o755)
    src = tmp_path / 'src'
    (src / 'master').mkdir(parents=True)
    (src / 'master' / 'module.c').write_text('x\n', encoding='utf-8')
    for path in (src, src / 'master'):
        path.chmod(0o755)
    patch = tmp_path / 'igh.patch'
    patch.write_text('x\n', encoding='utf-8')
    patch.chmod(0o644)
    env = {
        'PATH': f'{fake}{os.pathsep}{os.environ["PATH"]}',
        'RWSA_TEST': '1',
        'RWSA_SYSTEM_CONF': str(conf),
        'RWSA_RTW88_CONF': str(tmp_path / 'rtw88-robot.conf'),
        'RWSA_NM_CONF': str(nm_conf),
        'RWSA_SYS_MODULE': str(sys_dir),
        'RWSA_REBUILD': str(rebuild),
        'RWSA_ETHERLAB_SRC': str(src),
        'RWSA_ETHERLAB_PATCH': str(patch),
        'RWSA_ROOT_UID': str(os.getuid()),
        'RWSA_LOCK': str(tmp_path / 'lock'),
        'RWSA_RELINK_WAIT_SEC': '1',
        'RWSA_HOME': str(tmp_path),
        'ENV_X': 'leak',
    }
    return env


def _run_helper(env, *args):
    return subprocess.run(['bash', str(HELPER), *args], capture_output=True, text=True, timeout=60,
                          env={**os.environ, **env})


def _lines(out):
    return {line.split('] ', 1)[1].split(' · ', 1)[0]: line.split(']', 1)[0].lstrip(' [')
            for line in out.splitlines() if line.startswith('  [')}


@pytest.mark.skipif(os.getuid() == 0, reason='root 아닌 계정으로')
def test_helper_refuses_arguments_and_needs_root(tmp_path):
    env = _helper_env(tmp_path)
    assert _run_helper(env, '--force').returncode == 2
    assert _run_helper(env, 'a', 'b').returncode == 2
    assert not (tmp_path / 'rtw88-robot.conf').exists() and _mask_calls(tmp_path) == []
    plain = {**os.environ, **env}
    plain.pop('RWSA_TEST')
    refused = subprocess.run(['bash', str(HELPER)], capture_output=True, text=True, timeout=30, env=plain)
    assert refused.returncode == 2 and '관리자 권한' in refused.stderr
    assert not (tmp_path / 'rtw88-robot.conf').exists()
    version = _run_helper(env, '--version')
    assert version.returncode == 0 and version.stdout.strip().isdigit()


def test_helper_applies_every_item_once(tmp_path):
    env = _helper_env(tmp_path, link_up=True)
    first = _run_helper(env)
    assert first.returncode == 0, first.stdout + first.stderr
    states = _lines(first.stdout)
    assert states['Wi-Fi 칩 절전 끄기 (rtw88'] == '바꿈 · 재부팅 필요'
    assert states['EtherCAT 랜카드 NetworkManager 에서 빼기 (수정 목록 177'] == '바꿈'
    assert states['fwupd 끄기 (펌웨어 업데이트'] == '바꿈'
    assert states['EtherCAT SDO 사전 읽기 끄기 모듈 (IgH 패치'] == '이미 됨'
    rtw88 = (tmp_path / 'rtw88-robot.conf').read_text(encoding='utf-8').splitlines()
    assert 'options rtw88_pci disable_aspm=1' in rtw88 and 'options rtw88_core disable_lps_deep=1' in rtw88
    nm = (tmp_path / 'nm.conf').read_text(encoding='utf-8').splitlines()
    assert '[keyfile]' in nm and f'unmanaged-devices=mac:{ECAT_MAC.lower()}' in nm
    assert 'general reload conf' in (tmp_path / 'nmcli.log').read_text(encoding='utf-8')
    # NM 이 놓으며 내린 링크를 다시 켠다(180)
    assert (tmp_path / 'ip.log').read_text(encoding='utf-8').strip() == 'ip link set dev enp1s0 up'
    assert _mask_calls(tmp_path) == ['systemctl mask --now fwupd.service fwupd-refresh.timer']
    assert not list(tmp_path.glob('*.robot-web-tmp')), '임시 파일이 남지 않음'
    assert '재부팅 뒤 적용' in first.stdout

    # 두 번째 · 다 됐음 · rtw88 은 재부팅 전이라 「재부팅 필요」
    snapshot = {p: p.read_text(encoding='utf-8') for p in (tmp_path / 'rtw88-robot.conf', tmp_path / 'nm.conf')}
    second = _run_helper(env)
    assert second.returncode == 0, second.stdout + second.stderr
    states = _lines(second.stdout)
    assert states['Wi-Fi 칩 절전 끄기 (rtw88'] == '재부팅 필요'
    assert states['EtherCAT 랜카드 NetworkManager 에서 빼기 (수정 목록 177'] == '이미 됨'
    assert states['fwupd 끄기 (펌웨어 업데이트'] == '이미 됨'
    assert {p: p.read_text(encoding='utf-8') for p in snapshot} == snapshot
    assert len(_mask_calls(tmp_path)) == 1
    assert (tmp_path / 'nmcli.log').read_text(encoding='utf-8').count('reload') == 1


def test_helper_after_reboot_reports_everything_done(tmp_path):
    env = _helper_env(tmp_path, rtw88=('Y', 'Y'), nm_done=True,
                      units={'fwupd.service': 'masked', 'fwupd-refresh.timer': 'masked'})
    (tmp_path / 'rtw88-robot.conf').write_text('options rtw88_pci disable_aspm=1\noptions rtw88_core disable_lps_deep=1\n',
                                               encoding='utf-8')
    result = _run_helper(env)
    assert result.returncode == 0
    assert set(_lines(result.stdout).values()) == {'이미 됨'}
    assert '재부팅' not in result.stdout


def test_helper_turns_a_down_ethercat_link_back_on(tmp_path):
    """손으로 NM 에서 뺐는데 링크가 꺼진 채인 PC(180)"""
    env = _helper_env(tmp_path, nm_done=True, link_up=False)
    result = _run_helper(env)
    assert result.returncode == 0
    assert _lines(result.stdout)['EtherCAT 랜카드 NetworkManager 에서 빼기 (수정 목록 177'] == '바꿈'
    assert 'ip link set dev enp1s0 up' in (tmp_path / 'ip.log').read_text(encoding='utf-8')
    assert not (tmp_path / 'nmcli.log').exists(), '설정은 이미 있어 다시 읽지 않음'


def test_helper_on_a_speaker_pc_has_nothing_to_do_but_fwupd(tmp_path):
    env = _helper_env(tmp_path, rtw88=None, mac='none', ethercat_installed=False)
    result = _run_helper(env)
    assert result.returncode == 0, result.stdout + result.stderr
    states = _lines(result.stdout)
    assert states['Wi-Fi 칩 절전 끄기 (rtw88'] == '해당 없음'
    assert states['EtherCAT 랜카드 NetworkManager 에서 빼기 (수정 목록 177'] == '해당 없음'
    assert states['EtherCAT SDO 사전 읽기 끄기 모듈 (IgH 패치'] == '해당 없음'
    assert states['fwupd 끄기 (펌웨어 업데이트'] == '바꿈'
    assert not (tmp_path / 'nm.conf').exists() and not (tmp_path / 'ip.log').exists()


def test_helper_on_a_serial_only_pc_does_not_rebuild_the_igh_module(tmp_path):
    """jazzy · 라즈베리파이 · 직렬 서보 전용(SITE_ETHERCAT_NIC=none) · EtherLab 은 빌드용으로 깔렸지만 EtherCAT 안 씀"""
    env = _helper_env(tmp_path, rtw88=None, mac='none', patched=False)
    result = _run_helper(env)
    assert result.returncode == 0, result.stdout + result.stderr
    states = _lines(result.stdout)
    assert states['Wi-Fi 칩 절전 끄기 (rtw88'] == '해당 없음'
    assert states['EtherCAT 랜카드 NetworkManager 에서 빼기 (수정 목록 177'] == '해당 없음'
    assert states['EtherCAT SDO 사전 읽기 끄기 모듈 (IgH 패치'] == '해당 없음'
    assert '재빌드' not in result.stdout and not (tmp_path / 'built').exists()
    assert not (tmp_path / 'nm.conf').exists() and not (tmp_path / 'ip.log').exists()


def test_helper_skips_fwupd_when_it_is_not_installed(tmp_path):
    env = _helper_env(tmp_path, units={})
    result = _run_helper(env)
    assert _lines(result.stdout)['fwupd 끄기 (펌웨어 업데이트'] == '해당 없음'
    assert _mask_calls(tmp_path) == []


def test_helper_rebuilds_an_unpatched_module_without_touching_ethercat(tmp_path):
    env = _helper_env(tmp_path, patched=False)
    result = _run_helper(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _lines(result.stdout)['EtherCAT SDO 사전 읽기 끄기 모듈 (IgH 패치'] == '바꿈 · 재부팅 필요'
    assert (tmp_path / 'built').exists()
    assert '다음 재부팅 · EtherCAT 재시작 때 적용' in result.stdout
    # 재빌드는 깨끗한 환경으로 (밖의 변수 없이)
    assert f'재빌드 HOME={tmp_path} ENV_X=' in result.stdout and 'ENV_X=leak' not in result.stdout
    log = (tmp_path / 'systemctl.log').read_text(encoding='utf-8')
    assert 'ethercat' not in log, 'ethercat 서비스를 다시 시작하지 않는다(재생 중 모터를 끊지 않게)'
    # 깔렸고 올라간 것은 옛 모듈 · 다음엔 빌드 없이 「재부팅 필요」
    (tmp_path / 'sys' / 'ec_master' / 'parameters').mkdir(parents=True)
    again = _run_helper(env)
    assert _lines(again.stdout)['EtherCAT SDO 사전 읽기 끄기 모듈 (IgH 패치'] == '재부팅 필요'
    assert '재빌드' not in again.stdout


def test_helper_reports_a_failed_rebuild(tmp_path):
    env = _helper_env(tmp_path, patched=False, rebuild_rc=1)
    result = _run_helper(env)
    assert result.returncode == 1
    assert _lines(result.stdout)['EtherCAT SDO 사전 읽기 끄기 모듈 (IgH 패치'] == '실패'
    assert '[실패]' in result.stdout and '!!' in result.stdout
    # 다른 항목은 그대로 함
    assert _lines(result.stdout)['fwupd 끄기 (펌웨어 업데이트'] == '바꿈'


@pytest.mark.parametrize('weak', ['src_file', 'rebuild', 'patch'])
def test_helper_will_not_build_as_root_from_files_others_can_change(tmp_path, weak):
    env = _helper_env(tmp_path, patched=False)
    target = {'src_file': tmp_path / 'src' / 'master' / 'module.c',
              'rebuild': tmp_path / 'sbin' / 'ethercat-rebuild',
              'patch': tmp_path / 'igh.patch'}[weak]
    target.chmod(target.stat().st_mode | stat.S_IWOTH)
    result = _run_helper(env)
    assert result.returncode == 1
    assert _lines(result.stdout)['EtherCAT SDO 사전 읽기 끄기 모듈 (IgH 패치'] == '실패'
    assert 'root 로 빌드하지 않음' in result.stdout
    assert not (tmp_path / 'built').exists(), '재빌드를 부르지 않음'


def test_helper_distrusts_a_nic_record_it_cannot_trust(tmp_path):
    env = _helper_env(tmp_path)
    (tmp_path / 'etc' / 'system-apply.conf').chmod(0o666)
    result = _run_helper(env)
    assert result.returncode == 1
    assert _lines(result.stdout)['EtherCAT 랜카드 NetworkManager 에서 빼기 (수정 목록 177'] == '실패'
    assert not (tmp_path / 'nm.conf').exists()
    # 주인이 root 가 아님(시험에서는 RWSA_ROOT_UID 와 다름)
    (tmp_path / 'etc' / 'system-apply.conf').chmod(0o644)
    result = _run_helper({**env, 'RWSA_ROOT_UID': str(os.getuid() + 1)})
    assert _lines(result.stdout)['EtherCAT 랜카드 NetworkManager 에서 빼기 (수정 목록 177'] == '실패'
    # 값이 MAC 이 아님
    (tmp_path / 'etc' / 'system-apply.conf').write_text('ETHERCAT_MAC=enp1s0;reboot\n', encoding='utf-8')
    result = _run_helper(env)
    assert _lines(result.stdout)['EtherCAT 랜카드 NetworkManager 에서 빼기 (수정 목록 177'] == '실패'
    assert not (tmp_path / 'nm.conf').exists()


def test_helper_two_runs_do_not_overlap(tmp_path):
    env = _helper_env(tmp_path)
    holder = subprocess.Popen(['flock', str(tmp_path / 'lock'), 'sleep', '5'])
    try:
        for _ in range(50):
            if (tmp_path / 'lock').exists():
                break
            time.sleep(0.05)
        time.sleep(0.2)
        result = _run_helper(env)
    finally:
        holder.kill()
        holder.wait()
    assert result.returncode == 1 and '이미 도는 중' in result.stderr


def test_helper_is_self_contained_and_ignores_the_environment_as_root():
    """root 로 도는 파일 · 저장소 · 작업공간(사용자가 고칠 수 있는 곳)의 것을 source 하거나 실행하면 root 탈취 통로"""
    text = HELPER.read_text(encoding='utf-8')
    code = [line.split(' #', 1)[0] for line in text.splitlines() if not line.lstrip().startswith('#')]
    joined = '\n'.join(code)
    for line in code:
        assert not re.match(r'^\s*(source|\.)\s', line), line
    for word in ('site.sh', 'ros2_ws', 'WORKSPACE', 'SCRIPT_DIR', 'BASH_SOURCE', '$HOME', '~/'):
        assert word not in joined, word
    # root 면 PATH 고정 · RWSA_* 는 시험(root 아님)에서만
    root_branch = joined.split('if [[ "${EUID}" -eq 0 ]]; then', 1)[1].split('elif', 1)[0]
    assert 'TEST=0' in root_branch and 'export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' in root_branch
    assert 'if [[ "${TEST}" == "1" && -n "${!name:-}" ]]' in joined
    assert 'env -i PATH=' in joined, '재빌드는 깨끗한 환경으로'
    # 올라간 모듈 · ethercat 서비스는 건드리지 않는다(재생 중 모터를 끊지 않게) · 안내 글자는 빼고 명령 줄만
    for line in code:
        assert not re.match(r'^\s*(systemctl\s+(restart|stop|start)|rmmod|modprobe)\b', line), line


def test_helper_version_matches_site():
    helper = re.search(r'^HELPER_VERSION=(\d+)$', HELPER.read_text(encoding='utf-8'), re.M)
    site = re.search(r'^SITE_SYSTEM_HELPER_VERSION=(\d+)\b', SITE.read_text(encoding='utf-8'), re.M)
    assert helper and site and helper.group(1) == site.group(1), '도우미를 고치면 둘 다 올림'
    assert int(helper.group(1)) >= 1


# ------------------------------------------------------------------ #
# 211 · site.sh · 도우미 깔기 · sudoers 한 줄
# ------------------------------------------------------------------ #

def _install_env(tmp_path, *, visudo='exit 0', mac=ECAT_MAC, passwordless=True, allowed=False):
    """가짜 sudo · 비밀번호 없이 되는 PC(passwordless) 면 그대로 실행 · 아니면 거절 · 도우미는 RAN 만 찍음"""
    tmp_path.mkdir(parents=True, exist_ok=True)
    fake = tmp_path / 'bin'
    helper = tmp_path / 'sbin' / 'robot-web-system-apply'
    flags = tmp_path / 'flags'
    flags.mkdir()
    if passwordless:
        (flags / 'passwordless').touch()
    if allowed:
        (flags / 'allowed').touch()
    _fake(fake, 'sudo', f'''echo "sudo $*" >> "{tmp_path}/sudo.log"
while [ "$1" = "-n" ] || {{ [ "$1" = "-k" ] && [ $# -gt 1 ]; }}; do shift; done
case "$1" in
  -l) if [ -f "{flags}/allowed" ] || [ -f "{flags}/passwordless" ]; then echo "$2"; exit 0; fi; exit 1 ;;
  -k|-v) exit 0 ;;
  "{helper}") echo RAN; exit "${{HELPER_RC:-0}}" ;;
esac
[ -f "{flags}/passwordless" ] || {{ echo "sudo: a password is required" >&2; exit 1; }}
exec "$@"''')
    _fake(fake, 'visudo', f'echo "visudo $*" >> "{tmp_path}/visudo.log"\n{visudo}')
    sudoers_dir = tmp_path / 'sudoers.d'
    sudoers_dir.mkdir()
    ecat = tmp_path / 'ethercat.conf'
    if mac:
        ecat.write_text(f'MASTER0_DEVICE="{mac}"\nDEVICE_MODULES="generic"\n', encoding='utf-8')
    return {
        'PATH': f'{fake}{os.pathsep}{os.environ["PATH"]}',
        'SITE_SYSTEM_HELPER': str(helper),
        'SITE_SUDOERS_DIR': str(sudoers_dir),
        'SITE_SYSTEM_CONF': str(tmp_path / 'etc' / 'robot-web' / 'system-apply.conf'),
        'SITE_ROOT_OWNER': _me(),
        'SITE_ETHERCAT_CONF': str(ecat),
        'SITE_ETHERCAT_CONF_CANDIDATES': str(ecat),
        'SITE_ETHERCATCTL_CANDIDATES': str(tmp_path / 'none'),
    }, helper, sudoers_dir


def test_sudoers_line_is_exactly_one_command_without_arguments():
    out = _bash(f'source "{SITE}"; site_render_system_sudoers robot').stdout
    lines = [line for line in out.splitlines() if line and not line.startswith('#')]
    assert lines == ['robot ALL=(root) NOPASSWD: /usr/local/sbin/robot-web-system-apply ""']
    assert all(line.startswith('# ') for line in out.splitlines() if line.startswith('#')), '#include 로 읽히지 않게'


@pytest.mark.skipif(shutil.which('visudo') is None, reason='visudo 없음')
def test_real_visudo_accepts_the_rendered_sudoers(tmp_path):
    out = _bash(f'source "{SITE}"; site_render_system_sudoers robot').stdout
    path = tmp_path / 'robot-web-system-apply'
    path.write_text(out, encoding='utf-8')
    path.chmod(0o440)
    result = subprocess.run(['visudo', '-cf', str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_helper_install_copies_the_helper_records_the_nic_and_writes_the_sudoers_line(tmp_path):
    env, helper, sudoers_dir = _install_env(tmp_path)
    first = _site('site_system_helper_install robot', env)
    assert helper.read_bytes() == HELPER.read_bytes(), '저장소 파일의 복사본 · 실행할 때 저장소를 안 읽는다'
    assert stat.S_IMODE(helper.stat().st_mode) == 0o755
    sudoers = sudoers_dir / 'robot-web-system-apply'
    assert sudoers.read_text(encoding='utf-8').splitlines()[-1] == f'robot ALL=(root) NOPASSWD: {helper} ""'
    assert stat.S_IMODE(sudoers.stat().st_mode) == 0o440
    assert sorted(p.name for p in sudoers_dir.iterdir()) == ['robot-web-system-apply'], '임시 파일 없음'
    assert (tmp_path / 'visudo.log').read_text(encoding='utf-8').strip() == \
        f'visudo -cf {sudoers_dir}/.robot-web-system-apply.new', '「.」 든 이름(sudo 가 안 읽음)으로 확인 뒤 바꿔 넣기'
    conf = Path(env['SITE_SYSTEM_CONF'])
    assert f'ETHERCAT_MAC={ECAT_MAC.lower()}' in conf.read_text(encoding='utf-8').splitlines()
    assert stat.S_IMODE(conf.stat().st_mode) == 0o644
    assert '도우미 깔음' in first and 'sudo 허용' in first
    # 두 번째 · 바꿀 것 없음 · visudo 도 안 부름
    second = _site('site_system_helper_install robot', env)
    assert '도우미 이미 최신' in second and '랜카드 기록 그대로' in second and 'sudo 허용 그대로' in second
    assert (tmp_path / 'visudo.log').read_text(encoding='utf-8').count('visudo') == 1


def test_helper_install_refuses_bad_account_names(tmp_path):
    env, helper, sudoers_dir = _install_env(tmp_path)
    for name in ('root', 'Robot', 'a b', 'x;y', 'a:b', '%sudo', 'ALL', 'a\nb'):
        result = _bash(f'source "{SITE}"; site_system_helper_install "$NAME"', {**env, 'NAME': name})
        assert result.returncode == 1, name
        assert '넣지 않음' in result.stderr, name
    assert not helper.exists() and list(sudoers_dir.iterdir()) == []


def test_visudo_failure_installs_no_sudoers(tmp_path):
    env, helper, sudoers_dir = _install_env(tmp_path, visudo='echo "syntax error" >&2; exit 1')
    result = _bash(f'set -Eeuo pipefail; source "{SITE}"; site_system_helper_install robot || echo "실패 계속"', env)
    assert result.returncode == 0 and '실패 계속' in result.stdout
    assert 'visudo' in result.stderr
    assert list(sudoers_dir.iterdir()) == [], '틀린 줄도 임시 파일도 남지 않음'


def test_helper_install_dry_run_changes_nothing(tmp_path):
    env, helper, sudoers_dir = _install_env(tmp_path)
    out = _site('site_system_helper_install robot', {**env, 'SITE_DRY_RUN': '1'})
    assert '[dry-run]' in out and f'robot ALL=(root) NOPASSWD: {helper} ""' in out
    assert not helper.exists() and list(sudoers_dir.iterdir()) == []
    assert not Path(env['SITE_SYSTEM_CONF']).exists()
    assert not (tmp_path / 'sudo.log').exists()


def test_pc_without_ethercat_records_none(tmp_path):
    env, _, _ = _install_env(tmp_path / 'speaker', mac=None)
    _site('site_system_helper_install robot', env)
    assert 'ETHERCAT_MAC=none' in Path(env['SITE_SYSTEM_CONF']).read_text(encoding='utf-8').splitlines()
    # 직렬 서보 전용 표시(SITE_ETHERCAT_NIC=none)도 none
    env, _, _ = _install_env(tmp_path / 'serial')
    Path(env['SITE_ETHERCAT_CONF']).write_text(f'# robot_web-ethercat: none\nMASTER0_DEVICE="{ECAT_MAC}"\n',
                                               encoding='utf-8')
    _site('site_system_helper_install robot', env)
    assert 'ETHERCAT_MAC=none' in Path(env['SITE_SYSTEM_CONF']).read_text(encoding='utf-8').splitlines()


def test_nic_change_is_recorded_for_the_helper(tmp_path):
    """ethercat_nic.sh 로 랜카드를 바꾸면 도우미 기록도 바뀜"""
    env, _, _ = _install_env(tmp_path)
    _site('site_system_helper_install robot', env)
    Path(env['SITE_ETHERCAT_CONF']).write_text('MASTER0_DEVICE="aa:bb:cc:dd:ee:02"\n', encoding='utf-8')
    out = _site('site_system_record_nic', env)
    assert 'ETHERCAT_MAC=aa:bb:cc:dd:ee:02' in Path(env['SITE_SYSTEM_CONF']).read_text(encoding='utf-8').splitlines()
    assert '랜카드 기록 ·' in out


def test_selfcheck_row_for_the_helper(tmp_path):
    env, helper, _ = _install_env(tmp_path / 'a', passwordless=False)
    assert _site('site_system_helper_ok', env).strip() == '0'
    assert f'bash {ALLOW}' in _site('site_system_helper_detail', env)
    env, helper, _ = _install_env(tmp_path / 'b')
    _site('site_system_helper_install robot', env)
    assert _site('site_system_helper_ok', env).strip() == '1'
    assert '비밀번호 없이' in _site('site_system_helper_detail', env)
    # 옛 버전
    _put_helper(helper, version=0)
    assert _site('site_system_helper_ok', env).strip() == '0'
    assert '옛 버전' in _site('site_system_helper_detail', env)
    # 다른 계정이 고칠 수 있음
    _put_helper(helper)
    helper.chmod(0o777)
    assert _site('site_system_helper_ok', env).strip() == '0'
    assert '755 가 아님' in _site('site_system_helper_detail', env)


# ------------------------------------------------------------------ #
# 211 · 웹 업데이트(--code-only) 가 도우미를 부른다 · 없거나 옛 버전이면 까는 명령 한 줄
# ------------------------------------------------------------------ #

def _code_only(env):
    """install.sh --code-only 와 같은 조건 · set -Eeuo pipefail + ERR 덫 + sudo -n + `|| echo`"""
    return _bash(
        f'set -Eeuo pipefail; trap \'echo TRAP >&2; exit 9\' ERR; source "{SITE}"; '
        'sudo() { command sudo -n "$@"; }; '
        'site_system_apply_code_only || echo "계속"; echo 끝', env)


def _put_helper(helper, version=None):
    helper.parent.mkdir(parents=True, exist_ok=True)
    text = HELPER.read_text(encoding='utf-8')
    if version is not None:
        text = re.sub(r'^HELPER_VERSION=\d+$', f'HELPER_VERSION={version}', text, flags=re.M)
    helper.write_text(text, encoding='utf-8')
    helper.chmod(0o755)


def _hint_count(text):
    return text.count(f'bash {ALLOW}')


def test_code_only_runs_the_installed_helper(tmp_path):
    env, helper, _ = _install_env(tmp_path, passwordless=False, allowed=True)
    _put_helper(helper)
    result = _code_only(env)
    assert result.returncode == 0 and 'TRAP' not in result.stderr
    assert 'RAN' in result.stdout and result.stdout.strip().splitlines()[-1] == '끝'
    assert '계속' not in result.stdout, '도우미가 0 이면 성공'
    assert _hint_count(result.stdout + result.stderr) == 0
    log = (tmp_path / 'sudo.log').read_text(encoding='utf-8').splitlines()
    assert f'sudo -n -n {helper}' in log, '인자 없이 (sudoers 「""」)'
    assert f'sudo -n -n -k -l {helper}' in log, '방금 친 비밀번호(sudo 시간)로 「허용됨」 이 되지 않게'


def test_code_only_without_the_helper_prints_the_one_command_and_goes_on(tmp_path):
    env, helper, sudoers_dir = _install_env(tmp_path, passwordless=False)
    result = _code_only(env)
    assert result.returncode == 0 and 'TRAP' not in result.stderr
    assert result.stdout.strip().splitlines()[-2:] == ['계속', '끝']
    assert 'RAN' not in result.stdout
    assert _hint_count(result.stderr) == 1, result.stderr
    assert '수정 목록 211' in result.stderr
    assert not helper.exists() and list(sudoers_dir.iterdir()) == []


def test_code_only_with_an_old_helper_runs_it_and_asks_for_the_update(tmp_path):
    env, helper, _ = _install_env(tmp_path, passwordless=False, allowed=True)
    _put_helper(helper, version=0)
    result = _code_only(env)
    assert result.returncode == 0 and 'TRAP' not in result.stderr
    assert 'RAN' in result.stdout, '옛 것으로라도 한다'
    assert '옛 버전' in result.stderr and _hint_count(result.stderr) == 1
    assert '계속' in result.stdout


def test_code_only_with_the_helper_but_no_sudoers_prints_the_command(tmp_path):
    env, helper, _ = _install_env(tmp_path, passwordless=False, allowed=False)
    _put_helper(helper)
    result = _code_only(env)
    assert 'RAN' not in result.stdout and _hint_count(result.stderr) == 1
    assert '허용' in result.stderr


def test_code_only_on_a_passwordless_sudo_account_installs_then_runs(tmp_path):
    env, helper, sudoers_dir = _install_env(tmp_path, passwordless=True)
    result = _code_only(env)
    assert result.returncode == 0 and 'TRAP' not in result.stderr, result.stderr
    assert helper.read_bytes() == HELPER.read_bytes()
    assert (sudoers_dir / 'robot-web-system-apply').exists()
    assert 'RAN' in result.stdout and _hint_count(result.stderr) == 0


def test_code_only_dry_run_does_nothing(tmp_path):
    env, helper, _ = _install_env(tmp_path)
    out = _site('site_system_apply_code_only', {**env, 'SITE_DRY_RUN': '1'})
    assert f'[dry-run] sudo -n {helper}' in out
    assert not (tmp_path / 'sudo.log').exists()


def test_allow_script_installs_then_checks_without_the_cached_password(tmp_path):
    env, helper, sudoers_dir = _install_env(tmp_path)
    result = _bash(f'bash "{ALLOW}"', env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert helper.exists() and (sudoers_dir / 'robot-web-system-apply').exists()
    log = (tmp_path / 'sudo.log').read_text(encoding='utf-8').splitlines()
    assert 'sudo -k' in log, '저장된 비밀번호를 지우고'
    assert log.index('sudo -k') < log.index(f'sudo -n -k -l {helper}') < log.index(f'sudo -n {helper}')
    assert 'RAN' in result.stdout and '완료' in result.stdout


def test_helper_steps_are_wired_into_install_speaker_check_and_nic_script():
    install = INSTALL.read_text(encoding='utf-8')
    prepare = install.split('prepare_site() {', 1)[1].split('\n}\n', 1)[0]
    assert prepare.index('site_ethercat_configure') < prepare.index('site_system_helper_install'), '랜카드를 정한 뒤'
    step = install.split('print_step "2-1. 시스템 설정', 1)[1].split('print_step', 1)[0]
    code_only, terminal = step.split('else', 1)
    assert 'site_wifi_chip_powersave_off' not in code_only and 'site_ethercat_nm_unmanage' not in code_only
    assert 'site_system_helper_install' in terminal
    main = install[install.index('print_step "8. 전체 빌드"'):]
    assert main.index('build_workspace') < main.index('site_system_apply_code_only ||') < main.index('install_user_services'), \
        '서비스가 꺼진 동안(빌드 뒤 · 다시 켜기 전)'
    assert 'if [[ "${CODE_ONLY}" == true ]]' in main[:main.index('site_system_apply_code_only')]
    speaker = SPEAKER.read_text(encoding='utf-8')
    code_only_branch = speaker.split('if [[ "${CODE_ONLY}" == true ]]; then', 1)[1].split('\nelse\n', 1)
    assert 'site_system_apply_code_only ||' in code_only_branch[0]
    assert 'site_system_helper_install' in code_only_branch[1].split('step "2. 코드 갱신"', 1)[0]
    check = CHECK.read_text(encoding='utf-8')
    assert 'site_system_helper_ok' in check and 'site_system_helper_detail' in check
    assert 'site_system_helper_ok' in SITE.read_text(encoding='utf-8').split('site_selfcheck() {', 1)[1]
    assert 'site_system_record_nic' in (SCRIPTS / 'ethercat_nic.sh').read_text(encoding='utf-8')
    for path in (HELPER, ALLOW, INSTALL, SPEAKER, CHECK, SITE, SCRIPTS / 'ethercat_nic.sh'):
        assert _bash(f'bash -n "{path}"').returncode == 0, path.name
