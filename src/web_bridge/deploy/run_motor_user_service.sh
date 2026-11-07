#!/usr/bin/env bash
set -Eeuo pipefail

WORKSPACE="${MOTION_WORKSPACE:?MOTION_WORKSPACE is required}"
# 되풀이 재기동 상한 · 60초에 5번 · 넘으면 78(유닛이 다시 안 띄움) · 수정 목록 65
START_LIMIT_HELPER="${WORKSPACE}/src/web_bridge/deploy/start_limit.sh"
if [[ -f "${START_LIMIT_HELPER}" ]]; then
  # shellcheck disable=SC1090
  source "${START_LIMIT_HELPER}"
  if ! start_limit_check "$(start_limit_file motor)"       "${MOTION_MOTOR_START_LIMIT_BURST:-5}" "${MOTION_MOTOR_START_LIMIT_SEC:-60}"; then
    exit 78
  fi
fi
# 이 PC 안(루프백)에만 연다 · 수정 목록 176 (실물 NY 2026-11-07)
#
# §6-96 에서 연동된 PC 의 MIDI 로 모터를 움직이려고 네트워크에 열었다 · 그러자 Wi-Fi 가
# 막히거나 끊길 때 **이 PC 안의** 모터 상태까지 끊겼다(floating2 · 재부팅 전까지 못 돌아옴) ·
# PC 끼리 만나는 일은 연동 노드 하나가 맡는다(그룹 토픽 · 로컬과는 HTTP) · 이 서비스의 노드는
# 다른 PC 토픽을 쓰지 않는다 · 그래서 그룹과 다른 로컬 도메인 + 루프백(`group_env.py --local`).
#
# 되돌리기 · `MOTION_LOCAL_DDS=0` → 옛 방식(그룹 도메인 · 아래 `MOTION_GROUP_NETWORK` 가지).
export MOTION_GROUP_NETWORK="${MOTION_GROUP_NETWORK:-1}"
if [[ "${MOTION_GROUP_NETWORK}" == "1" ]]; then
  export ROS_LOCALHOST_ONLY=0
else
  export ROS_LOCALHOST_ONLY=1
fi
# PC 이름공간과 DDS 도메인 · §6-96
#
# "이 PC 는 누구인가"와 "어느 DDS 망에 있는가"는 그룹 설정이 주인이다 ·
# `config/motion_coordination.yaml` 의 `pc_id` 와 `dds_domain_id` · 호스트
# 이름을 따로 읽으면 주인이 둘이 된다.
#
# 바깥에서 이미 정했으면 그것을 존중한다 · 되돌릴 수 있어야 한다.
GROUP_ENV_HELPER="${WORKSPACE}/src/motion_common/motion_common/group_env.py"
if [[ -f "${GROUP_ENV_HELPER}" ]]; then
  eval "$(python3 "${GROUP_ENV_HELPER}" --local)"
fi
# 도우미가 없거나 실패해도 서비스는 떠야 한다 · 빈 값이면 예전 이름 그대로다
export MOTION_PC_NAMESPACE="${MOTION_PC_NAMESPACE:-}"
# ROS 버전 = OS 버전 (humble · jazzy) · scripts/lib/ros_distro.sh
# shellcheck disable=SC1091
source "${WORKSPACE}/scripts/lib/ros_distro.sh" 2>/dev/null || ROBOT_ROS_SETUP="/opt/ros/humble/setup.bash"
ROS_SETUP="${ROBOT_ROS_SETUP}"
WORKSPACE_SETUP="${WORKSPACE}/install/setup.bash"
SERVICE_EXECUTABLE="${WORKSPACE}/install/motion_web_bridge/lib/motion_web_bridge/motion_motor_service"

if [[ ! -f "${ROS_SETUP}" ]]; then
  echo "ROS 2 환경을 찾을 수 없습니다: ${ROS_SETUP}" >&2
  exit 1
fi
if [[ ! -f "${WORKSPACE_SETUP}" ]]; then
  echo "작업공간 빌드 환경을 찾을 수 없습니다: ${WORKSPACE_SETUP}" >&2
  exit 1
fi
if [[ ! -x "${SERVICE_EXECUTABLE}" ]]; then
  echo "Motor Manager 서비스 실행 파일을 찾을 수 없습니다: ${SERVICE_EXECUTABLE}" >&2
  exit 1
fi

# 랜이 생기기 전에 뜨면 DDS 가 루프백에 갇힌다 · §6-96
#
# Fast DDS 는 참가자를 만드는 그 순간의 랜카드만 훑는다 · 주소가 없을 때 뜨면
# `127.0.0.1` 만 광고하고, 나중에 랜이 살아나도 다시 보지 않는다 · 그래서 그 뒤로
# **영영 다른 PC 를 못 본다** · 화면에는 그냥 「통신 단절」로만 보인다.
#
# 유닛의 `After=network-online.target` 으로는 못 막는다 · 그 타깃은 시스템
# 스코프에만 있고 이건 사용자 서비스라, systemd 가 없는 유닛으로 보고 조용히
# 넘어간다 · 그래서 여기서 직접 기다린다.
#
# 랜이 영영 없어도 서비스는 떠야 한다 · 도우미는 기다리다 포기하고 0 으로 끝낸다.
NET_READY_HELPER="${WORKSPACE}/src/motion_common/motion_common/net_ready.py"
if [[ -f "${NET_READY_HELPER}" ]]; then
  python3 "${NET_READY_HELPER}" || true
fi
set +u
# 기록 파일 보존 · ROS 로그를 작업공간 log/ros 로 · 14일 지난 것 삭제 · 수정 목록 21
source "${WORKSPACE}/src/web_bridge/deploy/log_retention.sh"
prepare_ros_log_dir "${WORKSPACE}"
source "${ROS_SETUP}"
source "${WORKSPACE_SETUP}"
set -u
exec "${SERVICE_EXECUTABLE}"
