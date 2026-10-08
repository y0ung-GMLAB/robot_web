"""설치 스크립트 · pipefail 아래 「없으면 실패하는 명령 | wc」 금지 (실물 2026-10-08 · floating3)

`count=$(ls -1 /dev/shm/fastrtps_* 2>/dev/null | wc -l)` 는 조각이 하나도 없으면 `ls` 가
실패하고 `set -Eeuo pipefail` 때문에 8단계(전체 빌드)에서 설치가 멈췄다 · 조각이 남아 있던
PC 는 우연히 지나갔다.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = [ROOT / 'scripts/install.sh', ROOT / 'scripts/install_speaker.sh', ROOT / 'scripts/setup/site.sh']


def test_no_ls_glob_piped_into_a_count():
    offenders = []
    for path in SCRIPTS:
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if line.lstrip().startswith('#'):
                continue
            if re.search(r'\bls\b[^|#]*\*[^|#]*\|\s*wc\b', line):
                offenders.append(f'{path.name}:{number}: {line.strip()}')
    assert offenders == [], '\n'.join(offenders)


def test_dead_segment_count_survives_an_empty_folder():
    text = (ROOT / 'scripts/install.sh').read_text(encoding='utf-8')
    assert "count=$( { find /dev/shm -maxdepth 1 -name 'fastrtps_*' 2>/dev/null || true; } | wc -l)" in text
