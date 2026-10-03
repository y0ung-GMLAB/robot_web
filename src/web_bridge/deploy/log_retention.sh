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
