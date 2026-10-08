#!/usr/bin/env bash
# 기록 파일 보존 · 서비스 실행 스크립트 4개가 같이 쓴다 · 수정 목록 21 (2026-10-03)
#
#   prune_old_entries <폴더> [일수]   폴더 바로 아래 항목 중 수정 시각이 <일수> 넘은 것 삭제
#   prepare_ros_log_dir <워크스페이스>  ROS 2 노드 로그를 ~/.ros/log 대신 <워크스페이스>/log/ros 로 ·
#                                      오래된 실행 폴더 삭제 · ROS_LOG_DIR 내보냄
#
# 보존 일수 · LOG_RETENTION_DAYS (기본 14) · 0 이하면 정리하지 않는다
# 이 파일은 source 해서 쓴다 · set -e 아래에서도 정리 실패가 서비스 시작을 막지 않는다

LOG_RETENTION_DAYS="${LOG_RETENTION_DAYS:-14}"

prune_old_entries() {
  local dir="$1"
  local days="${2:-${LOG_RETENTION_DAYS}}"
  [[ -d "${dir}" ]] || return 0
  [[ "${days}" =~ ^[0-9]+$ ]] || return 0
  (( days > 0 )) || return 0
  # -mtime +N · N일 하고도 더 지난 것 · 심볼릭 링크는 따라가지 않는다
  find "${dir}" -mindepth 1 -maxdepth 1 ! -type l -mtime "+$((days - 1))" \
    -exec rm -rf -- {} + 2>/dev/null || true
  return 0
}

prepare_ros_log_dir() {
  local workspace="$1"
  local dir="${ROS_LOG_DIR:-${workspace}/log/ros}"
  mkdir -p "${dir}" 2>/dev/null || return 0
  prune_old_entries "${dir}"
  export ROS_LOG_DIR="${dir}"
  return 0
}

# 크기로 돌리기 · 수정 목록 77 (2026-10-08) · 날짜 정리(위)는 파일 단위라 오래 도는 프로세스의
# 파일 하나는 줄지 않는다(밤샘 13 h · 110 MB) · <파일> 이 <최대 MB> 를 넘으면 .1 .2 … 로 밀고
# 지금 파일은 비운다(copytruncate · 쓰는 쪽이 `>>` 이어 쓰기라 안전 · 옮기는 순간 몇 줄은 빠질 수 있음)
#
#   rotate_log_by_size <파일> [최대 MB] [남길 개수]   한 번 검사
#   watch_log_size <파일>                              부른 셸이 살아 있는 동안 LOG_CHECK_SEC 마다 검사
#
# LOG_MAX_MB (기본 50) · LOG_KEEP (기본 3 · 최대 ~200 MB) · LOG_CHECK_SEC (기본 300) · 0 이면 끔

LOG_MAX_MB="${LOG_MAX_MB:-50}"
LOG_KEEP="${LOG_KEEP:-3}"
LOG_CHECK_SEC="${LOG_CHECK_SEC:-300}"

rotate_log_by_size() {
  local file="$1"
  local max_mb="${2:-${LOG_MAX_MB}}"
  local keep="${3:-${LOG_KEEP}}"
  [[ -f "${file}" ]] || return 0
  [[ "${max_mb}" =~ ^[0-9]+$ && "${keep}" =~ ^[0-9]+$ ]] || return 0
  (( max_mb > 0 && keep > 0 )) || return 0
  local size
  size="$(stat -c %s -- "${file}" 2>/dev/null)" || return 0
  (( size > max_mb * 1024 * 1024 )) || return 0
  local i
  for (( i = keep - 1; i >= 1; i-- )); do
    if [[ -f "${file}.${i}" ]]; then
      mv -f -- "${file}.${i}" "${file}.$((i + 1))" 2>/dev/null || true
    fi
  done
  cp -f -- "${file}" "${file}.1" 2>/dev/null || return 0
  : > "${file}" 2>/dev/null || true
  return 0
}

watch_log_size() {
  local file="$1"
  local parent="$$"
  [[ "${LOG_CHECK_SEC}" =~ ^[0-9]+$ ]] || return 0
  (( LOG_CHECK_SEC > 0 )) || return 0
  # 부른 셸이 끝나면(정상 · 강제 종료 모두) 같이 끝난다 · 남아 도는 감시가 없게
  (
    while kill -0 "${parent}" 2>/dev/null; do
      sleep "${LOG_CHECK_SEC}" || break
      rotate_log_by_size "${file}" || true
    done
  ) </dev/null >/dev/null 2>&1 &
  return 0
}
