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
