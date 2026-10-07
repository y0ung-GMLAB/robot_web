"""상위 서비스 비정상 종료 표지 · 수정 목록 72

supervisor(또는 상태 모니터)가 죽으면 launch 가 통째로 끝나고 systemd 가
`motion-control` 을 다시 띄운다(29-3 · 실물 2026-10-07 시험 53 · 10 s 안 복귀) ·
그런데 웹 브리지도 같이 죽어 운영 로그(모터 이벤트)에 아무것도 남지 않았다.

    launch      죽은 노드를 보면 표지 파일을 쓴다(`write_marker`) · 그 뒤 Shutdown
    웹 브리지   다시 뜰 때 표지를 읽어 모터 이벤트 1건으로 옮기고 지운다(`take_marker`)

정상 종료(서비스 정지 · 「프로그램 재시작」)에서는 노드가 0 · SIGINT(-2) · SIGTERM(-15)
으로 끝난다 · 그때는 쓰지 않는다 · 그 밖의 코드(예 · `kill -9` = -9 · 예외 = 1)만 쓴다.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

MARKER_NAME = 'upper_service_crash.json'

#: 정상 종료로 보는 코드 · 0 · SIGINT · SIGTERM (launch 는 신호를 음수로 준다)
NORMAL_EXIT_CODES = frozenset({0, -2, -15})


def marker_path(workspace: Path) -> Path:
    return Path(workspace) / 'log' / MARKER_NAME


def is_abnormal(returncode: Optional[int]) -> bool:
    return returncode is not None and int(returncode) not in NORMAL_EXIT_CODES


def write_marker(workspace: Path, node: str, returncode: Optional[int], *, now: Optional[float] = None) -> bool:
    """비정상 종료면 표지를 쓴다 · 썼으면 True · 쓰기 실패는 삼킨다(재시작을 막으면 안 됨)"""
    if not is_abnormal(returncode):
        return False
    path = marker_path(workspace)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            'node': str(node),
            'returncode': int(returncode),
            'stopped_at': float(now if now is not None else time.time()),
        }, ensure_ascii=False), encoding='utf-8')
    except OSError:
        return False
    return True


def take_marker(workspace: Path) -> Optional[Dict[str, Any]]:
    """표지를 읽고 지운다 · 없거나 깨졌으면 None(깨진 것도 지운다)"""
    path = marker_path(workspace)
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        return None
    try:
        path.unlink()
    except OSError:
        pass
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def event_content(marker: Dict[str, Any]) -> str:
    node = str(marker.get('node') or '?')
    code = marker.get('returncode')
    when = marker.get('stopped_at')
    try:
        when_text = time.strftime('%H:%M:%S', time.localtime(float(when)))
    except (TypeError, ValueError):
        when_text = '?'
    return f'{node} 비정상 종료(코드 {code} · {when_text}) · 상위 서비스 자동 재시작 · 모터는 제자리 유지'
