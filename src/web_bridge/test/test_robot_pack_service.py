"""로봇 팩 업로드 · 하나라도 실패하면 교체하지 않는다 · 이전 팩 1개로 되돌린다

PC 1대 = 로봇 1대 · 팩은 PC 전역 `robot_pack/` · 조인트 매핑은 건드리지 않는다.
실행기 로드 검사(MuJoCo)는 주입해서 노드·uv 없이 시험한다.
"""

import io
import json
import stat
import zipfile
from pathlib import Path

import yaml

from motion_common import robot_pack
from motion_web_bridge import robot_pack_service

WORKSPACE = Path(__file__).resolve().parents[3]
CATALOG = WORKSPACE / 'catalog'

ROBOT = {
    'axes': [
        {'joint': 'neck_pitch', 'motion_id': '2-1', 'motor': 'MSMF082L1T2', 'reducer': 'KHY-90-2-RV',
         'ratio': 150, 'range_deg': [-10, 13], 'servo_bw_hz': 5},
        {'joint': 'neck_yaw', 'motion_id': '2-2', 'motor': 'MSMF082L1T2', 'reducer': 'KSD-90-2',
         'ratio': 100, 'range_deg': [-15, 15], 'servo_bw_hz': 5},
    ],
    'drive': {'profile_velocity_deg_s': 18000, 'profile_accel_deg_s2': 180000},
    'env': {
        'settle_body': 'base', 'settle_s': 10, 'torsion_k': 500, 'torsion_c': 150,
        'camera': {'lookat': [0, -0.2, 3.5], 'distance': 5.5, 'azimuth': -60, 'elevation': -5},
    },
}


def _ok_checker(workspace_root, pack_dir):
    return []


def pack_files(name='demo', version='1.0', robot=None):
    files = {
        'pack.yaml': yaml.safe_dump({'name': name, 'version': version, 'created': '2026-10-02'}),
        'robot.yaml': yaml.safe_dump(robot or ROBOT),
        'model.xml': '<mujoco/>',
        'meshes/base_0.stl': 'solid x',
    }
    for path in CATALOG.glob('*.yaml'):
        files[f'catalog/{path.name}'] = path.read_text(encoding='utf-8')
    return files


def make_zip(files, *, prefix='', extra=()):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, text in files.items():
            archive.writestr(prefix + name, text)
        for info, text in extra:
            archive.writestr(info, text)
    return buffer.getvalue()


def _install(tmp_path, data, checker=_ok_checker):
    return robot_pack_service.install_pack(tmp_path, data, checker=checker, now=lambda: 1_790_000_000)


def test_good_zip_replaces_and_keeps_the_previous(tmp_path):
    first = _install(tmp_path, make_zip(pack_files(version='1.0')))
    assert first['success'], first
    second = _install(tmp_path, make_zip(pack_files(version='2.0')))
    assert second['success'] and second['current']['version'] == '2.0'
    assert second['previous']['version'] == '1.0'
    installed = robot_pack.read_installed(tmp_path / 'robot_pack')
    assert installed['fingerprint'] == robot_pack.pack_fingerprint(tmp_path / 'robot_pack')
    assert installed['uploaded_at']
    assert not (tmp_path / 'robot_pack.incoming').exists()


def test_single_top_folder_is_the_pack_root(tmp_path):
    result = _install(tmp_path, make_zip(pack_files(), prefix='floating_1800/'))
    assert result['success'], result
    assert (tmp_path / 'robot_pack' / 'robot.yaml').is_file()
    assert (tmp_path / 'robot_pack' / 'meshes' / 'base_0.stl').is_file()


def test_macos_junk_is_ignored(tmp_path):
    data = make_zip(pack_files(), extra=[('__MACOSX/._robot.yaml', 'junk')])
    assert _install(tmp_path, data)['success']
    assert not (tmp_path / 'robot_pack' / '__MACOSX').exists()


def _refused(tmp_path, data, needle, checker=_ok_checker, limits=None, monkeypatch=None):
    assert _install(tmp_path, make_zip(pack_files(version='keep')))['success']
    for name, value in (limits or {}).items():
        monkeypatch.setattr(robot_pack_service, name, value)
    result = _install(tmp_path, data, checker)
    needles = needle if isinstance(needle, tuple) else (needle,)
    assert result['success'] is False
    assert any(n in e for e in result['errors'] for n in needles), result['errors']
    assert robot_pack.read_pack_info(tmp_path / 'robot_pack')['version'] == 'keep'
    assert not (tmp_path / 'robot_pack.incoming').exists()
    return result


def test_parent_path_is_refused(tmp_path):
    _refused(tmp_path, make_zip(pack_files(), extra=[('../evil.txt', 'x')]), '상위 폴더')
    assert not (tmp_path.parent / 'evil.txt').exists()


def test_absolute_and_backslash_paths_are_refused(tmp_path):
    _refused(tmp_path, make_zip(pack_files(), extra=[('/etc/evil', 'x')]), '절대 경로')
    _refused(tmp_path, make_zip(pack_files(), extra=[('C:/evil', 'x')]), '절대 경로')
    # Windows 의 zipfile 은 쓸 때 \ 를 / 로 바꾼다 · 어느 쪽이든 거부
    _refused(tmp_path, make_zip(pack_files(), extra=[('a\\..\\evil', 'x')]), ('\\ 포함', '상위 폴더'))


