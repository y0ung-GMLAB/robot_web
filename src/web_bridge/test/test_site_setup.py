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
    # dry-run 은 sudo 가 필요 없다 · 진짜 sudo 는 `sudo ufw status` 에서 비밀번호를 기다려 멈춘다(WSL)
    fake = tmp_path / 'bin'
    fake.mkdir()
    _fake(fake, 'sudo', 'exit 1')
    env = {
        'PATH': f'{fake}{os.pathsep}{os.environ["PATH"]}',
        'SITE_TIMEZONE': 'Pacific/Kiritimati',   # 이 PC 시간대와 달라야 set-timezone 줄이 찍힌다
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
                    'timedatectl set-timezone Pacific/Kiritimati', '--enable-generic=yes', '99-ethercat.rules',
                    # 직렬 서보 어댑터 latency_timer 1 ms · 수정 목록 158-5
                    '99-robot-serial.rules',
                    'ethercat-rebuild.service', 'UPDOWN_INTERFACES="eth9"', 'systemctl enable --now ethercat',
                    # SDO 사전 읽기 끄기 패치 · 빌드 전에 · 재빌드 훅이 읽을 고정 자리 · 수정 목록 139
                    'igh-1.6.9-sdo-dict-off.patch', '/usr/local/share/robot_web/igh-sdo-dict-off.patch']:
        assert command in out, command
    assert out.index(' apply ') < out.index('./bootstrap')
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
    assert 'reset --hard "origin/${BRANCH}"' in source and 'git clone -b' in source


def _os_release_blocks_bootstrap():
    path = Path('/etc/os-release')
    if not path.exists():
        return False
    text = path.read_text(encoding='utf-8', errors='replace')
    return not ('ID=ubuntu' in text and 'VERSION_ID="22.04"' in text)


@pytest.mark.skipif(_os_release_blocks_bootstrap(), reason='bootstrap 은 우분투 22.04 에서만 앞으로 간다')
def test_bootstrap_stops_on_an_old_stack_and_moves_it_only_with_replace_old(tmp_path):
    """옛 스택(kimjoonho motion_web)도 ~/ros2_ws · 2026-10-13
    옵션 없으면 아무것도 안 바꾸고 멈춤(sudo·PC 이름 전) · --replace-old 면 옛 서비스 멈추고 폴더를 옮김(지우지 않음)."""
    old = tmp_path / 'ros2_ws'
    (old / 'src' / 'motion_web').mkdir(parents=True)
    fake = tmp_path / 'bin'
    fake.mkdir()
    calls = tmp_path / 'calls.txt'
    for name, code in (('sudo', 1), ('systemctl', 0)):
        (fake / name).write_text(f'#!/bin/sh\necho "{name} $*" >> "{calls}"\nexit {code}\n', encoding='utf-8')
        (fake / name).chmod(0o755)
    env = {'MOTION_WORKSPACE': str(old), 'PATH': f'{fake}{os.pathsep}{os.environ["PATH"]}'}

    refused = _bash(f'bash "{SCRIPTS / "bootstrap.sh"}" --name floating9 </dev/null', env)
    assert refused.returncode == 1
    assert '--replace-old' in refused.stderr
    assert (old / 'src' / 'motion_web').is_dir()
    assert not calls.exists()  # sudo 도 systemctl 도 안 불림

    # 가짜 sudo 가 1 을 돌려 옮긴 직후 멈춘다 · 그 뒤 clone 은 이 시험 밖
    _bash(f'bash "{SCRIPTS / "bootstrap.sh"}" --replace-old </dev/null', env)
    moved = list(tmp_path.glob('ros2_ws_old_*'))
    assert len(moved) == 1 and (moved[0] / 'src' / 'motion_web').is_dir()
    assert not old.exists()
    log = calls.read_text(encoding='utf-8')
    assert 'systemctl --user stop motion-control.service motion-coordination.service' in log
    assert log.index('systemctl') < log.index('sudo')


