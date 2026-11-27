#!/usr/bin/env bash
# 되풀이 재기동 상한 · 수정 목록 65 (실물 2026-10-07)
#
# 유닛의 `StartLimitIntervalSec=60` · `StartLimitBurst=5` 가 우분투 22.04(systemd 249) 사용자 유닛에서
# 걸리지 않았다 · 1분에 6번 죽여도 7번 모두 다시 떴다 · 고장 난 채로 끝없이 다시 뜨면 원인이 로그에
# 묻히고 드라이브도 계속 흔든다 · 실행 스크립트가 직접 센다.
#
# 기록은 `$XDG_RUNTIME_DIR`(재부팅하면 비워지는 곳) · 웹 「모터 재시작」 은 기록을 지우고 다시 띄운다
# (`motor_restart_coordinator`) · 넘으면 78 로 끝낸다 · 유닛의 `RestartPreventExitStatus=78` 이 다시 안 띄운다.

start_limit_file() {
  echo "${XDG_RUNTIME_DIR:-/tmp}/robot-web/${1:-motor}-starts"
}

# start_limit_check <기록 파일> <횟수> <초> · 넘었으면 1 (부른 쪽이 78 로 끝냄) · 아니면 이번 시작을 적고 0
start_limit_check() {
  local file="$1" burst="${2:-5}" window="${3:-60}" now stamp
  local -a recent=()
  now="$(date +%s)"
  mkdir -p "$(dirname "${file}")" 2>/dev/null || return 0
  if [[ -f "${file}" ]]; then
    while read -r stamp; do
      if [[ "${stamp}" =~ ^[0-9]+$ ]] && (( now - stamp < window )); then
        recent+=("${stamp}")
      fi
    done < "${file}"
  fi
  if (( ${#recent[@]} >= burst )); then
    echo "${window}초 안에 ${#recent[@]}번 다시 떴습니다 · 같은 고장이 되풀이되는 것으로 보고 멈춥니다 · " \
      "원인(journalctl --user -u motion-motor) 확인 뒤 웹 「모터 재시작」 또는 ${window}초 뒤 systemctl --user restart motion-motor (수정 목록 65)" >&2
    return 1
  fi
  printf '%s\n' ${recent[@]+"${recent[@]}"} "${now}" > "${file}" 2>/dev/null || true
  return 0
}
