"""기록 파일 보존 상한 · 자동 정리 · 수정 목록 21 (2026-10-03)

    21-1  ROS 2 노드 로그 · ~/.ros/log 대신 <워크스페이스>/log/ros · 14일 지난 실행 폴더 삭제
    21-2  재시작 로그 log/web_apply_restart · 14일 지난 파일 삭제 · 스크립트 시작 때
    21-3  설정 변경 이력 <프로젝트>/runtime/history/<분류> · 50개 상한
    21-4  트레이스·이벤트 로그 정리는 새 기록이 쓰일 때만 · 유지 (문서화만)
"""

import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

from motion_common import store
from motion_web_bridge import motor_config_rules
from motion_web_bridge.motor_config_service import MotorConfigService

WORKSPACE = Path(__file__).resolve().parents[3]
DEPLOY = WORKSPACE / 'src/web_bridge/deploy'
HELPER = DEPLOY / 'log_retention.sh'


def _bash(script, env=None):
    return subprocess.run(
        ['bash', '-Eeuo', 'pipefail', '-c', f'source "{HELPER}"\n{script}'],
        capture_output=True, text=True, timeout=30, env={**os.environ, **(env or {})},
    )


def _aged(path, days):
    stamp = time.time() - days * 86400
    os.utime(path, (stamp, stamp))


def test_old_entries_are_removed_and_recent_ones_kept(tmp_path):
    old_file = tmp_path / 'restart-old.log'
    old_dir = tmp_path / 'launch-old'
    new_file = tmp_path / 'restart-new.log'
    old_file.write_text('x')
    old_dir.mkdir()
    (old_dir / 'launch.log').write_text('x')
    new_file.write_text('x')
    _aged(old_file, 20)
    _aged(old_dir, 20)
    _aged(new_file, 13)
    link = tmp_path / 'link'
    link.symlink_to(new_file)

    result = _bash(f'prune_old_entries "{tmp_path}"')

    assert result.returncode == 0, result.stderr
    assert not old_file.exists() and not old_dir.exists()
    assert new_file.exists() and link.is_symlink()


def test_retention_zero_or_a_missing_folder_does_nothing(tmp_path):
    victim = tmp_path / 'restart-old.log'
    victim.write_text('x')
    _aged(victim, 100)
    assert _bash(f'prune_old_entries "{tmp_path}"', {'LOG_RETENTION_DAYS': '0'}).returncode == 0
    assert victim.exists()
    assert _bash(f'prune_old_entries "{tmp_path}/none"').returncode == 0
    # 숫자가 아니면 정리하지 않는다 · 서비스 시작은 막지 않는다
    assert _bash(f'prune_old_entries "{tmp_path}" abc').returncode == 0
    assert victim.exists()


def test_ros_log_dir_moves_into_the_workspace_and_is_pruned(tmp_path):
    ros_log = tmp_path / 'log' / 'ros'
    ros_log.mkdir(parents=True)
    stale = ros_log / '2026-01-01-00-00-00-000000-pc-1'
    stale.mkdir()
    _aged(stale, 30)
    result = _bash(f'prepare_ros_log_dir "{tmp_path}"; echo "ROS_LOG_DIR=$ROS_LOG_DIR"')
    assert result.returncode == 0, result.stderr
    assert f'ROS_LOG_DIR={ros_log}' in result.stdout
    assert not stale.exists()
    # 이미 지정된 ROS_LOG_DIR 은 존중한다
    custom = tmp_path / 'elsewhere'
    result = _bash(f'prepare_ros_log_dir "{tmp_path}"; echo "ROS_LOG_DIR=$ROS_LOG_DIR"',
                   {'ROS_LOG_DIR': str(custom)})
    assert f'ROS_LOG_DIR={custom}' in result.stdout and custom.is_dir()


def test_every_service_runner_and_the_restart_script_use_the_helper():
    scripts = [
        DEPLOY / 'run_user_service.sh',
        DEPLOY / 'run_motor_service.sh',
        DEPLOY / 'run_motor_user_service.sh',
        WORKSPACE / 'src/motion_coordination/deploy/run_coordination_user_service.sh',
        WORKSPACE / 'scripts' / 'restart_motion_monitor.sh',
    ]
    for script in scripts:
        text = script.read_text(encoding='utf-8')
        assert 'deploy/log_retention.sh' in text, script.name
        assert 'prepare_ros_log_dir "${WORKSPACE}"' in text, script.name
    restart = scripts[-1].read_text(encoding='utf-8')
    # 재시작 로그는 새 로그 파일을 열기 전에 정리한다
    assert restart.index('prune_old_entries "${LOG_DIR}"') < restart.index('exec >> "${LOG_DIR}/restart-')


def test_motor_config_history_is_capped_at_fifty(tmp_path, monkeypatch):
    project = tmp_path / 'proj'
    selected = project / 'motor_axes' / 'motor_axes.yaml'
    selected.parent.mkdir(parents=True)
    selected.write_text('period: 1\n', encoding='utf-8')
    history = project / 'runtime' / 'history' / 'motor_axes'
    history.mkdir(parents=True)
    for index in range(52):
        (history / f'20250101-{index:06d}-motor_axes.yaml').write_text('old', encoding='utf-8')
    monkeypatch.setattr(motor_config_rules, 'write_motor_config_selection', lambda *a, **k: None)

    service = MotorConfigService.__new__(MotorConfigService)
    service.selected = selected
    service.repository = SimpleNamespace()
    service._write('period: 2\n')

    names = sorted(p.name for p in history.iterdir())
    assert len(names) == store.HISTORY_KEEP_FILES == 50
    assert names[0] == '20250101-000003-motor_axes.yaml'
    assert names[-1].endswith('-motor_axes.yaml') and not names[-1].startswith('20250101')
    assert selected.read_text(encoding='utf-8') == 'period: 2\n'


# 크기로 돌리기 · 수정 목록 77 (2026-10-08) · 밤샘 13 h 에 한 파일 110 MB

def test_a_log_over_the_size_limit_is_shifted_and_emptied(tmp_path):
    log = tmp_path / 'restart-1.log'
    log.write_bytes(b'x' * (1024 * 1024 + 10))
    (tmp_path / 'restart-1.log.1').write_text('older')

    result = _bash(f'rotate_log_by_size "{log}" 1 3')

    assert result.returncode == 0, result.stderr
    assert log.exists() and log.stat().st_size == 0
    assert (tmp_path / 'restart-1.log.1').stat().st_size == 1024 * 1024 + 10
    assert (tmp_path / 'restart-1.log.2').read_text() == 'older'


def test_a_small_log_or_zero_limit_is_left_alone(tmp_path):
    log = tmp_path / 'restart-1.log'
    log.write_text('short')

    assert _bash(f'rotate_log_by_size "{log}" 1 3').returncode == 0
    assert _bash(f'rotate_log_by_size "{log}" 0 3').returncode == 0
    assert log.read_text() == 'short'
    assert not (tmp_path / 'restart-1.log.1').exists()


def test_the_restart_launcher_watches_its_log_size():
    script = (WORKSPACE / 'scripts/restart_motion_monitor.sh').read_text(encoding='utf-8')
    assert 'watch_log_size "${LOG_DIR}/restart-${STAMP}.log"' in script
    assert script.index('exec >> "${LOG_DIR}/restart-${STAMP}.log"') < script.index('watch_log_size')
