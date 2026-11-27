# ROS 버전 · source 해서 쓴다 · 2026-10-27
#
#   Ubuntu 22.04 · ROS 2 Humble
#
# 정해 주는 값
#   ROBOT_ROS_DISTRO   humble
#   ROBOT_ROS_SETUP    /opt/ros/<distro>/setup.bash
# 바깥에서 ROBOT_ROS_DISTRO 를 정했으면 그것을 쓴다(시험 · 손 설치).
# 시험용 · ROBOT_OS_RELEASE (기본 /etc/os-release) · ROBOT_ROS_ROOT (기본 /opt/ros)

robot_os_release_value() {
  local file="${ROBOT_OS_RELEASE:-/etc/os-release}"
  [[ -r "${file}" ]] || return 0
  (. "${file}" && eval "echo \"\${$1:-}\"")
}

robot_ros_distro_for_os() {
  echo humble
}

# 지원하는 OS 인가 · 0 = 예 · Ubuntu 22.04
robot_os_supported() {
  local id version
  id="$(robot_os_release_value ID)"
  version="$(robot_os_release_value VERSION_ID)"
  [[ "${id}" == "ubuntu" && "${version}" == "22.04" ]]
}

ROBOT_ROS_DISTRO="${ROBOT_ROS_DISTRO:-$(robot_ros_distro_for_os)}"
ROBOT_ROS_SETUP="${ROBOT_ROS_ROOT:-/opt/ros}/${ROBOT_ROS_DISTRO}/setup.bash"