def test_the_stale_motor_config_sample_with_absolute_paths_is_gone():
    assert not (WORKSPACE / 'config' / 'active_motor_config.yaml').exists()
    for path in (WORKSPACE / 'config').glob('*.yaml'):
        assert '/home/joonho_test' not in path.read_text(encoding='utf-8'), path.name


@pytest.mark.skipif(not Path('/usr/bin/awk').exists(), reason='awk 없음')
def test_ethercat_rebuild_hook_exits_quietly_when_the_module_exists(tmp_path):
    fake = tmp_path / 'bin'
    fake.mkdir()
    # 모듈이 있고 SDO 사전 읽기 끄기 패치(sdo_dict)도 있어야 바로 끝난다 · 수정 목록 139
    _fake(fake, 'modinfo', 'if [ "$1" = "-p" ]; then echo "sdo_dict:Fetch SDO dictionaries automatically (0 = off) (uint)"; fi\nexit 0')
    result = _bash(f'PATH="{fake}:$PATH" bash "{SCRIPTS / "setup" / "ethercat-rebuild.sh"}"')
    assert result.returncode == 0 and result.stdout == ''


# ------------------------------------------------------------------ #
# 수정 목록 139 · IgH SDO 사전 자동 읽기 끄기 패치 · 설치(site.sh) · 커널 재빌드(ethercat-rebuild.sh)
# ------------------------------------------------------------------ #

LINUX_SHELL = Path('/usr/bin/awk').exists()
IGH_PATCH = SCRIPTS / 'setup' / 'patches' / 'igh-1.6.9-sdo-dict-off.patch'
REBUILD = SCRIPTS / 'setup' / 'ethercat-rebuild.sh'


def _fake(directory, name, body):
    path = directory / name
    path.write_text(f'#!/bin/sh\n{body}\n', encoding='utf-8')
    path.chmod(0o755)
    return path


# 패치 시험용 작은 소스 · IgH 소스는 저장소에 없다 · 진짜 패치가 1.6.9 에 맞는지는 문서 A(floating4 빌드)와 수동 확인
TOY_SOURCE = 'one\ntwo\nthree\n'
TOY_PATCH = (
    'diff --git a/a.txt b/a.txt\n'
    '--- a/a.txt\n'
    '+++ b/a.txt\n'
    '@@ -1,3 +1,3 @@\n'
    ' one\n'
    '-two\n'
    '+TWO\n'
    ' three\n'
)


def _toy_source(tmp_path):
    src = tmp_path / 'src'
    src.mkdir()
    (src / 'a.txt').write_text(TOY_SOURCE, encoding='utf-8', newline='\n')
    patch = tmp_path / 'toy.patch'
    patch.write_bytes(TOY_PATCH.encode())
    return src, patch


def test_igh_patch_is_a_clean_lf_git_patch_with_the_fetch_off_by_default(tmp_path):
    raw = IGH_PATCH.read_bytes()
    assert b'\r' not in raw and raw.endswith(b'\n'), 'LF · 끝 줄바꿈 (git apply 가 줄 끝까지 비교)'
    text = raw.decode('utf-8')
    assert '+unsigned int ec_sdo_dict = 0;' in text, '기본 0 = 사전 자동 읽기 안 함'
    assert '+module_param_named(sdo_dict, ec_sdo_dict, uint, S_IRUGO | S_IWUSR);' in text
    assert '+        if (!ec_sdo_dict' in text
    # IgH 소스는 4 칸 들여쓰기 · 탭이 섞이면 1.6.9 에 안 맞는다
    assert '\t' not in text
    numstat = _bash(f'git apply --numstat "{IGH_PATCH}"', cwd=tmp_path)    # 저장소 밖에서 · 패치 형식만 본다
    assert numstat.returncode == 0, numstat.stderr
    assert [line.split('\t')[2] for line in numstat.stdout.splitlines()] == [
        'master/fsm_master.c', 'master/globals.h', 'master/module.c']
    attributes = (WORKSPACE / '.gitattributes').read_text(encoding='utf-8')
    assert '* text=auto eol=lf' in attributes, '체크아웃 때 CRLF 로 바뀌면 패치가 안 맞는다'


