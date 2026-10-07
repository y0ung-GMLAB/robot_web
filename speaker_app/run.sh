#!/usr/bin/env bash
# 스피커 트리거 앱 실행 — ROS 환경을 로드한 뒤 웹 서버를 띄운다.
# robot_web 안(robot_web/speaker_app)에서 돈다 · 메시지는 robot_web 빌드(install/)를 먼저 쓴다
# (로봇 PC 와 같은 GroupCommand 정의여야 받는다 · 수정 목록 38) · 없으면 옛 ~/ros2_ws
set -e
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$(dirname "$APP_DIR")"
set +u
source /opt/ros/humble/setup.bash
if [ -f "$WS_DIR/install/setup.bash" ]; then
  source "$WS_DIR/install/setup.bash"
else
  source "$HOME/ros2_ws/install/setup.bash"
fi
set -u
export ROS_LOCALHOST_ONLY=0
exec python3 "$APP_DIR/backend/main.py"
