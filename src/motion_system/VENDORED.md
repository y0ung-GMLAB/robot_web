# motion_system · robot_web 안으로 합친 코드

2026-10-02 · git 서브모듈 → robot_web 저장소 안 코드 (사용자 결정)

- 이유 · 모터 통신층(온도 등) 수정이 필요할 때 커밋·push 할 곳이 없었음
  (원본 저장소 쓰기 권한 없음)
- 이후 수정 · robot_web 커밋으로 · 원본 저장소로 되돌려 보내지 않음
- 수정 규칙 · `AGENTS.md` 「motion_system 보호」 그대로 (사용자가 대상·범위를 명시할 때만)

## 가져온 커밋 (합친 시점 · 이 상태 그대로 · 코드 변경 없음)

| 경로 | 원본 저장소 | 커밋 |
|---|---|---|
| `.` | https://github.com/kimjoonho-git/motion_system_ros2 | 5ec19096952c1f536270ca50c75bedb6cc40e996 |
| `lib/motor_manager` | https://github.com/SeonilChoi/motor_manager | a77fd250ef7904cc637a95295a6b7d8333f9e5c7 |
| `lib/robot_manager` | https://github.com/SeonilChoi/robot_manager | 84999745512490f2415c6040878d4525b30fe9eb |
| `ros2/iahrs_driver_ros2` | https://github.com/SeonilChoi/iahrs_driver_ros2 | ed1a6236e12f1440f008e34f4ae9e534d8341e55 |
| `ros2/playstation_joy_interface_ros2` | https://github.com/SeonilChoi/PlayStation-JoyInterface-ROS2 | 892b3914578c9faa157279264a418623399ffc0a |
| `ros2/xtouch_midi_ros2` | https://github.com/SeonilChoi/xtouch_midi_ros2 | f0c9edd546ab486a72a34658f943f79cb3e9a8f8 |

원본 계보 · https://github.com/SeonilChoi/motion_system → kimjoonho-git/motion_system_ros2

## 빠진 파일 (robot_web `.gitignore` 대상 · 빌드와 무관)

- `.gitmodules` (서브모듈 정의 · 이제 필요 없음)
- `ros2/motion_system_ros2/motion_control_midi/launch/__pycache__/motion_control_midi_node.launch.cpython-310.pyc`
- `ros2/playstation_joy_interface_ros2/.vscode/` 4개 (편집기 설정)

나머지 250개 파일 · 원본 커밋과 blob 해시 동일 (합칠 때 확인)

## 이후 수정 (robot_web 커밋 · 사용자 명시 지시)

| 날짜 | 경로 | 수정 | 사유 |
|---|---|---|---|
| 2026-10-04 | `lib/motor_manager/hardware/dynamixel/src/dynamixel_driver.cpp` · `include/dynamixel/dynamixel_driver.hpp` | `position(double)` 한 바퀴(0~4095) 클램프 → Extended Position 허용 raw ±`extended_position_raw_limit_`(기본 1,048,575 · param yaml `extended_position_raw_limit`) | 다이나믹셀 멀티턴 · 외부 기어 사용 · 운전 한계는 상위 `lower/upper` 로 |
| 2026-10-06 | `ros2/motion_system_ros2/motion_control_bridge/src/motor_manager_node.cpp` | 토픽 `motion_control/motor_command`·`motor_status` 의 `position`·`velocity` 를 rad · rad/s 로 (받을 때 ×180/π · 낼 때 ×π/180) · motor_manager·드라이버 4종·모터 설정 파일은 deg 그대로 | robot_web 수정 목록 6-1 · 사용자 결정 「노드 경계만」 · 같은 토픽을 쓰는 MIDI·robot_manager·rqt 노드는 robot_web 서비스가 띄우지 않아 고치지 않음(띄우면 rad 로 읽어야 함) |
