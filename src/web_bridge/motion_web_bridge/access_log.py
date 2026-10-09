"""웹 접속 기록 줄이기 · 수정 목록 77 (2026-10-08)

uvicorn 은 요청마다 한 줄을 남긴다 · 화면이 상태를 주기적으로 묻는 GET
(`/api/coordination` · `/api/schedule/status` …) 이 탭마다 쌓여 밤샘 13 시간에
한 파일이 110 MB(109만 줄 중 101만 줄)가 됐다 · 매장에서 몇 주 돌면 GB.

남기는 것 · 사람이 누른 명령(GET 이 아닌 요청)과 실패(400 이상) · 버리는 것 ·
성공한 GET(조회 · 폴링) · 오류·기동 기록(`uvicorn.error`)은 그대로.
"""

from __future__ import annotations

import logging

ACCESS_LOGGER = 'uvicorn.access'


class QuietPollingFilter(logging.Filter):
    """성공한 GET 접속 기록만 버린다 · 형식을 모르는 기록은 남긴다."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # uvicorn 접속 기록 · (client, method, path, http_version, status)
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        method = str(args[1] or '').upper()
        try:
            status = int(args[4])
        except (TypeError, ValueError):
            return True
        return not (method in ('GET', 'HEAD') and status < 400)


def install_access_log_filter(logger_name: str = ACCESS_LOGGER) -> QuietPollingFilter:
    """접속 기록에 거름망을 단다 · 두 번 불러도 하나만."""
    logger = logging.getLogger(logger_name)
    for existing in logger.filters:
        if isinstance(existing, QuietPollingFilter):
            return existing
    quiet = QuietPollingFilter()
    logger.addFilter(quiet)
    return quiet
