"""rclpy 로거는 부르는 줄마다 등급 하나 · 수정 목록 137 (실물 2026-10-14 V-24)

`schedule_end._set` 이 한 줄에서 `(log.warn if loud else log.info)(…)` 로 info 뒤 warn 을 불러
「Logger severity cannot be changed between calls.」 로 구간 끝 주차 스레드가 죽었다 · 미니 PC pytest 는
가짜 로거라 못 잡았다 · 여기 가짜 로거는 rclpy 처럼 줄마다 등급을 고정한다.
"""

import inspect
import re
import threading
from pathlib import Path

import pytest

from motion_web_bridge.schedule_end import ScheduleEnd

ROOT = Path(__file__).resolve().parents[3]


class StrictLogger:
    """rclpy `rcutils_logger` 처럼 · 부른 곳(파일 · 줄)마다 첫 등급만 허용"""

    def __init__(self):
        self.sites = {}
        self.lines = []

    def _call(self, severity, text):
        caller = inspect.stack()[2]
        site = (caller.filename, caller.lineno)
        if self.sites.setdefault(site, severity) != severity:
            raise ValueError('Logger severity cannot be changed between calls.')
        self.lines.append((severity, text))

    def info(self, text):
        self._call('info', text)

    def warning(self, text):
        self._call('warn', text)

    warn = warning

    def error(self, text):
        self._call('error', text)


def test_strict_logger_catches_the_old_one_line_pattern():
    log = StrictLogger()

    def old_style(loud, text):
        (log.warn if loud else log.info)(text)

    old_style(False, 'a')
    with pytest.raises(ValueError):
        old_style(True, 'b')


def test_schedule_end_status_lines_can_change_severity():
    log = StrictLogger()
    end = ScheduleEnd.__new__(ScheduleEnd)
    end._lock = threading.Lock()
    end._status = {}
    end.bridge = type('B', (), {'get_logger': lambda self: log})()
    end._set('parking', '기준점으로 이동 중')
    end._set('retry_wait', '구간 끝 주차 실패 · 거절 (1/3회)')
    end._set('failed', '예기치 않은 오류')
    end._set('done', '서보 OFF')
    assert [severity for severity, _ in log.lines] == ['info', 'warn', 'warn', 'info']


def test_no_logging_call_picks_its_severity_on_one_line():
    """한 줄에서 등급을 고르는 꼴(`(a.warn if x else a.info)(…)` · `getattr(logger, level …)(…)`)을 다시 쓰지 않게"""
    bad = re.compile(
        r'\((?:\w+\.)*\w+\.(?:warn|warning|info|error|debug)\s+if\s.+else\s+(?:\w+\.)*\w+\.(?:warn|warning|info|error|debug)\)\('
        r'|getattr\(\s*(?:self\.)?_?logger\s*,\s*\w+\s*,'
    )
    found = []
    for path in (ROOT / 'src').rglob('*.py'):
        if 'motion_system' in path.parts or 'test' in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
            if bad.search(line):
                found.append(f'{path.relative_to(ROOT)}:{number}')
    assert found == []


def test_a_failing_logger_does_not_stop_the_status_update():
    class Broken:
        def info(self, _text):
            raise ValueError('Logger severity cannot be changed between calls.')
        warn = warning = error = info

    end = ScheduleEnd.__new__(ScheduleEnd)
    end._lock = threading.Lock()
    end._status = {}
    end.bridge = type('B', (), {'get_logger': lambda self: Broken()})()
    end._set('retry_wait', '구간 끝 주차 실패 (1/3회)', attempts=1)
    assert end._status['state'] == 'retry_wait' and end._status['attempts'] == 1
