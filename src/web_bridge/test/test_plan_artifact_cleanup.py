"""애니 변환본 폴더 정리 · 애니 삭제 · 이름 바꾸기 · 내용 저장 · 프로젝트 삭제 · 수정 목록 208

모션 실행 노드가 재생 등록 때 `<프로젝트>/runtime/plan_artifacts/<애니>/` 에 변환본을 만든다 ·
키(크기 · 수정 시각)가 달라 옛 것을 쓸 일은 없지만 지우지 않으면 디스크에 남는다.

여기서 지키는 것:

    애니를 지우면 · 이름을 바꾸면 · 내용을 저장하면 그 애니의 변환본 폴더만 지운다(다른 애니 것은 남는다)
    프로젝트를 지우면(휴지통) 휴지통 쪽 변환본 폴더도 지운다 · 프로젝트 파일은 그대로
    조인트 매핑 같은 다른 종류 파일은 변환본을 건드리지 않는다
    변환본 자리는 쓰는 쪽과 같은 함수(`motion_common.paths.plan_artifacts_dir`)
    프로젝트 백업(zip)에 안 든다
"""

import json
from pathlib import Path

from motion_common.paths import plan_artifacts_dir
from motion_web_bridge import project_backup
from motion_web_bridge.project_repository import ProjectRepository

MOTION_TEXT = '\n'.join([
    json.dumps({'type': 'motion_header', 'rotation_unit': 'deg'}),
    json.dumps([1, 0.0, '1-1', 0.0]),
])


def _project(tmp_path):
    repository = ProjectRepository(tmp_path / 'projects')
    project_id = repository.create_project('변환본')['project']['project_id']
    project_dir = tmp_path / 'projects' / project_id
    for name in ('a.json', 'b.json'):
        repository.import_text(project_id, 'motions', name, MOTION_TEXT)
    return repository, project_id, project_dir


def _fake_artifacts(project_dir: Path, name: str) -> Path:
    folder = plan_artifacts_dir(project_dir) / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'tracks-0123.rwplan').write_bytes(b'x' * 64)
    (folder / 'samples-4567.rwplan').write_bytes(b'y' * 64)
    return folder


def test_artifacts_live_under_the_project_runtime_folder(tmp_path):
    assert plan_artifacts_dir(tmp_path / 'p') == tmp_path / 'p' / 'runtime' / 'plan_artifacts'


def test_deleting_an_animation_removes_only_its_artifacts(tmp_path):
    repository, project_id, project_dir = _project(tmp_path)
    mine = _fake_artifacts(project_dir, 'a.json')
    other = _fake_artifacts(project_dir, 'b.json')

    repository.delete_file(project_id, 'motions', 'a.json')

    assert not mine.exists(), '지운 애니의 변환본이 남았습니다'
    assert other.is_dir() and len(list(other.iterdir())) == 2


def test_renaming_an_animation_removes_the_old_artifacts(tmp_path):
    repository, project_id, project_dir = _project(tmp_path)
    old = _fake_artifacts(project_dir, 'a.json')

    repository.rename_file(project_id, 'motions', 'a.json', 'c.json')

    assert not old.exists()
    assert (project_dir / 'motions' / 'c.json').is_file()


def test_saving_an_animation_removes_its_artifacts(tmp_path):
    repository, project_id, project_dir = _project(tmp_path)
    old = _fake_artifacts(project_dir, 'a.json')

    repository.save_file(project_id, 'motions', 'a.json', MOTION_TEXT + '\n' + json.dumps([2, 0.02, '1-1', 1.0]))

    assert not old.exists()


def test_other_categories_leave_the_artifacts_alone(tmp_path):
    repository, project_id, project_dir = _project(tmp_path)
    kept = _fake_artifacts(project_dir, 'a.json')
    repository.import_text(project_id, 'motion_axis_matching', 'map.yaml', 'mappings: []\n')

    repository.delete_file(project_id, 'motion_axis_matching', 'map.yaml')

    assert kept.is_dir()


def test_deleting_a_project_drops_its_artifacts_from_the_trash(tmp_path):
    repository, project_id, project_dir = _project(tmp_path)
    _fake_artifacts(project_dir, 'a.json')

    result = repository.delete_project(project_id)

    trashed = tmp_path / 'projects' / project_backup.TRASH_DIR / result['trash_entry']
    assert (trashed / 'motions' / 'a.json').is_file(), '프로젝트 파일까지 지웠습니다'
    assert not plan_artifacts_dir(trashed).exists(), '휴지통에 변환본이 남았습니다'


def test_project_backup_leaves_the_artifacts_out(tmp_path):
    _repository, _project_id, project_dir = _project(tmp_path)
    _fake_artifacts(project_dir, 'a.json')
    assert not project_backup._included(Path('runtime') / 'plan_artifacts' / 'a.json' / 'tracks-0123.rwplan')
