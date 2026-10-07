#!/usr/bin/env bash
# 스피커 트리거 앱 실행 — ROS 환경을 로드한 뒤 웹 서버를 띄운다.
set -e
set +u
source /opt/ros/humble/setup.bash
source "$HOME/ros2_ws/install/setup.bash"
set -u
export ROS_LOCALHOST_ONLY=0
exec python3 "$HOME/speaker_app/backend/main.py"
