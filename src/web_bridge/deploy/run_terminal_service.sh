#!/usr/bin/env bash
# 웹 터미널(ttyd) 실행 · motion-terminal.service 의 ExecStart · §6-99
#
# ttyd 버전에 따라 글자 입력 허용 플래그가 다르다 ·
#   1.6.x (우분투 22.04)  기본 쓰기 가능 · `-W` 옵션 자체가 없다 → 붙이면 안 뜬다
#   1.7.x (우분투 24.04)  기본 **읽기 전용** · `-W` 가 있어야 글자가 쳐진다
# 실제로 1.7.4 에서 셸은 뜨는데 아무것도 안 쳐졌다 · 도움말에 `--writable` 이
# 있을 때만 붙인다.
set -Eeuo pipefail

WORKSPACE="${1:?작업공간 경로가 필요합니다}"
PORT="${MOTION_WEB_TERMINAL_PORT:-8081}"

flags=(-p "${PORT}" -w "${WORKSPACE}")
if ttyd --help 2>&1 | grep -q -- '--writable'; then
  flags+=(-W)
fi

exec /usr/bin/ttyd "${flags[@]}" /bin/bash -l
