"""설치 스크립트의 코드 받기 · 실제 git 으로 돌려 본다 · 2026-10-27

브랜치 main → humble 전환을 넣으면서 줄 이어 쓰기(`\\` + 줄바꿈)가 글자 `\\n` 으로
들어간 적이 있다 · `bash -n` 은 통과했고 두 번째 업데이트부터 원격에 맞추기가 깨졌다.
그래서 문법이 아니라 동작을 본다 · 가짜 원격(main · humble)에 PC 하나를 붙여
install.sh 의 함수를 그대로 꺼내 돌린다.
"""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
INSTALL = ROOT / 'scripts' / 'install.sh'
SPEAKER = ROOT / 'scripts' / 'install_speaker.sh'

pytestmark = pytest.mark.skipif(not (shutil.which('bash') and shutil.which('git')), reason='bash · git 필요')

SCRIPT = r'''
set -euo pipefail
T="$1"; INSTALL="$2"
cd "$T"
g() { git -c user.name=t -c user.email=t@t "$@"; }
git init -q --bare remote.git
git clone -q remote.git seed 2>/dev/null
cd seed && git checkout -q -b main && echo a > f && git add f && g commit -qm one
git push -q origin main main:humble && cd ..
git clone -q -b main remote.git pc
eval "$(sed -n '/^switch_main_to_humble() {/,/^}/p; /^sync_git_repository() {/,/^}/p' "${INSTALL}")"
WORKSPACE_DIR="$T/pc"
sync_git_repository >/dev/null
echo "first=$(git -C pc rev-parse --abbrev-ref HEAD):$(git -C pc rev-parse --abbrev-ref '@{u}')"
(cd seed && echo b > f && g commit -qam two && git push -q origin main:humble)
sync_git_repository >/dev/null
echo "second=$(git -C pc log -1 --format=%s)"
git -C pc branch -q --unset-upstream
sync_git_repository >/dev/null
echo "no_upstream=$(git -C pc log -1 --format=%s)"
'''


def test_update_moves_main_to_humble_then_keeps_following_it(tmp_path):
    out = subprocess.run(['bash', '-c', SCRIPT, 'x', str(tmp_path), str(INSTALL)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert 'first=humble:origin/humble' in out.stdout
    assert 'second=two' in out.stdout
    assert 'no_upstream=two' in out.stdout


@pytest.mark.parametrize('path', [INSTALL, SPEAKER], ids=lambda p: p.name)
def test_no_literal_backslash_n_in_shell(path):
    # 파이썬으로 고치다 줄바꿈 대신 글자 `\n` 이 들어간 자국 · 셸은 `n` 이라는 인자로 읽는다
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        code = line.split('#', 1)[0]
        assert ' \\n ' not in code + ' ', f'{path.name}:{number}: {line.strip()}'