@pytest.mark.skipif(not LINUX_SHELL, reason='리눅스 셸에서')
def test_patch_apply_is_idempotent_and_stops_the_install_when_it_does_not_fit(tmp_path):
    src, patch = _toy_source(tmp_path)
    fake = tmp_path / 'bin'
    fake.mkdir()
    _fake(fake, 'sudo', 'exec "$@"')
    env = {'PATH': f'{fake}{os.pathsep}{os.environ["PATH"]}', 'SITE_ETHERLAB_PATCH': str(patch)}
    call = f'source "{SITE}"; site_etherlab_apply_patch "{src}"'

    first = _bash(call, env)
    assert first.returncode == 0, first.stderr
    assert '적용' in first.stdout and (src / 'a.txt').read_text(encoding='utf-8') == 'one\nTWO\nthree\n'
    again = _bash(call, env)
    assert again.returncode == 0 and '이미 들어감' in again.stdout
    assert (src / 'a.txt').read_text(encoding='utf-8') == 'one\nTWO\nthree\n', '두 번 넣지 않는다'

    (src / 'a.txt').write_text('one\nzwei\nthree\n', encoding='utf-8', newline='\n')     # 다른 버전 소스
    refused = _bash(call, env)
    assert refused.returncode == 1
    assert '안 맞음' in refused.stderr and '수정 목록 139' in refused.stderr
    assert (src / 'a.txt').read_text(encoding='utf-8') == 'one\nzwei\nthree\n'


def test_dry_run_shows_the_patch_step_and_where_the_rebuild_hook_finds_it():
    out = _site('site_etherlab_apply_patch /usr/local/src/ethercat', {'SITE_DRY_RUN': '1'})
    assert '[dry-run] sudo git -C /usr/local/src/ethercat apply' in out
    assert 'igh-1.6.9-sdo-dict-off.patch' in out
    source = SITE.read_text(encoding='utf-8')
    assert '/usr/local/share/robot_web/igh-sdo-dict-off.patch' in source
    assert '/usr/local/share/robot_web/igh-sdo-dict-off.patch' in REBUILD.read_text(encoding='utf-8')


def _installed_pc(tmp_path, *, version='1.6.9 b709e581', device_modules='"generic"', exec_args='start',
                  patched=False):
    """이미 깔린 PC 흉내 · CLI · 모듈(패치 없음) · ethercat.service → ethercatctl → ethercat.conf"""
    fake = tmp_path / 'bin'
    fake.mkdir()
    (tmp_path / 'etc').mkdir()
    conf = tmp_path / 'etc' / 'ethercat.conf'
    conf.write_text(f'MASTER0_DEVICE="aa:bb:cc:dd:ee:02"\nDEVICE_MODULES={device_modules}  # 랜카드 드라이버\n',
                    encoding='utf-8', newline='\n')
    ctl = tmp_path / 'ethercatctl'
    ctl.write_text('#!/bin/sh\nif [ "$1" = "-c" ]; then\n    ETHERCAT_CONFIG="$2"\nelse\n'
                   f'    ETHERCAT_CONFIG="{conf}"\nfi\n', encoding='utf-8', newline='\n')
    sdo = '; echo "sdo_dict:Fetch SDO dictionaries automatically (0 = off) (uint)"' if patched else ''
    _fake(fake, 'ethercat', f'[ "$1" = "version" ] && echo "IgH EtherCAT master {version}"\nexit 0')
    _fake(fake, 'modinfo', f'case "$1" in -p) echo "debug_level:Debug level (uint)"{sdo} ;; '
                           '-n) echo /lib/modules/x/ethercat/master/ec_master.ko;; esac\nexit 0')
    _fake(fake, 'systemctl', f'[ "$1" = "cat" ] && printf "[Service]\\nExecStart={ctl} {exec_args}\\n"\nexit 0')
    _fake(fake, 'sudo', 'exec "$@"')
    env = {
        'PATH': f'{fake}{os.pathsep}{os.environ["PATH"]}',
        'SITE_DRY_RUN': '1',
        'SITE_ETHERLAB_SRC': str(tmp_path / 'src'),
        'SITE_ETHERCAT_CONF': str(tmp_path / 'none.conf'),
        'SITE_SYS_MODULE_DIR': str(tmp_path / 'sys'),
    }
    return env, conf


