"""부팅 시 적용값은 지금 도는 세션 기준 · 옛 값이면 「설정 적용 필요」 · 수정 목록 116 (실물 2026-10-13)

floating4 · 업데이트(`2d5a5f8`) 뒤 모터 프로그램만 다시 켰다 · 세션 `motor-<sha>.yaml` 의 `param_file` 이
아직 플랫폼 `param/minas.yaml` 이라 Pr4.37 0 · Pr5.10 0 · Pr5.12 50 그대로 · 화면 「부팅 시 적용값」 은
새 공통 설정(150 · 4 · 0)을 보여 줬다 · 「적용」 한 번(param 파일 생성)으로 풀렸다.

시험은 모두 임시 폴더 · 저장소 `config/minas_params/` 에 쓰지 않는다.
"""

from pathlib import Path

import yaml

from motion_web_bridge import boot_params, drive_params, minas_params, service_entrypoint
from motion_web_bridge.motor_config_service import MotorConfigService

PR4_37 = (0x3437, 0)
PR5_10 = (0x3510, 0)
PR5_12 = (0x3512, 0)


def _platform_dir(root: Path) -> Path:
    """옛 세션이 가리키던 플랫폼 param 폴더 · 내용은 플랫폼 기반 그대로(Pr5.12 50 · 브레이크 지연 없음)"""
    folder = root / 'platform' / 'param'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'minas.yaml').write_text(
        yaml.safe_dump({'items': minas_params.EMBEDDED_BASE_ITEMS, 'interfaces': minas_params.EMBEDDED_INTERFACES}),
        encoding='utf-8',
    )
    return folder


