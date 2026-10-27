# ROS 버전 = OS 버전 · source 해서 쓴다 · 2026-10-27 (브랜치 humble · jazzy)
#
#   Ubuntu 22.04 → humble · Ubuntu 24.04 → jazzy
#   모르는 OS 면 깔려 있는 쪽(jazzy · humble 순) · 둘 다 없으면 humble
#
# 정해 주는 값
#   ROBOT_ROS_DISTRO   humble | jazzy
#   ROBOT_ROS_SETUP    /opt/ros/<distro>/setup.bash
# 바깥에서 ROBOT_ROS_DISTRO 를 정했으면 그것을 쓴다(시험 · 손 설치).
# 시험용 · ROBOT_OS_RELEASE (기본 /etc/os-release) · ROBOT_ROS_ROOT (기본 /opt/ros)

robot_os_release_value() {
  local file="${ROBOT_OS_RELEASE:-/etc/os-release}"
  [[ -r "${file}" ]] || return 0
  (. "${file}" && eval "echo \"\${$1:-}\"")
}

robot_ros_distro_for_os() {
  case "$(robot_os_release_value VERSION_ID)" in
    22.04) echo humble ;;
    24.04) echo jazzy ;;
    *)
      local distro
      for distro in jazzy humble; do
        if [[ -f "${ROBOT_ROS_ROOT:-/opt/ros}/${distro}/setup.bash" ]]; then
          echo "${distro}"
          return 0
        fi
      done
      echo humble
      ;;
  esac
}

# 지원하는 OS 인가 · 0 = 예
robot_os_supported() {
  local id version
  id="$(robot_os_release_value ID)"
  version="$(robot_os_release_value VERSION_ID)"
  [[ "${id}" == "ubuntu" && ( "${version}" == "22.04" || "${version}" == "24.04" ) ]]
}

ROBOT_ROS_DISTRO="${ROBOT_ROS_DISTRO:-$(robot_ros_distro_for_os)}"
ROBOT_ROS_SETUP="${ROBOT_ROS_ROOT:-/opt/ros}/${ROBOT_ROS_DISTRO}/setup.bash"
