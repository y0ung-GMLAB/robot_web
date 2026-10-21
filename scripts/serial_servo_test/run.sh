#!/bin/bash
# 직렬 서보 계층 시험 · WSL(Ubuntu 22.04 + ROS 2 Humble) · 수정 목록 158 (2026-10-21)
#   쓰는 법 · (윈도) wsl -d Ubuntu-22.04 -u root -- bash /mnt/d/my_ws/robot_web/scripts/serial_servo_test/run.sh <사용자>
#   <사용자> 의 ~/serial_servo_build 에 이 작업 폴더의 motion_system 을 EtherCAT 없이 빌드 → 가짜 버스 2개(pty) 로 노드 실행
#   root 인 이유 · motor_manager 가 SCHED_FIFO · mlockall 을 요구
set -e
USER_NAME="${1:?build user}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BUILD="$(getent passwd "$USER_NAME" | cut -d: -f6)/serial_servo_build"
su "$USER_NAME" -c "bash -c '
  set -e; set +u; source /opt/ros/humble/setup.bash
  rm -rf \"$BUILD\" && mkdir -p \"$BUILD/src\" && cd \"$BUILD\"
  S=\"$REPO/src/motion_system\"
  cp -r \"\$S/common/common_motor_interface\" \"\$S/lib/motor_manager\" \"\$S/ros2/motion_system_ros2/motion_control_msgs\" \"\$S/ros2/motion_system_ros2/motion_control_bridge\" src/
  colcon build --packages-up-to motion_control_bridge --cmake-args -DMOTOR_MANAGER_WITH_ETHERCAT=OFF -DCMAKE_BUILD_TYPE=Release > /tmp/serial_servo_build.log 2>&1 || { tail -30 /tmp/serial_servo_build.log; exit 1; }
'"
set +u
source /opt/ros/humble/setup.bash
source "$BUILD/install/setup.bash"
export ROS_DOMAIN_ID=77
echo "== param 손으로 쓴 것 (부호-크기 범위 넓힘)"
timeout 150 python3 "$HERE/serial_e2e.py"
echo "== param 웹이 저장 때 만드는 것 (serial_params)"
E2E_PARAMS=generated timeout 150 python3 "$HERE/serial_e2e.py"