def _config(path: Path, param_files):
    """세션(또는 프로젝트 모터 설정) · 축 n → 드라이버 n · MINAS"""
    payload = {
        'period': 1000000,
        'masters': [{'id': 0, 'type': 'ethercat', 'slaves': [
            {'id': axis, 'controller_index': axis, 'driver_id': axis} for axis in param_files
        ]}],
        'drivers': [
            {'id': axis, 'type': 'minas', 'param_file': str(param_file)} for axis, param_file in param_files.items()
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding='utf-8')
    return path


def _expected(ws):
    return boot_params.expected_for(ws, [{'axis': 0, 'config': {}}, {'axis': 1, 'config': {}}])


def test_an_old_session_on_the_platform_file_is_stale(tmp_path):
    ws = tmp_path / 'ws'
    session = _config(tmp_path / 'p' / 'runtime' / 'sessions' / 'motor-old.yaml',
                      {0: _platform_dir(tmp_path), 1: _platform_dir(tmp_path)})
    result = boot_params.status(session, _expected(ws), boot_params.LABELS)
    assert result['state'] == 'stale'
    assert result['message'] == '설정 적용 필요 · 지금 드라이브는 옛 부팅 값'
    assert result['source'] == 'file'   # 기록 없음(옛 버전이 켠 모터 프로그램) → 파일을 지금 읽음
    changed = {(row['axis'], row['label']): (row['running'], row['expected']) for row in result['differences']}
    assert changed[(0, 'Pr5.12')] == (50, 0)
    assert changed[(0, 'Pr4.37')] == (None, 150)
    assert changed[(1, 'Pr5.10')] == (None, 4)
    assert '0번 Pr5.12 50 → 0' in result['detail'] or '0번 Pr4.37 없음 → 150' in result['detail']
    # 표(「부팅 시 적용값」)는 지금 도는 값 · 50 이 보여야 한다
    assert result['running'][0][PR5_12] == 50


def test_a_session_on_the_generated_files_is_ok(tmp_path):
    ws = tmp_path / 'ws'
    files = {axis: minas_params.write_param_file(ws, axis, {}) for axis in (0, 1)}
    session = _config(tmp_path / 'p' / 'runtime' / 'sessions' / 'motor-new.yaml', files)
    result = boot_params.status(session, _expected(ws), boot_params.LABELS)
    assert result['state'] == 'ok' and result['differences'] == []
    assert result['running'][1][PR4_37] == 150


def test_the_snapshot_taken_at_motor_start_wins_over_the_file_now(tmp_path):
    """공통 설정을 저장(파일 다시 만듦)했지만 적용 안 함 · 드라이브는 켜질 때 값 · 다르다고 알린다"""
    ws = tmp_path / 'ws'
    file0 = minas_params.write_param_file(ws, 0, {})
    session = _config(tmp_path / 'p' / 'runtime' / 'sessions' / 'motor-a.yaml', {0: file0})
    snapshot = boot_params.write_snapshot(session, now=1000.0)
    assert snapshot.name == 'motor-a.boot.json'
    minas_params.save_site_local(ws, {'0x3437:0': 300})
    minas_params.write_param_file(ws, 0, {})
    result = boot_params.status(session, boot_params.expected_for(ws, [{'axis': 0, 'config': {}}]), boot_params.LABELS)
    assert result['source'] == 'snapshot' and result['started_at'] == 1000.0
    assert result['state'] == 'stale'
    assert result['running'][0][PR4_37] == 150   # 켜질 때 쓴 값
    assert [(r['running'], r['expected']) for r in result['differences']] == [(150, 300)]


def test_a_snapshot_of_another_session_is_ignored(tmp_path):
    session = _config(tmp_path / 'p' / 'runtime' / 'sessions' / 'motor-b.yaml', {0: _platform_dir(tmp_path)})
    boot_params.write_snapshot(session)
    session.write_text(session.read_text(encoding='utf-8') + '# 바뀜\n', encoding='utf-8')
    assert boot_params.read_snapshot(session) is None
    assert boot_params.running_values(session)['source'] == 'file'


def test_param_paths_follow_motor_manager_rules(tmp_path):
    config = tmp_path / 'sessions' / 'motor.yaml'
    absolute = tmp_path / 'abs' / 'param'
    assert boot_params.resolve_param_path(config, str(absolute), 'minas') == absolute / 'minas.yaml'
    assert boot_params.resolve_param_path(config, 'rel/driver_1.yaml', 'minas') == tmp_path / 'sessions' / 'rel' / 'driver_1.yaml'
    assert boot_params.resolve_param_path(config, 'x.yml', 'minas') == tmp_path / 'sessions' / 'x.yml'


def test_a_missing_param_file_is_stale_not_a_crash(tmp_path):
    ws = tmp_path / 'ws'
    session = _config(tmp_path / 'p' / 'runtime' / 'sessions' / 'motor-c.yaml', {0: tmp_path / 'nowhere.yaml'})
    result = boot_params.status(session, _expected(ws), boot_params.LABELS)
    assert result['state'] == 'stale'
    assert result['differences'][0]['object'] == '' and result['differences'][0]['error']


def test_no_applied_session_says_nothing(tmp_path):
    assert boot_params.status(None, _expected(tmp_path))['state'] == 'none'


def test_axes_unknown_to_the_settings_are_not_judged(tmp_path):
    ws = tmp_path / 'ws'
    session = _config(tmp_path / 'p' / 'runtime' / 'sessions' / 'motor-d.yaml', {5: _platform_dir(tmp_path)})
    assert boot_params.status(session, _expected(ws))['state'] == 'ok'


def test_the_watch_caches_and_rechecks_when_the_snapshot_changes(tmp_path):
    ws = tmp_path / 'ws'
    session = _config(tmp_path / 'p' / 'runtime' / 'sessions' / 'motor-e.yaml', {0: _platform_dir(tmp_path)})
    calls = []
    now = [0.0]

    def expected(axes):
        calls.append(list(axes))
        return _expected(ws)(axes)

    watch = boot_params.BootParamsWatch(config_file=lambda: session, expected=expected, ttl_sec=5.0, clock=lambda: now[0])
    assert watch.public_status()['state'] == 'stale'
    assert 'running' not in watch.public_status()
    assert len(calls) == 1
    now[0] = 4.0
    watch.status()
    assert len(calls) == 1, '5 초 안엔 같은 답'
    boot_params.write_snapshot(session)
    watch.status()
    assert len(calls) == 2, '모터 프로그램이 다시 켜지면(기록이 바뀌면) 바로 다시'
    assert watch.running_for_axis(0)[PR5_12] == 50
    assert watch.running_for_axis(3) is None


def test_the_watch_never_raises(tmp_path):
    def broken():
        raise RuntimeError('저장소 준비 전')

    watch = boot_params.BootParamsWatch(config_file=broken, expected=lambda axes: {})
    assert watch.status()['state'] == 'unknown'


def test_motor_start_records_what_it_writes(tmp_path):
    ws = tmp_path / 'ws'
    session = _config(tmp_path / 'p' / 'runtime' / 'sessions' / 'motor-f.yaml', {0: minas_params.write_param_file(ws, 0, {})})
    service_entrypoint.record_boot_params(session)
    assert boot_params.read_snapshot(session)['axes'][0]['values'][PR4_37] == 150
    # 기록을 못 남겨도 모터는 뜬다(예외를 밖으로 내지 않는다)
    service_entrypoint.record_boot_params(tmp_path / 'missing.yaml')


def test_motor_main_records_before_starting_the_motor_program():
    source = Path(service_entrypoint.__file__).read_text(encoding='utf-8')
    body = source.split('def motor_main', 1)[1]
    assert body.index('record_boot_params(runtime_config)') < body.index('os.execvpe')


# -- 「장비에 적용」 이 옛 부팅 목록을 다시 만든다 -- #

def _service(ws, config_file, saves):
    service = MotorConfigService.__new__(MotorConfigService)
    service.workspace_root = ws
    registry = {'motors': [{'axis': 0, 'config': {}}]}
    service.load = lambda: {'success': True, 'registry': registry, 'config_file': str(config_file), 'config_revision': 'rev-1'}

    def save(payload, *, within_operation=False):
        saves.append({**payload, 'within_operation': within_operation})
        return {'success': True}

    service.save = save
    return service


def test_apply_resaves_when_the_saved_config_still_points_at_old_boot_values(tmp_path):
    ws = tmp_path / 'ws'
    project_file = _config(tmp_path / 'p' / 'motor_axes' / 'motor.yaml', {0: _platform_dir(tmp_path)})
    saves = []
    summary = _service(ws, project_file, saves)._refresh_boot_param_files()
    assert len(saves) == 1 and saves[0]['base_revision'] == 'rev-1'
    assert saves[0]['within_operation'] is True     # 129 · 적용 작업 안에서 제 자물쇠에 안 막히게
    assert '0번' in summary


def test_apply_leaves_the_file_alone_when_boot_values_already_match(tmp_path):
    ws = tmp_path / 'ws'
    project_file = _config(tmp_path / 'p' / 'motor_axes' / 'motor.yaml', {0: minas_params.write_param_file(ws, 0, {})})
    saves = []
    assert _service(ws, project_file, saves)._refresh_boot_param_files() == ''
    assert saves == []


def test_apply_refreshes_before_preparing_the_session():
    from motion_web_bridge import motor_config_service

    text = Path(motor_config_service.__file__).read_text(encoding='utf-8')
    body = text.split('    def apply(self)', 1)[1]
    assert body.index('self._refresh_boot_param_files()') < body.index('prepare_runtime_motor_config(')


# -- 고급 표 · 「부팅 시 적용값」 은 지금 도는 값 · 적용하면 바뀔 값은 따로 -- #

def test_the_table_shows_the_running_boot_value_and_what_apply_would_write():
    from types import SimpleNamespace

    def runner(command, **_kwargs):
        index = int(command[-2], 16)
        drive = {0x3437: 0, 0x3512: 50}.get(index)
        if drive is None:
            return SimpleNamespace(returncode=1, stdout='', stderr='SDO upload aborted')
        return SimpleNamespace(returncode=0, stdout=f'0x{drive:04x} {drive}\n', stderr='')

    service = drive_params.DriveParams(
        runner=runner, target=lambda axis: {'master': 0, 'position': axis},
        boot_values=lambda axis: {PR4_37: 0, PR5_12: 50},
        boot_next=lambda axis: {PR4_37: 150, PR5_12: 50},
        boot_stale=lambda: '설정 적용 필요 · 지금 드라이브는 옛 부팅 값',
        safety_blocker=lambda: '', record=lambda _record: None,
    )
    table = service.table(0)
    rows = {row['number']: row for row in table['rows']}
    assert rows['Pr4.37']['boot'] == 0 and rows['Pr4.37']['differs_boot'] is False   # 드라이브 = 지금 도는 부팅 값
    assert rows['Pr4.37']['boot_next'] == 150
    assert rows['Pr5.12']['boot_next'] is None                                        # 같으면 안 보임
    assert table['boot_stale'].startswith('설정 적용 필요')


def test_a_save_inside_the_apply_operation_is_not_blocked_by_that_operation():
    """수정 목록 129 (실물 2026-10-13) · 「적용」 이 모터 작업을 연 채로 부른 저장이
    「모터 설정·검색·재시작 작업이 진행 중」 검사에 걸려 적용이 매번 실패했다 ·
    작업 안 저장은 그 검사를 건너뛴다 · 밖에서 부른 저장은 그대로 막힌다"""
    from types import SimpleNamespace

    busy = '모터 설정·검색·재시작 작업이 진행 중이므로 프로젝트를 변경할 수 없습니다'

    def blocked(_project_id):
        raise ValueError(busy)

    def stop_here(_payload):
        raise ValueError('검사 다음 단계까지 옴')

    service = MotorConfigService.__new__(MotorConfigService)
    service.bridge = SimpleNamespace(ensure_project_mutation_allowed=blocked)
    service.repository = SimpleNamespace(selected_project_id=lambda: 'p1')
    service.selected = Path('motor.yaml')
    service._file_from_payload = stop_here

    outside = service.save({'registry': {}})
    assert outside['success'] is False and busy in outside['message']

    inside = service.save({'registry': {}}, within_operation=True)
    assert inside['success'] is False
    assert busy not in inside['message'] and '검사 다음 단계까지 옴' in inside['message']
