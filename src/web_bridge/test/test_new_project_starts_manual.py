"""새 프로젝트는 운전 모드 「수동」 으로 시작 · 수정 목록 120 (가)

실물 2026-10-13 S-1 · 새 프로젝트를 만들자 운전 모드가 「스케줄」 이었다 · 모터·매핑을
설정하기 전에 운영 구간이 오면 스케줄이 재생을 시작하려 한다 · 새 프로젝트는 수동이 안전하다.

파일이 없는 옛 프로젝트는 그대로 「스케줄」(기본값) · 설치된 PC 가 업데이트로 멈추면 안 된다.
"""

import json

from motion_common.schedule_store import (
    DEFAULT_RUN_MODE, MANUAL_MODE, SCHEDULE_MODE, STORE_FILE_NAME, ScheduleStore,
)
from motion_web_bridge.project_repository import ProjectRepository


def test_new_project_is_manual(tmp_path):
    repository = ProjectRepository(tmp_path / 'projects')
    created = repository.create_project('시험')
    project_id = created['project']['project_id']
    data = json.loads((tmp_path / 'projects' / project_id / STORE_FILE_NAME).read_text(encoding='utf-8'))
    assert data == {'version': 2, 'mode': MANUAL_MODE, 'schedules': []}
    store = ScheduleStore(projects_dir=str(tmp_path / 'projects'), current_project_id=project_id)
    assert store.mode == MANUAL_MODE


def test_old_project_without_file_keeps_schedule_default(tmp_path):
    (tmp_path / 'projects' / 'old').mkdir(parents=True)
    store = ScheduleStore(projects_dir=str(tmp_path / 'projects'), current_project_id='old')
    assert DEFAULT_RUN_MODE == SCHEDULE_MODE
    assert store.mode == SCHEDULE_MODE
