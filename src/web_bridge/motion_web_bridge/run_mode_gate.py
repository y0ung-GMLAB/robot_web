"""오프 모드 게이트 · 운전 모드가 「오프」면 움직임 명령을 전부 막는다.

세 모드의 뜻 (`motion_common.schedule_store`):

    schedule  스케줄이 1분마다 맞춘다
    manual    스케줄만 멈춘다 · 사람 조작(조그·재생·그룹)은 된다
    off       움직임 명령을 전부 차단한다 · 서보는 켠 채 제자리 유지

여기서 막는 것 · 조그 / 절대 이동 / 수동 스트림(페이더) / 애니메이션 재생
시작·초기 위치 이동 / 그룹 시작.
막지 않는 것 · 정지·긴급정지(언제나 통과) · 서보 켜고 끄기 · 알람 해제 ·
조회·설정 저장.

판정은 **저장 파일**을 읽는다 · 조회 경유(0.5초 제한)는 브리지가 잠깐 막히면
기본값(스케줄)으로 둔갑했던 전력이 있다 (§6-270 과 같은 이유).
"""

from __future__ import annotations

from typing import Any

from motion_common.schedule_store import OFF_MODE, ScheduleStore

OFF_BLOCK_MESSAGE = '오프 모드 · 명령이 차단되어 있습니다 (상단에서 모드를 바꾸세요)'


def current_run_mode(bridge: Any) -> str:
    """선택된 프로젝트의 운전 모드 · 프로젝트가 없으면 빈 문자열."""
    project_id = bridge.project_repository.selected_project_id()
    if not project_id:
        return ''
    store = ScheduleStore(
        projects_dir=str(bridge.workspace_root / 'motion_projects'),
        current_project_id=project_id,
    )
    return store.mode


def motion_command_block_reason(bridge: Any) -> str:
    """막혔으면 사유를, 아니면 빈 문자열을 돌려준다 · 읽기 실패는 막지 않는다."""
    try:
        if current_run_mode(bridge) == OFF_MODE:
            return OFF_BLOCK_MESSAGE
    except Exception as exc:  # noqa: BLE001 - 어떤 실패든 게이트는 막지 않는다
        # 파일 읽기(OSError)만이 아니다 · 프로젝트 저장소가 아직 없는 기동
        # 초기에도 여기로 온다 · 게이트의 실패가 정지 명령보다 위험해선 안 된다
        logger = getattr(bridge, 'get_logger', None)
        if callable(logger):
            logger().warn(f'운전 모드 확인 실패 · 명령은 통과시킨다: {exc}')
    return ''
