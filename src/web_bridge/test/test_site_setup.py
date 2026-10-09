"""한 줄 설치 · 현장 준비 스크립트 · 수정 목록 11 (2026-10-04)

    scripts/bootstrap.sh          curl | bash 진입 · 코드 받기 → install.sh --site
    scripts/install.sh --site     현장 준비(README 2~5단계) + 설치 + 자가 점검 · 재부팅 뒤 --resume
    scripts/setup/site.sh         멱등 함수 · SITE_DRY_RUN=1 이면 바꾸지 않고 찍기만

이 컨테이너엔 우분투 데스크톱·EtherLab·실기가 없다 · 여기서는 문법 · 순수 함수(자동
로그인 파일 합성 · 랜카드 고르기 · 같은 망 계산) · dry-run 경로를 본다 · 실물은 미니PC 1대로.
"""

import os
import subprocess
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[3]
SCRIPTS = WORKSPACE / 'scripts'
SITE = SCRIPTS / 'setup' / 'site.sh'


def _bash(script, env=None, cwd=None, timeout=60):
    return subprocess.run(
        ['bash', '-c', script], capture_output=True, text=True, timeout=timeout,
        cwd=str(cwd or WORKSPACE), env={**os.environ, **(env or {})},
    )


def _site(fn_call, env=None):
    result = _bash(f'set -Eeuo pipefail; source "{SITE}"; {fn_call}', env)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_every_script_parses():
    for path in [SCRIPTS / 'bootstrap.sh', SCRIPTS / 'install.sh', SITE, SCRIPTS / 'setup' / 'ethercat-rebuild.sh']:
        result = _bash(f'bash -n "{path}"')
        assert result.returncode == 0, f'{path.name}: {result.stderr}'
    for unit in ['ethercat-rebuild.service', 'motion-site-resume.service.in']:
        text = (SCRIPTS / 'setup' / unit).read_text(encoding='utf-8')
        assert '[Service]' in text and 'ExecStart=' in text, unit


def test_autologin_lines_are_added_once_and_replace_old_ones(tmp_path):
    conf = tmp_path / 'custom.conf'
    conf.write_text('# GDM\n[daemon]\nAutomaticLoginEnable=false\nAutomaticLogin=someone\n\n[security]\n', encoding='utf-8')
    out = _site(f'site_render_gdm_conf "{conf}" robot')
    assert out.count('AutomaticLoginEnable=true') == 1
    assert out.count('AutomaticLogin=robot') == 1
    assert 'someone' not in out and '[security]' in out
    # [daemon] 이 없으면 만든다 · 파일이 없어도 된다
    out = _site(f'site_render_gdm_conf "{tmp_path / "none.conf"}" robot')
    assert out.strip().splitlines()[-3:] == ['[daemon]', 'AutomaticLoginEnable=true', 'AutomaticLogin=robot']
    # 같은 입력을 두 번 넣어도 결과가 같다 (멱등)
    conf.write_text(out, encoding='utf-8')
    assert _site(f'site_render_gdm_conf "{conf}" robot').strip() == out.strip()


LINKS = (
    'lo               UNKNOWN        00:00:00:00:00:00 <LOOPBACK,UP,LOWER_UP>\n'
    'enp1s0           UP             aa:bb:cc:dd:ee:01 <BROADCAST,MULTICAST,UP,LOWER_UP>\n'
    'enp2s0           UP             aa:bb:cc:dd:ee:02 <BROADCAST,MULTICAST,UP,LOWER_UP>\n'
    'wlp3s0           UP             aa:bb:cc:dd:ee:03 <BROADCAST,MULTICAST,UP,LOWER_UP>\n'
)
ADDRS = '2: enp1s0    inet 192.168.0.23/24 brd 192.168.0.255 scope global dynamic enp1s0\n'


def test_ethercat_nic_is_the_wired_port_without_an_ip():
    picked = _site(f'site_pick_ethercat_nic_from "$(cat <<\'L\'\n{LINKS}L\n)" "$(cat <<\'A\'\n{ADDRS}A\n)" enp1s0').strip()
    assert picked == 'enp2s0 aa:bb:cc:dd:ee:02'


def test_ethercat_nic_is_not_guessed_when_ambiguous_or_absent():
    links = LINKS + 'enp4s0           UP             aa:bb:cc:dd:ee:04 <BROADCAST,MULTICAST,UP,LOWER_UP>\n'
    picked = _site(f'site_pick_ethercat_nic_from "$(cat <<\'L\'\n{links}L\n)" "$(cat <<\'A\'\n{ADDRS}A\n)" enp1s0').strip()
    assert picked == '', '유선 두 개가 다 비어 있으면 고르지 않고 묻는다'
    # 링크가 하나만 살아 있으면 그것
    links = LINKS.replace('enp2s0           UP', 'enp2s0           DOWN') + 'enp4s0           UP             aa:bb:cc:dd:ee:04 <X>\n'
    picked = _site(f'site_pick_ethercat_nic_from "$(cat <<\'L\'\n{links}L\n)" "$(cat <<\'A\'\n{ADDRS}A\n)" enp1s0').strip()
    assert picked == 'enp4s0 aa:bb:cc:dd:ee:04'
    only_lan = 'enp1s0           UP             aa:bb:cc:dd:ee:01 <X>\nwlp3s0           UP             aa:bb:cc:dd:ee:03 <X>\n'
    picked = _site(f'site_pick_ethercat_nic_from "$(cat <<\'L\'\n{only_lan}L\n)" "$(cat <<\'A\'\n{ADDRS}A\n)" enp1s0').strip()
    assert picked == ''