@pytest.mark.skipif(not LINUX_SHELL, reason='리눅스 셸에서')
def test_installed_but_unpatched_pc_rebuilds_only_the_kernel_modules(tmp_path):
    """PC 마다 IgH 가 다른 자리에 깔려 있다(/opt/etherlab · /usr/local/etherlab · /usr/local) ·
    `make install` 을 하면 /usr/local 에 CLI·라이브러리·ethercatctl 이 한 벌 더 생긴다 → 모듈만"""
    env, conf = _installed_pc(tmp_path)
    result = _bash(f'set -Eeuo pipefail; source "{SITE}"; site_ethercat_install', env)
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert '커널 모듈만 다시 빌드' in out
    assert f'EtherCAT 설정 · {conf} · DEVICE_MODULES="generic"' in out
    assert 'git clone --depth 1 --branch 1.6.9' in out
    assert f'sudo git -C {tmp_path / "src"} apply' in out
    assert 'make modules && sudo make modules_install && sudo depmod' in out
    assert 'modules_install install' not in out and 'ldconfig' not in out, 'make install 안 함'
    assert out.index(' apply ') < out.index('./bootstrap'), '패치가 빌드 전에'
    assert 'install -D -m 0644' in out and 'igh-sdo-dict-off.patch' in out
    assert 'ethercat-rebuild.service' in out


@pytest.mark.skipif(not LINUX_SHELL, reason='리눅스 셸에서')
def test_patched_pc_builds_nothing(tmp_path):
    env, _ = _installed_pc(tmp_path, patched=True)
    result = _bash(f'set -Eeuo pipefail; source "{SITE}"; site_ethercat_install', env)
    assert result.returncode == 0, result.stderr
    assert '패치 들어감' in result.stdout
    assert 'bootstrap' not in result.stdout and ' apply ' not in result.stdout


@pytest.mark.skipif(not LINUX_SHELL, reason='리눅스 셸에서')
def test_modules_only_rebuild_refuses_a_native_nic_driver(tmp_path):
    env, conf = _installed_pc(tmp_path, device_modules='"generic r8169"')
    result = _bash(f'set -Eeuo pipefail; source "{SITE}"; site_ethercat_install', env)
    assert result.returncode != 0
    assert 'DEVICE_MODULES="generic r8169"' in result.stderr and '수정 목록 139' in result.stderr
    assert str(conf) in result.stderr
    assert 'bootstrap' not in result.stdout and ' apply ' not in result.stdout, '아무것도 안 바꾸고 멈춤'


@pytest.mark.skipif(not LINUX_SHELL, reason='리눅스 셸에서')
def test_modules_only_rebuild_refuses_another_igh_version(tmp_path):
    env, _ = _installed_pc(tmp_path, version='1.5.2 abc')
    result = _bash(f'source "{SITE}"; site_ethercat_install', env)
    assert result.returncode == 1
    assert '1.6.9 이 아님' in result.stderr and 'bootstrap' not in result.stdout


@pytest.mark.skipif(not LINUX_SHELL, reason='리눅스 셸에서')
def test_active_ethercat_conf_follows_the_service(tmp_path):
    # ethercatctl 안의 ETHERCAT_CONFIG (configure sysconfdir) · `-c` 분기의 "$2" 는 무시
    env, conf = _installed_pc(tmp_path)
    assert _site('site_ethercat_active_conf', env).strip() == str(conf)
    # ExecStart 에 -c 설정 이 있으면 그것
    other = tmp_path / 'other.conf'
    other.write_text('DEVICE_MODULES=generic\n', encoding='utf-8')
    second = tmp_path / 'b'
    second.mkdir()
    env, _ = _installed_pc(second, exec_args=f'-c {other} start')
    assert _site('site_ethercat_active_conf', env).strip() == str(other)


