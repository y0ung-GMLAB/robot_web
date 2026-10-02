# robot_manager

## English

`robot_manager` is a Python package that loads robot configuration files, creates robot objects, and manages robot commands and states.

The package includes both the `robot_manager` module and the `robots` module.

`RobotManager` reads a YAML configuration file, creates the robot implementation that matches each robot name, distributes joint status to each robot, and collects command frames generated from action frames.

## Build

```bash
colcon build --packages-select robot_manager
```

## Configuration

### YAML Example

```yaml
dt: 0.01

robot:
  - index: 0
    name: "rocking_chair"
    dt: 0.01
    controller_indices: [0]
    target_interface_ids:
      - [0, 1]
    home_positions: [0.0]
    home_duration: 5.0
    move_duration: 60.0
    init_controlword: 0x103F
    motion_data_file_path: "../motions"
```

`motion_data_file_path` may be relative to the YAML file directory.

## API

### `RobotManager`

| Function | Purpose |
| --- | --- |
| `number_of_robots` | Returns the number of robots managed by `RobotManager`. |
| `dt` | Returns the control period loaded from the YAML file. |
| `controller_indices()` | Returns a flat list of controller indices used by all robots. |
| `number_of_target_interfaces()` | Returns a flat list of target interface counts for all controllers. |
| `target_interface_ids()` | Returns a flat list of target interface ID lists for all controllers. |
| `loadConfigurations()` | Loads each robot configuration from the YAML file and creates robot objects. |
| `updateJointStatus(joint_status)` | Splits `joint_status` by robot and updates each robot's current joint status. |
| `get_state_frames()` | Returns the current `state_frame` from each robot. |
| `set_action_frames(action_frames)` | Applies each `action_frame` to the matching robot and returns the merged joint command. |

## Korean

`robot_manager`는 robot configuration 파일을 읽고, 로봇 객체를 생성하며, 로봇의 명령과 상태를 관리하는 Python 패키지이다.

이 패키지는 `robot_manager` 모듈과 `robots` 모듈을 함께 포함한다.

`RobotManager`는 YAML 설정 파일을 읽어서 각 robot 이름에 맞는 robot 구현체를 생성하고, joint status를 각 robot에 분배하며, action frame으로부터 생성된 command frame을 하나로 모아 반환한다.

## Build

```bash
colcon build --packages-select robot_manager
```

## Configuration

### YAML Example

```yaml
dt: 0.01

robot:
  - index: 0
    name: "rocking_chair"
    dt: 0.01
    controller_indices: [0]
    target_interface_ids:
      - [0, 1]
    home_positions: [0.0]
    home_duration: 5.0
    move_duration: 60.0
    init_controlword: 0x103F
    motion_data_file_path: "../motions"
```

`motion_data_file_path`는 YAML 파일 위치를 기준으로 한 상대 경로를 사용할 수 있다.

## API

### `RobotManager`

| Function | Purpose |
| --- | --- |
| `number_of_robots` | `RobotManager`가 관리하는 robot의 수를 반환한다. |
| `dt` | YAML 파일에서 읽은 제어 주기를 반환한다. |
| `controller_indices()` | 모든 robot이 사용하는 controller index를 하나의 list로 반환한다. |
| `number_of_target_interfaces()` | 모든 controller의 target interface 개수를 하나의 list로 반환한다. |
| `target_interface_ids()` | 모든 controller의 target interface ID list를 하나의 list로 반환한다. |
| `loadConfigurations()` | YAML 파일에서 각 robot 설정을 읽고 robot 객체를 생성한다. |
| `updateJointStatus(joint_status)` | `joint_status`를 robot별로 나누어 각 robot의 현재 joint status를 업데이트한다. |
| `get_state_frames()` | 각 robot의 현재 `state_frame`을 반환한다. |
| `set_action_frames(action_frames)` | 각 `action_frame`을 해당 robot에 적용하고 병합된 joint command를 반환한다. |