def test_symlink_is_refused(tmp_path):
    info = zipfile.ZipInfo('meshes/link.stl')
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    _refused(tmp_path, make_zip(pack_files(), extra=[(info, '/etc/passwd')]), '링크 파일')


def test_size_limits(tmp_path, monkeypatch):
    _refused(tmp_path / 'a', make_zip(pack_files()), 'zip 크기 초과',
             limits={'MAX_ZIP_BYTES': 100}, monkeypatch=monkeypatch)
    monkeypatch.undo()
    _refused(tmp_path / 'b', make_zip(pack_files()), '풀린 크기 초과',
             limits={'MAX_UNPACKED_BYTES': 200}, monkeypatch=monkeypatch)


def test_not_a_zip(tmp_path):
    _refused(tmp_path, b'not a zip', 'zip 파일이 아님')


def test_schema_errors_are_shown(tmp_path):
    files = pack_files()
    del files['model.xml']
    _refused(tmp_path, make_zip(files), 'model.xml · 파일 없음')


def test_runner_check_failure_keeps_the_current_pack(tmp_path):
    def failing(workspace_root, pack_dir):
        assert (pack_dir / 'robot.yaml').is_file()   # 검사는 풀어 둔 새 팩을 본다
        return ['model.xml · joint 없음: neck_yaw']
    _refused(tmp_path, make_zip(pack_files()), 'joint 없음: neck_yaw', checker=failing)


def test_rollback_swaps_current_and_previous(tmp_path):
    _install(tmp_path, make_zip(pack_files(version='1.0')))
    _install(tmp_path, make_zip(pack_files(version='2.0')))
    result = robot_pack_service.rollback_pack(tmp_path)
    assert result['success']
    assert result['current']['version'] == '1.0' and result['previous']['version'] == '2.0'
    assert robot_pack_service.rollback_pack(tmp_path)['current']['version'] == '2.0'


def test_rollback_without_previous(tmp_path):
    assert robot_pack_service.rollback_pack(tmp_path)['success'] is False


def test_status_without_pack(tmp_path):
    status = robot_pack_service.pack_status(tmp_path)
    assert status['current'] is None and status['previous'] is None


def test_missing_runner_is_a_reason(tmp_path):
    reasons = robot_pack_service.run_checker(tmp_path, tmp_path)
    assert reasons and '실행기 없음' in reasons[0]


def test_missing_uv_says_how_to_install(tmp_path, monkeypatch):
    """미니 PC 실측 · uv 가 없어 팩을 못 올렸다 · 고치는 길을 같이 말한다 (2026-10-02)."""
    script = tmp_path / 'scripts' / 'sim' / 'sim_run.py'
    script.parent.mkdir(parents=True)
    script.write_text('', encoding='utf-8')
    monkeypatch.setattr(robot_pack_service, '_uv', lambda: None)
    reasons = robot_pack_service.run_checker(tmp_path, tmp_path)
    assert 'uv 없음' in reasons[0]
    assert 'scripts/install.sh' in reasons[1]


def test_installer_sets_up_uv_and_mujoco():
    from pathlib import Path
    installer = (Path(__file__).resolve().parents[3] / 'scripts' / 'install.sh').read_text(encoding='utf-8')
    assert 'install_uv_and_mujoco' in installer
    assert 'https://astral.sh/uv/install.sh' in installer
    assert 'import mujoco' in installer
    # 시스템 pip 에는 깔지 않는다
    assert 'pip install' not in installer


def test_mapping_diff_only_reports(tmp_path):
    _install(tmp_path, make_zip(pack_files()))
    mapping = {'mappings': [
        {'motion_id': '2-1', 'gear_ratio': 150, 'motion_lower_deg': -10, 'motion_upper_deg': 13},
        {'motion_id': '2-2', 'gear_ratio': 50, 'motion_lower_deg': -15, 'motion_upper_deg': 15},
        {'motion_id': '9-9', 'gear_ratio': 1},
    ]}
    before = json.dumps(mapping, sort_keys=True)
    rows = {row['motion_id']: row for row in robot_pack_service.mapping_diff(tmp_path, mapping)['rows']}
    assert rows['2-1']['differences'] == []
    assert rows['2-2']['differences'] == ['감속비']
    assert rows['9-9']['differences'] == ['팩에 motion_id 없음']
    assert json.dumps(mapping, sort_keys=True) == before


def test_mapping_diff_without_pack(tmp_path):
    assert robot_pack_service.mapping_diff(tmp_path, {})['available'] is False


class _Repo:
    def __init__(self, text):
        self.text = text

    def selected_project_id(self):
        return 'p1'

    def active_file_name(self, project_id, category):
        assert category == 'motion_axis_matching'
        return 'm.yaml'

    def read_file(self, project_id, category, name):
        return {'content': self.text}


def test_active_mapping_diff_reads_the_registered_file(tmp_path):
    _install(tmp_path, make_zip(pack_files()))
    repo = _Repo(yaml.safe_dump({'mappings': [{'motion_id': '2-1', 'gear_ratio': 150,
                                              'motion_lower_deg': -10, 'motion_upper_deg': 12}]}))
    result = robot_pack_service.active_mapping_diff(tmp_path, repo)
    rows = {row['motion_id']: row for row in result['rows']}
    assert result['mapping_file'] == 'm.yaml'
    assert rows['2-1']['differences'] == ['범위']
    assert rows['2-2']['differences'] == ['조인트 매핑에 motion_id 없음']