def test_device_modules_are_read_without_running_the_conf(tmp_path):
    conf = tmp_path / 'ethercat.conf'
    cases = {
        'DEVICE_MODULES="generic"\n': 'generic',
        'DEVICE_MODULES=generic\n': 'generic',
        "DEVICE_MODULES='generic igb'  # 주석\n": 'generic igb',
        'DEVICE_MODULES="r8169"\n#DEVICE_MODULES="generic"\n': 'r8169',
        'DEVICE_MODULES=""\n': '',
        'DEVICE_MODULES="e1000e"\nDEVICE_MODULES="generic"\n': 'generic',
    }
    for text, expected in cases.items():
        conf.write_text(text, encoding='utf-8', newline='\n')
        assert _site(f'site_ethercat_device_modules_from "{conf}"').strip() == expected, text
    assert _bash(f'source "{SITE}"; site_ethercat_generic_only "generic"').returncode == 0
    assert _bash(f'source "{SITE}"; site_ethercat_generic_only ""').returncode == 0
    assert _bash(f'source "{SITE}"; site_ethercat_generic_only "generic r8169"').returncode == 1


def test_sdo_dict_check_row_reads_the_loaded_module(tmp_path):
    sys_dir = tmp_path / 'sys'
    env = {'SITE_SYS_MODULE_DIR': str(sys_dir)}
    assert _site('site_sdo_dict_value', env).strip() == '안 올라감'
    (sys_dir / 'ec_master' / 'parameters').mkdir(parents=True)
    assert _site('site_sdo_dict_value', env).strip() == '없음'
    assert 'systemctl restart ethercat' in _site('site_sdo_dict_detail 없음')
    (sys_dir / 'ec_master' / 'parameters' / 'sdo_dict').write_text('0\n', encoding='utf-8')
    assert _site('site_sdo_dict_value', env).strip() == '0'
    assert 'EtherCAT SDO 사전 읽기 꺼짐' in SITE.read_text(encoding='utf-8')
    check = (SCRIPTS / 'check.sh').read_text(encoding='utf-8')
    assert 'EtherCAT SDO 사전 읽기 꺼짐' in check and '/sys/module/ec_master/parameters/sdo_dict' in check
    assert _bash(f'bash -n "{SCRIPTS / "check.sh"}"').returncode == 0


@pytest.mark.skipif(not LINUX_SHELL, reason='리눅스 셸에서')
def test_ethercat_rebuild_patches_then_builds_modules_only(tmp_path):
    src, patch = _toy_source(tmp_path)
    configure = src / 'configure'
    configure.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
    configure.chmod(0o755)
    state = tmp_path / 'state'
    state.mkdir()
    fake = tmp_path / 'bin'
    fake.mkdir()
    log = tmp_path / 'make.log'
    _fake(fake, 'make', f'echo "make $*" >> "{log}"\n[ "$1" = "modules_install" ] && touch "{state}/built"\nexit 0')
    _fake(fake, 'depmod', 'exit 0')
    _fake(fake, 'dpkg', 'exit 0')
    _fake(fake, 'modinfo', f'case "$1" in -p) [ -f "{state}/built" ] && echo "sdo_dict:x (uint)";; '
                           '-n) echo /lib/modules/x/ethercat/master/ec_master.ko;; esac\nexit 0')
    env = {'PATH': f'{fake}{os.pathsep}{os.environ["PATH"]}', 'ETHERLAB_SRC': str(src), 'ETHERLAB_PATCH': str(patch)}

    first = _bash(f'bash "{REBUILD}"', env)
    assert first.returncode == 0, first.stdout + first.stderr
    assert 'sdo_dict)가 없다' in first.stdout and 'IgH 패치 적용' in first.stdout and '재빌드 완료' in first.stdout
    assert (src / 'a.txt').read_text(encoding='utf-8') == 'one\nTWO\nthree\n'
    made = log.read_text(encoding='utf-8').split()
    assert 'install' not in made, '모듈만 · CLI·라이브러리는 그대로'
    assert log.read_text(encoding='utf-8').splitlines()[1:] == ['make modules_install']

    # 패치된 모듈이면 그냥 끝 · --force 면 다시(패치는 두 번 안 넣음)
    assert _bash(f'bash "{REBUILD}"', env).stdout == ''
    forced = _bash(f'bash "{REBUILD}" --force', env)
    assert forced.returncode == 0 and '이미 들어감' in forced.stdout
    assert (src / 'a.txt').read_text(encoding='utf-8') == 'one\nTWO\nthree\n'

    # 소스가 다른 버전이면 패치 없는 모듈을 만들지 않고 멈춤
    (src / 'a.txt').write_text('one\nzwei\nthree\n', encoding='utf-8', newline='\n')
    log.unlink()
    refused = _bash(f'bash "{REBUILD}" --force', env)
    assert refused.returncode == 1 and '수정 목록 139' in refused.stderr
    assert not log.exists()

    assert _bash(f'bash "{REBUILD}" --what', env).returncode == 2


