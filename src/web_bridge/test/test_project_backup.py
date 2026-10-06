"""프로젝트 백업·복원·휴지통 · 수정 목록 33 (2026-10-06)"""

import hashlib
import io
import os
import time
import zipfile

import pytest

from motion_web_bridge import project_backup
from motion_web_bridge.project_repository import ProjectRepository


def _hashes(folder):
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in folder.rglob('*') if path.is_file()
    }


def _project(repository, root, name='store a'):
    project_id = repository.create_project(name)['project']['project_id']
    folder = root / project_id
    (folder / 'motions' / 'a.json').write_text('{"type":"motion_header"}\n[1,0,"x",1]\n', encoding='utf-8')
    (folder / 'runtime' / 'motion_automation.json').write_text('{"repeat_mode":"reinitialize"}', encoding='utf-8')
    (folder / 'runtime' / 'schedule_end_state.json').write_text('{}', encoding='utf-8')   # 실행 중 상태 · 빼야 함
    (folder / 'logs' / 'big.log').write_text('x' * 100, encoding='utf-8')
    return project_id, folder


def test_export_then_import_round_trips_the_settings_but_not_logs(tmp_path):
    root = tmp_path / 'projects'
    repository = ProjectRepository(root)
    project_id, folder = _project(repository, root)
    before = {
        key: value for key, value in _hashes(folder).items()
        if not key.startswith(('logs/', 'trash/')) and key != 'runtime/schedule_end_state.json'
    }

    exported = repository.export_project_zip(project_id)
    names = zipfile.ZipFile(io.BytesIO(exported['data'])).namelist()
    assert f'{project_id}/project.json' in names
    assert f'{project_id}/runtime/motion_automation.json' in names
    assert not any('logs/' in name or 'schedule_end_state' in name for name in names)

    # 새 PC · 빈 저장소에 복원
    other = ProjectRepository(tmp_path / 'new_pc')
    result = other.import_project_zip(exported['data'])
    restored = tmp_path / 'new_pc' / project_id
    assert result['imported_project_id'] == project_id
    after = {
        key: value for key, value in _hashes(restored).items()
        if not key.startswith(('logs/', 'trash/'))
    }
    assert after == before


def test_import_over_an_existing_project_needs_overwrite_and_keeps_the_old_one_in_trash(tmp_path):
    root = tmp_path / 'projects'
    repository = ProjectRepository(root)
    project_id, folder = _project(repository, root)
    other_id, other_folder = _project(repository, root, 'store b')
    data = repository.export_project_zip(project_id)['data']
    (folder / 'motions' / 'a.json').write_text('{"type":"motion_header"}\n[1,0,"x",9]\n', encoding='utf-8')

    with pytest.raises(FileExistsError):
        repository.import_project_zip(data)

    result = repository.import_project_zip(data, overwrite=True)

    assert result['replaced_to_trash'] is True
    assert '1,0,"x",1' in (folder / 'motions' / 'a.json').read_text(encoding='utf-8')
    assert any(entry['project_id'] == project_id for entry in repository.list_trash()['entries'])
    assert other_folder.is_dir()        # 다른 프로젝트는 건드리지 않는다


def test_unsafe_zip_is_refused_without_touching_the_repository(tmp_path):
    root = tmp_path / 'projects'
    repository = ProjectRepository(root)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('p/project.json', '{"project_id":"p"}')
        archive.writestr('../escape.txt', 'x')
    before = sorted(path.name for path in root.iterdir())

    with pytest.raises(ValueError, match='zip 검사 실패'):
        repository.import_project_zip(buffer.getvalue())

    assert sorted(path.name for path in root.iterdir()) == before
    assert not (tmp_path / 'escape.txt').exists()


def test_deleted_project_can_be_restored_from_trash(tmp_path):
    root = tmp_path / 'projects'
    repository = ProjectRepository(root)
    project_id, folder = _project(repository, root)
    digest = _hashes(folder)

    deleted = repository.delete_project(project_id)
    assert not folder.exists()
    entries = repository.list_trash()['entries']
    assert entries[0]['project_id'] == project_id and entries[0]['entry'] == deleted['trash_entry']

    repository.restore_trash(deleted['trash_entry'])

    assert _hashes(folder) == digest
    assert repository.list_trash()['entries'] == []


def test_trash_is_pruned_after_seven_days_counting_from_deletion(tmp_path):
    root = tmp_path / 'projects'
    repository = ProjectRepository(root)
    project_id, folder = _project(repository, root)
    old = time.time() - 30 * 24 * 3600
    os.utime(folder, (old, old))          # 오래 안 고친 프로젝트

    deleted = repository.delete_project(project_id)
    # 지운 지 얼마 안 됐다 · 프로젝트가 오래됐어도 바로 정리되면 안 된다
    assert [entry['entry'] for entry in repository.list_trash()['entries']] == [deleted['trash_entry']]

    trashed = root / project_backup.TRASH_DIR / deleted['trash_entry']
    eight_days_ago = time.time() - 8 * 24 * 3600
    os.utime(trashed, (eight_days_ago, eight_days_ago))

    assert repository.list_trash()['entries'] == []
    assert not trashed.exists()


