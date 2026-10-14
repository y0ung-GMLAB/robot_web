#!/bin/bash
# robot_web 한 브랜치를 개발 PC 의 WSL(Ubuntu 22.04 + ROS 2 Humble)에서 rclpy 시험까지 · 2026-10-13
#   윈도에선 rclpy 가 없어 노드 시험(그룹 · 스케줄 · 감독 · 브리지 일부)을 못 돌렸다 · 이걸로 푸시 전에
#   쓰는 법 · (윈도 PowerShell) wsl -d Ubuntu-22.04 -- bash /mnt/d/my_ws/robot_web/scripts/test_ros_wsl.sh <브랜치> [pytest 대상...]
#   처음 한 번 · WSL 에 ros-humble · colcon 과 미니 PC 와 같은 apt 패키지
#     sudo apt-get install -y python3-fastapi python3-uvicorn python3-yaml python3-pytest python3-pytest-timeout python3-httpx python3-websockets python3-numpy
#   ~/rw_test 에 GitHub 저장소를 받아 그 브랜치를 시험(푸시된 것만) · 메시지 패키지만 빌드(motor_manager C++ 는 빼고)
#   빼는 시험 · test_site_setup dry-run(설치 스크립트를 실제로 돌려 WSL 에서 멈춤 · 실제 PC 에서만)
REF="${1:-main}"; shift || true
[[ -d ~/rw_test/.git ]] || git clone -q https://github.com/y0ung-GMLAB/robot_web.git ~/rw_test
cd ~/rw_test && git fetch -q origin "+refs/heads/${REF}:refs/remotes/origin/${REF}" && git checkout -q --detach "origin/${REF}" && echo "commit $(git log --oneline -1 | cut -c1-80)"
set +u
source /opt/ros/humble/setup.bash
colcon build --packages-up-to motion_coordination_interfaces motion_control_msgs common_motor_interface motion_web_ui >/tmp/rw_colcon.log 2>&1 || { tail -20 /tmp/rw_colcon.log; exit 1; }
source install/setup.bash
export PYTHONPATH="$(ls -d src/*/ | grep -v motion_system | sed 's#/$##' | tr '\n' ':')${PYTHONPATH}"
if [[ $# -eq 0 ]]; then set -- -m "not slow" src --deselect src/web_bridge/test/test_site_setup.py::test_dry_run_site_install_changes_nothing_and_lists_every_step; fi
timeout 1500 python3 -m pytest -p no:cacheprovider -q --tb=line --timeout=60 --timeout-method=thread "$@" > /tmp/rw_pytest.log 2>&1
echo "exit=$?"
grep -E "^/|FAILED|ERROR|passed|failed" /tmp/rw_pytest.log | cut -c1-300 | tail -40