@pytest.mark.skipif(not LINUX_SHELL, reason='리눅스 셸에서')
def test_ethercat_rebuild_needs_the_installed_patch_file(tmp_path):
    src, _ = _toy_source(tmp_path)
    (src / 'configure').write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
    fake = tmp_path / 'bin'
    fake.mkdir()
    _fake(fake, 'modinfo', 'exit 0')       # 모듈은 있는데 sdo_dict 없음
    env = {'PATH': f'{fake}{os.pathsep}{os.environ["PATH"]}', 'ETHERLAB_SRC': str(src),
           'ETHERLAB_PATCH': str(tmp_path / 'missing.patch')}
    result = _bash(f'bash "{REBUILD}"', env)
    assert result.returncode == 1 and '패치 파일이 없다' in result.stderr


def test_wayland_off_line_is_added_once_and_keeps_autologin(tmp_path):
    """애니데스크 · 마스터 PC 만 · Wayland 끄기 · 수정 목록 135 (2026-10-14)"""
    conf = tmp_path / 'custom.conf'
    conf.write_text('# GDM\n[daemon]\nAutomaticLoginEnable=true\nAutomaticLogin=robot\n#WaylandEnable=false\n\n[security]\n', encoding='utf-8')
    out = _site(f'site_render_gdm_wayland_off "{conf}"')
    assert out.count('WaylandEnable=false') == 1 and '#WaylandEnable' not in out
    assert 'AutomaticLogin=robot' in out and '[security]' in out
    conf.write_text(out, encoding='utf-8')
    assert _site(f'site_render_gdm_wayland_off "{conf}"').strip() == out.strip()      # 멱등
    out = _site(f'site_render_gdm_wayland_off "{tmp_path / "none.conf"}"')
    assert out.strip().splitlines()[-2:] == ['[daemon]', 'WaylandEnable=false']


def test_serial_adapter_latency_rule_is_written_and_reloaded_in_dry_run(tmp_path):
    """직렬 서보 어댑터(U2D2 · FTDI) latency_timer 1 ms · 멱등 · 수정 목록 158-5"""
    rule = tmp_path / '99-robot-serial.rules'
    out = _site('site_serial_udev', {'SITE_DRY_RUN': '1', 'SITE_SERIAL_UDEV_RULE': str(rule)})
    assert f'[dry-run] {rule}' in out
    assert 'ACTION=="add", SUBSYSTEM=="usb-serial", DRIVER=="ftdi_sio", ATTR{latency_timer}="1"' in out
    assert 'udevadm control --reload-rules' in out
    assert 'udevadm trigger --subsystem-match=usb-serial --action=add' in out
    assert not rule.exists()          # dry-run 은 쓰지 않는다
    install = (SCRIPTS / 'install.sh').read_text(encoding='utf-8')
    assert 'site_serial_udev' in install    # EtherCAT 과 무관하게 현장 준비에서 돈다


def test_anydesk_script_parses_and_is_not_run_by_install():
    script = SCRIPTS / 'setup' / 'anydesk.sh'
    assert _bash(f'bash -n "{script}"').returncode == 0
    install = (SCRIPTS / 'install.sh').read_text(encoding='utf-8')
    assert 'anydesk' not in install.lower()        # 마스터에서만 손으로
    text = script.read_text(encoding='utf-8')
    assert 'site_wayland_off' in text and 'site_anydesk_install' in text
