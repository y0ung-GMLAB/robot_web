#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${MOTION_WORKSPACE:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/ros_distro.sh" 2>/dev/null || ROBOT_ROS_SETUP="/opt/ros/humble/setup.bash"
ROS_SETUP="${ROBOT_ROS_SETUP}"
WORKSPACE_SETUP="${WORKSPACE}/install/setup.bash"

cd "${WORKSPACE}"

if [[ ! -f "${ROS_SETUP}" ]]; then
  echo "ROS 2 환경을 찾을 수 없습니다: ${ROS_SETUP}" >&2
  exit 1
fi

set +u
source "${ROS_SETUP}"
set -u

echo "[1/3] 전체 빌드: colcon build --symlink-install"
# UI 정적 자산 업데이트가 누락되지 않도록 기존 UI 빌드 캐시 강제 삭제
rm -rf "${WORKSPACE}/build/motion_web_ui" "${WORKSPACE}/install/motion_web_ui"
colcon build --symlink-install

if [[ ! -f "${WORKSPACE_SETUP}" ]]; then
  echo "빌드 환경을 찾을 수 없습니다: ${WORKSPACE_SETUP}" >&2
  exit 1
fi

set +u
source "${WORKSPACE_SETUP}"
set -u

echo "[2/3] 서비스 재시작: motion-control.service motion-coordination.service"
# 기다리게 둔다(`--no-block` 아님) · 수정 목록 206 점검 · 연동 서비스는 Type=notify(202) 라 노드가 「준비 끝」 을 알릴 때까지
# 이 줄에서 선다(보통 수 초 · 랜 대기 최대 60 s · 끝내 안 오면 TimeoutStartSec 600 s 뒤 실패) · 바로 아래 [3/3] 이
# `is-active` 로 결과를 보므로 기동이 끝난 뒤여야 한다(`--no-block` 이면 「activating」 으로 이 스크립트가 실패)
echo "    연동 서비스 「준비 끝」 까지 기다림 · 보통 수 초 · 랜 대기 최대 60 s"
systemctl --user restart motion-control.service motion-coordination.service

echo "[3/3] 서비스 상태"
systemctl --user is-active motion-control.service motion-coordination.service

echo "빌드·재시작 완료"