def test_local_networks_come_from_the_ip_addresses():
    text = ('2: enp1s0    inet 192.168.0.23/24 brd 192.168.0.255 scope global enp1s0\n'
            '3: wlp3s0    inet 10.20.30.7/16 brd 10.20.255.255 scope global wlp3s0\n')
    out = _site(f'site_local_networks_from "$(cat <<\'T\'\n{text}T\n)"')
    assert out.split() == ['10.20.0.0/16', '192.168.0.0/24']


def test_dry_run_site_install_changes_nothing_and_lists_every_step(tmp_path):
    env = {
        'SITE_TIMEZONE': 'Asia/Seoul',
        'SITE_GDM_CONF': str(tmp_path / 'gdm.conf'),
        'SITE_ETHERCAT_CONF': str(tmp_path / 'ethercat.conf'),
        'SITE_STATE_DIR': str(tmp_path / 'state'),
        'SITE_ETHERCAT_NIC': 'eth9',
    }
    result = _bash(f'bash "{SCRIPTS / "install.sh"}" --site --dry-run', env, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    for title in ['0. 사전 확인', '1. Ubuntu 버전 확인', '1-1. 현장 준비', 'dry-run 끝']:
        assert title in out, title
    # linger 가 이미 켜진 PC 는 명령 대신 「이미 켜져 있음」 을 찍는다 · 둘 다 정상 · 수정 목록 63
    linger = out.split('(linger)', 1)[-1].split('자동 로그인', 1)[0]
    assert 'loginctl enable-linger' in linger or '이미 켜져 있음' in linger, linger
    for command in ['20auto-upgrades', 'AutomaticLoginEnable=true',
                    'timedatectl set-timezone Asia/Seoul', '--enable-generic=yes', '99-ethercat.rules',
                    'ethercat-rebuild.service', 'UPDOWN_INTERFACES="eth9"', 'systemctl enable --now ethercat']:
        assert command in out, command
    # 바꾼 것이 없다
    assert not (tmp_path / 'gdm.conf').exists()
    assert not (tmp_path / 'ethercat.conf').exists()
    assert not (tmp_path / 'state').exists()


def test_install_without_options_behaves_as_before_and_rejects_unknown_ones():
    source = (SCRIPTS / 'install.sh').read_text(encoding='utf-8')
    assert 'SITE_MODE=false' in source and 'if [[ "${SITE_MODE}" == true ]]; then' in source
    result = _bash(f'bash "{SCRIPTS / "install.sh"}" --what')
    assert result.returncode == 2 and '알 수 없는 옵션' in result.stderr
    helped = _bash(f'bash "{SCRIPTS / "install.sh"}" --help')
    assert helped.returncode == 0 and '--site' in helped.stdout and '--resume' in helped.stdout


def test_the_dynamixel_only_message_no_longer_says_etherlab_is_optional():
    source = (SCRIPTS / 'install.sh').read_text(encoding='utf-8')
    assert '다이나믹셀만 쓰신다면 이 경고를 무시해도 됩니다' not in source
    assert 'libethercat' in source


def test_first_run_reboot_is_scheduled_only_in_site_mode():
    source = (SCRIPTS / 'install.sh').read_text(encoding='utf-8')
    assert 'if [[ "${rc}" == "78" ]]; then' in source
    assert 'site_schedule_resume "${WORKSPACE_DIR}"' in source
    assert 'sudo reboot' in source
    resume = (SCRIPTS / 'setup' / 'motion-site-resume.service.in').read_text(encoding='utf-8')
    assert 'install.sh --resume' in resume and '@WORKSPACE@' in resume


def test_bootstrap_refuses_root_and_other_repos_but_updates_our_workspace():
    source = (SCRIPTS / 'bootstrap.sh').read_text(encoding='utf-8')
    assert 'id -u' in source and 'robot_web' in source
    assert 'exec bash scripts/install.sh --site' in source
    assert 'pull --ff-only' in source and 'git clone -b' in source


def test_the_stale_motor_config_sample_with_absolute_paths_is_gone():
    assert not (WORKSPACE / 'config' / 'active_motor_config.yaml').exists()
    for path in (WORKSPACE / 'config').glob('*.yaml'):
        assert '/home/joonho_test' not in path.read_text(encoding='utf-8'), path.name


@pytest.mark.skipif(not Path('/usr/bin/awk').exists(), reason='awk 없음')
def test_ethercat_rebuild_hook_exits_quietly_when_the_module_exists(tmp_path):
    fake = tmp_path / 'bin'
    fake.mkdir()
    (fake / 'modinfo').write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
    (fake / 'modinfo').chmod(0o755)
    result = _bash(f'PATH="{fake}:$PATH" bash "{SCRIPTS / "setup" / "ethercat-rebuild.sh"}"')
    assert result.returncode == 0 and result.stdout == ''
