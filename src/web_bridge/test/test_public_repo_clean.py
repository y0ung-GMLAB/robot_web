"""공개 저장소 · 다른 라인(비공개) 관련 정보 없음 (사용자 2026-11-27 「퍼블릭 레포는 재지 관련 정보가 전혀 없어야」)

이 저장소(github.com/y0ung-GMLAB/robot_web)는 공개 · humble 만 둔다 · 다른 라인의 이름 · 기능 · 현장 PC 이름이
코드 · 주석 · 문서 · 시험에 들어오면 실패한다 · 걸리면 글을 고칠 것(이 목록에 예외를 더하지 말 것).
가져온 외부 코드(src/motion_system) · 외부 라이브러리(static/vendor)까지 전부 본다 · 제외는 이 파일 하나.
"""

from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
BANNED = re.compile(
    r'jazzy|raspberry|라즈베리|feetech|chicken|iic_lab|24\.04|직렬 서보|serial[_ -]servo', re.IGNORECASE)
SKIP_PREFIX = ()
SKIP_FILES = {'src/web_bridge/test/test_public_repo_clean.py'}
TEXT_SUFFIX = {'.py', '.sh', '.md', '.js', '.mjs', '.css', '.html', '.yaml', '.yml', '.json', '.txt', '.cfg',
               '.toml', '.xml', '.in', '.service', '.rules', '.pkla', ''}


def _tracked():
    if not (shutil.which('git') and (ROOT / '.git').exists()):
        pytest.skip('git 저장소 아님')
    out = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-z'], capture_output=True, timeout=60)
    if out.returncode != 0:
        pytest.skip('git ls-files 실패')
    return [name for name in out.stdout.decode('utf-8', 'replace').split('\0') if name]


def test_no_other_line_information_in_the_public_repo():
    hits = []
    for name in _tracked():
        if name.startswith(SKIP_PREFIX) or name in SKIP_FILES:
            continue
        path = ROOT / name
        if path.suffix.lower() not in TEXT_SUFFIX or not path.is_file():
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if BANNED.search(line):
                hits.append(f'{name}:{number}: {line.strip()[:100]}')
    assert hits == []