def test_restore_refuses_when_the_id_is_taken(tmp_path):
    root = tmp_path / 'projects'
    repository = ProjectRepository(root)
    project_id, _folder = _project(repository, root)
    data = repository.export_project_zip(project_id)['data']
    deleted = repository.delete_project(project_id)
    repository.import_project_zip(data)

    with pytest.raises(ValueError, match='이미 있습니다'):
        repository.restore_trash(deleted['trash_entry'])


def test_peek_reads_the_project_id_without_unpacking(tmp_path):
    root = tmp_path / 'projects'
    repository = ProjectRepository(root)
    project_id, _folder = _project(repository, root)
    data = repository.export_project_zip(project_id)['data']

    assert project_backup.peek_project_id(data) == project_id
    assert project_backup.peek_project_id(b'not a zip') == ''


# --------------------------------------------------------------------------- #
# 자동 백업 · 하루 1회 · 14일 · 수정 목록 33-4
# --------------------------------------------------------------------------- #

def test_daily_backup_writes_one_restorable_zip_per_project_once_a_day(tmp_path):
    from datetime import date
    root = tmp_path / 'projects'
    repository = ProjectRepository(root)
    first_id, _ = _project(repository, root, 'store a')
    second_id, _ = _project(repository, root, 'store b')
    repository.delete_project(second_id)          # 휴지통 것은 백업하지 않는다

    day = date(2026, 10, 6)
    result = project_backup.daily_backup(root, repository._project_dirs(), today=day)
    assert result['created'] is True
    assert result['projects'] == [first_id]
    again = project_backup.daily_backup(root, repository._project_dirs(), today=day)
    assert again['created'] is False                # 같은 날은 한 번
    listed = repository.list_auto_backups()
    assert listed['keep_days'] == 14
    assert listed['days'][0]['day'] == '2026-10-06'
    assert [item['project_id'] for item in listed['days'][0]['projects']] == [first_id]
    # 숨김 폴더라 프로젝트 목록에 안 섞인다
    assert [item['project_id'] for item in repository.list_projects()['projects']] == [first_id]

    # 「zip 올려 복원」 에 그대로
    file = repository.auto_backup_file('2026-10-06', first_id)
    assert file['filename'] == f'{first_id}-2026-10-06-auto.zip'
    other = ProjectRepository(tmp_path / 'new_pc')
    with open(file['path'], 'rb') as handle:
        assert other.import_project_zip(handle.read())['imported_project_id'] == first_id


def test_auto_backups_older_than_fourteen_days_are_pruned(tmp_path):
    from datetime import date, timedelta
    root = tmp_path / 'projects'
    repository = ProjectRepository(root)
    _project(repository, root)
    start = date(2026, 10, 1)
    for offset in range(16):
        project_backup.daily_backup(root, repository._project_dirs(), today=start + timedelta(days=offset))
    days = [item['day'] for item in repository.list_auto_backups()['days']]
    assert len(days) == 14
    assert days[0] == '2026-10-16' and days[-1] == '2026-10-03'


def test_backup_file_names_cannot_leave_the_backup_folder(tmp_path):
    root = tmp_path / 'projects'
    root.mkdir()
    for day, project_id in (('../x', 'a'), ('2026-10-06', '../a'), ('2026-10-06', '.trash')):
        with pytest.raises(ValueError):
            project_backup.auto_backup_file(root, day, project_id)


def test_auto_backup_service_runs_in_the_background_once_per_interval():
    from motion_web_bridge import auto_backup
    now = [0.0]
    started = []
    service = auto_backup.AutoBackupService(
        lambda: {'created': True, 'day': 'd', 'projects': ['a'], 'pruned': []},
        log_info=lambda _m: None, log_error=lambda _m: None,
        clock=lambda: now[0], start_thread=started.append,
    )
    assert service.tick() is False                       # 켠 직후는 기다린다
    now[0] = auto_backup.FIRST_DELAY_SEC
    assert service.tick() is True
    assert service.tick() is False                       # 도는 중
    started[0]()                                         # 스레드가 끝난다
    assert service.last_result['projects'] == ['a']
    assert service.tick() is False                       # 다음 확인은 30분 뒤
    now[0] += auto_backup.CHECK_INTERVAL_SEC
    assert service.tick() is True


def test_auto_backup_failure_is_logged_not_raised():
    from motion_web_bridge import auto_backup
    errors = []

    def broken():
        raise OSError('disk full')

    now = [0.0]
    service = auto_backup.AutoBackupService(
        broken, log_info=lambda _m: None, log_error=errors.append,
        clock=lambda: now[0], start_thread=lambda work: work(),
    )
    now[0] = auto_backup.FIRST_DELAY_SEC
    assert service.tick() is True
    assert errors and 'disk full' in errors[0]
    assert service.tick() is False
